"""
SECQAAgent — answers a question about a ticker's SEC filings using local
semantic search (SECVectorStore/chromadb) over ingested 10-K/10-Q sections
(SECIngestAgent/EdgarTools), then an LLM synthesis over the retrieved
chunks with citations back to filing/section. Loosely modeled on the
sec-insights reference app's citation pattern, without its Postgres+PGVector
infra — see requirements.md for that scoping decision.
"""

import json
import logging

from agents.api_utils import LLMClient
from agents.stock.sec_ingest import SECIngestAgent
from schemas.sec_insights import SECAnswer, SECCitation
from store.sec_vector_store import SECVectorStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are answering a question about a company's SEC filings using ONLY \
the filing excerpts provided below. If the excerpts don't contain the answer, say so \
explicitly rather than guessing or using outside knowledge. Cite which excerpt number(s) \
support each claim using [1], [2] style markers matching the excerpt numbering in the answer text.

Return ONLY valid JSON: {"answer": "<answer text with [n] markers inline>", "used_excerpts": [<excerpt numbers actually cited>]}"""


class SECQAAgent:
    def __init__(
        self,
        llm: LLMClient,
        vector_store: SECVectorStore,
        ingest: SECIngestAgent,
        verbose: bool = False,
    ):
        self.llm          = llm
        self.vector_store = vector_store
        self.ingest       = ingest
        self.verbose      = verbose

    def answer(self, ticker: str, question: str, force_refresh: bool = False) -> SECAnswer:
        ticker = ticker.upper().strip()

        if force_refresh or not self.vector_store.is_ingested(ticker):
            if self.verbose:
                print(f"  [SECQA] Ingesting SEC filings for {ticker}...")
            chunks = self.ingest.fetch_chunks(ticker)
            if chunks:
                self.vector_store.replace_ticker(ticker, chunks)

        results = self.vector_store.query(ticker, question, n_results=5)
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]

        if not documents:
            return SECAnswer(
                ticker=ticker,
                question=question,
                answer=(
                    "No SEC filing data is available for this ticker — ingestion may have "
                    "failed (check SEC EDGAR connectivity) or no 10-K/10-Q filings were found."
                ),
                citations=[],
            )

        if self.verbose:
            print(f"  [SECQA] Answering with {len(documents)} retrieved excerpts...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(question, documents, metadatas)}],
            max_tokens=800,
        )

        try:
            data = json.loads(raw)
            used = set(data.get("used_excerpts", []))
            citations = self._build_citations(documents, metadatas, used)
            return SECAnswer(ticker=ticker, question=question, answer=data.get("answer", ""), citations=citations)
        except Exception as e:
            logger.warning(f"SECQA JSON parse failed: {e}\nRaw: {raw[:300]}")
            citations = self._build_citations(documents, metadatas, used=None)
            return SECAnswer(
                ticker=ticker, question=question,
                answer=raw.strip() or "Unable to generate an answer.", citations=citations,
            )

    def _build_prompt(self, question: str, documents: list[str], metadatas: list[dict]) -> str:
        lines = [f"Question: {question}", "", "Excerpts:"]
        for i, (doc, meta) in enumerate(zip(documents, metadatas), start=1):
            lines.append(
                f"[{i}] ({meta.get('filing_type')}, {meta.get('section')}, {meta.get('filing_date')}): {doc[:800]}"
            )
        return "\n".join(lines)

    def _build_citations(self, documents: list[str], metadatas: list[dict], used: set | None) -> list[SECCitation]:
        citations = []
        for i, (doc, meta) in enumerate(zip(documents, metadatas), start=1):
            if used is not None and used and i not in used:
                continue
            citations.append(SECCitation(
                filing_type=meta.get("filing_type", ""),
                section=meta.get("section", ""),
                filing_date=meta.get("filing_date", ""),
                excerpt=doc[:400],
            ))
        return citations
