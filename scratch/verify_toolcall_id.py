"""Reproduce the `[400] missing field id` path end-to-end, through the REAL
ChatNVIDIA serializer. Run: python scratch/verify_toolcall_id.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, ToolMessage
from langchain_nvidia_ai_endpoints._utils import convert_message_to_dict

from nemotron_harness import NemotronWireCompatibilityMiddleware

fails = []


def check(name, cond):
    print(f"  {'[PASS]' if cond else '[FAIL]'} {name}")
    if not cond:
        fails.append(name)


# Exactly what NemotronToolCallRepairMiddleware produces: typed tool_calls,
# NO additional_kwargs mirror. This is the message that 400'd.
repaired = AIMessage(
    content="",
    tool_calls=[{"name": "get_current_time", "args": {"tz": "UTC"}, "id": "nh_repair_0", "type": "tool_call"}],
)
result = ToolMessage(content="12:30", tool_call_id="nh_repair_0", name="get_current_time")

print("1. repaired call survives the wire mirror")
mirrored = NemotronWireCompatibilityMiddleware._repair_message(repaired)
wire = convert_message_to_dict(mirrored)
print(f"     wire tool_calls -> {wire.get('tool_calls')}")
check("tool_calls present on the wire", bool(wire.get("tool_calls")))
call = (wire.get("tool_calls") or [{}])[0]
check("has non-empty 'id' (the 400)", bool(call.get("id")))
check("id matches the source call", call.get("id") == "nh_repair_0")
check("type/function intact", call.get("type") == "function" and call["function"]["name"] == "get_current_time")

print("2. id pairs to the ToolMessage the endpoint validates against")
check("tool_call_id matches assistant id", convert_message_to_dict(result)["tool_call_id"] == call.get("id"))

print("3. server-parsed calls (additional_kwargs already set) are left alone")
server = AIMessage(
    content="",
    tool_calls=[{"name": "t", "args": {}, "id": "call_srv", "type": "tool_call"}],
    additional_kwargs={"tool_calls": [{"id": "call_srv", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
)
check("unchanged (identity)", NemotronWireCompatibilityMiddleware._repair_message(server) is server)

print("4. malformed call (no id) still never emits a missing id")
noid = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": None, "type": "tool_call"}])
w = convert_message_to_dict(NemotronWireCompatibilityMiddleware._repair_message(noid))
check("fallback id generated", bool((w.get("tool_calls") or [{}])[0].get("id")))

print("\n" + "=" * 60)
if fails:
    print(f"{len(fails)} FAILURES: {fails}")
    sys.exit(1)
print("ALL CHECKS PASSED")
sys.exit(0)
