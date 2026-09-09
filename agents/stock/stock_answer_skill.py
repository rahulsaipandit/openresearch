"""
StockAnswerSkill — the retrieval + answer-generation flow behind
POST /v1/stock/answer (docs/openresearch-integration-requirements.md §10).

Mirrors agents/interview/skills/live_interview_coach.py's shape (retrieval,
then one grounded LLM call to actually answer the question, with graceful
image degradation) — but single-tenant, no candidate_id, no cognitive
memory. Reuses the existing QueryRouterAgent for intent/ticker extraction
(the same "never trust an LLM ticker guess blindly, verify against
yfinance" logic already proven in agents/stock/query_router.py) rather than
inventing a second one.
"""

import logging
from typing import Optional

from agents.api_utils import LLMClient
from agents.stock.query_router import QueryRouterAgent
from pipelines.stock_pipeline import StockResearchPipeline
from schemas.answer_common import AnswerStyle, ImageAttachment, MatchedSource
from schemas.domain_answer import DomainAnswerResult
from schemas.stock import ResearchBrief, StockPipelineInput
from store.watchlist_store import WatchlistStore

logger = logging.getLogger(__name__)

_FORMAT_INSTRUCTIONS = {
    "full_text": "Answer in full, read-aloud-ready sentences.",
    "list": "Answer as short bulleted key points, one per line — no paragraphs.",
    "keywords": "Answer as minimal standalone words or short phrases, one per line.",
}
_DEPTH_INSTRUCTIONS = {
    "one_liner": "Keep it to a single sentence or line.",
    "balanced": "A few sentences — enough to be complete, not exhaustive.",
    "detailed": "Thorough — cover context, specifics, and concrete numbers.",
}

_SYSTEM_PROMPT_TEMPLATE = """You are a stock research assistant. Ground your \
answer in the research context provided below — never invent numbers, \
company names, or outcomes not present in it. If the context doesn't cover \
what's being asked, say so rather than guessing.

Format: {format_instruction}
Depth: {depth_instruction}
"""


class StockAnswerSkill:
    def __init__(
        self,
        llm: LLMClient,
        query_router: QueryRouterAgent,
        stock_pipeline: StockResearchPipeline,
        watchlist_store: Optional[WatchlistStore] = None,
    ):
        self.llm             = llm
        self.query_router    = query_router
        self.stock_pipeline  = stock_pipeline
        self.watchlist_store = watchlist_store

    def apply(
        self,
        *,
        question: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
        answer_style: Optional[AnswerStyle] = None,
        images: Optional[list[ImageAttachment]] = None,
    ) -> DomainAnswerResult:
        answer_style = answer_style or AnswerStyle()
        conversation_history = conversation_history or []

        routed = self.query_router.route(question)

        if routed.clarification_needed:
            return DomainAnswerResult(answer_text=routed.clarification_question or "Could you clarify which company or ticker you mean?")

        if routed.intent == "watchlist_add" and routed.resolved:
            ticker = routed.resolved[0].ticker
            if self.watchlist_store is None:
                return DomainAnswerResult(answer_text="Watchlist isn't available right now.")
            try:
                self.watchlist_store.add(ticker)
            except ValueError as e:
                return DomainAnswerResult(answer_text=str(e))
            return DomainAnswerResult(
                answer_text=f"Added {ticker} to your watchlist.",
                matched_sources=[MatchedSource(id=ticker, title=ticker, category="watchlist")],
            )

        if not routed.resolved:
            return DomainAnswerResult(answer_text="I couldn't resolve a ticker to research — could you name the company or ticker directly?")

        briefs: list[ResearchBrief] = []
        for company in routed.resolved[:2]:  # comparison intent: research both; single_analysis: just one
            try:
                briefs.append(self.stock_pipeline.run(StockPipelineInput(ticker=company.ticker, depth=routed.depth)))
            except Exception as e:
                logger.error(f"StockAnswerSkill: research failed for {company.ticker}: {e}", exc_info=True)
                return DomainAnswerResult(answer_text=f"Research failed for {company.ticker}: {e}")

        context = "\n\n".join(self._format_brief(b) for b in briefs)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            format_instruction=_FORMAT_INSTRUCTIONS[answer_style.format],
            depth_instruction=_DEPTH_INSTRUCTIONS[answer_style.depth],
        )
        user_prompt = self._build_user_prompt(context, conversation_history, question)

        image_payload = (
            [{"media_type": img.media_type, "data": img.data} for img in images] if images else None
        )
        answer_text, images_used = self.llm.create_multimodal(
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=700,
            images=image_payload,
        )

        matched_sources = [
            MatchedSource(id=b.ticker, title=b.company_name, category="research_brief") for b in briefs
        ]
        return DomainAnswerResult(
            answer_text=answer_text,
            matched_sources=matched_sources,
            images_ignored=bool(images) and not images_used,
        )

    def _format_brief(self, brief: ResearchBrief) -> str:
        return (
            f"## {brief.ticker} ({brief.company_name})\n"
            f"Verdict: {brief.verdict} | Price target: ${brief.price_target_low:.0f}-${brief.price_target_high:.0f}\n"
            f"Summary: {brief.summary}\n"
            f"Bull case: {'; '.join(brief.bull_case)}\n"
            f"Bear case: {'; '.join(brief.bear_case)}\n"
            f"Key risks: {'; '.join(brief.key_risks)}"
        )

    def _build_user_prompt(self, context: str, conversation_history: list[dict], question: str) -> str:
        sections = [f"## Research context\n{context}"]
        if conversation_history:
            history_text = "\n".join(
                f"{turn.get('role', '?')}: {turn.get('content', '')}" for turn in conversation_history[-6:]
            )
            sections.append(f"## Recent conversation\n{history_text}")
        sections.append(f"## Question to answer now\n{question}")
        return "\n\n".join(sections)
