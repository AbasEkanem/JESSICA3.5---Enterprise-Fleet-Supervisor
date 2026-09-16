"""
scratch/live_tool_test.py — LIVE, READ-ONLY connectivity probes for Jessica's tools.

Unlike feature_test.py (pure offline), this actually reaches each external service
using the credentials in .env — but ONLY with safe, READ-ONLY / non-destructive
calls. It NEVER sends an email, posts to Slack, creates/deletes a Jira issue,
or touches Google Drive contents.

Probes:
  - Jira        : list_my_jira_issues (read)
  - Slack       : list_slack_channels (read)
  - Email/inbox : read_inbox (read)  [IMAP]
  - Web search  : tavily_search a trivial query (read)   [set LIVE_WEBSEARCH=1]
  - Datetime    : get_current_datetime (pure)

Each probe is wrapped so a failure/timeout is reported, never fatal.

Run:
    .\jessica3.0_venv\Scripts\python.exe scratch\live_tool_test.py
    LIVE_WEBSEARCH=1 to also fire one Tavily query (uses a search credit).
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

warnings.filterwarnings("ignore")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_TIMEOUT_S = float(os.getenv("LIVE_TOOL_TIMEOUT_S", "40"))
_results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    _results.append((name, status, detail))
    print(f"[{status}] {name:26s} {detail}")


def _short(x: object, n: int = 160) -> str:
    s = str(x).replace("\n", " ")
    return s[:n] + ("…" if len(s) > n else "")


def _invoke_sync(tool, payload: dict):
    """Invoke a (possibly async) LangChain tool with a wall-clock timeout."""
    def _call():
        try:
            return tool.invoke(payload)
        except NotImplementedError:
            # async-only tool: drive it through asyncio
            return asyncio.run(tool.ainvoke(payload))
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_call).result(timeout=_TIMEOUT_S)


def probe(name: str, tool_path: tuple[str, str], payload: dict) -> None:
    mod_name, attr = tool_path
    try:
        mod = __import__(mod_name)
        tool = getattr(mod, attr)
    except Exception as exc:  # noqa: BLE001
        record(name, "FAIL", f"import: {_short(exc)}")
        return
    try:
        out = _invoke_sync(tool, payload)
        record(name, "PASS", _short(out))
    except FutureTimeout:
        record(name, "FAIL", f"timeout after {_TIMEOUT_S:.0f}s")
    except Exception as exc:  # noqa: BLE001
        record(name, "WARN", f"{type(exc).__name__}: {_short(exc)}")


def main() -> int:
    print("=" * 78)
    print("JESSICA 3.5 — LIVE read-only tool connectivity probes")
    print("=" * 78)

    # Datetime (pure, always safe)
    probe("datetime", ("datetime_tools", "get_current_datetime"),
          {"timezone_offset_hours": 1.0})

    # Jira — read-only list of my issues
    probe("jira.list_my_issues", ("atlassian_tools", "list_my_jira_issues"),
          {"max_results": 3})

    # Slack — read-only channel list
    probe("slack.list_channels", ("slack_tools", "list_slack_channels"),
          {})

    # Email — read-only inbox peek
    probe("email.read_inbox", ("email_tools", "read_inbox"),
          {"max_results": 2})

    # Web search — costs a credit, opt-in only
    if os.getenv("LIVE_WEBSEARCH", "").strip() in ("1", "true", "yes"):
        probe("web.tavily_search", ("websearch_tools", "tavily_search"),
              {"query": "current UTC time"})
    else:
        record("web.tavily_search", "SKIP", "set LIVE_WEBSEARCH=1 to enable")

    print("\n" + "=" * 78)
    n_pass = sum(1 for _, s, _ in _results if s == "PASS")
    n_fail = sum(1 for _, s, _ in _results if s == "FAIL")
    n_warn = sum(1 for _, s, _ in _results if s == "WARN")
    n_skip = sum(1 for _, s, _ in _results if s == "SKIP")
    print(f"SUMMARY: {n_pass} PASS · {n_fail} FAIL · {n_warn} WARN · {n_skip} SKIP")
    print("Note: WARN usually means the service credential/permission is the issue,")
    print("      not Jessica's tool code. FAIL = tool code or import problem.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
