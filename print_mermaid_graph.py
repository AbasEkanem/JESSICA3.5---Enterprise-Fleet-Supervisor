import importlib.util
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load Jessica app dynamically
# ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("jessica", "JESSICA3.5.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

graph = mod.create_jessicaAI()

# ---------------------------------------------------------------------------
# Extract raw Mermaid definition (includes YAML front-matter — mmdc handles it)
# ---------------------------------------------------------------------------
mermaid_raw = graph.get_graph().draw_mermaid()

print("=== Mermaid Definition ===")
print(mermaid_raw)
print("==========================\n")

base      = Path(__file__).parent
mmd_file  = base / "jessica_fleet_graph.mmd"
png_file  = base / "jessica_fleet_graph.png"
cfg_file  = base / "mmdc_config.json"

# Write a minimal mmdc theme config
cfg_file.write_text('{"theme": "default"}', encoding="utf-8")

# Write the Mermaid source
mmd_file.write_text(mermaid_raw, encoding="utf-8")
print(f"[OK] Written {mmd_file.name}")

# ---------------------------------------------------------------------------
# Render with mmdc (Mermaid CLI) via npx — installs automatically if absent
# ---------------------------------------------------------------------------
cmd = [
    "npx", "-y", "@mermaid-js/mermaid-cli",
    "-i", str(mmd_file),
    "-o", str(png_file),
    "-c", str(cfg_file),
    "--quiet",
]

print(f"Rendering with mmdc …")
result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

if result.returncode == 0:
    size = png_file.stat().st_size
    print(f"[OK] Saved {png_file.name} ({size:,} bytes)")
else:
    print("[STDERR]", result.stderr)
    print("[STDOUT]", result.stdout)
    sys.exit(1)
