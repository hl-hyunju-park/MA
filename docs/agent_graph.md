# Agent graph

The query agent (`apps/agent`) is a LangGraph `StateGraph` compiled by
`apps/agent/graph/build.py`. Interactive view: open
[`agent_graph.html`](agent_graph.html) in a browser (drag nodes, Cytoscape.js — the same
style as the *langgraph-visualizer* VS Code extension, which can also auto-render
`build.py` live in the editor).

## Compiled topology

What LangGraph actually compiles — the `solve` step is a single node that fans out via the
`Send` API (dotted edge) and runs the router→retriever→verifier loop internally.

```mermaid
graph TD;
  __start__([__start__]) --> planner;
  planner -. "Send · one per sub-question" .-> solve;
  solve --> synthesizer;
  synthesizer --> __end__([__end__]);
```

## Expanded pipeline

What runs at query time. The planner splits the question; each sub-question becomes a
concurrent `solve` branch (≤4 in flight, semaphore-bounded); the synthesizer joins once all
branches have merged their evidence/paths/trace into the `operator.add` channels.

```mermaid
flowchart TD;
  START([__start__]) --> P["🧭 planner<br/><i>question → ordered sub-questions<br/>tags each lookup | trace + direction</i>"];

  P -. "Send · sub-Q 0" .-> B0;
  P -. "Send · sub-Q 1" .-> B1;
  P -. "Send · sub-Q N" .-> Bn;

  subgraph FAN["parallel solve branches — ≤4 concurrent (STELLA_FANOUT semaphore)"];
    direction LR;
    subgraph B0["solve · branch 0"];
      direction TB;
      R0["🔀 router<br/><i>lookup → pick page(s)<br/>trace → walk formula DAG</i>"] --> T0["📄 retriever<br/><i>open pages · 1 LLM call / page (fan-out)</i>"];
      T0 --> V0{"✅ verifier"};
      V0 -. "gap → retry (avoid tried)" .-> R0;
    end;
    subgraph B1["solve · branch 1"];
      direction TB;
      R1["🔀 router"] --> T1["📄 retriever"] --> V1{"✅ verifier"};
      V1 -. retry .-> R1;
    end;
    subgraph Bn["solve · branch N"];
      direction TB;
      Rn["🔀 router"] --> Tn["📄 retriever"] --> Vn{"✅ verifier"};
      Vn -. retry .-> Rn;
    end;
  end;

  B0 --> SY["📝 synthesizer<br/><i>join evidence + provenance paths<br/>→ cited Korean answer</i>"];
  B1 --> SY;
  Bn --> SY;
  SY --> END([__end__]);
```

**Merge channels (reducers).** Branches never share working state — picked pages, retries,
and the per-page extraction stay local inside `solve_node`. They return only the
`operator.add` channels, which LangGraph concatenates/sums across the parallel barrier:

| channel | reducer | carries |
|---|---|---|
| `evidence` | `operator.add` | `[{page, cell, term, value, ask}]` from every page read |
| `paths`    | `operator.add` | provenance chains traced over the sheet-level formula DAG |
| `trace`    | `operator.add` | per-turn records (tagged with `sub`; renumbered in `core`) |
| `steps`    | `operator.add` | retriever reads consumed (total work) |

Deterministic tools (no LLM): `lookup` (term→page), `open_page` (page→facts), `trace_links`
(BFS over the formula DAG). The LLM only routes and writes prose.
