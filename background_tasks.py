"""
background_tasks.py — In-Process Background Task Manager for Jessica 3.5

Production-ready async subagent execution without requiring separately deployed
graph services. Wraps inline subagent invocations in managed asyncio.Tasks,
giving the orchestrator non-blocking lifecycle tools (start, check, get, cancel).

Architecture:
    - Subagents keep their full tool/prompt/model definitions (inline execution)
    - BackgroundTaskManager spawns asyncio.Tasks for long-running subagent work
    - Task state (status, result, errors) persists for 24 hours (configurable)
    - Orchestrator receives 4 LangChain-compatible tool functions
    - SSE handler streams live status cards for all lifecycle events

Design decisions:
    - In-process asyncio.Tasks (no separate deployments, no message queues)
    - Thread-safe task registry with asyncio.Lock
    - GC-safe: tasks are stored in a set to prevent Python 3.12+ garbage collection
    - 24-hour TTL cleanup via periodic background sweep
    - Fallback to inline execution (path of least latency) if task manager fails
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from langchain_core.tools import tool

from config import BACKGROUND_TASK_TIMEOUT_S, MAX_CONCURRENT_BG_TASKS, BACKGROUND_RECURSION_LIMIT

_log = logging.getLogger(__name__)

# ── Task retention policy ────────────────────────────────────────────────────
TASK_TTL_HOURS = 24

# Durability: LangGraph store namespace under which background-task metadata is
# persisted (see BackgroundTaskManager.set_store / _persist / recover_from_store).
# Records here are written with index=False — they are operational state, not
# semantic memories, so they must never be embedded or surface in memory search.
_STORE_NAMESPACE: tuple[str, ...] = ("background_tasks",)



class TaskStatus(str, Enum):
    """Lifecycle states for a background task."""
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """Metadata for a single background task."""
    task_id: str
    subagent_name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    _asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False)


class BackgroundTaskManager:
    """Manages background asyncio.Tasks for non-blocking subagent execution.

    Usage:
        manager = BackgroundTaskManager()
        tools = manager.get_tools()  # 4 LangChain tool functions
        # Pass tools to create_deep_agent via jessica_tools
    """

    def __init__(self, *, ttl_hours: int = TASK_TTL_HOURS):
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = asyncio.Lock()
        self._ttl = timedelta(hours=ttl_hours)
        # GC-safe: prevent Python 3.12+ from garbage-collecting running tasks
        self._running_tasks: set[asyncio.Task] = set()
        # Compiled orchestrator graph used to execute background runs. It does
        # not exist at import time (it is built later in the FastAPI lifespan),
        # so it is injected via set_agent() at startup. Until then start_bg_task
        # refuses to launch rather than spawning a task that cannot run.
        self._agent: Any = None
        # Durability (bg-task registry): a LangGraph BaseStore (the shared
        # AsyncPostgresStore in production, or the degraded-mode InMemoryStore),
        # injected via set_store() at startup. When set, task metadata is
        # write-through persisted under the ("background_tasks",) namespace so
        # results survive a process restart and orphaned in-flight tasks can be
        # reconciled on boot. None → pure in-process behavior (no persistence).
        self._store: Any = None
        # Backpressure: cap simultaneous background runs so a burst cannot
        # exhaust the shared Postgres pool and starve live /ask chat turns.
        # asyncio.Semaphore binds to the running loop on first await, not at
        # construction, so building it here (import time) is safe — same pattern
        # as self._lock above.
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_BG_TASKS)
        _log.info(
            "[BackgroundTaskManager] Initialized with TTL=%dh, max_concurrent=%d, timeout=%.0fs",
            ttl_hours, MAX_CONCURRENT_BG_TASKS, BACKGROUND_TASK_TIMEOUT_S,
        )


    def set_agent(self, agent: Any) -> None:
        """Bind the compiled agent graph used to run background tasks.

        Must be called once at startup, AFTER the agent is constructed (see the
        FastAPI lifespan in fastAPI_backend.py). Without this, start_task has no
        graph to invoke and every background task fails immediately with
        "No agent instance available for background execution."
        """
        self._agent = agent
        _log.info("[BackgroundTaskManager] Agent bound for background execution.")

    def set_store(self, store: Any) -> None:
        """Bind the durable store used to persist background-task metadata.

        Must be called once at startup (see the FastAPI lifespan). When set,
        every task state transition is write-through persisted to the store's
        ("background_tasks",) namespace, and recover_from_store() can reconcile
        tasks that were in flight when a previous process exited. Persistence is
        best-effort: a store hiccup never fails a task (see _persist).
        """
        self._store = store
        _log.info("[BackgroundTaskManager] Durable store bound for task persistence.")

    # ── Durable persistence (survive a process restart) ───────────────────────

    @staticmethod
    def _serialize(task: BackgroundTask) -> dict[str, Any]:
        """Flatten a BackgroundTask to a JSON-safe dict for the store.

        The live asyncio.Task handle is intentionally dropped — it cannot (and
        must not) survive a restart; recover_from_store() reconciles orphans.
        """
        return {
            "task_id": task.task_id,
            "subagent_name": task.subagent_name,
            "description": task.description,
            "status": task.status.value,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> BackgroundTask:
        """Rebuild a BackgroundTask from a persisted dict (asyncio task stays None)."""
        def _dt(v: Any) -> Optional[datetime]:
            if not v:
                return None
            try:
                return datetime.fromisoformat(v)
            except (TypeError, ValueError):
                return None

        created = _dt(data.get("created_at")) or datetime.now(timezone.utc)
        try:
            status = TaskStatus(data.get("status", TaskStatus.PENDING.value))
        except ValueError:
            status = TaskStatus.PENDING
        return BackgroundTask(
            task_id=data["task_id"],
            subagent_name=data.get("subagent_name", "unknown"),
            description=data.get("description", ""),
            status=status,
            result=data.get("result"),
            error=data.get("error"),
            created_at=created,
            completed_at=_dt(data.get("completed_at")),
        )

    async def _persist(self, task: BackgroundTask) -> None:
        """Write-through a task's current state to the durable store.

        Best-effort: a store failure is logged and swallowed — persistence must
        NEVER crash or fail the underlying background task.
        """
        store = self._store
        if store is None:
            return
        try:
            await store.aput(
                _STORE_NAMESPACE,
                task.task_id,
                self._serialize(task),
                index=False,  # operational state, not a semantic memory — never embed
            )
        except Exception as exc:
            _log.warning(
                "[BackgroundTaskManager] Persist failed for %s: %s", task.task_id, exc
            )

    async def recover_from_store(self) -> int:
        """Reconcile persisted tasks on startup. Returns the number recovered.

        Terminal tasks (completed/failed/cancelled) are loaded verbatim so
        get_result() keeps working across restarts. Any task still PENDING/RUNNING
        is an orphan — its asyncio.Task died with the previous process — so it is
        marked FAILED with a truthful message rather than left stuck "running"
        forever. We deliberately do NOT auto-resume orphans: blindly re-invoking
        the graph could double irreversible side effects (re-send an email,
        re-create a file) and bypass human-in-the-loop. The checkpoint at the
        task's bg_thread_id survives, so the user can re-issue to continue.
        """
        store = self._store
        if store is None:
            return 0
        try:
            items = await store.asearch(_STORE_NAMESPACE, limit=1000)
        except Exception as exc:
            _log.warning("[BackgroundTaskManager] recover_from_store search failed: %s", exc)
            return 0

        recovered = 0
        orphan_ids: list[str] = []
        async with self._lock:
            for item in items or []:
                data = getattr(item, "value", None)
                if not isinstance(data, dict) or "task_id" not in data:
                    continue
                try:
                    task = self._deserialize(data)
                except Exception as exc:
                    _log.warning("[BackgroundTaskManager] skip un-deserializable task: %s", exc)
                    continue
                if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    task.status = TaskStatus.FAILED
                    task.error = (
                        "Interrupted by a server restart; partial work may exist. "
                        "Re-issue the request to continue."
                    )
                    task.completed_at = datetime.now(timezone.utc)
                    orphan_ids.append(task.task_id)
                self._tasks[task.task_id] = task
                recovered += 1

        # Re-persist corrected orphan statuses OUTSIDE the lock (aput is async I/O).
        for tid in orphan_ids:
            task = self._tasks.get(tid)
            if task is not None:
                await self._persist(task)

        if recovered:
            _log.info(
                "[BackgroundTaskManager] Recovered %d task(s) from store (%d orphaned → failed).",
                recovered, len(orphan_ids),
            )
        return recovered


    async def start_task(
        self,
        subagent_name: str,
        description: str,
        *,
        agent: Any = None,
        thread_id: str = "",
        user_id: str = "",
    ) -> str:
        """Spawn a background asyncio.Task for a subagent invocation.

        Returns the task_id immediately (non-blocking).
        """
        task_id = f"bg-{uuid.uuid4().hex[:12]}"
        bg_task = BackgroundTask(
            task_id=task_id,
            subagent_name=subagent_name,
            description=description,
        )

        async with self._lock:
            self._tasks[task_id] = bg_task

        # Create the asyncio.Task that will run the subagent
        coro = self._execute_subagent(
            task_id=task_id,
            subagent_name=subagent_name,
            description=description,
            agent=agent,
            thread_id=thread_id,
            user_id=user_id,
        )
        asyncio_task = asyncio.create_task(coro, name=f"bg-task-{task_id}")
        asyncio_task.add_done_callback(self._running_tasks.discard)
        self._running_tasks.add(asyncio_task)

        async with self._lock:
            bg_task._asyncio_task = asyncio_task
            bg_task.status = TaskStatus.RUNNING

        await self._persist(bg_task)
        _log.info(
            "[BackgroundTaskManager] Started task %s (subagent=%s)",
            task_id, subagent_name,
        )
        return task_id

    async def check_task(self, task_id: str) -> dict[str, Any]:
        """Check the status and result of a background task."""
        async with self._lock:
            task = self._tasks.get(task_id)

        if task is None:
            return {"task_id": task_id, "status": "not_found", "error": "No task found with this ID."}

        result: dict[str, Any] = {
            "task_id": task.task_id,
            "subagent": task.subagent_name,
            "status": task.status.value,
            "created_at": task.created_at.isoformat(),
        }
        if task.completed_at:
            result["completed_at"] = task.completed_at.isoformat()
            result["duration_s"] = round((task.completed_at - task.created_at).total_seconds(), 1)
        if task.result:
            result["result"] = task.result
        if task.error:
            result["error"] = task.error
        return result

    async def get_result(self, task_id: str) -> str:
        """Retrieve the final result of a completed background task."""
        async with self._lock:
            task = self._tasks.get(task_id)

        if task is None:
            return f"❌ No task found with ID '{task_id}'."

        if task.status == TaskStatus.RUNNING:
            return f"⏳ Task '{task_id}' ({task.subagent_name}) is still running. Check back shortly."
        elif task.status == TaskStatus.COMPLETED:
            return task.result or "✅ Task completed but produced no output."
        elif task.status == TaskStatus.FAILED:
            return f"❌ Task '{task_id}' failed: {task.error or 'Unknown error'}"
        elif task.status == TaskStatus.CANCELLED:
            return f"🚫 Task '{task_id}' was cancelled."
        else:
            return f"Task '{task_id}' status: {task.status.value}"

    async def cancel_task(self, task_id: str) -> str:
        """Cancel a running background task."""
        async with self._lock:
            task = self._tasks.get(task_id)

        if task is None:
            return f"❌ No task found with ID '{task_id}'."

        if task.status != TaskStatus.RUNNING:
            return f"Task '{task_id}' is not running (status: {task.status.value})."

        if task._asyncio_task and not task._asyncio_task.done():
            task._asyncio_task.cancel()

        async with self._lock:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(timezone.utc)

        await self._persist(task)
        _log.info("[BackgroundTaskManager] Cancelled task %s", task_id)
        return f"🚫 Task '{task_id}' ({task.subagent_name}) cancelled."

    async def list_tasks(self) -> list[dict[str, Any]]:
        """List all tracked background tasks and their statuses."""
        async with self._lock:
            tasks = list(self._tasks.values())

        return [
            {
                "task_id": t.task_id,
                "subagent": t.subagent_name,
                "status": t.status.value,
                "description": t.description[:100],
                "created_at": t.created_at.isoformat(),
            }
            for t in sorted(tasks, key=lambda t: t.created_at, reverse=True)
        ]

    # ── Internal: subagent execution coroutine ────────────────────────────────

    async def _execute_subagent(
        self,
        *,
        task_id: str,
        subagent_name: str,
        description: str,
        agent: Any,
        thread_id: str,
        user_id: str,
    ) -> None:
        """Run a subagent task in the background via the compiled graph.

        This invokes the agent graph with a synthetic user message that triggers
        the `task` tool for the target subagent. The result is captured and stored.
        """
        try:
            if agent is None:
                raise RuntimeError("No agent instance available for background execution.")

            # Build a synthetic invocation that triggers the task tool
            # for the specified subagent
            bg_thread_id = f"{thread_id}__bg__{task_id}" if thread_id else f"bg__{task_id}"

            invoke_input = {
                "messages": [{
                    "role": "user",
                    "content": (
                        f"[BACKGROUND TASK {task_id}] "
                        f"Execute this task using the {subagent_name} subagent: {description}"
                    ),
                }]
            }

            config = {
                "configurable": {
                    "thread_id": bg_thread_id,
                    "user_id": user_id or "system",
                },
                # Was hardcoded 40 (below the conversation budget) — the starved
                # path that produced background GraphRecursionError failures.
                # Now tracks BACKGROUND_RECURSION_LIMIT (defaults to the
                # conversation limit) so a delegated workflow gets real room.
                "recursion_limit": BACKGROUND_RECURSION_LIMIT,
            }

            # Use ainvoke for background execution (no streaming needed).
            # Two guards (see config.py):
            #   - self._semaphore caps concurrent background runs so they cannot
            #     drain the shared Postgres pool out from under live chat turns.
            #   - asyncio.wait_for bounds a single hung run to
            #     BACKGROUND_TASK_TIMEOUT_S instead of leaking a connection until
            #     the 2x-TTL (48h) cleanup sweep reaps it.
            async with self._semaphore:
                result = await asyncio.wait_for(
                    agent.ainvoke(invoke_input, config=config),
                    timeout=BACKGROUND_TASK_TIMEOUT_S,
                )


            # Extract the final AI message text
            final_text = ""
            if result and "messages" in result:
                for msg in reversed(result["messages"]):
                    if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content.strip():
                        final_text = msg.content.strip()
                        break

            async with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task.status = TaskStatus.COMPLETED
                    task.result = final_text or "Task completed successfully."
                    task.completed_at = datetime.now(timezone.utc)

            if task:
                await self._persist(task)
            _log.info(
                "[BackgroundTaskManager] Task %s completed (%d chars)",
                task_id, len(final_text),
            )

        except asyncio.CancelledError:
            async with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task.status = TaskStatus.CANCELLED
                    task.completed_at = datetime.now(timezone.utc)
            if task:
                # Best-effort persist during cancellation. _persist swallows
                # ordinary errors; guard the CancelledError path too so this
                # branch keeps its existing "record CANCELLED and return"
                # semantics rather than propagating a second cancellation.
                try:
                    await self._persist(task)
                except asyncio.CancelledError:
                    pass
            _log.info("[BackgroundTaskManager] Task %s cancelled", task_id)

        except (asyncio.TimeoutError, TimeoutError):
            # Explicit branch: str(TimeoutError()) is empty, so the generic
            # handler below would store a blank error. Give a clear message.
            async with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task.status = TaskStatus.FAILED
                    task.error = (
                        f"Timed out after {BACKGROUND_TASK_TIMEOUT_S:.0f}s "
                        f"(background task execution limit)."
                    )
                    task.completed_at = datetime.now(timezone.utc)
            if task:
                await self._persist(task)
            _log.warning(
                "[BackgroundTaskManager] Task %s timed out after %.0fs",
                task_id, BACKGROUND_TASK_TIMEOUT_S,
            )

        except Exception as exc:

            async with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task.status = TaskStatus.FAILED
                    task.error = str(exc)[:500]
                    task.completed_at = datetime.now(timezone.utc)
            if task:
                await self._persist(task)
            _log.error(
                "[BackgroundTaskManager] Task %s failed: %s",
                task_id, exc, exc_info=True,
            )

    # ── Periodic cleanup ──────────────────────────────────────────────────────

    async def cleanup_expired(self) -> int:
        """Remove tasks older than the TTL. Returns count of removed tasks."""
        now = datetime.now(timezone.utc)
        expired: list[str] = []

        async with self._lock:
            for tid, task in self._tasks.items():
                if task.completed_at and (now - task.completed_at) > self._ttl:
                    expired.append(tid)
                elif (now - task.created_at) > self._ttl * 2:
                    # Safety: remove even running tasks that are stuck (2x TTL)
                    if task._asyncio_task and not task._asyncio_task.done():
                        task._asyncio_task.cancel()
                    expired.append(tid)

            for tid in expired:
                del self._tasks[tid]

        # Mirror the eviction into the durable store so persisted records don't
        # outlive their TTL. Best-effort — a store hiccup never fails cleanup.
        if expired and self._store is not None:
            for tid in expired:
                try:
                    await self._store.adelete(_STORE_NAMESPACE, tid)
                except Exception as exc:
                    _log.warning(
                        "[BackgroundTaskManager] store delete failed for %s: %s", tid, exc
                    )

        if expired:
            _log.info(
                "[BackgroundTaskManager] Cleaned up %d expired tasks", len(expired)
            )
        return len(expired)

    # ── Tool factory ──────────────────────────────────────────────────────────

    def get_tools(self) -> list:
        """Return 4 LangChain-compatible tool functions for the orchestrator.

        These tools let the orchestrator start, check, retrieve, and cancel
        background subagent tasks without blocking the conversation.
        """
        manager = self  # closure reference

        @tool
        async def start_bg_task(subagent_name: str, description: str) -> str:
            """Launch a subagent task in the background. Returns a task_id immediately.

            Use this for long-running operations (deep web research, document generation,
            complex multi-step pipelines) that would take more than 10 seconds.
            The task runs asynchronously — the user can continue chatting.

            Args:
                subagent_name: The exact subagent name (e.g. research_agent, comms_agent, google_workspace_agent, project_mgmt_agent)
                description: Detailed task instructions for the subagent
            """
            # BUG-FIX: the background run needs a compiled graph to invoke and the
            # current user's identity so Google Workspace tools resolve the right
            # credentials. The manager's agent is bound once at startup via
            # set_agent(); the user email is read from the same request-scoped
            # contextvar the /ask handler sets (set_current_user_email), so the
            # background run acts as the same user who launched it. Both are
            # captured HERE (inside the live tool call) rather than at get_tools()
            # time, because the agent does not exist yet when get_tools() runs.
            agent = manager._agent
            if agent is None:
                return (
                    "⚠️ Background execution is not available right now "
                    "(the task runner has no agent bound). I'll run this inline "
                    "instead — please re-issue the request."
                )
            try:
                from agents.google_workspace.auth import get_current_user_email
                _user_id = get_current_user_email() or "system"
            except Exception:
                _user_id = "system"
            task_id = await manager.start_task(
                subagent_name,
                description,
                agent=agent,
                user_id=_user_id,
            )
            return (
                f"✅ Background task launched!\n"
                f"• Task ID: `{task_id}`\n"
                f"• Subagent: {subagent_name}\n"
                f"• Status: running\n\n"
                f"The task is running in the background. "
                f"The user can continue chatting. "
                f"Use `check_bg_task` with this task_id to check progress."
            )


        @tool
        async def check_bg_task(task_id: str) -> str:
            """Check the status of a background task.

            Args:
                task_id: The task ID returned by start_bg_task
            """
            info = await manager.check_task(task_id)
            status = info.get("status", "unknown")
            parts = [f"**Task {task_id}** — Status: **{status}**"]
            if "subagent" in info:
                parts.append(f"• Subagent: {info['subagent']}")
            if "duration_s" in info:
                parts.append(f"• Duration: {info['duration_s']}s")
            if status == "completed" and "result" in info:
                result_preview = info["result"][:300]
                parts.append(f"• Result preview: {result_preview}...")
            elif "error" in info:
                parts.append(f"• Error: {info['error']}")
            return "\n".join(parts)

        @tool
        async def get_bg_result(task_id: str) -> str:
            """Retrieve the full result of a completed background task.

            Args:
                task_id: The task ID returned by start_bg_task
            """
            return await manager.get_result(task_id)

        @tool
        async def cancel_bg_task(task_id: str) -> str:
            """Cancel a running background task.

            Args:
                task_id: The task ID returned by start_bg_task
            """
            return await manager.cancel_task(task_id)

        return [start_bg_task, check_bg_task, get_bg_result, cancel_bg_task]


# ── Module-level singleton ────────────────────────────────────────────────────
# Created once at import time. The lifespan in fastAPI_backend.py starts the
# periodic cleanup task; the tools are wired into JESSICA3.5.py.
bg_task_manager = BackgroundTaskManager(ttl_hours=TASK_TTL_HOURS)
