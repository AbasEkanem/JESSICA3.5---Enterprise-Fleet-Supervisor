"""
fix_mermaid_and_render.py
Reads jessica_fleet_graph.mmd, sanitises it, and renders a PNG via mmdc.

Fixes applied
─────────────
1. Strips YAML front-matter  (--- block)
2. Decodes LangGraph hex escapes in node IDs  (\2e → _dot_  \5b → _lb_  \5d → _rb_)
3. Strips HTML <p> tags from __start__ / __end__ labels
4. Quotes any node label that contains literal [ or ]
   (Mermaid's parser treats [ as a shape delimiter inside labels)
"""

import re
import subprocess
import sys
from pathlib import Path

BASE  = Path(__file__).parent
SRC   = BASE / "jessica_fleet_graph.mmd"
FIXED = BASE / "jessica_fleet_graph_fixed.mmd"
PNG   = BASE / "jessica_fleet_graph.png"
CFG   = BASE / "mmdc_config.json"

if not CFG.exists():
    CFG.write_text('{"theme":"default"}', encoding="utf-8")

raw_lines = SRC.read_text(encoding="utf-8").splitlines()

# ── 1. Strip YAML front-matter  ─────────────────────────────────────────────
if raw_lines and raw_lines[0].strip() == "---":
    for i in range(1, len(raw_lines)):
        if raw_lines[i].strip() == "---":
            raw_lines = raw_lines[i + 1:]
            break

# ── 2-4. Process each line  ──────────────────────────────────────────────────
out_lines = []
for line in raw_lines:
    # 2. Decode hex escapes (only appear in node IDs, never in labels)
    line = line.replace("\\2e", "_dot_")
    line = line.replace("\\5b", "_lb_")
    line = line.replace("\\5d", "_rb_")

    # 3. Strip HTML paragraph tags from labels
    line = line.replace("<p>", "").replace("</p>", "")

    # 4. Quote labels containing [ or ]
    # Only touch node *definition* lines, not edge lines
    is_edge = ("-->" in line or "-.->" in line or "-..->" in line)
    if not is_edge:
        # Pattern: <indent><nodeId><( or ([><label><) or ])><:::class>?
        m = re.match(
            r'^(\s+)(\S+?)(\(\[?|\[\[?)(.+?)(\]?\)|\]\])(:::[\w]+)?\s*$',
            line
        )
        if m:
            indent, node_id, open_p, label, close_p, cls = m.groups()
            cls = cls or ""
            if "[" in label or "]" in label:
                # Double-quote the label so Mermaid treats it as literal text
                label = '"' + label.replace('"', '\\"') + '"'
            line = f"{indent}{node_id}{open_p}{label}{close_p}{cls}"

    out_lines.append(line)

fixed_mmd = "\n".join(out_lines)
FIXED.write_text(fixed_mmd, encoding="utf-8")

print("[OK] Fixed .mmd written")
print("-" * 60)
print(fixed_mmd[:900])
print("-" * 60, "\n")

# ── Render with mmdc  ────────────────────────────────────────────────────────
print("Rendering PNG with mmdc …")
r = subprocess.run(
    [
        "npx", "-y", "@mermaid-js/mermaid-cli",
        "-i", str(FIXED),
        "-o", str(PNG),
        "-c", str(CFG),
    ],
    capture_output=True, text=True, shell=True,
)

if r.returncode == 0:
    size = PNG.stat().st_size
    print(f"[OK] Saved jessica_fleet_graph.png — {size:,} bytes")
else:
    print("[STDERR]", r.stderr[-2000:])
    print("[STDOUT]", r.stdout[-500:])
    sys.exit(1)
