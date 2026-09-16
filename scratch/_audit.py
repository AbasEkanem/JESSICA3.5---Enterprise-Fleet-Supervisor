"""Static project audit: syntax + unresolvable local imports (no .pyc litter).

Catches the class of bug that py_compile cannot: a module imported at top level
that does not exist anywhere (e.g. jessica_harness), which only fails at runtime.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(".")
SKIP = {"jessica3.0_venv", "node_modules", "__pycache__", ".git", ".kilo", "uploads"}

files: list[Path] = []
local_mods: set[str] = set()
for p in sorted(ROOT.rglob("*.py")):
    if set(p.parts) & SKIP:
        continue
    files.append(p)
    if p.name == "__init__.py":
        local_mods.add(p.parent.name)
    elif p.parent == ROOT:
        local_mods.add(p.stem)

sp = Path("jessica3.0_venv/Lib/site-packages")
installed = {d.name.split(".")[0].lower() for d in sp.iterdir() if d.is_dir()}
installed |= {f.stem.split(".")[0].lower() for f in sp.glob("*.py")}
stdlib = {m.lower() for m in sys.stdlib_module_names}

syntax_errors: list[str] = []
missing: dict[str, list[str]] = {}

for f in files:
    try:
        tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError as exc:
        syntax_errors.append(f"{f}:{exc.lineno}: {exc.msg}")
        continue
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # relative import, resolvable by construction
            if node.module:
                names = [node.module.split(".")[0]]
        for n in names:
            if n.lower() in installed or n.lower() in stdlib or n in local_mods:
                continue
            missing.setdefault(n, []).append(f"{f}:{getattr(node, 'lineno', '?')}")

print(f"scanned_py_files={len(files)}")
print(f"local_top_level_modules={len(local_mods)}")
print(f"syntax_errors={len(syntax_errors)}")
for s in syntax_errors:
    print(f"  SYNTAX {s}")
print(f"unresolvable_imports={len(missing)}")
for name in sorted(missing):
    refs = missing[name]
    print(f"  MISSING '{name}' referenced {len(refs)}x")
    for r in refs[:8]:
        print(f"      {r}")
