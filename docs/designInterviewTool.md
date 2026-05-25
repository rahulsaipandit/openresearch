# Interview Prep Pipeline Design

Here's my assessment of mirrorwork and whether it's a good fit for openresearch:

## Mirrorwork Fit Assessment for OpenResearch

### What Mirrorwork Is

Mirrorwork is a local-first, CLI-based career tool for senior software engineers searching for jobs. Its core features:

- **Job fit brutality check** — Candid assessment of experience-vs-JD match
- **Company-modelled interview prep** — Researches employer interview style, generates STAR-format answers from your profile
- **Spaced repetition learning** — SM-2 algorithm to track and resurface knowledge gaps
- **Application tracking** — Pipeline metrics

**Tech:** Python, Claude Code agents, MCP, Anthropic Claude API, local-first.

### Fit Assessment: Not a Natural Match

| Dimension        | OpenResearch                          | Mirrorwork                              |
|------------------|---------------------------------------|-----------------------------------------|
| Target user      | Executive / org leader                | Job-seeking software engineer           |
| Domain           | Org intelligence, stock research      | Career/hiring pipeline                  |
| LLM integration  | FastAPI server, multi-provider        | Claude Code agent + MCP                 |
| Data sources     | Jira, Linear, Notion, Slack, SEC, Yahoo Finance | Resume, JD text, web company research |
| Output           | Board briefings, research briefs      | Interview prep, fit verdicts            |

The personas don't overlap. OpenResearch serves executives making organizational decisions; mirrorwork serves engineers optimizing their job search. These are essentially opposite ends of the hiring relationship.

### Where There Could Be Crossover

There are two narrow integration angles worth considering:

- **VP People agent enhancement** — Mirrorwork's job-fit scoring logic (experience vs. JD gap analysis) could inform your VP People agent's talent assessment or hiring advisory capabilities. If your exec board is advising on org health, a "candidate quality signal" or "role spec alignment" tool could be relevant.
- **Architecture patterns worth borrowing** — The SM-2 spaced repetition approach for surfacing recurring org issues (your ConflictDetector already does episodic conflict tracking) is an interesting structural idea. Not a direct lift, but a design pattern worth considering for the planned Executive Heuristics Library.
- **Company research module** — Mirrorwork does company intelligence (interview culture, values). Your planned Executive Review Prep Assistant also involves org-level pattern reasoning. The approach to company research is related, even if the purpose differs.

### Recommendation: Skip the integration, consider the patterns

The codebase isn't directly usable — the user story, data model, and agent goals are misaligned with where OpenResearch is going. Bolting on a job-search tool to an executive intelligence platform would dilute focus.

However, two things from mirrorwork are worth a closer look:

- **SM-2 / spaced repetition** — Could be adapted for the planned Executive Heuristics Library to resurface recurring org risk patterns across review cycles
- **STAR-format structured reasoning** — A good pattern for how your board agents articulate findings (Situation → Task → Action → Result) in the planned BoardBriefing output

If your roadmap eventually expands to include a talent intelligence / executive hiring advisory module (which would fit naturally under the VP People agent), revisiting mirrorwork as a reference implementation would make more sense then.

## Comparison: OpenResearch Interview Prep vs InterviewMentor

https://github.com/PrepLabsAI/InterviewMentor

They solve different halves of the same problem — they're actually complementary, not competitors.

| Category        | Preparation Pipeline                                   | Mock Interview Simulator               |
| --------------- | ------------------------------------------------------ | -------------------------------------- |
| Core paradigm   | Preparation pipeline                                   | Mock interview simulator               |
| Input           | Your resume + a job description                        | You show up and practice               |
| Output          | Tailored brief, resume, STAR answers                   | Scorecard + performance rating         |
| Tech            | Python pipeline, FastAPI, Pydantic, LLM agents         | Markdown prompt files, zero code       |
| Persistence     | JSON stores (profile, tracker, SM-2 skills bank)       | Stateless (no memory between sessions) |
| Personalisation | Deep - every output is keyed to your actual experience | None - same prompt for everyone        |

### What OpenResearch Interview Prep Does Better

✅ **Candidate-centric personalisation**  
The entire pipeline is anchored to your MasterProfile. The fit analysis, STAR answers, tailored resume, and questions are all generated from your actual work history. InterviewMentor has no concept of who you are - it gives every user the same Uber system design problem.

✅ **Resume → role mapping**  
Node 5 (ResumeWriterAgent) rewrites your master profile as a JD-targeted resume with a transparency log (tailoring_notes). InterviewMentor can't do this at all - it has no input channel for your background.

✅ **Job fit intelligence**  
The JobFitAnalyzerAgent applies an 80/20 gap analysis: it identifies the 20% of missing qualifications causing 80% of rejection risk and flags deal_breakers. That tells you whether to apply, not just how to prepare. InterviewMentor skips this entirely.

