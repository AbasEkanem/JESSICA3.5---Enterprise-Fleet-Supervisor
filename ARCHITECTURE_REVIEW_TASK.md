# Jessica 3.5 — Architecture Review Fix Tracker

2026-08-01 production review. Verified finding → decision → status.

## Verification & Fixes
| ID | Claim | Verified | Action | Status |
|----|-------|----------|--------|--------|
| HIGH-01 | `_SEARCH_LABELS` unclosed → SyntaxError | **FALSE** — closed at `chat_utils.py` L213 | none | ⏭ |
| CRIT-01 | 13 subagent constructors unguarded at import | **TRUE** — all fire at module scope in `loadenv.py` | wrap in `_safe_build_subagent_model` (+ routing_model guard) | ✅ |
| CRIT-02 | `/resume` missing callbacks/step guard/think-filter | **TRUE** | add handler + step counter + token `<think>` filter (mirror `_run_agent`) | ✅ |
| CRIT-03 | `juliet_agent` invisible to router | **PARTIAL** — present in `system_prompts.py`+`chat_utils.py`; missing in `guardrails/router.py` (count "12") + `JESSICA.md` | add juliet to router literal/hints/prompt + JESSICA.md; split classroom routing (Sam=courses/rosters, Juliet=coursework/grading) | ✅ |
| HIGH-02 | email_worker `time.sleep(30)` blocks executor | **TRUE** — sync `while True` in `asyncio.to_thread` | async `_email_poll_loop`; drop blocking ThreadPoolExecutor fallback | ✅ |
| HIGH-03 | Auto-resume injects full user message | **TRUE** — verbatim at `chat.py` L556 | truncate `safe_message[:200]` | ✅ |
| HIGH-04 | RateLimiter lock TTL eviction race | **TRUE** — lock fetched then released before acquire | acquire/hold strong ref inside `meta_lock` | ✅ |
| MED-01 | search_memory instructions use WRITE triggers | **TRUE** — `memory_manager.py` L33-36 | rewrite as retrieve triggers | ✅ |
| MED-02 | `_HARD_RISK` defined inline in loop | **TRUE** — rebuilt every `__interrupt__` at `chat.py` L689 | hoist to module level | ✅ |
| MED-03 | `google_classroom_tools` duplicated | **TRUE** — identical to `google_classroom_courses_tools` | remove duplicate (canonical = courses_tools, per subagent.yaml) | ✅ |

Final: `python -m py_compile` on all 8 modified files → EXITCODE=0.
LH-01/02/03 are long-horizon recommendations (not defects) — out of scope unless requested.
