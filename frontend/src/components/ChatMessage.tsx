import { highlightCells } from "../format";
import TracePanel from "./TracePanel";
import type { TraceStep } from "../api";

export interface ChatTurn {
  id: number;
  role: "user" | "bot";
  text: string; // empty while the bot is still thinking
  trace: TraceStep[];
  status: "thinking" | "done" | "error";
}

export default function ChatMessage({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === "user";
  return (
    <div className={`msg ${turn.role}`}>
      <div className="role">{isUser ? "나" : "Stella"}</div>

      {isUser ? (
        <div className="bubble">{turn.text}</div>
      ) : (
        <>
          {turn.status === "thinking" && turn.text === "" && (
            <div className="thinking">
              <span className="pulse" />
              위키를 탐색하는 중…
            </div>
          )}
          <TracePanel steps={turn.trace} defaultOpen={turn.status === "thinking"} />
          {turn.text !== "" && (
            <div className={`bubble ${turn.status === "error" ? "error" : ""}`}>
              {turn.status === "error" ? `⚠ ${turn.text}` : highlightCells(turn.text)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
