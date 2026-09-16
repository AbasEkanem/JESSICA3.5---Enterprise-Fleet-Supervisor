# Portable Nemotron Harness & Agent Workspace (Pluggable Edition)

A completely standalone, portable extraction of:
1. **`nemotron_harness.py`**: The production anti-Nemotron middleware harness for LangChain & LangGraph agents.
2. **`AgentWorkspace.tsx`**: The rich, collapsible execution console UI component with typewriter animation, execution rail, nested delegations, and guardrail event display.
3. **`corrections.ts`**: Taxonomy and copy mapper for all harness steering events and guardrail notifications.
4. **`chat_types.ts`**: TypeScript interfaces for the agent execution stream (`StatusStep`, `SubagentEvent`, `CorrectionEvent`, etc.).

All project-specific references and branding have been stripped. These files have zero project coupling and are ready to drop into any Python backend and React/Next.js frontend.

### Layout in this repo

| File | Location | Notes |
| --- | --- | --- |
| `nemotron_harness.py` | repo root | Imported by `JESSICA3.5.py` → `attach_to_deepagents(...)` registers it as the brain's harness profile at import time |
| `AgentWorkspace.tsx` | `ui/src/components/` | Sibling imports `./corrections` + `./chat_types` resolve in place |
| `corrections.ts` | `ui/src/components/` | `nh_*` / `nemotron_*` source taxonomy |
| `chat_types.ts` | `ui/src/components/` | Superset of `ui/src/types/chat.ts` — adopt it in `page.tsx` to enable nesting/corrections |

---

## 1. Pluggable Nemotron Harness (`nemotron_harness.py`)

### What It Fights
- **Empty completions**: The model returns empty content and no tool call; default LangGraph terminates prematurely thinking the run completed.
- **Tool calls as text**: NIM parser emits raw JSON inside `content` with empty `tool_calls`.
- **Truncated tool calls**: The model finishes without a closing `}`.
- **Reasoning trace pollution**: `</think>` tags and raw `reasoning_content` bleeding into graph state.
- **Wire-format drift**: OpenAI / ChatNVIDIA tool format alignment.
- **Infinite loops**: Identical tool calls or repeated delegations without progress.
- **Date hallucination**: Anchors the authoritative current timestamp into the system frame.

### How to Use
```python
from nemotron_harness import build_nemotron_model, build_nemotron_harness
from langchain.agents import create_react_agent

# Initialize model
model = build_nemotron_model(
    model_name="nvidia/nemotron-3-super-120b-a12b",
    api_key=os.environ["NVIDIA_API_KEY"]
)

# Apply the complete pluggable harness as middleware
agent = create_react_agent(
    model=model,
    tools=tools,
    middleware=build_nemotron_harness()
)
```

---

## 2. Agent Workspace Component (`AgentWorkspace.tsx`)

### Key Features
- **Monotonically Gated Typewriter**: Renders stream events sequentially with clause/word boundary pacing without re-renders restarting lines.
- **Reduced Motion Support**: Automatically observes OS `prefers-reduced-motion`.
- **Harness Steering / Guardrails**: Directly captures and renders `nh_*` steering events as first-class visual items with custom status badges (warn vs info).
- **Nested Task Delegations**: Renders child agent / subagent steps indented under parent delegations with fold/unfold.
- **Sticky Terminal Field**: Styled with an internal dark-field console palette (`#131316`) that composites cleanly into light or dark mode layouts.
- **One-Click Verbatim Copy**: Exports clean text transcript of the entire execution rail.

### Dependencies
- `react` 18+ or 19+
- `lucide-react`
- `./corrections.ts`
- `./chat_types.ts`

### Usage in React / Next.js
```tsx
import { AgentWorkspace } from "./AgentWorkspace";
import type { StatusStep, SubagentEvent, CorrectionEvent, TerminalEvent } from "./chat_types";

export function ChatMessageCard({
  steps,
  subagents,
  corrections,
  terminal,
  live,
  notes,
}: {
  steps: StatusStep[];
  subagents?: SubagentEvent[];
  corrections?: CorrectionEvent[];
  terminal?: TerminalEvent;
  live?: boolean;
  notes?: string;
}) {
  return (
    <div className="agent-card">
      <AgentWorkspace
        steps={steps}
        subagents={subagents}
        corrections={corrections}
        terminal={terminal}
        live={live}
        notes={notes}
      />
    </div>
  );
}
```
