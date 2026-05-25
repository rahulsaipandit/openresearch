"""
Tolaria MCP Integration — save research artefacts to Tolaria folders.

Tolaria is an Obsidian-compatible knowledge base that exposes an MCP endpoint.
This integration uses the Tolaria MCP server to write Markdown notes into
configured vault folders directly from the research pipelines.

How it works:
  1. TolariaClient connects to the Tolaria MCP server (stdio or HTTP SSE transport).
  2. It calls the `write_note` MCP tool with a folder path, note title, and Markdown body.
  3. The note appears in your Tolaria vault immediately, ready to link and navigate.

Supported artefacts:
  - Interview prep brief   → vault_folder/interview/<company>-<role>.md
  - Tailored resume        → vault_folder/resumes/<company>-<role>-resume.md
  - Stock research brief   → vault_folder/stock/<ticker>.md
  - Board briefing         → vault_folder/board/<date>.md

Configuration (config.yaml):
  mcp:
    tolaria:
      enabled: true
      server_url: "http://localhost:27123"   # Tolaria MCP endpoint (HTTP SSE)
      api_key: ""                            # Tolaria API key if auth required
      vault_folder: "OpenResearch"           # root folder in vault (created if absent)

MCP transport:
  Current implementation uses HTTP to the Tolaria REST/MCP endpoint.
  This is equivalent to the filesystem MCP tool but routed through Tolaria's
  own server so notes land inside the vault with correct metadata.

  The underlying Tolaria server must be running. For local use, Tolaria typically
  exposes a REST API on localhost:27123 (compatible with the Obsidian Local REST
  API plugin — same format).

Fallback:
  If Tolaria is not configured or unavailable, TolariaClient writes to a local
  `output/` directory instead. This means the pipeline always produces an
  artefact — the destination is just a local file rather than the vault.
"""

import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Obsidian Local REST API / Tolaria endpoint paths
_VAULT_NOTE_PATH = "/vault/{path}"
_CONTENT_TYPE    = "text/markdown"


