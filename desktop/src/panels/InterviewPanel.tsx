import { useState } from "react";
import { runInterviewPrep } from "../api";
import type { InterviewPrepBrief, STARAnswer } from "../types";
import { ContentDialog } from "../components/ContentDialog";

export function InterviewPanel() {
  const [jdText, setJdText] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [roleTitle, setRoleTitle] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InterviewPrepBrief | null>(null);

  async function handleRun() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runInterviewPrep({
        jd_text: jdText,
        company_name: companyName,
        role_title: roleTitle,
        depth: "full",
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <h3>Interview Prep</h3>
      <div className="form-stack">
        <div className="form-row">
          <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="Company name" />
          <input value={roleTitle} onChange={(e) => setRoleTitle(e.target.value)} placeholder="Role title" />
        </div>
        <textarea
          value={jdText}
          onChange={(e) => setJdText(e.target.value)}
          placeholder="Paste job description..."
          rows={8}
        />
        <button type="button" onClick={handleRun} disabled={loading}>
          {loading ? "Preparing..." : "Prepare"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {result && <BriefView brief={result} />}
    </div>
  );
}

function recommendationClass(rec: string): string {
  if (rec === "strong_fit") return "score-good";
  if (rec === "worth_pursuing") return "score-good";
  if (rec === "stretch") return "score-warn";
  return "score-bad";
}

function BriefView({ brief }: { brief: InterviewPrepBrief }) {
  const [openAnswer, setOpenAnswer] = useState<STARAnswer | null>(null);
  const [resumeOpen, setResumeOpen] = useState(false);

  return (
    <div className="brief-view">
      <h2>
        {brief.company_name} — {brief.role_title}
      </h2>

      <div className="stat-row">
        <div className={`stat-badge ${recommendationClass(brief.fit.recommendation)}`}>
          {brief.fit.recommendation.replace(/_/g, " ")} ({brief.fit.overall_score.toFixed(1)}/10)
        </div>
      </div>
      <p>{brief.fit.summary}</p>

      <div className="two-col">
        <div>
          <h4>Match Strengths</h4>
          <ul>
            {brief.fit.match_strengths.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Gaps</h4>
          <ul>
            {brief.fit.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </div>
      </div>

      {brief.fit.deal_breakers.length > 0 && (
        <>
          <h4>Deal Breakers</h4>
          <ul className="risk-list">
            {brief.fit.deal_breakers.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </>
      )}

      <h4>Company &amp; Culture</h4>
      <p>{brief.company.culture_summary}</p>
      <p className="muted">Interview style: {brief.company.interview_style}</p>
      {brief.company.known_values.length > 0 && (
        <p className="muted">Values: {brief.company.known_values.join(", ")}</p>
      )}

      <h4>Top 3 Priorities</h4>
      <ol>
        {brief.top_3_priorities.map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ol>

      <h4>Practice Questions</h4>
      <div className="two-col">
        <QuestionGroup title="Behavioural" items={brief.questions.behavioural} />
        <QuestionGroup title="Technical" items={brief.questions.technical} />
        <QuestionGroup title="Culture Fit" items={brief.questions.culture_fit} />
        <QuestionGroup title="Curveball" items={brief.questions.curveball} />
      </div>

      {brief.answers.answers.length > 0 && (
        <>
          <h4>STAR Answers</h4>
          <ul className="answer-list">
            {brief.answers.answers.map((a, i) => (
              <li key={i}>
                <button type="button" className="link-btn" onClick={() => setOpenAnswer(a)}>
                  {a.question}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {brief.tailored_resume && (
        <>
          <h4>Tailored Resume</h4>
          <p>{brief.tailored_resume.summary}</p>
          <button type="button" onClick={() => setResumeOpen(true)}>
            View Full Resume
          </button>
        </>
      )}

      <ContentDialog title={openAnswer?.question ?? ""} open={openAnswer !== null} onClose={() => setOpenAnswer(null)}>
        {openAnswer && (
          <div>
            <p>
              <strong>Situation:</strong> {openAnswer.situation}
            </p>
            <p>
              <strong>Task:</strong> {openAnswer.task}
            </p>
            <p>
              <strong>Action:</strong> {openAnswer.action}
            </p>
            <p>
              <strong>Result:</strong> {openAnswer.result}
            </p>
            <p className="muted">{openAnswer.tailoring_note}</p>
          </div>
        )}
      </ContentDialog>

      <ContentDialog title="Tailored Resume" open={resumeOpen} onClose={() => setResumeOpen(false)}>
        <pre className="resume-md">{brief.tailored_resume?.full_resume_md}</pre>
      </ContentDialog>
    </div>
  );
}

function QuestionGroup({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h5>{title}</h5>
      <ul>
        {items.map((q, i) => (
          <li key={i}>{q}</li>
        ))}
      </ul>
    </div>
  );
}
