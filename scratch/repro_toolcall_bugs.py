"""Repro for the two defects behind the `400 missing field id` + `</tool_call>` leak.

Run:  ./jessica3.0_venv/Scripts/python.exe scratch/repro_toolcall_bugs.py
Exits non-zero while the bugs are present.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, ToolMessage
import nemotron_harness as nh

fails = []
def check(name, cond):
    print(f"  {'[PASS]' if cond else '[FAIL]'} {name}")
    if not cond:
        fails.append(name)

# ── Defect A: the OpenAI mirror must carry `id` (NIM 400 `missing field id`)
print("A. _to_openai_tool_calls preserves id")
tc = [{"name": "get_current_datetime", "args": {}, "id": "nh_repair_0", "type": "tool_call"}]
mirror = nh._to_openai_tool_calls(tc)
check("mirror entry has 'id' key", "id" in mirror[0])
check("mirror id == source id (ToolMessage pairing)", mirror[0].get("id") == "nh_repair_0")
check("mirror keeps type/function shape",
      mirror[0].get("type") == "function" and mirror[0]["function"]["name"] == "get_current_datetime")

# ── Defect A end-to-end: repaired message -> wire middleware -> valid wire payload
print("A2. wire middleware end-to-end")
msg = AIMessage(content="", tool_calls=tc)
repaired = nh.NemotronWireCompatibilityMiddleware._repair_message(msg)
wire = (repaired.additional_kwargs or {}).get("tool_calls") or []
check("wire mirror produced", bool(wire))
check("wire mirror has id", bool(wire) and bool(wire[0].get("id")))
check("wire id matches tool_call id", bool(wire) and wire[0].get("id") == "nh_repair_0")

# ── Defect B: the real Nemotron/Hermes tag is lowercase+underscore
print("B. <tool_call> envelope recognised")
real = '<tool_call>{"name": "get_current_datetime", "arguments": {}}</tool_call>'
check("regex matches <tool_call>", bool(nh._TOOLCALL_TAG_RE.search(real)))
check("candidate parsed from <tool_call>",
      bool(nh._candidates_from_text(real)) and nh._candidates_from_text(real)[0]["name"] == "get_current_datetime")
check("envelope fully stripped", nh._strip_call_text(real) == "")
check("legacy <TOOLCALL> still works",
      bool(nh._TOOLCALL_TAG_RE.search('<TOOLCALL>{"name": "x", "arguments": {}}</TOOLCALL>')))

# ── Defect B2: orphan closing tag (NIM ate the opener) must not reach the user
print("B2. orphan tag leak")
orphan = '</tool_call>'
check("bare orphan tag scrubbed to empty", nh._strip_call_text(orphan) == "")
half = '{"name": "get_current_datetime", "arguments": {}}\n</tool_call>'
check("half-consumed envelope parses", bool(nh._candidates_from_text(half)))
check("half-consumed envelope strips clean", nh._strip_call_text(half) == "")

# ── Regression guard: prose mentioning the tag must NOT be destroyed
print("B3. regression guard - prose is preserved")
prose = "You can wrap calls in a <tool_call> envelope when using Hermes models."
check("prose without JSON left intact", nh._strip_call_text(prose) == prose)

print()
if fails:
    print(f"{len(fails)} FAILING: {fails}")
    sys.exit(1)
print("repro: all green")
