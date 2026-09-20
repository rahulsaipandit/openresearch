"""
ChromaVectorStore — shared base for local, embedded semantic search over a
single small-to-modest corpus (a ticker's SEC filings, a candidate's
interview memory, ...). Wraps chromadb's PersistentClient with its default
on-device embedding model (ONNX MiniLM, cached on first use) — no server, no
cloud embeddings API.

That choice (over heavier options like turbovec/LEANN, or a no-vector-DB
approach like Mnemosyne's) was made once in store/sec_vector_store.py and
re-confirmed for a second, differently-shaped use case in
memory/interview_vector_store.py (see docs/openresearch-integration-
requirements.md §6.1) — both land on the same conclusion because both
corpora are the same shape: a handful to a few hundred documents per scope
(ticker / candidate_id), not the millions-of-documents scale those
alternatives are built for.

Factored out here after the two concrete stores (SECVectorStore,
InterviewVectorStore) started as near-identical hand-copies and began
drifting apart method-by-method — see the code review that flagged it.
Subclasses keep their own public method names/signatures (is_ingested,
replace_ticker, upsert, most_similar, ...); this base only owns the parts
that were actually identical: client/collection setup, delete-by-id,
delete-by-where, and query.
"""

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ChromaVectorStore:
    def __init__(
        self, path: Path | str, collection_name: str, embedding_function: Optional[Any] = None
    ):
        """`embedding_function`, when given, replaces chromadb's bundled
        default (ONNX MiniLM) — e.g. store/embedding_functions.py's
        NomicEmbeddingFunction. Kept as an explicit opt-in constructor arg
        (not a config global) since switching a collection's embedding
        function requires a one-time re-embed migration — see
        scripts/reembed_interview_memory.py and docs/designInterviewTool.md's
        "Embedding model" section — not something to silently pick up."""
        import chromadb

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.path))
        self._embedding_function = embedding_function
        kwargs: dict[str, Any] = {}
        if embedding_function is not None:
            kwargs["embedding_function"] = embedding_function
        self._collection = self._client.get_or_create_collection(collection_name, **kwargs)

    def _upsert_one(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        if not text.strip():
            return
        self._collection.upsert(documents=[text], ids=[doc_id], metadatas=[metadata])

    def _add_many(self, ids: list[str], texts: list[str], metadatas: list[dict[str, Any]]) -> None:
        if not ids:
            return
        self._collection.add(documents=texts, ids=ids, metadatas=metadatas)

    def _delete_by_ids(self, ids: list[str]) -> None:
        try:
            self._collection.delete(ids=ids)
        except Exception as e:
            logger.debug(f"{type(self).__name__} delete by id (non-fatal): {e}")

    def _delete_by_where(self, where: dict[str, Any]) -> None:
        try:
            self._collection.delete(where=where)
        except Exception as e:
            logger.debug(f"{type(self).__name__} delete by where (non-fatal, likely nothing to delete): {e}")

    def _query_texts(self, query_text: str, n_results: int, where: dict[str, Any]) -> dict[str, Any]:
        return self._collection.query(query_texts=[query_text], n_results=n_results, where=where)

    def _query_embedding(
        self, query_embedding: list[float], n_results: int, where: dict[str, Any]
    ) -> dict[str, Any]:
        """For an asymmetric embedding function (e.g. nomic-embed-text-v1.5's
        search_document/search_query prefixes) — chromadb's collection.query()
        always runs query_texts through the *same* embedding_function used
        for .add(), so it can't apply a different query-side prefix on its
        own. Subclasses that need that (see InterviewVectorStore._query)
        embed the query text themselves via embedding_function.embed_query()
        and pass the resulting vector here instead of raw text."""
        return self._collection.query(
            query_embeddings=[query_embedding], n_results=n_results, where=where
        )

    def _get(self, where: dict[str, Any], limit: Optional[int] = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"where": where}
        if limit is not None:
            kwargs["limit"] = limit
        return self._collection.get(**kwargs)

    @staticmethod
    def _data_dir_from_config(config_path: str, config_section: str) -> Path:
        import yaml

        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        return Path(cfg.get(config_section, {}).get("data_dir", "data"))
