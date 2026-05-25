"""
Interview Research Pipeline

Sequential 5-node pipeline:
  JobFitAnalyzer → CompanyResearcher → QuestionGenerator → AnswerGenerator → ResumeWriter

Each node reads outputs from previous nodes and contributes to the final
InterviewPrepBrief. The pipeline runs synchronously (~35–60 seconds at full depth).

depth="quick": skips CompanyResearcher LLM call AND ResumeWriter — returns generic
               company profile and no tailored resume. Fast for testing.
depth="full":  runs all 5 nodes with full LLM analysis + live web search if MCP configured.

MCPClient integration:
  CompanyResearcher uses mcp.call_sync("brave-search", ...) when an MCPClient with a
  configured brave_search_key is provided. Falls back to LLM-only if mcp is None or
  the key is not set. Pass mcp=None to disable entirely (or use depth="quick").
"""

import logging
from datetime import date
from typing import Optional

from agents.api_utils import LLMClient
from agents.interview.job_fit_analyzer import JobFitAnalyzerAgent
from agents.interview.company_researcher import CompanyResearcherAgent
from agents.interview.question_generator import QuestionGeneratorAgent
from agents.interview.answer_generator import AnswerGeneratorAgent
from agents.interview.resume_writer import ResumeWriterAgent
from schemas.interview import (
    InterviewPipelineInput,
    InterviewPrepBrief,
)

logger = logging.getLogger(__name__)