def _slugify(text: str) -> str:
    """Convert a string to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return re.sub(r"-+", "-", text)


class TolariaClient:
    """
    Saves Markdown artefacts to a Tolaria (or Obsidian Local REST API) vault.

    Instantiate via TolariaClient.from_config("config.yaml").
    If Tolaria is not configured, save() writes to the local output/ directory instead.
    """

    def __init__(
        self,
        server_url: str | None = None,
        api_key: str | None = None,
        vault_folder: str = "OpenResearch",
        local_fallback_dir: str = "output",
    ):
        self.server_url         = (server_url or "").rstrip("/") or None
        self.api_key            = api_key or None
        self.vault_folder       = vault_folder.strip("/")
        self.local_fallback_dir = Path(local_fallback_dir)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "TolariaClient":
        """Build a TolariaClient from config.yaml mcp.tolaria section."""
        import yaml
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
        except Exception:
            return cls()

        t_cfg = cfg.get("mcp", {}).get("tolaria", {})
        return cls(
            server_url=t_cfg.get("server_url", "") or None,
            api_key=t_cfg.get("api_key", "") or None,
            vault_folder=t_cfg.get("vault_folder", "OpenResearch"),
            local_fallback_dir=t_cfg.get("local_fallback_dir", "output"),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_configured(self) -> bool:
        """Return True if a Tolaria server_url is set (note-saving will be attempted)."""
        return bool(self.server_url)

    def save(
        self,
        content: str,
        subfolder: str,
        title: str,
        overwrite: bool = True,
    ) -> str:
        """
        Save a Markdown note to Tolaria (or local fallback).

        Args:
            content:   Full Markdown content of the note.
            subfolder: Vault subfolder relative to vault_folder.
                       e.g. "interview", "resumes", "stock"
            title:     Note title (used as filename, slugified).
            overwrite: If True, replace existing note with same path.

        Returns:
            Path/URL of the saved note as a string.
        """
        slug     = _slugify(title)
        note_path = f"{self.vault_folder}/{subfolder}/{slug}.md"

        if self.is_configured:
            return self._save_to_vault(content, note_path, overwrite=overwrite)
        else:
            return self._save_locally(content, subfolder, slug)

    # ── Convenience methods ───────────────────────────────────────────────────

    def save_interview_brief(
        self,
        brief_md: str,
        company_name: str,
        role_title: str,
    ) -> str:
        """Save an interview prep brief to vault/interview/."""
        title = f"{company_name} - {role_title}"
        return self.save(brief_md, subfolder="interview", title=title)

    def save_tailored_resume(
        self,
        resume_md: str,
        company_name: str,
        role_title: str,
    ) -> str:
        """Save a tailored resume to vault/resumes/."""
        title = f"{company_name} - {role_title} - Resume"
        return self.save(resume_md, subfolder="resumes", title=title)

    def save_stock_brief(self, brief_md: str, ticker: str) -> str:
        """Save a stock research brief to vault/stock/."""
        title = f"{ticker.upper()} - {date.today().isoformat()}"
        return self.save(brief_md, subfolder="stock", title=title)

    def save_board_briefing(self, briefing_md: str) -> str:
        """Save an executive board briefing to vault/board/."""
        title = f"Board Briefing {date.today().isoformat()}"
        return self.save(briefing_md, subfolder="board", title=title)

    # ── Internal: Vault save (Tolaria / Obsidian Local REST API) ─────────────

    def _save_to_vault(self, content: str, note_path: str, overwrite: bool) -> str:
        """
        PUT the note to the Tolaria/Obsidian Local REST API vault endpoint.

        The Obsidian Local REST API (and Tolaria) accept:
          PUT /vault/<path-to-note.md>
          Content-Type: text/markdown
          Authorization: Bearer <api_key>   (if auth enabled)
          Body: raw Markdown text

        A 200/201/204 response means success.
        """
        try:
            import httpx
        except ImportError:
            logger.warning("TolariaClient: httpx not installed — saving locally")
            return self._save_locally_from_path(content, note_path)

        url = f"{self.server_url}/vault/{note_path}"
        headers: dict[str, str] = {"Content-Type": _CONTENT_TYPE}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Use PUT (create-or-replace) or POST (create-only)
        method = "PUT" if overwrite else "POST"

        try:
            with httpx.Client(timeout=10) as client:
                resp = getattr(client, method.lower())(
                    url, content=content.encode("utf-8"), headers=headers
                )
                if resp.status_code in (200, 201, 204):
                    logger.info(f"TolariaClient: saved note to vault: {note_path}")
                    return f"tolaria://{note_path}"
                else:
                    logger.warning(
                        f"TolariaClient: vault PUT returned {resp.status_code}. "
                        f"Falling back to local save."
                    )
                    return self._save_locally_from_path(content, note_path)
        except Exception as e:
            logger.warning(f"TolariaClient: vault save failed ({e}). Saving locally.")
            return self._save_locally_from_path(content, note_path)

    # ── Internal: Local fallback ──────────────────────────────────────────────

    def _save_locally(self, content: str, subfolder: str, slug: str) -> str:
        output_dir = self.local_fallback_dir / subfolder
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{slug}.md"
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"TolariaClient: saved locally to {output_path}")
        return str(output_path)

    def _save_locally_from_path(self, content: str, note_path: str) -> str:
        """Local fallback when vault save fails — reuses the vault path as a local path."""
        local_path = self.local_fallback_dir / note_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")
        logger.info(f"TolariaClient: saved locally to {local_path}")
        return str(local_path)


# ── Markdown renderers ────────────────────────────────────────────────────────
# Convert Pydantic output schemas to clean Markdown for vault notes.

def render_interview_brief(brief) -> str:
    """Render an InterviewPrepBrief as a vault-ready Markdown note."""
    from datetime import date as _date

    lines = [
        f"# Interview Prep: {brief.role_title} at {brief.company_name}",
        f"*Generated: {brief.as_of_date}*",
        "",
        "---",
        "",
        f"## Fit Assessment — {brief.fit.overall_score}/10 ({brief.fit.recommendation.replace('_', ' ').title()})",
        "",
        f"> {brief.fit.summary}",
        "",
    ]

    if brief.fit.match_strengths:
        lines += ["**Strengths:**"] + [f"- {s}" for s in brief.fit.match_strengths] + [""]
    if brief.fit.gaps:
        lines += ["**Gaps:**"] + [f"- {g}" for g in brief.fit.gaps] + [""]
    if brief.fit.deal_breakers:
        lines += ["**⚠️ Deal-breakers:**"] + [f"- {d}" for d in brief.fit.deal_breakers] + [""]

    lines += [
        "---",
        "",
        f"## Company: {brief.company_name}",
        "",
        f"**Culture:** {brief.company.culture_summary}",
        f"**Interview style:** {brief.company.interview_style}",
        "",
    ]
    if brief.company.known_values:
        lines += ["**Values:**"] + [f"- {v}" for v in brief.company.known_values] + [""]
    if brief.company.prep_priorities:
        lines += ["**Prep priorities:**"] + [f"- {p}" for p in brief.company.prep_priorities] + [""]
    if brief.company.red_flags:
        lines += ["**Red flags:**"] + [f"- {r}" for r in brief.company.red_flags] + [""]

    lines += [
        "---",
        "",
        "## Top 3 Priorities",
        "",
    ]
    for i, p in enumerate(brief.top_3_priorities, 1):
        lines.append(f"{i}. {p}")
    lines.append("")

    lines += ["---", "", "## Questions", ""]
    if brief.questions.behavioural:
        lines += ["### Behavioural"] + [f"- {q}" for q in brief.questions.behavioural] + [""]
    if brief.questions.technical:
        lines += ["### Technical"] + [f"- {q}" for q in brief.questions.technical] + [""]
    if brief.questions.culture_fit:
        lines += ["### Culture Fit"] + [f"- {q}" for q in brief.questions.culture_fit] + [""]
    if brief.questions.curveball:
        lines += ["### Curveball"] + [f"- {q}" for q in brief.questions.curveball] + [""]

    if brief.answers.answers:
        lines += ["---", "", "## STAR Answers", ""]
        for ans in brief.answers.answers:
            lines += [
                f"### {ans.question}",
                "",
                f"**Situation:** {ans.situation}",
                f"**Task:** {ans.task}",
                f"**Action:** {ans.action}",
                f"**Result:** {ans.result}",
                f"*Tailoring note: {ans.tailoring_note}*",
                "",
            ]

    if brief.tailored_resume:
        lines += ["---", "", "## Tailored Resume", "", brief.tailored_resume.full_resume_md, ""]

    return "\n".join(lines)


def render_stock_brief(brief) -> str:
    """Render a ResearchBrief as a vault-ready Markdown note."""
    lines = [
        f"# Stock Research: {brief.ticker} — {brief.company_name}",
        f"*As of: {brief.as_of_date}*",
        "",
        f"**Verdict:** {brief.verdict}  |  **Price target:** ${brief.price_target_low:.2f}–${brief.price_target_high:.2f}  |  "
        f"**Current:** ${brief.current_price:.2f}" if brief.current_price else f"**Verdict:** {brief.verdict}",
        "",
        f"## Summary",
        f"{brief.summary}",
        "",
    ]
    if brief.bull_case:
        lines += ["## Bull Case"] + [f"- {b}" for b in brief.bull_case] + [""]
    if brief.bear_case:
        lines += ["## Bear Case"] + [f"- {b}" for b in brief.bear_case] + [""]
    if brief.key_risks:
        lines += ["## Key Risks"] + [f"- {r}" for r in brief.key_risks] + [""]
    if brief.upcoming_catalysts:
        lines += ["## Upcoming Catalysts"] + [f"- {c}" for c in brief.upcoming_catalysts] + [""]
    return "\n".join(lines)
