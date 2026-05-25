"""
CompanyResearcher — Node 2 of the interview research pipeline.

Produces a CompanyProfile covering interview style, culture, values,
and the highest-leverage prep priorities for a specific company and role.

Company research strategy (two-tier):
  1. Live web search (when MCPClient is configured with brave_search_key):
     Fetches current Glassdoor signals, engineering blog posts, recent news,
     and interview reviews before the LLM call. This produces genuinely
     current intel rather than static LLM knowledge.
  2. LLM knowledge only (fallback when MCP not configured):
     Draws on the LLM's training knowledge of the company's interview process.
     Works well for well-known companies (FAANG, unicorns) but may be stale
     for fast-changing companies or smaller orgs.

Phase 7 note: the MCPClient currently calls Brave Search API directly via HTTP.
When mcp_server.py is built (Phase 7), replace MCPClient._brave_search() with
a proper MCP stdio/SSE transport — the agent-facing API stays identical.
"""

import json
import logging

from agents.api_utils import LLMClient
from schemas.interview import CompanyProfile

logger = logging.getLogger(__name__)

# Lazy import to avoid circular deps — MCPClient is optional
_MCPClient = None


def _get_mcp_client_class():
    global _MCPClient
    if _MCPClient is None:
        try:
            from agents.mcp_client import MCPClient
            _MCPClient = MCPClient
        except ImportError:
            pass
    return _MCPClient


SYSTEM_PROMPT = """You are an experienced career coach who has helped hundreds of engineers and
executives prepare for interviews at top companies. You have specific, detailed knowledge of
how different companies interview — not generic advice, but what actually happens in the room.

Given a company and role, provide:
1. How this company structures its interview process (number of rounds, types of interviews)
2. The interview style — e.g. behavioural-heavy, case-based, system design, take-home, etc.
3. The values they assess, both explicitly stated and implicitly tested
4. The highest-leverage prep priorities specific to this company (not generic "study LeetCode")
5. Red flags: common mistakes candidates make or things that have caused offers to be pulled

Be specific. If you have company-specific knowledge (e.g. Amazon uses Leadership Principles,
Google uses structured behavioural questions, McKinsey uses case interviews), use it.
If live web research is provided, prioritise it over your training knowledge — it is more current.
If the company is not well known, give the best assessment you can from the role type and industry.

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

COMPANY_SCHEMA = """{
  "culture_summary": "<2–3 sentences on what it is actually like to work here>",
  "interview_style": "<concise label + 1 sentence: e.g. 'Behavioural-heavy — 4 rounds, each with 2 LP stories and 1 technical deep-dive'>",
  "known_values": [
    "<specific value or principle the company assesses — use the company's own language where possible>",
    ...
  ],
  "prep_priorities": [
    "<specific, actionable prep item ranked by importance — not generic advice>",
    ...
  ],
  "red_flags": [
    "<common mistake or signal that hurts candidates at this company specifically>",
    ...
  ]
}"""

# Depth=quick fallback: generic profile when company intel is limited
_GENERIC_PROFILE_TEMPLATE = CompanyProfile(
    culture_summary="Company culture details not available for this organisation.",
    interview_style="Standard multi-round interview process; specific format unknown.",
    known_values=[],
    prep_priorities=[
        "Prepare 5–7 STAR stories covering leadership, conflict, failure, and delivery",
        "Review the job description for explicit technical requirements and prepare examples for each",
        "Research the company's recent news, products, and challenges before the interview",
    ],
    red_flags=[],
)

# Search queries to run for each company (ordered by value)
_SEARCH_QUERIES = [
    "{company} {role} interview process rounds 2024 2025",
    "{company} engineering culture interview tips Glassdoor",
    "{company} {role} interview experience leetcode behavioural",
]


class CompanyResearcherAgent:
    """
    Researches company interview culture and produces a CompanyProfile.

    Args:
        llm:     LLMClient instance
        mcp:     Optional MCPClient for live web search (brave-search tool).
                 If None, falls back to LLM knowledge only.
        verbose: print progress to stdout
    """

    def __init__(self, llm: LLMClient, mcp=None, verbose: bool = False):
        self.llm     = llm
        self.mcp     = mcp
        self.verbose = verbose

    def research(
        self,
        company_name: str,
        role_title: str,
        depth: str = "full",
    ) -> CompanyProfile:
        """
        Research interview culture for company_name + role_title.

        depth="quick" returns a generic profile without making any calls.
        depth="full"  runs live web search (if MCP configured) then LLM analysis.
        """
        if depth == "quick":
            if self.verbose:
                print(f"  [CompanyResearcher] Skipping company research (depth=quick)")
            return _GENERIC_PROFILE_TEMPLATE

        # Gather live web context if MCP is available
        web_context = self._gather_web_context(company_name, role_title)

        prompt = self._build_prompt(company_name, role_title, web_context)

        if self.verbose:
            source = "live web + LLM" if web_context else "LLM knowledge"
            print(f"  [CompanyResearcher] Researching {company_name} interview culture ({source})...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )

        try:
            data = json.loads(raw)
            return CompanyProfile(**data)
        except Exception as e:
            logger.warning(f"CompanyResearcher JSON parse failed: {e}\nRaw: {raw[:300]}")
            return _GENERIC_PROFILE_TEMPLATE

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _gather_web_context(self, company_name: str, role_title: str) -> str:
        """
        Run brave-search queries for the company and return concatenated results.
        Returns empty string if MCP is not configured or search fails.
        """
        if self.mcp is None or not self.mcp.is_available("brave-search"):
            return ""

        results: list[str] = []
        for query_template in _SEARCH_QUERIES:
            query = query_template.format(
                company=company_name,
                role=role_title,
            )
            try:
                result = self.mcp.call_sync("brave-search", {"query": query})
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"CompanyResearcher web search failed for '{query}': {e}")

        if not results:
            return ""

        combined = "\n\n---\n\n".join(results)
        # Cap total web context to ~4000 chars to leave room for LLM reasoning
        return combined[:4000]

    def _build_prompt(
        self,
        company_name: str,
        role_title: str,
        web_context: str,
    ) -> str:
        web_section = ""
        if web_context:
            web_section = f"""
=== LIVE WEB RESEARCH (prioritise this over training knowledge) ===
{web_context}

===

"""
        return f"""Company: {company_name}
Role: {role_title}
{web_section}
Produce a CompanyProfile JSON matching this schema:
{COMPANY_SCHEMA}

Be as specific as possible to {company_name}. If you have knowledge of their actual
interview process (e.g. rounds, named frameworks, known question patterns), include it.
{"Use the live web research above to provide current, accurate interview intel." if web_context else ""}"""
