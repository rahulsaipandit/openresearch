import { useState } from "react";
import { runRealEstateResearch } from "../api";
import type { RealEstateBrief } from "../types";
import { KeyValueList } from "../components/KeyValueList";
import { US_STATES, resolveStateInput, stateOptionLabel } from "../constants/usStates";

export function RealEstatePanel() {
  const [city, setCity] = useState("");
  const [stateInput, setStateInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RealEstateBrief | null>(null);

  async function handleRun() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const state = resolveStateInput(stateInput);
      const res = await runRealEstateResearch({ city, state, depth: "full" });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <h3>Real Estate Research</h3>
      <div className="form-row">
        <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="City" />
        <input
          list="us-states-datalist"
          value={stateInput}
          onChange={(e) => setStateInput(e.target.value)}
          placeholder="State (type name or abbreviation)"
        />
        <datalist id="us-states-datalist">
          {US_STATES.map((s) => (
            <option key={s.code} value={stateOptionLabel(s)} />
          ))}
        </datalist>
        <button type="button" onClick={handleRun} disabled={loading}>
          {loading ? "Researching..." : "Research"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {result && <BriefView brief={result} />}
    </div>
  );
}

function signalClass(signal: string): string {
  if (signal === "Strong Buy" || signal === "Buy") return "score-good";
  if (signal === "Hold") return "score-warn";
  return "score-bad";
}

function BriefView({ brief }: { brief: RealEstateBrief }) {
  return (
    <div className="brief-view">
      <h2>
        {brief.address ? `${brief.address}, ` : ""}
        {brief.city}, {brief.state}
      </h2>

      <div className="stat-row">
        <div className={`stat-badge ${signalClass(brief.investment_signal)}`}>{brief.investment_signal}</div>
        <div className="stat-badge">{brief.demand_verdict.replace(/_/g, " ")}</div>
        <div className="stat-badge">Confidence {(brief.confidence * 100).toFixed(0)}%</div>
      </div>

      <p>{brief.summary}</p>

      <div className="two-col">
        <div>
          <h4>Pull Factors</h4>
          <ul>
            {brief.dominant_pull_factors.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Push Factors</h4>
          <ul>
            {brief.dominant_push_factors.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      </div>

      {brief.key_risks.length > 0 && (
        <>
          <h4>Key Risks</h4>
          <ul className="risk-list">
            {brief.key_risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </>
      )}

      {brief.upcoming_catalysts.length > 0 && (
        <>
          <h4>Upcoming Catalysts</h4>
          <ul>
            {brief.upcoming_catalysts.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      )}

      <h4>Migration</h4>
      <div className="two-col">
        <div>
          <p className="muted">City</p>
          <KeyValueList data={brief.city_migration} />
        </div>
        <div>
          <p className="muted">State</p>
          <KeyValueList data={brief.state_migration} />
        </div>
      </div>
      {brief.migration_divergence && <p className="muted">{brief.migration_divergence}</p>}

      <h4>Labor Market</h4>
      <KeyValueList data={brief.labor_market} />

      <h4>Housing Market</h4>
      <KeyValueList data={brief.housing_market} />

      <h4>Cost of Living</h4>
      <KeyValueList data={brief.cost_of_living} />

      <h4>Demand Factors</h4>
      <KeyValueList data={brief.demand_factors} />

      {brief.climate_risk && (
        <>
          <h4>Climate &amp; Flood Risk</h4>
          <KeyValueList data={brief.climate_risk} />
        </>
      )}

      {brief.rental_analysis && (
        <>
          <h4>Rental Analysis</h4>
          <KeyValueList data={brief.rental_analysis} />
        </>
      )}

      {brief.data_gaps.length > 0 && (
        <>
          <h4>Data Gaps</h4>
          <ul className="muted">
            {brief.data_gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </>
      )}

      {brief.sources.length > 0 && (
        <>
          <h4>Sources</h4>
          <ol className="citation-list">
            {brief.sources.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
