# Agent graph

The query agent (`apps/agent`) is **two backends behind one router**. `core.answer()`
first calls `core.route()` — an LLM classifier — to pick a backend, then dispatches:

- **wiki** (default) — the Centroid valuation KB. A LangGraph `StateGraph` compiled by
  `apps/agent/graph/build.py`: planner → fan-out `solve` (router→retriever→verifier) →
  synthesizer, over deterministic wiki reads.
- **dart** — public listed companies. A native tool-calling agent (`apps/agent/dart_agent.py`,
  LangChain `create_agent`) that calls the DART MCP server over SSE.

`get_graph()` only sees the *wiki* `StateGraph` — the `route` tier and the DART branch live
in `core.py`, outside the compiled graph — so the full architecture is drawn here, not by
LangGraph. Interactive view: open [`agent_graph.html`](agent_graph.html) in a browser
(drag nodes, Cytoscape.js).

## Full architecture

Everything `core.answer()` can do — both backends and the router that chooses between them.
This is the diagram the visualizer renders to PNG.

<!-- full-arch:begin -->
```mermaid
flowchart TD;
  Q(["question"]) --> RT{"🧭 route<br/><i>LLM classifies backend</i>"};
  RT -- "dart · public listed co." --> DART;
  RT -- "wiki · Centroid KB (default / fallback)" --> WIKI;

  subgraph DART["DART backend — native tool-calling (dart_agent.py)"];
    direction TB;
    DA["🤖 create_agent loop<br/><i>tool-LLM :8001 picks a DART tool + args</i>"];
    DT[("DART MCP tools")];
    DA -. "MCP over SSE (:8002, bearer)" .-> DT;
    DT -. "tool result" .-> DA;
  end;

  subgraph WIKI["wiki backend — LangGraph StateGraph (build.py)"];
    direction TB;
    P["🧭 planner<br/><i>question → ordered sub-questions</i>"];
    subgraph SB["solve branch ×N (parallel, ≤4 concurrent)"];
      direction TB;
      R["🔀 router<br/><i>lookup→page · trace→formula DAG</i>"] --> TR["📄 retriever<br/><i>open pages · 1 LLM / page</i>"];
      TR --> V{"✅ verifier"};
      V -. "gap → retry (avoid tried)" .-> R;
    end;
    P -. "Send · one per sub-Q" .-> SB;
    SB --> SY["📝 synthesizer<br/><i>join evidence + provenance → cited answer</i>"];
  end;

  DART --> A(["cited answer + trace"]);
  WIKI --> A;
```
<!-- full-arch:end -->

Deterministic tools (no LLM) on the wiki side: `lookup` (term→page), `open_page`
(page→facts), `trace_links` (BFS over the formula DAG). The LLM only routes and writes prose.
On the DART side the model itself calls the tools — the gemma-4 container is served *with*
`--tool-call-parser gemma4`, unlike the guest vLLM the wiki agent uses.

## Wiki backend — compiled topology

What LangGraph actually compiles (`build_app().get_graph()`) — the `solve` step is a single
node that fans out via the `Send` API (dotted edge) and runs the router→retriever→verifier
loop internally.

```mermaid
graph TD;
  __start__([__start__]) --> planner;
  planner -. "Send · one per sub-question" .-> solve;
  solve --> synthesizer;
  synthesizer --> __end__([__end__]);
```

## Wiki backend — expanded pipeline

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

## DART backend — tool-calling loop

`dart_agent.run_dart()` builds a LangChain `create_agent` over the DART MCP tools (fetched
from the SSE server with a bearer token) and a tools-capable gemma-4 model. The model loops:
call a DART tool → read the result → call again or answer. Network/LLM failures degrade to an
error string in the answer rather than raising, so the router can always fall back to wiki.
Its message log is rendered into the **same** `{step, agent, action, arg, thought}` trace
shape the wiki agent emits, so the API/UI shows DART tool calls identically.
