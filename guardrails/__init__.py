"""
guardrails/ — Production guardrail middleware for Jessica 3.5.

Layers implemented:
    Layer 1: input_guard  — Prompt injection detection, PII scan, message sanitization
    Layer 2: router       — LLM-based intent classification → subagent routing hint
    Layer 3: output_guard — SSE stream sanitization (JSON/tool-call leak prevention)
"""

from guardrails.input_guard import InputGuardResult, contains_injection, scan_message
from guardrails.router import RoutingDecision, recursion_budget_for, route_message

__all__ = [
    "InputGuardResult",
    "scan_message",
    "contains_injection",
    "RoutingDecision",
    "route_message",
    "recursion_budget_for",
]

