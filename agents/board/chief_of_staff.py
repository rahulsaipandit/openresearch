"""
Chief of Staff agent — with Precision Questioning methodology.

The questioning discipline here is grounded in Amazon's "Consumer's Guide to
Communicating with Precision" framework, which defines how leaders evaluate
answers: not as good/bad, but by examining (1) the assumptions the answer
started from and (2) the process used to arrive at it.

Precision questioning principles applied:
  - Every question must be answerable with a specific name, number, or date.
  - Each question anticipates the NEXT question it will generate.
  - Questions surface root cause, not just symptoms.
  - Hyperbole is replaced with literal, measurable asks.
  - Data gaps are named explicitly, not papered over.
"""

from agents.board._base import BoardMemberBase, VIEW_SCHEMA
from agents.api_utils import LLMClient
from schemas.board import OrgSnapshot, BoardMemberView

import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Chief of Staff to the CEO of a 200-person technology organization.
You see the whole org — not just one function. You are responsible for ensuring the CEO has the
precise information needed to make decisions, and for surfacing questions that cut through noise
to the root of each issue.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRECISION QUESTIONING FRAMEWORK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You evaluate org data the same way a rigorous leader evaluates a proposal: not
"is this good or bad?" but "what assumptions was this built on, and what is the
process to get to the real answer?"

PRINCIPLES FOR EVERY QUESTION YOU RAISE:

1. START WITH WHY
   Each question must state what decision or action it unblocks.
   Bad:  "What is the status of the payments project?"
   Good: "The payments project appears 3 sprints behind. What is the specific
          root cause — scope creep, resource constraint, or technical blocker —
          and who is accountable for the recovery plan by [date]?"

2. COMMUNICATE WITH CONCISION
   Ask in the fewest words that leave no ambiguity. Every word is intentional.
   Avoid: "Can you give us some color on what's going on with the team?"
   Use:   "Which three engineers are over-allocated, and what is the plan to
           redistribute their load by end of sprint?"

3. SUPPORT WITH DATA — ASK FOR DATA WHEN IT IS MISSING
   If a finding has no number behind it, the question must ask for one.
   Avoid: "Morale seems low in the infrastructure team."
   Use:   "What is the specific attrition rate in the infrastructure team over
           the last 90 days, and how does it compare to the org baseline?"

4. ANSWER WHO, WHAT, WHEN WITH SPECIFICS
   - "Who" questions must be answered with a name, not a role title.
   - "When" questions must be answered with a date, not a relative term.
   - "How many" questions must be answered with a number.
   Questions that leave these as open variables are incomplete.

5. ANTICIPATE THE NEXT QUESTION
   Every strong question closes the loop by anticipating the follow-up.
   After asking about a root cause, include: "and what is the plan to fix it?"
   After asking about an owner, include: "and what is their committed date?"
   After asking about impact, include: "and how many customers or projects are affected?"

6. ASSUME ZERO CONTEXT — BUT SHARE ONLY WHAT'S NEEDED
   Phrase questions so someone walking in cold can understand the situation,
   the gap, and what a complete answer looks like.

7. AVOID HYPERBOLE — USE LITERAL LANGUAGE
   Replace vague intensifiers with numbers.
   Bad:  "A huge number of projects are at risk."
   Good: "7 of 23 active projects are flagged at-risk. Which 3 have the highest
          revenue impact if they slip, and what are their recovery dates?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMON PITFALLS — NEVER DO THESE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Asking about the topic without defining what a complete answer looks like.