✅ **Live company intelligence**  
CompanyResearcherAgent fires 3 Brave Search queries and injects live Glassdoor / engineering blog data into the brief before the LLM call. InterviewMentor's prompts use only training-data knowledge - no live web.

✅ **Long-term learning system**  
The SM-2 spaced repetition tracker (store/skills_store.py) seeds every question generated from a run into a reviewable bank. /api/learn/due tells you what to review today. InterviewMentor has no persistence - close the session and it's gone.

✅ **Application tracking and analytics**  
ApplicationStore logs every run with stage, outcome, and fit score. GET /api/tracker/insights computes win rate, funnel drop-off, and fit-score correlation. InterviewMentor has no concept of an application lifecycle.

✅ **Composable infrastructure**  
Because it's a proper pipeline on FastAPI, it integrates with Tolaria/Obsidian vault, the stock research tool, and the executive board. It can be exposed as an MCP tool (Phase 7). InterviewMentor is a standalone Claude Code plugin with no integration surface.

### What InterviewMentor Does Better

✅ **Mock interview simulation**  
This is its defining strength - and it's a gap in OpenResearch. InterviewMentor puts you in the interview: an adaptive AI interviewer asks follow-ups, responds to your answers, and adjusts difficulty in real time. OpenResearch generates prep materials before the interview but doesn't simulate the interview itself.

✅ **40+ specialised domains**  
50+ skill modules: arrays/hashmaps, dynamic programming, graph algorithms, distributed systems, Kubernetes, MySQL performance, ML system design, AI PM, leadership principles - breadth that would take months to match. OpenResearch's QuestionGeneratorAgent produces a single question set (15 questions: 5 behavioural + 5 technical + 3 culture + 2 curveball) per run.

✅ **4-level hint system**  
During practice, the interviewer can give a gentle nudge, a pattern suggestion, approach guidance, or a full walkthrough - adaptive to how stuck you are. OpenResearch generates answers for you (STAR format), but there's no interactive coaching loop.

✅ **Zero setup, zero infrastructure**  
No Python, no server, no API keys, no config. Clone the repo, run `claude --plugin-dir`, and start an interview in 30 seconds. OpenResearch requires a running FastAPI server, API keys (Anthropic, optionally Brave/NewsAPI), and a candidate profile already loaded.

✅ **Scorecard evaluation**  
Post-interview rubric scores you on Problem Understanding, Solution Approach, Code Quality, Complexity Analysis, Edge Cases, and Communication. OpenResearch's FitVerdict scores fit (0–10) against the JD but doesn't evaluate your actual performance in practice.

### Key Gaps in Each

| Gap                          | OpenResearch                                     | InterviewMentor                                |
| ---------------------------- | ------------------------------------------------ | ---------------------------------------------- |
| No mock interview loop       | ❌ You get answers but can't practice giving them | -                                              |
| No scorecard on live answers | ❌ SM-2 tracks retention, not performance quality | -                                              |
| No personalisation           | -                                                | ❌ Every user gets the same problem             |
| No resume processing         | -                                                | ❌ Can't rewrite your CV for a role             |
| No fit assessment            | -                                                | ❌ Can't tell you if the role is worth pursuing |
| No application tracking      | -                                                | ❌ No longitudinal view across applications     |
| No live web data             | -                                                | ❌ Company research is training-data only       |
| Setup friction               | ❌ Server + keys + config                         | -                                              |
| Stateless (no memory)        | -                                                | ❌ No SM-2, no learning curve                   |


## The Obvious Synthesis
The ideal interview prep workflow is OpenResearch first, InterviewMentor second:
1. POST /api/profile/add-resume          ← load your profile
2. POST /api/interview-prep              ← get fit score, tailored resume,
                                            company brief, STAR answers
3. Review the InterviewPrepBrief         ← know your story cold
4. /uber-interviewer (InterviewMentor)   ← simulate the actual interview
5. Score yourself on the rubric          ← identify weak dimensions
6. GET /api/learn/due                    ← review the questions you
                                            flagged as weak (SM-2)
**Steps 1–3 and 6 are OpenResearch; steps 4–5 are InterviewMentor**. Neither tool covers the full loop alone.

## Verdict

**Use OpenResearch Interview Prep when**: you have a specific JD, want to know if it's a fit, need a tailored resume, want STAR answers drawn from your real experience, and want to track your application pipeline over time.

**Use InterviewMentor when**: you want to drill a specific technical domain (system design, DP, Kubernetes), need adaptive live practice, or want an outside-in scorecard on how well you actually perform under pressure.

If you wanted to close the gap, the single highest-value addition to OpenResearch would be a **Node 6: MockInterviewAgent** — a follow-up session that takes the generated QuestionSet and runs an interactive round where it evaluates your spoken/typed answers, adapts its follow-ups, and produces a post-session scorecard appended to the ApplicationRecord.
