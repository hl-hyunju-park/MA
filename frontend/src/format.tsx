import type { ReactNode } from "react";

// Sheet!Cell references (e.g. "DCF 장표 #1_MGT!E10", "AUM Projection!B12") are the
// agent's provenance. Highlight them inline as <code> so every number is traceable.
const CELL_RE = /([A-Za-z0-9 가-힣()_#.&,\-]+![A-Z]{1,3}\d{1,4})/g;

export function highlightCells(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  CELL_RE.lastIndex = 0;
  while ((m = CELL_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(
      <code key={`${m.index}-${m[0]}`} className="cell-ref">
        {m[0]}
      </code>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
