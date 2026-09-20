"""
InterviewVectorStore — local, embedded semantic search over a candidate's
topic notes, question history, and answer-bank entries. See
store/chroma_vector_store.py's ChromaVectorStore for the shared chromadb
setup this is built on (no server, no cloud embeddings API) — that choice
was deliberately re-examined against LEANN, turbovec, and Mnemosyne's
no-vector-DB approach for this use case (see docs/openresearch-integration-
requirements.md §6.1) and re-confirmed: a candidate's practice corpus is a
few hundred documents, not the millions-of-documents scale those
alternatives are built for.

One collection ("interview_memory") shared across all candidates, filtered
by a `candidate_id` metadata field on query — mirrors SECVectorStore's
`ticker`-filtered single-collection design.
"""

from pathlib import Path
from typing import Any, Optional

from store.chroma_vector_store import ChromaVectorStore

_DEFAULT_PATH = Path("data") / "interview_memory_vectors"
_COLLECTION_NAME = "interview_memory"

DocType = str  # "answer_bank" | "topic" | "question"


class InterviewVectorStore(ChromaVectorStore):
    def __init__(self, path: Path | str = _DEFAULT_PATH, embedding_function: Optional[Any] = None):
        super().__init__(path, _COLLECTION_NAME, embedding_function=embedding_function)

    def _query(self, query_text: str, n_results: int, where: dict[str, Any]) -> dict[str, Any]:
        """Routes through the asymmetric query-side embedding (nomic's
        "search_query: " prefix) when embedding_function supports it,
        otherwise the plain query_texts path chromadb's default embedder
        uses. See store/embedding_functions.py's NomicEmbeddingFunction
        docstring for why these can't share one code path."""
        has_query_embedder = self._embedding_function is not None and hasattr(
            self._embedding_function, "embed_query"
        )
        if has_query_embedder:
            embedding = self._embedding_function.embed_query(query_text)
            return self._query_embedding(embedding, n_results, where)
        return self._query_texts(query_text, n_results, where)

    def upsert(
        self,
        doc_id: str,
        text: str,
        candidate_id: str,
        doc_type: DocType,
        topic: Optional[str] = None,
    ) -> None:
        metadata: dict[str, Any] = {"candidate_id": candidate_id, "doc_type": doc_type}
        if topic:
            metadata["topic"] = topic
        self._upsert_one(doc_id, text, metadata)

    def add_document_chunks(
        self,
        candidate_id: str,
        source_doc_id: str,
        source_filename: str,
        document_kind: str,
        chunks: list[tuple[int, int, str]],
    ) -> int:
        """Bulk-upsert a document's chunks: chunks is (page_number, chunk_index, text).

        Every ingested-document chunk gets the coarse `doc_type="document"`
        (a new retrieval category alongside the existing "answer_bank" /
        "question" / "topic") so `query_documents()` can filter on it — kept
        distinct from `document_kind` (the finer resume/candidate_document/
        seed_question/answer_bank_manual category from DocumentRecord), which
        would otherwise collide with `doc_type`'s existing meaning elsewhere
        in this class.

        Record ids are deterministic (doc_id:page:chunk) so re-ingesting the
        same source_doc_id with the same page/chunk layout overwrites in
        place instead of duplicating."""
        ids, texts, metadatas = [], [], []
        for page_number, chunk_index, text in chunks:
            if not text.strip():
                continue
            ids.append(f"document:{candidate_id}:{source_doc_id}:{page_number}:{chunk_index}")
            texts.append(text)
            metadatas.append(
                {
                    "candidate_id": candidate_id,
                    "doc_type": "document",
                    "document_kind": document_kind,
                    "doc_id": source_doc_id,
                    "source_filename": source_filename,
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                }
            )
        self._add_many(ids, texts, metadatas)
        return len(ids)

    def delete_document_chunks(self, candidate_id: str, source_doc_id: str) -> None:
        """Delete every chunk belonging to one ingested document — used both
        on document delete and before re-embedding an updated document
        (docs/designInterviewTool.md "Staleness tracking")."""
        self._delete_by_where({"$and": [{"candidate_id": candidate_id}, {"doc_id": source_doc_id}]})

    def delete(self, doc_id: str) -> None:
        self._delete_by_ids([doc_id])

    def query(
        self,
        candidate_id: str,
        query_text: str,
        n_results: int = 5,
        doc_type: Optional[DocType] = None,
    ) -> dict[str, Any]:
        where: dict[str, Any] = (
            {"$and": [{"candidate_id": candidate_id}, {"doc_type": doc_type}]}
            if doc_type
            else {"candidate_id": candidate_id}
        )
        return self._query(query_text, n_results, where)

    def query_documents(
        self,
        candidate_id: str,
        query_text: str,
        doc_ids: list[str],
        n_results: int = 5,
    ) -> dict[str, Any]:
        """Scope retrieval to exactly the given ingested document(s) — the
        `document_ids` RAG-scoping control (docs/designInterviewTool.md).
        `doc_ids` must be non-empty; an empty list has no valid "$in" filter
        so callers should fall back to the unscoped `query()` instead."""
        where = {
            "$and": [
                {"candidate_id": candidate_id},
                {"doc_type": "document"},
                {"doc_id": {"$in": doc_ids}},
            ]
        }
        return self._query(query_text, n_results, where)

    def most_similar(
        self, candidate_id: str, text: str, doc_type: DocType
    ) -> Optional[tuple[str, float]]:
        """Nearest existing document of the same type, as (doc_id, distance).

        Used for near-duplicate detection on the answer bank (Mnemosyne-style
        cosine-threshold dedup — see §6.1) — not applied to the question log,
        which is an append-only record of distinct practice attempts even
        when phrased similarly.
        """
        result = self.query(candidate_id, text, n_results=1, doc_type=doc_type)
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        if not ids:
            return None
        return ids[0], distances[0]

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "InterviewVectorStore":
        import yaml

        data_dir = cls._data_dir_from_config(config_path, "interview_memory")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        embedding_model = cfg.get("interview_memory", {}).get("embedding_model", "default")

        embedding_function = None
        if embedding_model == "nomic-embed-text-v1.5":
            from store.embedding_functions import get_nomic_embedding_function

            embedding_function = get_nomic_embedding_function()

        # Path is namespaced by embedding_model rather than shared — two
        # embedders can produce different-dimension vectors, and chromadb
        # can't reopen an existing collection under a different embedding
        # function without erroring. Namespacing means flipping this config
        # value always lands on a distinct (initially empty) collection
        # instead of crashing against one built under the other embedder, at
        # the cost of starting that collection unindexed — an acceptable
        # tradeoff before there's any real data to preserve across a switch.
        collection_dirname = (
            "interview_memory_vectors" if embedding_model == "default"
            else f"interview_memory_vectors_{embedding_model}"
        )
        return cls(data_dir / collection_dirname, embedding_function=embedding_function)
