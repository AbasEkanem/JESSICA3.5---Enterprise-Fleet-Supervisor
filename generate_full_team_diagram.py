"""
generate_full_team_diagram.py
Generates jessica_full_team.mmd (full L0→L1→L2 hierarchy)
and renders jessica_full_team.png via mmdc.
"""
import subprocess, sys
from pathlib import Path

BASE = Path(__file__).parent
MMD  = BASE / "jessica_full_team.mmd"
PNG  = BASE / "jessica_full_team.png"
CFG  = BASE / "mmdc_config.json"

if not CFG.exists():
    CFG.write_text('{"theme":"default"}', encoding="utf-8")

DIAGRAM = """\
---
config:
  theme: base
  themeVariables:
    primaryColor: "#121a23"
    primaryTextColor: "#e9eef4"
    primaryBorderColor: "#5c93f5"
    lineColor: "#5c93f5"
    secondaryColor: "#1a242f"
    tertiaryColor: "#0d141c"
    background: "#0d141c"
    mainBkg: "#121a23"
    clusterBkg: "#1a242f"
    clusterBorder: "#3fcbb6"
    titleColor: "#e9eef4"
    edgeLabelBackground: "#1a242f"
    fontFamily: "Inter, system-ui, sans-serif"
  flowchart:
    curve: basis
    padding: 20
---
flowchart TD
    %% ── L0 Orchestrator ─────────────────────────────────────────────────────
    J["Jessica 3.5\nOrchestrator — L0\n(memory · datetime · bg-tasks)"]

    %% ── L1 Domain Supervisors ───────────────────────────────────────────────
    subgraph SCOUT["Scout — Research Supervisor"]
        direction TB
        Sophie["Sophie\nMulti-engine search\nTavily · Exa · Linkup\nFact-check · News"]
    end

    subgraph RELAY["Relay — Comms Supervisor"]
        direction TB
        Jordan["Jordan\nEmail\ndraft · schedule · send\nread · search"]
        Tyler["Tyler\nSlack\nmessages · threads\nDMs · reactions"]
    end

    subgraph GEMMA["Gemma — Google Workspace Supervisor"]
        direction LR
        Alex["Alex\nDrive\nsearch · upload\nshare · trash"]
        Taylor["Taylor\nDocs"]
        Riley["Riley\nSlides"]
        Chris["Chris\nSheets"]
        Francis["Francis\nForms"]
        Casey["Casey\nCalendar"]
        Sam["Sam\nClassroom\ncourses · rosters"]
        Juliet["Juliet\nClassroom\ncoursework · grades"]
    end

    subgraph FORGE["Forge — Project Mgmt Supervisor"]
        direction TB
        Morgan["Morgan\nJira\nissues · sprints\ntransitions · BSE"]
        Connie["Connie\nConfluence\npages · CQL\ncomments"]
    end

    %% ── Edges L0 → L1 ───────────────────────────────────────────────────────
    J -->|"research_agent"| SCOUT
    J -->|"comms_agent"| RELAY
    J -->|"google_workspace_agent"| GEMMA
    J -->|"project_mgmt_agent"| FORGE

    %% ── Style classes ────────────────────────────────────────────────────────
    classDef l0 fill:#5c93f5,color:#06101f,stroke:#5c93f5,font-weight:bold,font-size:14px
    classDef scout fill:#3fcbb6,color:#05080c,stroke:#3fcbb6
    classDef relay fill:#8f7bf8,color:#fff,stroke:#8f7bf8
    classDef gemma fill:#5c93f5,color:#fff,stroke:#5c93f5
    classDef forge fill:#f5a35c,color:#06101f,stroke:#f5a35c

    class J l0
    class Sophie scout
    class Jordan,Tyler relay
    class Alex,Taylor,Riley,Chris,Francis,Casey,Sam,Juliet gemma
    class Morgan,Connie forge
"""

MMD.write_text(DIAGRAM, encoding="utf-8")
print("[OK] jessica_full_team.mmd written")

print("Rendering PNG ...")
r = subprocess.run(
    ["npx", "-y", "@mermaid-js/mermaid-cli",
     "-i", str(MMD), "-o", str(PNG), "-c", str(CFG)],
    capture_output=True, text=True, shell=True,
)

if r.returncode == 0:
    print(f"[OK] jessica_full_team.png saved -- {PNG.stat().st_size:,} bytes")
else:
    print("STDERR:", r.stderr[-2000:])
    print("STDOUT:", r.stdout[-500:])
    sys.exit(1)
