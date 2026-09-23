"""
EarningsCallSummarizer — earnings-call transcript fetch + LLM summary.

Unlike every other LLM agent in this pipeline, this one operates directly on
a document rather than pre-computed structured facts — and that's fine: the
"no LLM does math" rule (see CLAUDE.md/AGENTS.md) is about not letting the
LLM compute numbers, not about banning text summarization of a fixed source
document. Summarizing a transcript into highlights/guidance/tone is exactly
the kind of bounded, groundable task an LLM is well suited for.

Transcript source (see docs/designStock_DashboardUI.md for how this was
decided — confirmed live against Alpha Vantage's own API, not just docs):
  Primary    — Alpha Vantage's EARNINGS_CALL_TRANSCRIPT endpoint, available
               on the same free API key already used for
               INCOME_STATEMENT/BALANCE_SHEET (agents/stock/data_fetcher.py).
  Enrichment — Equibles (if running), which layers in verified speaker
               roles, the linked 8-K, and pre-extracted guidance statements.
               Optional — the summarizer works without it, same
               "Equibles enriches when available" pattern used for
               institutional/short-interest data.
"""

import json
import logging
from datetime import date

import httpx

from agents.api_utils import LLMClient
from agents.mcp_client import MCPClient
from schemas.stock import EarningsCallSummary

logger = logging.getLogger(__name__)

_ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
_MAX_TRANSCRIPT_CHARS = 24000  # keeps the summarization prompt within a reasonable token budget

SYSTEM_PROMPT = """You are an equity research associate summarizing an earnings call transcript for a \
portfolio manager who has two minutes to read it.

Ground every point in the transcript text provided — do not add outside knowledge or speculate about \
numbers not stated in the call. Classify management's overall tone from their language and how they \
handled analyst questions, not from the reported numbers themselves.

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

SUMMARY_SCHEMA = """{
  "key_highlights": ["<3-5 specific points from prepared remarks>", ...],
  "guidance": ["<forward-looking statement or numeric guidance given, if any>", ...],
  "management_tone": "<confident|cautious|mixed|defensive|neutral>",
  "notable_qa": ["<analyst question + gist of management's answer>", ...]
}"""


class EarningsCallSummarizer:
    def __init__(
        self,
        llm: LLMClient,
        alpha_vantage_key: str = "",
        mcp: MCPClient | None = None,
        verbose: bool = False,
    ):
        self.llm = llm
        self.alpha_vantage_key = alpha_vantage_key
        self.mcp = mcp
        self.verbose = verbose

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "EarningsCallSummarizer":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        sources = cfg.get("stock_research", {}).get("data_sources", {})
        return cls(
            llm=LLMClient.from_config(config_path),
            alpha_vantage_key=sources.get("alpha_vantage_key", "") or "",
            mcp=MCPClient.from_config(config_path),
            verbose=cfg.get("server", {}).get("verbose", True),
        )

    def summarize(self, ticker: str, quarter: str | None = None) -> EarningsCallSummary | None:
        """
        Fetch the transcript for `ticker` (most recently reported quarter, or
        a specific "YYYYQ#" if given) and return an LLM summary. Returns None
        if no Alpha Vantage key is configured or no transcript is found.
        """
        ticker = ticker.upper().strip()
        if not self.alpha_vantage_key:
            logger.info("EarningsCallSummarizer skipped — no Alpha Vantage key configured.")
            return None

        turns, resolved_quarter = self._fetch_transcript(ticker, quarter or self._guess_latest_quarter())
        if not turns:
            return None

        linked_8k_url = None
        if self.mcp and self.mcp.is_available("equibles"):
            enrichment = self._fetch_equibles_enrichment(ticker, resolved_quarter)
            if enrichment:
                linked_8k_url = enrichment.get("linked_8k_url") or enrichment.get("8k_url")

        transcript_text = self._format_transcript(turns)

        if self.verbose:
            print(f"  [EarningsCallSummarizer] Summarizing {ticker} {resolved_quarter}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(ticker, resolved_quarter, transcript_text)}],
            max_tokens=1200,
        )

        try:
            data = json.loads(raw)
        except Exception as e:
            logger.warning(f"EarningsCallSummarizer JSON parse failed: {e}\nRaw: {raw[:300]}")
            return None

        return EarningsCallSummary(
            quarter=resolved_quarter,
            source="alpha_vantage",
            key_highlights=data.get("key_highlights", []),
            guidance=data.get("guidance", []),
            management_tone=data.get("management_tone", "neutral"),
            notable_qa=data.get("notable_qa", []),
            linked_8k_url=linked_8k_url,
        )

    # ── Quarter resolution ────────────────────────────────────────────────────

    def _guess_latest_quarter(self) -> str:
        """
        Companies typically report 3-6 weeks after quarter-end, so for most
        of any given quarter, the most recently *reported* quarter is one
        quarter back from today, not the one currently in progress. Early in
        a quarter (before the prior quarter's earnings season has finished),
        that guess can still be too recent — _fetch_transcript() steps back
        one more quarter if it comes back empty.
        """
        today = date.today()
        q = (today.month - 1) // 3 + 1 - 1
        year = today.year
        while q < 1:
            q += 4
            year -= 1
        return f"{year}Q{q}"

    def _prev_quarter(self, quarter: str) -> str:
        year, q = int(quarter[:4]), int(quarter[5])
        q -= 1
        if q < 1:
            q, year = 4, year - 1
        return f"{year}Q{q}"

    # ── Transcript fetch ──────────────────────────────────────────────────────

    def _fetch_transcript(self, ticker: str, quarter: str) -> tuple[list[dict], str]:
        for candidate in (quarter, self._prev_quarter(quarter)):
            turns = self._fetch_transcript_for_quarter(ticker, candidate)
            if turns:
                return turns, candidate
        return [], quarter

    def _fetch_transcript_for_quarter(self, ticker: str, quarter: str) -> list[dict]:
        try:
            with httpx.Client(timeout=20) as client:
                r = client.get(_ALPHA_VANTAGE_URL, params={
                    "function": "EARNINGS_CALL_TRANSCRIPT",
                    "symbol":   ticker,
                    "quarter":  quarter,
                    "apikey":   self.alpha_vantage_key,
                })
                data = r.json()
        except Exception as e:
            logger.warning(f"EarningsCallSummarizer transcript fetch failed for {ticker} {quarter}: {e}")
            return []

        transcript = data.get("transcript")
        return transcript if isinstance(transcript, list) else []

    def _fetch_equibles_enrichment(self, ticker: str, quarter: str) -> dict | None:
        try:
            return self.mcp.equibles_earnings_call_transcript(ticker, quarter=quarter)
        except Exception as e:
            logger.debug(f"EarningsCallSummarizer Equibles enrichment failed for {ticker}: {e}")
            return None

    # ── Prompt building ───────────────────────────────────────────────────────

    def _format_transcript(self, turns: list[dict]) -> str:
        lines = []
        for turn in turns:
            speaker = turn.get("speaker", "Unknown")
            title = turn.get("title")
            content = turn.get("content", "")
            header = f"{speaker} ({title})" if title else speaker
            lines.append(f"{header}: {content}")
        return "\n\n".join(lines)[:_MAX_TRANSCRIPT_CHARS]

    def _build_prompt(self, ticker: str, quarter: str, transcript_text: str) -> str:
        return (
            f"Ticker: {ticker}\n"
            f"Quarter: {quarter}\n\n"
            f"=== Transcript ===\n{transcript_text}\n\n"
            f"Produce an EarningsCallSummary JSON matching this schema:\n{SUMMARY_SCHEMA}"
        )
