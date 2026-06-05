"""
Prompt injection detector — Security Capa 2.

Scans incoming user messages for prompt injection patterns before they
reach the LLM. Operates in three severity levels:

  high   → block the request  (attempts to hijack agent identity/behavior)
  medium → sanitize + warn    (suspicious but not definitively malicious)
  low    → log only           (borderline patterns worth tracking)

Complements:
  - Capa 1: anti-injection rules in the system prompt (prompts/base.py)
  - Capa 4: user_id isolation in tools via ContextVar (core/context.py)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

from core.logging import get_audit_logger

_log = logging.getLogger("sara.security")
_audit = get_audit_logger()

# ── Pattern registry ──────────────────────────────────────────────────────────


@dataclass
class InjectionRule:
    """A regex pattern that matches a prompt injection attempt."""

    pattern: re.Pattern
    reason: str          # Human-readable explanation
    severity: str        # "high", "medium", or "low"


_RULES: list[InjectionRule] = [
    # ── HIGH severity: definitive hijack attempts ───
    InjectionRule(
        re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
        "attempt to override system instructions",
        "high",
    ),
    InjectionRule(
        re.compile(r"olvid[áa]\s+(todas|las)\s+(instrucciones|reglas|indicaciones)\s+(anteriores|previas)", re.IGNORECASE),
        "intento de ignorar instrucciones del sistema (español)",
        "high",
    ),
    InjectionRule(
        re.compile(r"you\s+are\s+now\s+(?!SARA|ITS|helpdesk|mesa)", re.IGNORECASE),
        "attempt to redefine agent identity",
        "high",
    ),
    InjectionRule(
        re.compile(r"act[uú]a\s+como\s+(?!SARA|asistente|soporte)", re.IGNORECASE),
        "intento de cambiar rol del agente",
        "high",
    ),
    InjectionRule(
        re.compile(r"(reveal|show|display|print|dump)\s+(the\s+)?(system\s+)?(prompt|instructions?|rules?)", re.IGNORECASE),
        "attempt to extract system prompt",
        "high",
    ),
    InjectionRule(
        re.compile(r"(mu[eé]str[aá]me?|dime?|revela)\s+(las?\s+)?(el\s+)?(prompt|sistema|instrucciones|reglas)\b", re.IGNORECASE),
        "intento de extraer prompt del sistema (español)",
        "high",
    ),
    InjectionRule(
        re.compile(r"(api[_\s]?key|api_key|apikey|contraseña|password|secret)", re.IGNORECASE),
        "attempt to extract credentials",
        "high",
    ),
    InjectionRule(
        re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
        "attempt to override system instructions (disregard)",
        "high",
    ),

    # ── MEDIUM severity: suspicious patterns ───
    InjectionRule(
        re.compile(r"(respond|reply|answer)\s+(only|exclusively|siempre)\s+(in|en)\s+(english|ingl[eé]s)", re.IGNORECASE),
        "attempt to force language override",
        "medium",
    ),
    InjectionRule(
        re.compile(r"(eres|ahora eres|tu eres)\s+(un|una)\s+(?!asistente|SARA)", re.IGNORECASE),
        "intento de redefinir rol del agente (español, débil)",
        "medium",
    ),
    InjectionRule(
        re.compile(r"(delete|borra|elimina|drop)\s+.*\s+(from|de)\s+(database|base|bd)", re.IGNORECASE),
        "suspicious database manipulation request",
        "medium",
    ),
    InjectionRule(
        re.compile(r"(sudo|root|admin)\s+(access|acceso)", re.IGNORECASE),
        "privilege escalation attempt",
        "medium",
    ),

    # ── LOW severity: worth logging ───
    InjectionRule(
        re.compile(r"(fake|false|mentira|falso)\s+(response|respuesta|answer)", re.IGNORECASE),
        "requesting fake/misleading output",
        "low",
    ),
    InjectionRule(
        re.compile(r"jailbreak|bypass|saltar\s+(restricci[oó]n|filtro)", re.IGNORECASE),
        "jailbreak/bypass terminology",
        "low",
    ),
]

# ── Detector function ─────────────────────────────────────────────────────────


@dataclass
class DetectionResult:
    """Result of scanning a message for injection patterns."""

    blocked: bool
    reason: Optional[str] = None
    severity: Optional[str] = None
    pattern_matched: Optional[str] = None  # The regex that matched


def scan_message(message: str, user_id: int, thread_id: str) -> DetectionResult:
    """
    Scans a user message for prompt injection patterns.

    Blocking rules (high severity):
      - Returns DetectionResult(blocked=True) immediately.
      - Logs a warning with user_id and thread_id.

    Non-blocking rules (medium/low severity):
      - Logs the pattern but does NOT block.
      - Returns DetectionResult(blocked=False).

    All matches are logged to sara.security logger for audit.
    """
    if not message:
        return DetectionResult(blocked=False)

    for rule in _RULES:
        match = rule.pattern.search(message)
        if match:
            ctx = f"user={user_id} thread={thread_id} severity={rule.severity}"
            matched_text = match.group(0)[:80]

            if rule.severity == "high":
                _log.warning(
                    "PROMPT INJECTION BLOCKED — %s | pattern='%s' | text='%s'",
                    ctx, rule.reason, matched_text,
                )
                _audit.warning(
                    "injection_blocked",
                    extra={
                        "user_id": user_id,
                        "thread_id": thread_id,
                        "severity": rule.severity,
                        "pattern": rule.reason,
                        "matched_text": matched_text[:100],
                    },
                )
                return DetectionResult(
                    blocked=True,
                    reason=rule.reason,
                    severity="high",
                    pattern_matched=rule.pattern.pattern[:80],
                )
            elif rule.severity == "medium":
                _log.info(
                    "PROMPT INJECTION WARN — %s | pattern='%s' | text='%s'",
                    ctx, rule.reason, matched_text,
                )
                # Medium: sanitize by replacing suspicious text
                sanitized = rule.pattern.sub("[contenido filtrado]", message)
                if sanitized != message:
                    _log.info("PROMPT SANITIZED — %s | original_len=%d sanitized_len=%d",
                              ctx, len(message), len(sanitized))
                return DetectionResult(blocked=False, severity="medium")
            else:  # low
                _log.info(
                    "PROMPT INJECTION LOG — %s | pattern='%s' | text='%s'",
                    ctx, rule.reason, matched_text,
                )
                return DetectionResult(blocked=False, severity="low")

    return DetectionResult(blocked=False)
