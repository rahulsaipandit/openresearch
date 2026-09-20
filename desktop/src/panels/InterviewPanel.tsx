import { useState } from "react";
import { deleteInterviewQuestion, getInterviewQuestions, runInterviewPrep } from "../api";
import type { InterviewPrepBrief, QuestionRecord, STARAnswer } from "../types";
import { ContentDialog } from "../components/ContentDialog";
import { AnswerTesterSection, DocumentLibrarySection } from "./DocumentLibraryPanel";

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

      <QuestionHistorySection />
      <DocumentLibrarySection />
      <AnswerTesterSection />
    </div>
  );
}

function QuestionHistorySection() {
  const [candidateId, setCandidateId] = useState("");
  const [questions, setQuestions] = useState<QuestionRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<QuestionRecord | null>(null);

  async function handleLoad() {
    if (!candidateId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getInterviewQuestions(candidateId.trim());
      setQuestions(res.questions);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(questionId: string) {
    try {
      await deleteInterviewQuestion(candidateId.trim(), questionId);
      setQuestions((prev) => prev.filter((q) => q.id !== questionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="panel">
      <h3>Live Interview Question History</h3>
      <div className="query-box">
        <input
          value={candidateId}
          onChange={(e) => setCandidateId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLoad()}
          placeholder="Candidate ID"
        />
        <button type="button" onClick={handleLoad} disabled={loading}>
          {loading ? "Loading..." : "Load"}
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}

      <ul className="watchlist-grid">
        {questions.map((q) => (
          <li key={q.id} className="watchlist-row">
            <button type="button" className="link-btn" onClick={() => setViewing(q)}>
              {q.question_text || "(untitled question)"}
            </button>
            <span className="added-at">
              {q.topic} · {q.timestamp ? new Date(q.timestamp).toLocaleString() : ""}
              {q.judge_score !== null && ` · score ${q.judge_score.toFixed(1)}`}
            </span>
            <button type="button" className="remove-btn" onClick={() => handleDelete(q.id)}>
              Delete
            </button>
          </li>
        ))}
        {questions.length === 0 && <li className="empty-state">No questions loaded yet.</li>}
      </ul>

      <ContentDialog title={viewing?.question_text ?? ""} open={viewing !== null} onClose={() => setViewing(null)}>
        {viewing && (
          <div>
            <p>
              <strong>Answer:</strong> {viewing.answer_text}
            </p>
            {viewing.judge_rationale && (
              <p className="muted">
                <strong>Judge rationale:</strong> {viewing.judge_rationale}
              </p>
            )}
          </div>
        )}
      </ContentDialog>
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
