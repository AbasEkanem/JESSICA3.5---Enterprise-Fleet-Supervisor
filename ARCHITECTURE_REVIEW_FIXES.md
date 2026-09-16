# Architecture Review — Fix Tracking

2026-08-01 production review. Claim → verified-against-code → status.
Legend: ✅ done · ⏭ skipped (false positive)

## CRITICAL
- **CRIT-01 · Unguarded subagent model constructors at import** (`loadenv.py` L241-253) — **VERIFIED.** All 13 `_build_subagent_model(...)` run unconditionally at import; a transient NVIDIA/DNS error aborts the whole module so `chat_model` never binds. **Fix:** wrap each in `_safe_build_subagent_model` returning `None` on failure (loader already treats `None` as fallback). ✅
- **CRIT-02 · `/resume` feature-poor after HITL approve** (`routes/chat.py` `_stream_resumed`) — **VERIFIED.** No status callback, no `_MAX_STEPS` guard, no `<think>` filter on streamed tokens. **Fix:** add `callbacks=[JessicaStatusHandler(...)]`, `<think>` strip, and a step-counter guard mirroring `_run_agent`. ✅
- **CRIT-03 · `juliet_agent` invisible to orchestrator/router** (`guardrails/router.py`, `JESSICA.md`) — **PARTIAL.** `system_prompts.py` + `chat_utils.py` already list 13 incl. juliet; router (`SubagentType`, `_HINTS`, `_ROUTER_SYSTEM`, count "12") and `JESSICA.md` omit it. **Fix:** add juliet everywhere; split classroom routing (Sam=courses/rosters, Juliet=coursework/grading). ✅

## HIGH
- **HIGH-01 · `_SEARCH_LABELS` unclosed → SyntaxError** — **FALSE POSITIVE.** Dict closes at `chat_utils.py` L213; `ast.parse` succeeds. ⏭
- **HIGH-02 · Email worker blocks executor forever** (`email_worker.py`, `fastAPI_backend.py`) — **VERIFIED.** `start_worker` is `while True: … time.sleep(30)` in `asyncio.to_thread`. **Fix:** cancellation-aware async `_email_poll_loop()`; keep sync `start_worker` for `__main__`. ✅
- **HIGH-03 · Auto-resume injects full user message** (`chat.py` L554-559) — **VERIFIED.** **Fix:** truncate to 200 chars in the unclassified-resume path. ✅
- **HIGH-04 · RateLimiter lock race on TTL eviction** (`rate_limiter.py` L108-125) — **VERIFIED.** `_get_lock` releases `_meta_lock` before caller acquires the returned lock; entry can be evicted between, yielding two locks per user (single-process). **Fix:** hold a strong ref and take the user lock while safe. ✅

## MEDIUM
- **MED-01 · `search_memory_instructions` describe WRITE triggers** (`memory_manager.py` L29-39) — **VERIFIED.** **Fix:** rewrite to retrieval triggers. ✅
- **MED-02 · `_HARD_RISK` defined inline in streaming loop** (`chat.py` L689-698) — **VERIFIED.** Rebuilt every event; drift risk vs subagent.yaml. **Fix:** hoist to module-level constant. ✅
- **MED-03 · Classroom tool registry duplication** (`subagent_loader.py` L323-348) — **VERIFIED.** `google_classroom_tools` == `google_classroom_courses_tools` (11 fns); yaml uses the latter, so the former is unused. **Fix:** remove the unused key. ✅

## LONG-HORIZON (documented, not code-fixed)
- LH-01 surface partial research findings on step-limit — deferred (needs checkpoint-read design).
- LH-02 enforce complete `task` descriptions — addressed via prompt note.
- LH-03 harness-level subagent retry — deferred (harness change).
