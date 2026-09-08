"""
SECVectorStore — local, embedded semantic search over ingested SEC filing
chunks. See store/chroma_vector_store.py's ChromaVectorStore for the shared
chromadb setup (no server, no cloud embeddings API) and why that choice was
made over turbovec/LEANN — both solve a corpus-scale problem (10M+
documents) that a handful of filings per ticker never reaches.

One collection ("sec_filings") shared across all tickers, filtered by a
`ticker` metadata field on query, rather than a collection per ticker.
"""

from pathlib import Path
from typing import Any

from schemas.sec_insights import SECChunk
from store.chroma_vector_store import ChromaVectorStore

_DEFAULT_PATH = Path("data") / "sec_vectors"
_COLLECTION_NAME = "sec_filings"


class SECVectorStore(ChromaVectorStore):
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        super().__init__(path, _COLLECTION_NAME)

    def is_ingested(self, ticker: str) -> bool:
        result = self._get(where={"ticker": ticker.upper()}, limit=1)
        return len(result.get("ids", [])) > 0

    def replace_ticker(self, ticker: str, chunks: list[SECChunk]) -> None:
        """Delete any existing chunks for this ticker, then add the fresh set."""
        ticker = ticker.upper()
        self._delete_by_where({"ticker": ticker})

        if not chunks:
            return

        ids = [f"{ticker}-{c.filing_type}-{c.section}-{i}" for i, c in enumerate(chunks)]
        self._add_many(
            ids=ids,
            texts=[c.text for c in chunks],
            metadatas=[
                {
                    "ticker": ticker,
                    "filing_type": c.filing_type,
                    "section": c.section,
                    "filing_date": c.filing_date,
                }
                for c in chunks
            ],
        )

    def query(self, ticker: str, question: str, n_results: int = 5) -> dict[str, Any]:
        return self._query_texts(question, n_results, where={"ticker": ticker.upper()})

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "SECVectorStore":
        data_dir = cls._data_dir_from_config(config_path, "stock_research")
        return cls(data_dir / "sec_vectors")