class InterviewPipeline:
    """
    Runs the full interview research pipeline for a given JD + candidate profile.

    Usage:
        pipeline = InterviewPipeline.from_config("config.yaml")
        brief = pipeline.run(InterviewPipelineInput(
            jd_text="...",
            profile_text="...",
            company_name="Acme Corp",
            role_title="Staff Engineer",
        ))
    """

    def __init__(self, llm: LLMClient, mcp=None, verbose: bool = True):
        self.llm     = llm
        self.mcp     = mcp
        self.verbose = verbose

        self.fit_analyzer       = JobFitAnalyzerAgent(llm, verbose)
        self.company_researcher = CompanyResearcherAgent(llm, mcp=mcp, verbose=verbose)
        self.question_generator = QuestionGeneratorAgent(llm, verbose)
        self.answer_generator   = AnswerGeneratorAgent(llm, verbose)
        self.resume_writer      = ResumeWriterAgent(llm, verbose)

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "InterviewPipeline":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        llm     = LLMClient.from_config(config_path)
        verbose = cfg.get("server", {}).get("verbose", True)

        # Build MCPClient if brave_search_key is configured
        mcp = None
        try:
            from agents.mcp_client import MCPClient
            mcp = MCPClient.from_config(config_path)
            if mcp.is_available("brave-search") and verbose:
                print("  [InterviewPipeline] MCPClient: brave-search enabled (live company research)")
            elif verbose:
                print("  [InterviewPipeline] MCPClient: brave-search not configured — using LLM knowledge")
        except Exception as e:
            logger.warning(f"MCPClient init failed: {e}. Continuing without live web search.")

        return cls(llm=llm, mcp=mcp, verbose=verbose)

    def run(self, request: InterviewPipelineInput) -> InterviewPrepBrief:
        company  = request.company_name.strip()
        role     = request.role_title.strip()
        depth    = request.depth
        total    = 5 if depth == "full" else 3

        if self.verbose:
            print(f"\n[InterviewPipeline] Starting prep for {role} at {company} (depth={depth})")

        # Node 1: Job fit analysis
        if self.verbose:
            print(f"  [1/{total}] Analysing job fit...")
        fit = self.fit_analyzer.analyze(
            jd_text=request.jd_text,
            profile_text=request.profile_text,
            company_name=company,
            role_title=role,
        )

        # Node 2: Company research (LLM-only in quick mode; live web in full mode if MCP configured)
        if self.verbose:
            print(f"  [2/{total}] Researching company interview culture...")
        company_profile = self.company_researcher.research(
            company_name=company,
            role_title=role,
            depth=depth,
        )

        # Node 3: Generate tailored questions
        if self.verbose:
            print(f"  [3/{total}] Generating interview questions...")
        questions = self.question_generator.generate(
            jd_text=request.jd_text,
            fit=fit,
            company=company_profile,
            company_name=company,
            role_title=role,
        )

        # Node 4 + 5 only run on full depth
        tailored_resume = None
        answers = None

        if depth == "full":
            # Node 4: Generate STAR answers
            if self.verbose:
                print(f"  [4/{total}] Generating STAR answers from profile...")
            answers = self.answer_generator.generate(
                profile_text=request.profile_text,
                questions=questions,
                company=company_profile,
                fit=fit,
                company_name=company,
            )

            # Node 5: Write tailored resume
            if self.verbose:
                print(f"  [5/{total}] Writing tailored resume...")
            try:
                tailored_resume = self.resume_writer.write(
                    profile_text=request.profile_text,
                    jd_text=request.jd_text,
                    fit=fit,
                    company=company_profile,
                    company_name=company,
                    role_title=role,
                )
            except Exception as e:
                logger.warning(f"ResumeWriter failed (non-fatal): {e}")
                tailored_resume = None

        else:
            # Quick mode: still run answer generator (just no resume)
            if self.verbose:
                print(f"  [4/{total}] Generating STAR answers from profile...")
            answers = self.answer_generator.generate(
                profile_text=request.profile_text,
                questions=questions,
                company=company_profile,
                fit=fit,
                company_name=company,
            )

        # Derive top 3 priorities from fit + company profile
        top_3 = self._derive_priorities(fit, company_profile)

        from schemas.interview import AnswerSet
        brief = InterviewPrepBrief(
            role_title=role,
            company_name=company,
            as_of_date=date.today().isoformat(),
            fit=fit,
            company=company_profile,
            questions=questions,
            answers=answers if answers is not None else AnswerSet(answers=[]),
            top_3_priorities=top_3,
            tailored_resume=tailored_resume,
        )

        if self.verbose:
            resume_status = "✓ tailored resume" if tailored_resume else "— no resume (quick mode)"
            print(
                f"[InterviewPipeline] Done. "
                f"Fit: {fit.overall_score}/10 ({fit.recommendation}) | "
                f"Questions: {len(questions.behavioural)}B "
                f"{len(questions.technical)}T "
                f"{len(questions.culture_fit)}C "
                f"{len(questions.curveball)}X | "
                f"Answers: {len(brief.answers.answers)} | "
                f"{resume_status}"
            )

        return brief

    def _derive_priorities(self, fit, company_profile) -> list[str]:
        """
        Derive the 3 highest-leverage prep priorities.

        Order: deal-breakers first (if any — candidate needs to know),
        then top gap, then top company prep priority.
        """
        priorities: list[str] = []

        if fit.deal_breakers:
            priorities.append(
                f"Address deal-breaker: {fit.deal_breakers[0]} — "
                "prepare a direct, honest answer for how you'd close this gap on the job."
            )

        if fit.gaps and len(priorities) < 3:
            priorities.append(
                f"Prepare for gap exposure: {fit.gaps[0]} — "
                "interviewers will probe here; have a clear narrative about your closest analogue."
            )

        if company_profile.prep_priorities:
            for p in company_profile.prep_priorities:
                if len(priorities) >= 3:
                    break
                priorities.append(p)

        # Pad to 3 if we have fewer
        defaults = [
            "Prepare 5–7 STAR stories covering leadership, conflict, failure, and delivery.",
            "Research the company's recent news, products, and competitive position.",
            "Practice delivering concise answers: Situation + Task in under 60 seconds.",
        ]
        for d in defaults:
            if len(priorities) >= 3:
                break
            priorities.append(d)

        return priorities[:3]
