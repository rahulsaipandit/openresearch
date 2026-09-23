"""
OpportunityRadarAgent — cross-ticker/sector theme detection over the
watchlist. See docs/Stocks/designStock_DashboardUI.md for the design
decisions (watchlist-driven universe, JSON storage, daily asyncio batch job)
and why Approach A (deterministic clustering) was chosen over having an LLM
propose themes ad hoc from raw headlines.

Pipeline, all deterministic except the final narration step:
  1. Pull headlines for each watchlist ticker (NewsAggregatorAgent).
  2. Extract candidate theme phrases from headline text — regex-based
     capitalized-phrase extraction. No TF-IDF/embedding library added as a
     new dependency; this repo has no scikit-learn, and a lightweight
     heuristic is enough at watchlist scale (up to 20 tickers).
  3. Score each phrase: frequency, recency-weighted, times distinct
     watchlist-ticker count (a source-diversity proxy) -> "Theme Strength,"
     normalized 0-100 against the strongest surviving theme.
  4. Classify each mentioning ticker's stance (benefit/pressured/mentioned)
     with a small keyword lexicon per headline — a documented heuristic, not
     a sentiment model.
  5. LLM writes one paragraph per surviving theme, grounded only in the
     evidence headlines already collected (same narrate-not-decide pattern
     as ResearchSynthesizerAgent).

Known limitation: the capitalization heuristic requires a phrase's first
character to be uppercase, so camel-case brand names ("iPhone", "eBay",
"iOS") don't get picked up as their own token — a headline like "Apple
iPhone Demand Misses" only yields "Demand Misses[...]" style fragments, not
"iPhone Demand". Acceptable for a first pass; would need a small brand-name
exception list to fix properly.
"""

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timezone

from agents.api_utils import LLMClient
from agents.stock.news_aggregator import NewsAggregatorAgent
from schemas.opportunity_radar import OpportunityRadarResult, OpportunityTheme, ThemeEvidence, ThemeTickerStance

logger = logging.getLogger(__name__)

MAX_THEMES = 8
MIN_MENTIONS = 2               # a phrase needs at least this many headline mentions to count as a theme
RECENCY_HALF_LIFE_DAYS = 7.0   # a mention's weight halves every this many days

# Runs of consecutive Title-Case words — candidate phrases are every 2-3 word
# window within a run, not just the longest match, so "AI Capex" is still
# recognized as the same phrase whether a headline says "AI Capex Surge" or
# "AI Capex Demand". A workable proxy for named entities/themes without an
# NLP dependency. Single-word windows are skipped — too noisy (mostly just
# the ticker's own company name; MIN_MENTIONS alone doesn't filter well
# enough, since a company's own name naturally repeats across its headlines).
_CAP_RUN_RE = re.compile(r"\b[A-Z][a-zA-Z0-9&]*(?:\s+[A-Z][a-zA-Z0-9&]*)*\b")
_PHRASE_WINDOW_SIZES = (2, 3)

# Words/phrases that match the pattern but aren't themes — news sources,
# generic capitalized words, day/month names. Not exhaustive; extend as noise
# shows up in practice.
_BLOCKLIST = {
    "the", "inc", "corp", "co", "ltd", "llc", "reuters", "bloomberg", "cnbc",
    "ap", "afp", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "january", "february", "march", "april", "may",
    "june", "july", "august", "september", "october", "november", "december",
    "q1", "q2", "q3", "q4", "eps", "update", "breaking", "watch", "why",
    "how", "what",
}

# Deliberately small, documented lexicon — see class docstring. Not a
# sentiment model; a coarse deterministic read of headline framing.
_POSITIVE_WORDS = {
    "surge", "surges", "soar", "soars", "beat", "beats", "record", "boost",
    "boosts", "rally", "rallies", "gain", "gains", "upgrade", "upgraded",
    "jump", "jumps", "strong", "growth", "wins", "win", "expand", "expands",
}
_NEGATIVE_WORDS = {
    "miss", "misses", "cut", "cuts", "plunge", "plunges", "warn", "warns",
    "warning", "downgrade", "downgraded", "slump", "slumps", "lawsuit",
    "recall", "probe", "investigation", "layoffs", "decline", "declines",
    "fall", "falls", "loss", "losses", "delay", "delays",
}


