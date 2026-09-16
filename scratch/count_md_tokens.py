"""
Count tokens (tiktoken cl100k_base, exact) for every prompt/markdown file that
feeds the model, so we can measure context bloat before/after edits.

Usage:  python scratch/count_md_tokens.py
"""
from __future__ import annotations

from pathlib import Path

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")

    def _count(text: str) -> int:
        return len(_enc.encode(text))

    _METHOD = "tiktoken cl100k_base (exact)"
except Exception:  # pragma: no cover - fallback if tiktoken missing
    def _count(text: str) -> int:
        # ~4 chars/token heuristic
        return max(1, len(text) // 4)

    _METHOD = "char/4 heuristic (approx)"


ROOT = Path(__file__).resolve().parent.parent

# Glob the model-facing markdown: subagent prompts, skills, and the top-level
# persistent memory / workspace docs.
PATTERNS = [
    "prompts/**/*.md",
    "skills/**/*.md",
    "*.md",
    "Users/**/*.md",
]


def main() -> None:
    seen: set[Path] = set()
    rows: list[tuple[int, str]] = []
    for pat in PATTERNS:
        for p in ROOT.glob(pat):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            rows.append((_count(text), str(p.relative_to(ROOT))))

    rows.sort(reverse=True)
    total = sum(n for n, _ in rows)

    print(f"Method: {_METHOD}\n")
    for n, name in rows:
        print(f"{n:6d}  {name}")
    print("=" * 50)
    print(f"{total:6d}  TOTAL TOKENS")
    print(f"{len(rows):6d}  FILE COUNT")

    # Focused subtotal: just the subagent prompt files.
    sub = [(n, name) for n, name in rows if "prompts/subagents/" in name.replace("\\", "/")]
    if sub:
        sub_total = sum(n for n, _ in sub)
        print("\n-- prompts/subagents/ only --")
        for n, name in sorted(sub, reverse=True):
            print(f"{n:6d}  {name}")
        print(f"{sub_total:6d}  SUBAGENT PROMPT TOTAL  ({len(sub)} files)")


if __name__ == "__main__":
    main()
