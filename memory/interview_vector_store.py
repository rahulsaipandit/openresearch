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
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        super().__init__(path, _COLLECTION_NAME)

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
        return self._query_texts(query_text, n_results, where)

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
        data_dir = cls._data_dir_from_config(config_path, "interview_memory")
        return cls(data_dir / "interview_memory_vectors")
