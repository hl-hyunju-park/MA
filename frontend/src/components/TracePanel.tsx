import { useState } from "react";
import type { TraceStep } from "../api";

// Collapsible "추론 과정" panel: one row per pipeline agent decision
// (planner → router → retriever → verifier → synthesizer).
export default function TracePanel({
  steps,
  defaultOpen,
}: {
  steps: TraceStep[];
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (steps.length === 0) return null;

  return (
    <div className={`trace ${open ? "open" : ""}`}>
      <button className="trace-summary" onClick={() => setOpen((o) => !o)}>
        <span className="caret">▸</span>
        추론 과정 · {steps.length}단계
      </button>
      {open && (
        <div className="steps">
          {steps.map((s, i) => (
            <div className="step" key={i}>
              <span className="n">{s.step}</span>
              {s.agent && <span className={`agent ${s.agent.toLowerCase()}`}>{s.agent}</span>}
              <span className={`act ${s.action.toLowerCase()}`}>{s.action}</span>
              <div className="step-body">
                {s.arg && <div className="arg">{s.arg}</div>}
                {s.thought && <div className="thought">{s.thought}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
