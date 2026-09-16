"""
Verify every subagent prompt loads cleanly and carries the new contract lines.

Checks, per subagent document in subagent.yaml:
  1. prompt_file resolves + is non-empty.
  2. Prompt contains an `EXPERIENCE:` contract line.
  3. Prompt contains a `RESULT:` contract line.
  4. Prompt contains the `<think>` reasoning-wrap instruction.

This deliberately avoids importing loadenv / building live models — it only
parses the YAML + reads the referenced markdown, so it runs with zero network.

Usage:  python scratch/verify_subagent_prompts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
YAML = ROOT / "subagent.yaml"


def main() -> int:
    docs = [d for d in yaml.safe_load_all(YAML.read_text(encoding="utf-8")) if d]
    failures: list[str] = []
    print(f"Found {len(docs)} subagent document(s) in {YAML.name}\n")

    for doc in docs:
        name = doc.get("name", "<unnamed>")
        pf = doc.get("prompt_file") or doc.get("system_prompt_file")
        if not pf:
            failures.append(f"{name}: no prompt_file")
            continue
        path = ROOT / pf
        if not path.exists():
            failures.append(f"{name}: prompt_file missing → {pf}")
            continue
        text = path.read_text(encoding="utf-8")
        checks = {
            "EXPERIENCE:": "EXPERIENCE:" in text,
            "RESULT:": "RESULT:" in text,
            "<think>": "<think>" in text,
            "non-empty": bool(text.strip()),
        }
        missing = [k for k, ok in checks.items() if not ok]
        status = "OK " if not missing else "FAIL"
        print(f"[{status}] {name:26s} ({len(text):4d} chars)  {pf}")
        if missing:
            failures.append(f"{name}: missing {missing}")

    print()
    if failures:
        print("VERIFICATION FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("All subagent prompts verified: EXPERIENCE + RESULT + <think> present, files load.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
