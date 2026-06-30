import type { Source } from "../api";

// "Where it actually came from" — the cell-anchored sources the answer was built from, grouped by
// the page/file they came from and shown as a nav-folder breadcrumb (2. 재무 › 2.9. 특수관계자 › …).
// Hidden when the agent cited nothing.

// Full folder breadcrumb: the backend's nav path when present, else the page key's "__" segments.
function crumb(s: Source): string {
  const parts = s.path && s.path.length ? s.path : s.page.split("__");
  return parts.map((p) => p.trim()).filter(Boolean).join(" › ");
}

// A plain number (incl. scientific notation) → thousands-separated; leave %, IDs-as-text, prose alone.
function fmtValue(v: string): string {
  const t = v.trim();
  if (/^-?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(t)) {
    const n = Number(t);
    if (Number.isFinite(n)) return n.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  }
  return v;
}

export default function SourcesPanel({ sources }: { sources: Source[] }) {
  if (!sources || sources.length === 0) return null;

  // group cells under their source page, preserving first-seen order
  const byPage = new Map<string, Source[]>();
  for (const s of sources) {
    const arr = byPage.get(s.page);
    if (arr) arr.push(s);
    else byPage.set(s.page, [s]);
  }

  return (
    <details className="sources">
      <summary>
        출처 · {byPage.size}개 자료 · {sources.length}개 셀
      </summary>
      <ul className="src-list">
        {[...byPage.entries()].map(([page, cells]) => (
          <li key={page} className="src-item">
            <div className="src-page" title={page}>
              {crumb(cells[0])}
            </div>
            <ul className="src-cells">
              {cells.map((c, i) => (
                <li key={`${c.cell}-${i}`}>
                  <code>{c.cell}</code>
                  {c.term ? <span className="src-term"> {c.term}</span> : null}
                  {c.value ? <span className="src-val"> = {fmtValue(c.value)}</span> : null}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </details>
  );
}
