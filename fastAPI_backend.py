"""
fastAPI_backend.py — Jessica 3.5 API server entry point (Clean & Hardened Version)
"""

import asyncio
import os
import selectors
import sys
import traceback
from contextlib import asynccontextmanager, suppress
from typing import AsyncGenerator

import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        RotatingFileHandler("server_output.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ],
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

import structlog as _structlog

_structlog.configure(
    processors=[
        _structlog.contextvars.merge_contextvars,
        _structlog.stdlib.add_log_level,
        _structlog.stdlib.PositionalArgumentsFormatter(),
        _structlog.processors.StackInfoRenderer(),
        _structlog.processors.format_exc_info,   # ← renders exc_info from .exception()
        _structlog.processors.KeyValueRenderer(
            key_order=["event", "level"], sort_keys=False
        ),
    ],
    wrapper_class=_structlog.stdlib.BoundLogger,
    logger_factory=_structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


# Windows UTF-8 & Event Loop fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
# A3 (Fix #5): genuine in-process persistence for degraded mode — a graceful
# fallback that survives across turns within the process, instead of the old
# amnesiac checkpointer=None/store=None (which forgot everything every turn).
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from config import RESEARCH_SEMAPHORE_SIZE, CONVERSATION_SEMAPHORE_SIZE
from memory_config import CONN_STRING, embedding_model
try:
    from loadenv import chat_model  # noqa: F401
except Exception as _loadenv_exc:  # pragma: no cover - defensive startup guard
    logging.warning(
        "loadenv import failed at startup: %s — continuing; lifespan will retry/degrade",
        _loadenv_exc,
        exc_info=True,
    )


import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "jessica35",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "JESSICA3.5.py"),
)
_j35 = _ilu.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_j35)
    create_jessica_conversation_agent = _j35.create_jessica_conversation_agent
except Exception as _j35_exc:  # pragma: no cover - defensive startup guard
    logging.error(
        "JESSICA3.5 module load failed at startup: %s — booting degraded; the "
        "lifespan will run without a conversation agent until this is fixed",
        _j35_exc,
        exc_info=True,
    )
    create_jessica_conversation_agent = None


# Routes
from routes.auth import router as auth_router
from routes.greeting import router as greeting_router
from routes.chat import router as chat_router
from routes.upload import router as upload_router
from routes.google_oauth import router as google_oauth_router
from agents.comms.slack_webhook import router as slack_router
from background_tasks import bg_task_manager


async def _run_email_worker_forever() -> None:
    while True:
        try:
            from agents.comms.email_worker import async_start_worker  # type: ignore
            await async_start_worker()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[EMAIL WORKER] Error: {e}. Restarting in 5s...", flush=True)
            traceback.print_exc()
            await asyncio.sleep(5)


