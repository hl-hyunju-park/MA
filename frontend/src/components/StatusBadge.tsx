import { useEffect, useState } from "react";
import { getHealth, type Health } from "../api";

// Live backend/LLM health pill, polled every 15s (matches the HTML fallback's cadence).
export default function StatusBadge() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const h = await getHealth();
        if (alive) {
          setHealth(h);
          setDown(false);
        }
      } catch {
        if (alive) setDown(true);
      }
    };
    poll();
    const id = setInterval(poll, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const ok = !down && health?.status === "ok";
  const label = down
    ? "서버 연결 끊김"
    : ok
      ? `${health!.wiki_pages} 페이지 · ${health!.llm.model}`
      : "LLM 연결 끊김";

  return (
    <div className="status">
      <span className={`dot ${ok ? "ok" : "err"}`} />
      <span>{label}</span>
    </div>
  );
}