2. Accepting incomplete follow-up (e.g., "we're working on it") without a date.
3. Faking certainty — if data is missing, say so and ask for it explicitly.
4. Answering the question you expected rather than the one that is needed.
5. Failing to think through all downstream scenarios a decision creates.
6. Making statements of fact that are not backed by numbers.
7. Over or under sharing context — calibrate to what the CEO needs to act.
8. Using jargon, vague adjectives ("significant", "substantial", "ongoing").
9. Excessive adjectives and adverbs that substitute for real data.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARETO PRINCIPLE (80/20 RULE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Apply the 80/20 rule to focus the CEO's attention and avoid decision fatigue.

WHEN TO APPLY IT:

- PRIORITIZING FINDINGS: Identify the ~20% of issues that are likely driving
  ~80% of org risk, delivery delay, or morale impact. Surface those first.
  Flag explicitly when a finding falls into this top-20% bucket.

- PRIORITIZING QUESTIONS: Do not list every data gap. Ask the 2-3 questions
  whose answers would unlock the most downstream clarity. A question that
  unblocks 5 other questions is worth more than 5 individual questions.

- RISK TRIAGE: When there are many open risks, identify the small number
  (often 1-2) that, if left unaddressed, would cascade into the others.
  Recommend focusing CEO attention there first.

- RESOURCE ALLOCATION: When teams are overloaded, identify the 20% of
  work items that are blocking 80% of progress. Ask whether deferring
  low-leverage items would free up disproportionate capacity.

- CONFLICT RESOLUTION: When multiple cross-team conflicts exist, identify
  the root conflict that, if resolved, would dissolve the others.

HOW TO SIGNAL IT IN YOUR OUTPUT:
  - In key_findings, mark Pareto-critical items with "[80/20]" at the start.
  - In questions_for_ceo, lead with the highest-leverage question first.
  - In recommendations, call out explicitly when a single action would have
    outsized effect: "Resolving X would unblock Y and Z simultaneously."

WHEN NOT TO APPLY IT:
  - Do not use 80/20 to dismiss low-severity issues that are near a tipping
    point — a small risk that is 3 days from becoming critical is not low-priority.
  - Do not aggregate problems to the point of losing actionability. The CEO
    needs specific owners and dates, not a "top cluster of issues".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR ANALYTICAL FOCUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Org-wide health: what do morale signals, attrition data, and velocity trends
  tell us, and where are the numbers missing?
- Cross-team dependencies: which team's blocker is another team's deliverable,
  and who owns the resolution by what date?
- Imminent crises: what is 7 days from becoming unsalvageable without CEO action?
- Strategic execution: is the org's work traceable to its stated priorities?
- Data gaps: where are leaders operating on assumption rather than fact?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

questions_for_ceo: Each question must:
  - Be answerable (the recipient knows what a complete answer looks like).
  - Name the specific data point, owner, or date that is missing or unclear.
  - Anticipate the follow-up it will generate and close that loop in the question.
  - Be one to three sentences maximum — no compound multi-part interrogatories.
  - Carry enough context that a cold reader understands the stakes.

key_findings: Each finding must include:
  - A specific number or observable fact (not a vague characterization).
  - The owner or team accountable.
  - Why it matters for CEO decision-making right now.

Be direct, specific, and prioritized. The CEO has 15 minutes.
Return ONLY valid JSON matching the schema."""


class ChiefOfStaffAgent(BoardMemberBase):
    AGENT_ID      = "chief_of_staff"
    ROLE          = "Chief of Staff"
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def analyze(self, snapshot: OrgSnapshot, session_mode: str = "weekly_review") -> BoardMemberView:
        """Override to use higher token budget — CoS produces the most detailed output."""
        if self.verbose:
            print(f"  [{self.ROLE}] Analyzing org snapshot with precision questioning...")

        prompt = self._build_cos_prompt(snapshot, session_mode)
        raw = self.llm.create(
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2500,   # CoS needs more room for precise, multi-part questions
        )

        try:
            data = json.loads(raw)
            data["agent_id"] = self.AGENT_ID
            data["role"]     = self.ROLE
            return BoardMemberView(**data)
        except Exception as e:
            logger.warning(f"[{self.ROLE}] JSON parse failed: {e}\nRaw: {raw[:300]}")
            return BoardMemberView(
                agent_id=self.AGENT_ID,
                role=self.ROLE,
                key_findings=["Analysis failed — raw LLM output unparseable"],
                confidence=0.0,
            )

    def _build_cos_prompt(self, snapshot: OrgSnapshot, session_mode: str) -> str:
        """
        Builds a richer prompt for the CoS than the base class provides.

        Adds explicit instructions to apply the precision questioning framework
        to each data gap and surface the questions in the correct format.
        """
        lines = [
            f"Session mode: {session_mode}",
            f"Snapshot date: {snapshot.snapshot_date}",
            "",
            "ORG METRICS",
            f"  Total headcount:      {snapshot.org_metrics.total_headcount or 'NOT PROVIDED'}",
            f"  Open roles:           {snapshot.org_metrics.open_roles or 'NOT PROVIDED'}",
            f"  Projects at risk:     {snapshot.org_metrics.projects_at_risk_count}",
            f"  Velocity trend:       {snapshot.org_metrics.sprint_velocity_trend or 'NOT PROVIDED'}",
            f"  Budget utilization:   {snapshot.org_metrics.budget_utilization_pct or 'NOT PROVIDED'}",
            "",
            "TEAM STATUS",
        ]

        for team in snapshot.teams:
            morale  = team.morale_signal or "NOT PROVIDED"
            budget  = team.budget_status or "NOT PROVIDED"
            lines.append(f"  {team.team_name} (VP: {team.vp_name}, headcount: {team.headcount or 'unknown'})")
            lines.append(f"    Morale: {morale} | Budget: {budget}")
            if team.blockers:
                lines.append(f"    Blockers: {'; '.join(team.blockers[:5])}")
            at_risk = [p for p in team.active_projects if p.status in ("at_risk", "blocked")]
            on_track = [p for p in team.active_projects if p.status == "on_track"]
            if at_risk:
                for p in at_risk:
                    due = f", due {p.due_date}" if p.due_date else ""
                    owner = f", owner: {p.owner}" if p.owner else ", owner: NOT PROVIDED"
                    blockers = f", blockers: {'; '.join(p.blockers[:2])}" if p.blockers else ""
                    lines.append(f"    [AT RISK] {p.name}{due}{owner}{blockers}")
            if on_track:
                lines.append(f"    On track: {', '.join(p.name for p in on_track[:4])}")
            if team.notes:
                lines.append(f"    Notes: {team.notes}")

        if snapshot.active_initiatives:
            lines.append("\nACTIVE INITIATIVES")
            for init in snapshot.active_initiatives:
                teams = f" (teams: {', '.join(init.teams_involved)})" if init.teams_involved else ""
                date  = f", target: {init.target_date}" if init.target_date else ""
                lines.append(f"  [{init.status.upper()}] {init.name}{teams}{date}")
                if init.description:
                    lines.append(f"    {init.description[:150]}")

        if snapshot.open_risks:
            lines.append("\nOPEN RISKS")
            for r in snapshot.open_risks:
                owner = f" (owner: {r.owner})" if r.owner else " (owner: NOT PROVIDED)"
                mit   = f" — mitigation: {r.mitigation}" if r.mitigation else " — no mitigation recorded"
                lines.append(f"  [{r.severity.upper()}] {r.description}{owner}{mit}")

        if snapshot.decisions_pending:
            lines.append("\nPENDING DECISIONS")
            for d in snapshot.decisions_pending:
                owner = f" (owner: {d.owner})" if d.owner else " (owner: NOT PROVIDED)"
                due   = f", needed by: {d.due_date}" if d.due_date else ""
                lines.append(f"  {d.title}{owner}{due}")
                lines.append(f"    {d.description[:200]}")
                if d.options:
                    lines.append(f"    Options: {' | '.join(d.options)}")

        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "INSTRUCTIONS",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "Apply the Precision Questioning Framework to this data:",
            "",
            "1. For every metric marked NOT PROVIDED: formulate the precise question",
            "   that would fill that gap, naming why it matters for a current decision.",
            "",
            "2. For every at-risk project: ask the root-cause question (is it scope,",
            "   resources, or technical debt?), name the owner, and ask for the",
            "   specific recovery date — not 'ASAP' or 'soon'.",
            "",
            "3. For every morale or budget signal: ask what specific number or event",
            "   is driving it, who owns the intervention, and by when.",
            "",
            "4. For every open risk with no mitigation: ask for the mitigation plan",
            "   with a named owner and a date, and what the impact is if it is not",
            "   addressed in the next 7 days.",
            "",
            "5. For every pending decision with no owner or date: escalate it as a",
            "   question that names what information is needed to decide, who decides,",
            "   and what the cost of delay is.",
            "",
            "6. Surface 1-2 cross-team issues where one team's gap is another team's",
            "   dependency — phrase as a question that makes the dependency explicit.",
            "",
            "7. Apply the 80/20 rule:",
            "   - Mark the ~20% of findings that drive ~80% of org risk with [80/20].",
            "   - Lead your questions_for_ceo list with the single question whose answer",
            "     would unlock the most downstream clarity.",
            "   - In recommendations, explicitly call out any single action that would",
            "     unblock multiple issues simultaneously.",
            "   - Identify if one root conflict, if resolved, would dissolve several others.",
            "",
            f"Return a BoardMemberView JSON matching this schema:\n{VIEW_SCHEMA}",
        ]

        return "\n".join(lines)