class OpportunityRadarAgent:
    def __init__(self, llm: LLMClient, news_aggregator: NewsAggregatorAgent, verbose: bool = False):
        self.llm = llm
        self.news_aggregator = news_aggregator
        self.verbose = verbose

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "OpportunityRadarAgent":
        import yaml
        from agents.mcp_client import MCPClient

        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        sources = cfg.get("stock_research", {}).get("data_sources", {})
        return cls(
            llm=LLMClient.from_config(config_path),
            news_aggregator=NewsAggregatorAgent(
                news_api_key=sources.get("news_api_key", "") or "",
                mcp=MCPClient.from_config(config_path),
            ),
            verbose=cfg.get("server", {}).get("verbose", True),
        )

    def generate(self, tickers: list[str]) -> OpportunityRadarResult:
        tickers = [t.upper().strip() for t in tickers if t.strip()]
        if not tickers:
            return OpportunityRadarResult(generated_at=date.today().isoformat(), universe=[], themes=[])

        if self.verbose:
            print(f"[OpportunityRadar] Scanning {len(tickers)} watchlist tickers...")

        headlines_by_ticker = self._fetch_all_headlines(tickers)
        candidates = self._extract_candidates(headlines_by_ticker)
        themes = self._score_and_build(candidates)

        for theme in themes:
            theme.description = self._narrate(theme)

        return OpportunityRadarResult(
            generated_at=date.today().isoformat(),
            universe=tickers,
            themes=themes,
        )

    # ── Headline fetch ────────────────────────────────────────────────────────

    def _fetch_all_headlines(self, tickers: list[str]) -> dict[str, list[dict]]:
        result = {}
        for ticker in tickers:
            try:
                news = self.news_aggregator.fetch(ticker, company_name="", depth="quick")
                result[ticker] = news.get("headlines", [])
            except Exception as e:
                logger.warning(f"OpportunityRadar headline fetch failed for {ticker}: {e}")
                result[ticker] = []
        return result

    # ── Candidate extraction ─────────────────────────────────────────────────

    def _extract_candidates(self, headlines_by_ticker: dict[str, list[dict]]) -> dict[str, list[dict]]:
        """
        Returns {phrase: [{ticker, title, source, published_at, url, stance}, ...]}
        """
        candidates: dict[str, list[dict]] = defaultdict(list)
        for ticker, headlines in headlines_by_ticker.items():
            for h in headlines:
                title = h.get("title", "")
                text = f"{title} {h.get('description', '')}"
                stance = self._classify_stance(text)
                for phrase in self._phrases_in(title):
                    candidates[phrase].append({
                        "ticker":       ticker,
                        "title":        title,
                        "source":       h.get("source", ""),
                        "published_at": h.get("published_at", ""),
                        "url":          h.get("url", ""),
                        "stance":       stance,
                    })
        return candidates

    def _phrases_in(self, title: str) -> set[str]:
        phrases = set()
        for run_match in _CAP_RUN_RE.finditer(title):
            words = run_match.group(0).split()
            for size in _PHRASE_WINDOW_SIZES:
                for start in range(0, len(words) - size + 1):
                    window = words[start:start + size]
                    # any(), not all(): a phrase containing even one noise
                    # word (a source name, day/month, generic term) isn't a
                    # theme, even if its other word(s) look legitimate.
                    if any(w.lower() in _BLOCKLIST for w in window):
                        continue
                    phrases.add(" ".join(window))
        return phrases

    def _classify_stance(self, text: str) -> str:
        words = set(re.findall(r"[a-z']+", text.lower()))
        return self._resolve_stance(
            has_positive=bool(words & _POSITIVE_WORDS),
            has_negative=bool(words & _NEGATIVE_WORDS),
        )

    def _resolve_stance(self, has_positive: bool, has_negative: bool) -> str:
        """Shared benefit/pressured/mentioned tie-break — used at both the
        per-headline level (_classify_stance) and the per-ticker aggregate
        level (_ticker_stances) so the "mixed signals -> mentioned" rule
        can't drift out of sync between the two."""
        if has_positive and not has_negative:
            return "benefit"
        if has_negative and not has_positive:
            return "pressured"
        return "mentioned"

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_and_build(self, candidates: dict[str, list[dict]]) -> list[OpportunityTheme]:
        scored: list[tuple[float, str, list[dict]]] = []
        for phrase, mentions in candidates.items():
            if len(mentions) < MIN_MENTIONS:
                continue
            distinct_tickers = len({m["ticker"] for m in mentions})
            recency_weight = sum(self._recency_weight(m["published_at"]) for m in mentions)
            raw_score = recency_weight * distinct_tickers
            if raw_score <= 0:
                continue
            scored.append((raw_score, phrase, mentions))

        if not scored:
            return []

        scored.sort(key=lambda s: s[0], reverse=True)
        top = scored[:MAX_THEMES]
        max_raw = top[0][0]

        themes = []
        for raw_score, phrase, mentions in top:
            strength = round((raw_score / max_raw) * 100, 1) if max_raw > 0 else 0.0
            themes.append(OpportunityTheme(
                theme=phrase,
                strength_score=strength,
                description="",  # filled by _narrate() after scoring
                tickers=self._ticker_stances(mentions),
                evidence=self._evidence(mentions),
            ))
        return themes

    def _recency_weight(self, published_at: str) -> float:
        try:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            days_old = (datetime.now(timezone.utc) - published).total_seconds() / 86400
        except (ValueError, TypeError):
            days_old = RECENCY_HALF_LIFE_DAYS  # unknown date -> treat as one half-life old
        days_old = max(days_old, 0.0)
        return 0.5 ** (days_old / RECENCY_HALF_LIFE_DAYS)

    def _ticker_stances(self, mentions: list[dict]) -> list[ThemeTickerStance]:
        by_ticker: dict[str, list[str]] = defaultdict(list)
        for m in mentions:
            by_ticker[m["ticker"]].append(m["stance"])

        stances = []
        for ticker, stance_list in by_ticker.items():
            stance = self._resolve_stance(
                has_positive="benefit" in stance_list,
                has_negative="pressured" in stance_list,
            )
            stances.append(ThemeTickerStance(ticker=ticker, stance=stance, mention_count=len(stance_list)))
        stances.sort(key=lambda s: s.mention_count, reverse=True)
        return stances

    def _evidence(self, mentions: list[dict], limit: int = 5) -> list[ThemeEvidence]:
        seen_urls = set()
        evidence = []
        for m in sorted(mentions, key=lambda m: m["published_at"], reverse=True):
            if m["url"] in seen_urls:
                continue
            seen_urls.add(m["url"])
            evidence.append(ThemeEvidence(
                ticker=m["ticker"], title=m["title"], source=m["source"],
                published_at=m["published_at"], url=m["url"],
            ))
            if len(evidence) >= limit:
                break
        return evidence

    # ── LLM narration ─────────────────────────────────────────────────────────

    def _narrate(self, theme: OpportunityTheme) -> str:
        evidence_lines = "\n".join(
            f"- [{e.ticker}] {e.title} ({e.source}, {e.published_at})" for e in theme.evidence
        )
        tickers_line = ", ".join(
            f"{t.ticker} ({t.stance}, {t.mention_count} mentions)" for t in theme.tickers
        )
        prompt = (
            f"Theme: {theme.theme}\n"
            f"Theme strength: {theme.strength_score}/100 (deterministic — frequency, recency, "
            f"and how many watchlist tickers' headlines mention it)\n"
            f"Tickers mentioned: {tickers_line}\n\n"
            f"Evidence headlines:\n{evidence_lines}\n\n"
            "Write one paragraph (2-3 sentences) explaining this theme and which tickers stand to "
            "benefit or face pressure, grounded ONLY in the evidence headlines above — do not cite "
            "facts not present there. Return plain text, no markdown, no JSON."
        )
        try:
            return self.llm.create(
                system=(
                    "You are an equity research associate writing a one-paragraph theme summary "
                    "for a portfolio manager scanning their watchlist. Be specific and grounded; "
                    "never state a fact the evidence doesn't support."
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            ).strip()
        except Exception as e:
            logger.warning(f"OpportunityRadar narration failed for theme '{theme.theme}': {e}")
            return f"{theme.theme} appeared across {len(theme.evidence)} recent headlines; narration unavailable."
