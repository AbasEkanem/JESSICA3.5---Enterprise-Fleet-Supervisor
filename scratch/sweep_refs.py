"""scratch/sweep_refs.py — Reference sweep before moving Google tool modules.

Finds every importer of the 7 google_*_tools modules + google_auth +
google_token_store, and flags __file__/token/credential path logic inside
the 9 files that will move into agents/google_workspace/.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = ("jessica3.0_venv", "__pycache__", "node_modules", ".next", "large_tool_results", "site-packages")

IMPORT_PAT = re.compile(
    r"google_(?:calendar|classroom|docs|drive|forms|sheets|slides)_tools"
    r"|from google_auth|import google_auth|google_token_store"
)
PATH_PAT = re.compile(r"__file__|token[.]json|google_service_account|credentials[.]json")
MOVE_MODULES = [
    "google_calendar_tools", "google_classroom_tools", "google_docs_tools",
    "google_drive_tools", "google_forms_tools", "google_sheets_tools",
    "google_slides_tools", "google_auth", "google_token_store",
]

out: list[str] = []
for p in sorted(ROOT.rglob("*.py")):
    if any(s in str(p) for s in SKIP):
        continue
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        continue
    for i, line in enumerate(lines, 1):
        if IMPORT_PAT.search(line):
            out.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()}")

out.append("--- PATH LOGIC inside the 9 moving files ---")
for name in MOVE_MODULES:
    p = ROOT / f"{name}.py"
    if not p.exists():
        out.append(f"{name}.py: MISSING")
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if PATH_PAT.search(line):
            out.append(f"{name}.py:{i}: {line.strip()}")

report = ROOT / "scratch" / "sweep.txt"
report.write_text("\n".join(out), encoding="utf-8")
print(f"{len(out)} lines written to scratch/sweep.txt")
sys.exit(0)