async def _run_bg_cleanup_forever() -> None:
    """Periodic cleanup of expired background tasks (24h TTL)."""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            removed = await bg_task_manager.cleanup_expired()
            if removed:
                print(f"[BG TASKS] Cleaned up {removed} expired tasks", flush=True)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[BG TASKS] Cleanup error: {e}", flush=True)
            await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # Semaphores
    app.state.research_semaphore = asyncio.Semaphore(RESEARCH_SEMAPHORE_SIZE)
    app.state.conversation_semaphore = asyncio.Semaphore(CONVERSATION_SEMAPHORE_SIZE)
    app.state.agent_semaphore = app.state.research_semaphore  # legacy alias

    email_task: asyncio.Task | None = None
    cleanup_task: asyncio.Task | None = None
    app.state.degraded = False
    pg_pool = None
    startup_failed = False

    try:
        # B3: if JESSICA3.5 failed to import (factory is the None sentinel set at
        # module load), there is no graph to build — skip straight to degraded
        # mode rather than opening a Postgres pool we cannot use.
        if create_jessica_conversation_agent is None:
            raise RuntimeError(
                "create_jessica_conversation_agent unavailable "
                "(JESSICA3.5 module failed to load at import time)"
            )

        pool_max_size = RESEARCH_SEMAPHORE_SIZE + CONVERSATION_SEMAPHORE_SIZE + 4

        # open=False: psycopg_pool deprecates implicit-open-in-constructor
        # for async pools; explicit await pg_pool.open() below is the
        # documented pattern for FastAPI lifespans.
        pg_pool = AsyncConnectionPool(
            CONN_STRING,
            min_size=2,
            max_size=pool_max_size,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            max_lifetime=3600,
            max_idle=300,
            timeout=30,
            check=AsyncConnectionPool.check_connection,
        )
    
        checkpointer = AsyncPostgresSaver(conn=pg_pool)
        memory_store = AsyncPostgresStore(
            conn=pg_pool,
            index={"dims": 384, "embed": embedding_model},
        )

        _open_attempts = 3
        for _attempt in range(_open_attempts):
            try:
                await pg_pool.open()
                await asyncio.gather(checkpointer.setup(), memory_store.setup())
                break
            except Exception as _open_exc:
                if _attempt == _open_attempts - 1:
                    raise
                _delay = 2 ** _attempt  # 1s, 2s, 4s
                logging.warning(
                    "Postgres open/setup attempt %d/%d failed: %s — retrying in %ds",
                    _attempt + 1, _open_attempts, _open_exc, _delay,
                )
                await asyncio.sleep(_delay)

        app.state.conversation_agent = create_jessica_conversation_agent(checkpointer, memory_store)
        app.state.memory_store = memory_store
        app.state.conversation_pool = pg_pool  # A4: target for the live /health DB probe

        bg_task_manager.set_agent(app.state.conversation_agent) 
        bg_task_manager.set_store(memory_store)
        _recovered = await bg_task_manager.recover_from_store()
        if _recovered:
            print(f"[OK] Recovered {_recovered} background task(s) from store")

        print(f"[OK] Agent initialized with pooled Postgres (max_size={pool_max_size})")


        # Redis pre-warm
        try:
            import redis.asyncio as aioredis
            from config import REDIS_URL
            r = aioredis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            try:
                await r.ping()
                print("[OK] Redis pre-warmed")
            finally:
                # A5: always release the client, even if ping() raised — otherwise
                # a failed pre-warm leaks the connection/socket on every boot.
                await r.aclose()
        except Exception as e:
            print(f"[WARN] Redis pre-warm skipped: {e}")

        email_task = asyncio.create_task(_run_email_worker_forever(), name="email-worker")
        app.state.email_worker_running = True
        print("[OK] Email worker started")

        # Background task manager: store on app.state + start cleanup
        app.state.bg_task_manager = bg_task_manager
        cleanup_task = asyncio.create_task(_run_bg_cleanup_forever(), name="bg-cleanup")
        print("[OK] Background task manager started (24h TTL cleanup)")

    except Exception as e:
        startup_failed = True
        app.state.degraded = True
        logging.error(f"Startup failed: {e}", exc_info=True)
        print(f"[CRITICAL] Postgres/Database unavailable: {e} → Running in degraded (in-memory) mode", flush=True)
        _mem_saver = MemorySaver()
        try:
            _mem_store = InMemoryStore(index={"dims": 384, "embed": embedding_model})
        except Exception as _idx_err:
            # A broken/unreachable embedding model must not defeat the fallback —
            # drop semantic indexing and keep a plain key/value store.
            logging.warning(
                "Degraded InMemoryStore index build failed (%s) — using unindexed store",
                _idx_err,
            )
            _mem_store = InMemoryStore()

        try:
            if create_jessica_conversation_agent is None:
                raise RuntimeError(
                    "create_jessica_conversation_agent unavailable "
                    "(JESSICA3.5 module failed to load)"
                )
            app.state.conversation_agent = create_jessica_conversation_agent(_mem_saver, _mem_store)
            app.state.memory_store = _mem_store
            # Bind the degraded agent + store so background tasks still work
            # (in-memory, non-durable across restarts, but functional).
            bg_task_manager.set_agent(app.state.conversation_agent)
            bg_task_manager.set_store(_mem_store)
            await bg_task_manager.recover_from_store()  # no-op on a fresh store
            print("[OK] Degraded in-memory agent initialized (MemorySaver + InMemoryStore)", flush=True)
        except Exception as fallback_err:
            logging.error(f"Fallback agent startup failed: {fallback_err}", exc_info=True)
            app.state.conversation_agent = None
            app.state.memory_store = None

        app.state.conversation_pool = None  # A4: no live Postgres pool in degraded mode
        # A pool may have partially opened before the failure — don't leak it.
        if pg_pool is not None:
            with suppress(Exception):
                await pg_pool.close()
            pg_pool = None

    try:
        yield  # ← single yield point, always reached exactly once

    finally:
        if not startup_failed:
            # Give background tasks a brief window to flush before teardown.
            with suppress(Exception):
                await asyncio.sleep(0.2)

        if cleanup_task and not cleanup_task.done():
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
            print("[OK] Background task cleanup stopped")

        if email_task and not email_task.done():
            email_task.cancel()
            with suppress(asyncio.CancelledError):
                await email_task
            app.state.email_worker_running = False
            print("[OK] Email worker stopped")

        if pg_pool is not None:
            try:
                await pg_pool.close()
                print("[OK] Postgres pool closed")
            except Exception as close_err:
                logging.error(f"Error closing Postgres pool: {close_err}", exc_info=True)
            finally:
                # A4: drop the /health probe's pool reference so a shutdown-time
                # health check reports "none" rather than probing a closed pool.
                app.state.conversation_pool = None


