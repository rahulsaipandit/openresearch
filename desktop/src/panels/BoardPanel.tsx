import { useState } from "react";
import { getBoardStatus, runBoardSession } from "../api";
import type { BoardBriefing } from "../types";

export function BoardPanel() {
  const [context, setContext] = useState("");
  const [mode, setMode] = useState("weekly_review");
  const [status, setStatus] = useState<"idle" | "running" | "done" | "failed">("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BoardBriefing | null>(null);

  async function handleRun() {
    setStatus("running");
    setError(null);
    setResult(null);
    try {
      const { session_id } = await runBoardSession({
        mode,
        context,
        data_sources: [],
        raw_paste: context,
      });

      const poll = setInterval(async () => {
        try {
          const res = await getBoardStatus(session_id);
          if (res.status === "running") return;
          clearInterval(poll);
          if (res.status === "failed") {
            setStatus("failed");
            setError(res.error ?? "Board session failed.");
          } else {
            setStatus("done");
            setResult(res.result);
          }
        } catch (e) {
          clearInterval(poll);
          setStatus("failed");
          setError(e instanceof Error ? e.message : String(e));
        }
      }, 2000);
    } catch (e) {
      setStatus("failed");
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="panel">
      <h3>Executive Board</h3>
      <div className="form-stack">
        <select className="select-narrow" value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="weekly_review">Weekly Review</option>
          <option value="decision_advisory">Decision Advisory</option>
          <option value="health_scan">Health Scan</option>
        </select>
        <textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          placeholder="Paste org context, or raise a decision to get board input on..."
          rows={6}
        />
        <button type="button" onClick={handleRun} disabled={status === "running"}>
          {status === "running" ? "Running (board members are deliberating)..." : "Run Session"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {result && <BriefingView briefing={result} />}
    </div>
  );
}

function healthColor(score: number): string {
  if (score >= 7) return "score-good";
  if (score >= 4) return "score-warn";
  return "score-bad";
}

function BriefingView({ briefing }: { briefing: BoardBriefing }) {
  return (
    <div className="brief-view">
      <div className="stat-row">
        <div className={`stat-badge ${healthColor(briefing.org_health_score)}`}>
          Org Health: {briefing.org_health_score.toFixed(1)}/10
        </div>
        <div className="stat-badge">{briefing.mode.replace(/_/g, " ")}</div>
      </div>

      <p>{briefing.executive_summary}</p>

      {briefing.red_flags.length > 0 && (
        <>
          <h4>Red Flags</h4>
          <ul className="risk-list">
            {briefing.red_flags.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </>
      )}

      <h4>Top Priorities</h4>
      <ol>
        {briefing.top_priorities.map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ol>

      {briefing.action_items.length > 0 && (
        <>
          <h4>Action Items</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>Description</th>
                <th>Owner</th>
                <th>Due</th>
                <th>Priority</th>
              </tr>
            </thead>
            <tbody>
              {briefing.action_items.map((a, i) => (
                <tr key={i}>
                  <td>{a.description}</td>
                  <td>{a.owner}</td>
                  <td>{a.due_date ?? "—"}</td>
                  <td>
                    <span className={`priority priority-${a.priority}`}>{a.priority}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {briefing.cross_team_conflicts.length > 0 && (
        <>
          <h4>Cross-Team Conflicts</h4>
          {briefing.cross_team_conflicts.map((c, i) => (
            <div key={i} className="card">
              <p>
                <strong>{c.description}</strong>{" "}
                <span className={`priority priority-${c.severity}`}>{c.severity}</span>
              </p>
              {c.parties.length > 0 && <p className="muted">Parties: {c.parties.join(", ")}</p>}
              {c.suggested_resolution && <p>Suggested resolution: {c.suggested_resolution}</p>}
            </div>
          ))}
        </>
      )}

      <h4>Board Member Views</h4>
      <div className="board-member-grid">
        {briefing.board_member_views.map((m) => (
          <div key={m.agent_id} className="card">
            <h5>{m.role}</h5>
            {m.key_findings.length > 0 && (
              <>
                <p className="muted">Findings</p>
                <ul>
                  {m.key_findings.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </>
            )}
            {m.recommendations.length > 0 && (
              <>
                <p className="muted">Recommendations</p>
                <ul>
                  {m.recommendations.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </>
            )}
            {m.questions_for_ceo.length > 0 && (
              <>
                <p className="muted">Questions for CEO</p>
                <ul>
                  {m.questions_for_ceo.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        ))}
      </div>

      {briefing.decisions_recommended.length > 0 && (
        <>
          <h4>Decisions Recommended</h4>
          {briefing.decisions_recommended.map((d, i) => (
            <div key={i} className="card">
              <p>
                <strong>{d.title}</strong>
              </p>
              <p>{d.description}</p>
              {d.recommended && <p>Recommended: {d.recommended}</p>}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
