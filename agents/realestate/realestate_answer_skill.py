"""
RealEstateAnswerSkill — the retrieval + answer-generation flow behind
POST /v1/realestate/answer (docs/openresearch-integration-requirements.md §10).

RealEstatePipeline needs structured city/state (+ optional property
details), not free text — unlike stock's QueryRouterAgent, there's no
existing entity-extraction step for real estate questions. This skill adds
a small one: a single LLM call extracts city/state/property details from
the question (schemas.realestate.RealEstateQueryExtraction) before running
the pipeline, then a second LLM call answers the actual question grounded
in the resulting RealEstateBrief — mirrors agents/stock/stock_answer_skill.py's
shape (and, further back, agents/interview/skills/live_interview_coach.py's),
single-tenant, no candidate_id.
"""

import logging
from typing import Optional

from agents.api_utils import LLMClient, parse_llm_json
from pipelines.realestate_pipeline import RealEstatePipeline
from schemas.answer_common import AnswerStyle, ImageAttachment, MatchedSource
from schemas.domain_answer import DomainAnswerResult
from schemas.realestate import RealEstateBrief, RealEstatePipelineInput, RealEstateQueryExtraction

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = """Extract the location and (if mentioned) property \
details from a real-estate research question. city and state are required for \
research to proceed — if either is missing or too vague to resolve (e.g. \
"a good area to invest in"), leave it null rather than guessing.

Return ONLY valid JSON matching this schema — no prose, no markdown fences:
{"city": "<city name or null>", "state": "<2-letter state abbreviation or null>", \
"address": "<street address or null>", "bedrooms": <int or null>, \
"bathrooms": <number or null>, "sqft": <int or null>, "purchase_price": <number or null>}"""

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

_ANSWER_SYSTEM_PROMPT_TEMPLATE = """You are a real-estate research assistant. \
Ground your answer in the market research context provided below — never \
invent numbers, addresses, or outcomes not present in it. If the context \
doesn't cover what's being asked, say so rather than guessing.

Format: {format_instruction}
Depth: {depth_instruction}
"""


class RealEstateAnswerSkill:
    def __init__(self, llm: LLMClient, realestate_pipeline: RealEstatePipeline):
        self.llm                 = llm
        self.realestate_pipeline = realestate_pipeline

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

        extraction = self._extract_location(question)
        if not extraction.city or not extraction.state:
            return DomainAnswerResult(
                answer_text="I need a city and state to research — which market are you asking about?"
            )

        try:
            brief = self.realestate_pipeline.run(
                RealEstatePipelineInput(
                    city=extraction.city,
                    state=extraction.state,
                    address=extraction.address or "",
                    bedrooms=extraction.bedrooms,
                    bathrooms=extraction.bathrooms,
                    sqft=extraction.sqft,
                    purchase_price=extraction.purchase_price,
                )
            )
        except Exception as e:
            logger.error(f"RealEstateAnswerSkill: research failed for {extraction.city}, {extraction.state}: {e}", exc_info=True)
            return DomainAnswerResult(answer_text=f"Research failed for {extraction.city}, {extraction.state}: {e}")

        system_prompt = _ANSWER_SYSTEM_PROMPT_TEMPLATE.format(
            format_instruction=_FORMAT_INSTRUCTIONS[answer_style.format],
            depth_instruction=_DEPTH_INSTRUCTIONS[answer_style.depth],
        )
        user_prompt = self._build_user_prompt(brief, conversation_history, question)

        image_payload = (
            [{"media_type": img.media_type, "data": img.data} for img in images] if images else None
        )
        answer_text, images_used = self.llm.create_multimodal(
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=700,
            images=image_payload,
        )

        source_id = f"{brief.city}-{brief.state}".lower().replace(" ", "-")
        matched_sources = [
            MatchedSource(id=source_id, title=f"{brief.city}, {brief.state}", category="market_brief")
        ]
        return DomainAnswerResult(
            answer_text=answer_text,
            matched_sources=matched_sources,
            images_ignored=bool(images) and not images_used,
        )

    def _extract_location(self, question: str) -> RealEstateQueryExtraction:
        raw = self.llm.create(
            system=_EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
            max_tokens=200,
        )
        return parse_llm_json(
            raw, "RealEstateAnswerExtraction",
            builder=lambda data: RealEstateQueryExtraction(**data),
            fallback=lambda: RealEstateQueryExtraction(),
        )

    def _format_brief(self, brief: RealEstateBrief) -> str:
        lines = [
            f"## {brief.city}, {brief.state}",
            f"Demand: {brief.demand_verdict} | Investment signal: {brief.investment_signal} "
            f"| Confidence: {brief.confidence:.0%}",
            f"Summary: {brief.summary}",
            f"Pull factors: {'; '.join(brief.dominant_pull_factors)}",
            f"Push factors: {'; '.join(brief.dominant_push_factors)}",
            f"Key risks: {'; '.join(brief.key_risks)}",
        ]
        if brief.rental_analysis:
            lines.append(f"Rental feasibility: {brief.rental_analysis.feasibility_verdict}")
        return "\n".join(lines)

    def _build_user_prompt(
        self, brief: RealEstateBrief, conversation_history: list[dict], question: str
    ) -> str:
        sections = [f"## Research context\n{self._format_brief(brief)}"]
        if conversation_history:
            history_text = "\n".join(
                f"{turn.get('role', '?')}: {turn.get('content', '')}" for turn in conversation_history[-6:]
            )
            sections.append(f"## Recent conversation\n{history_text}")
        sections.append(f"## Question to answer now\n{question}")
        return "\n\n".join(sections)
