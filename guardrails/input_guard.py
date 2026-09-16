"""
guardrails/input_guard.py — Layer 1: Input Guardrail.

Production pattern (LangChain 2025):
    Deterministic, regex-based scan of user input BEFORE the LLM sees it.
    Catches prompt injection attempts, jailbreak patterns, and PII.
    Fast (<1ms), zero LLM cost, runs on every request.

Why deterministic, not LLM-based:
    LLM-based input classifiers can themselves be jailbroken.
    A fast regex/keyword layer is the first line of defense —
    the LLM-based guardrail (NeMo, LlamaGuard) is a second optional layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# ── Prompt injection patterns ─────────────────────────────────────────────────
# Research-backed pattern set (2025 production standard):
# Covers the most common injection vectors used in production adversarial datasets.
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in [
        r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?",
        r"forget\s+(everything|all\s+previous|your\s+instructions?)",
        r"your\s+new\s+instructions?\s+(are|is)\s*[:\-]",
        r"(you\s+are\s+now|from\s+now\s+on\s+you\s+are)\s+(?!jessica)",
        r"pretend\s+(you\s+are|to\s+be)\s+(?!jessica)",
        r"\bDAN\b",                          # Do Anything Now jailbreak
        r"jailbreak",
        r"override\s+(your\s+)?(safety|guidelines?|system\s+prompt|instructions?)",
        r"(act\s+as|roleplay\s+as)\s+(?!jessica)",
        r"disregard\s+(all\s+)?(rules?|guidelines?|instructions?|constraints?)",
        r"system\s*prompt\s*[:=]\s*",        # Injection via fake system prompt header
        r"<\s*system\s*>",                   # XML-style injection
        r"\[SYSTEM\]",                       # Bracket injection
        r"##\s*Instructions?\s*##",          # Markdown header injection
    ]
]

# ── Basic PII patterns (flag, do not block — log for observability) ───────────
_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("ssn",         re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")),
    ("api_key",     re.compile(r"\b(sk-[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9_-]{30,})\b")),
]

# ── Max message length ────────────────────────────────────────────────────────
_MAX_MESSAGE_LENGTH = 32_000  # chars — prevents context stuffing attacks


def contains_injection(text: str) -> Optional[str]:
    """Return the matched injection snippet if `text` contains a known
    prompt-injection pattern, else None.

    MEM-01: exposed as a reusable helper so other layers (e.g. the memory-write
    validator in memory_manager.py) can reject content that survived Layer 1 or
    arrived via an untrusted channel (an uploaded file, a tool output) before it
    is persisted as a long-lived memory. Reuses the same compiled pattern set as
    scan_message so there is a single source of truth for what "injection" means.
    """
    if not text:
        return None
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)[:60]
    return None


@dataclass
class InputGuardResult:

    """Result of an input guard scan."""
    safe:           bool
    message:        str                    # original or cleaned message
    blocked_reason: Optional[str] = None
    pii_detected:   list[str] = field(default_factory=list)
    was_truncated:  bool = False


def scan_message(message: str, user_email: str = "") -> InputGuardResult:
    """
    Scan a user message for prompt injection and PII.

    Returns an InputGuardResult. If safe=False, the caller MUST NOT
    pass the message to the agent.

    Args:
        message:    Raw user message string.
        user_email: Used for audit log correlation only.
    """
    log = logger.bind(user=user_email)

    # ── 1. Length guard 
    was_truncated = False
    if len(message) > _MAX_MESSAGE_LENGTH:
        log.warning(
            "input_guard.truncated",
            original_len=len(message),
            limit=_MAX_MESSAGE_LENGTH,
        )
        message = message[:_MAX_MESSAGE_LENGTH]
        was_truncated = True

    # ── 2. Prompt injection detection 
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(message)
        if m:
            reason = f"Prompt injection pattern detected: '{m.group(0)[:60]}'"
            log.warning("input_guard.injection_blocked", reason=reason)
            return InputGuardResult(
                safe=False,
                message=message,
                blocked_reason=reason,
                was_truncated=was_truncated,
            )

    # ── 3. PII detection + redaction 
    # MED-04: previously PII was logged but the ORIGINAL message was passed
    # through unredacted — leaking credit cards / SSNs / API keys to the NVIDIA
    # NIM API, LangSmith traces, and the Postgres checkpointer. We now redact
    # each detected pattern before the message continues downstream. The
    # detected-type list is still returned for observability.
    detected_pii: list[str] = []
    redacted = message
    for pii_type, pattern in _PII_PATTERNS:
        if pattern.search(redacted):
            detected_pii.append(pii_type)
            log.warning("input_guard.pii_detected", pii_type=pii_type)
            redacted = pattern.sub(f"[REDACTED_{pii_type.upper()}]", redacted)

    return InputGuardResult(
        safe=True,
        message=redacted,
        pii_detected=detected_pii,
        was_truncated=was_truncated,
    )

