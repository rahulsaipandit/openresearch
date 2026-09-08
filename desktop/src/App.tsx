import { useState } from "react";
import { StockPanel } from "./panels/StockPanel";
import { BoardPanel } from "./panels/BoardPanel";
import { InterviewPanel } from "./panels/InterviewPanel";
import { RealEstatePanel } from "./panels/RealEstatePanel";

// The shared Tauri shell across all four OpenResearch verticals — see
// requirements.md "Target Architecture": Tauri replaces the planned-but-
// unbuilt Chrome Extension as the one desktop shell, not a stock-only app.

type Vertical = "stock" | "board" | "interview" | "realestate";

const TABS: { id: Vertical; label: string }[] = [
  { id: "stock", label: "Stock Research" },
  { id: "board", label: "Executive Board" },
  { id: "interview", label: "Interview Prep" },
  { id: "realestate", label: "Real Estate" },
];

export default function App() {
  const [active, setActive] = useState<Vertical>("stock");

  return (
    <div className="app-shell">
      <nav className="app-nav">
        <div className="app-nav-title">OpenResearch</div>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`app-nav-item ${active === tab.id ? "active" : ""}`}
            onClick={() => setActive(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <main className="app-content">
        {active === "stock" && <StockPanel />}
        {active === "board" && <BoardPanel />}
        {active === "interview" && <InterviewPanel />}
        {active === "realestate" && <RealEstatePanel />}
      </main>
    </div>
  );
}
