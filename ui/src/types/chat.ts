// Shared types for the Jessica 3.5 chat UI

export interface StatusStep {
  phase:
    | "thinking"
    | "subagent"
    | "tool"
    | "tool_done"
    | "reading"
    | "writing"
    | "searching"
    | "memory"
    | "emailing"
    | "researching"
    | "delegating"
    | "verifying";
  detail: string;
  tool?: string;
  /** Stable run-id from the backend — used to merge start/done events for the same call. */
  id?: string;
  /** True once the underlying tool/subagent call has finished. */
  done?: boolean;
  timestamp?: number;
}


export interface StreamEvent {
  type: "status" | "response" | "response_complete" | "token" | "done" | "error" | "todo" | "subagent" | "terminal" | "rate_limit" | "refinement" | "stream_abort" | "interrupt";
  data: string | StatusStep | TodoTask[] | { tool: string; output: string; timestamp?: number } | { phase: string; detail: string; tool?: string } | { resume_at: number } | InterruptPayload | any;
}

export interface TodoTask {
  task_description?: string;
  description?: string;
  task_status?: "pending" | "in-progress" | "in_progress" | "completed";
  status?: "pending" | "in-progress" | "in_progress" | "completed";
}

export interface InterruptPayload {
  thread_id: string;
  tool: string;
  args: Record<string, unknown>;
  risk: "low" | "medium" | "high";
}

export interface InterruptState extends InterruptPayload {
  agentMsgId: string;
}