# ── FastAPI App 
app = FastAPI(
    title="Jessica 3.5 — Deep Research AI",
    description="Multi-source investigative research agent with real-time streaming",
    version="3.5.0",
    lifespan=lifespan,
)

app.state.degraded = False
app.state.email_worker_running = False
app.state.conversation_agent = None
app.state.memory_store = None
app.state.conversation_pool = None  # A4: set to the live pool on healthy boot

# CORS
cors_origins = [
    "http://localhost:8000", "http://localhost:5173",
    "http://localhost:3000", "http://localhost:3005", "http://localhost:3006",
]
if frontend_url := os.getenv("FRONTEND_URL"):
    cors_origins.append(frontend_url)


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Cookie"],
)


# Static files (mount before routers)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(auth_router)
app.include_router(greeting_router)
app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(google_oauth_router)
app.include_router(slack_router)


# Core routes
@app.get("/health")
async def health():
    # OBS-01: surface LangSmith trace visibility in the health payload so an
    # operator (or uptime check) can detect a deployment that went live with
    # zero trace coverage — a passive startup log warning is easy to miss.
    try:
        from loadenv import LANGSMITH_TRACING_ENABLED
        langsmith_tracing = bool(LANGSMITH_TRACING_ENABLED)
    except Exception:
        langsmith_tracing = False

    # A4 (Fix #5): probe the DB LIVE rather than reporting only boot-time state,
    # so a Postgres death (or recovery) AFTER startup is visible to uptime
    # checks. Short, bounded, and guarded — a slow/broken DB yields "down", never
    # a 500 on the health endpoint itself.
    pool = getattr(app.state, "conversation_pool", None)
    if pool is None:
        db_status = "none"  # degraded/in-memory mode — no Postgres pool
    else:
        async def _probe() -> None:
            async with pool.connection(timeout=5) as conn:
                await conn.execute("SELECT 1")
        try:
            await asyncio.wait_for(_probe(), timeout=6)
            db_status = "up"
        except Exception:
            db_status = "down"

    # Overall status reflects the LIVE probe: a boot-healthy server whose DB
    # later died reports "degraded" here even though app.state.degraded is False.
    degraded = bool(app.state.degraded) or db_status == "down"

    return {
        "status": "degraded" if degraded else "healthy",
        "version": "3.5.0",
        "agent_ready": app.state.conversation_agent is not None,
        "email_worker_running": app.state.email_worker_running,
        "langsmith_tracing": langsmith_tracing,
        "db": db_status,
    }



@app.get("/")
async def root():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"message": "Jessica 3.5 API is running"}


# SPA catch-all (must be LAST)
if os.path.exists("static"):
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        fp = os.path.join("static", full_path)
        if os.path.exists(fp) and os.path.isfile(fp):
            return FileResponse(fp)
        return FileResponse("static/index.html")


# Entry point
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))

    if sys.platform == "win32":
        asyncio.set_event_loop(asyncio.SelectorEventLoop(selectors.SelectSelector()))
        loop = asyncio.get_event_loop()
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port))
        loop.run_until_complete(server.serve())
    else:
        uvicorn.run(app, host="0.0.0.0", port=port)