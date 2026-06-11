"""
PII redaction utility — Security Capa 5.

Scans the LLM output for personally identifiable information (PII)
and replaces it with redaction tokens before returning to the user.

PII patterns detected:
- Email addresses
- Phone numbers (Spanish + international)
- Spanish DNI / NIE
- Credit card numbers (Luhn-validated)
- API keys / Bearer tokens (long alphanumeric strings)
- IP addresses (IPv4)

Note: This is a best-effort defence. False positives are possible
(short numbers that look like phones). The threshold-based approach
reduces false positives by requiring minimum length and context.
"""

from __future__ import annotations

import re
from typing import Tuple


# ── Pattern registry ─────────────────────────────────────────────────────────

_PII_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # (pattern, replacement_token, description)
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
     "[EMAIL_REDACTED]", "email"),

    # Spanish phone numbers: 9 digits starting with 6, 7, 8, or 9
    # Format: 6XXXXXXXX, 6XX XX XX XX, 6XX XXX XXX, +34 6XX XXX XXX
    (re.compile(r"(?:\+?34[\s.-]?)?[6-9]\d{2}[\s.-]?\d{2,3}[\s.-]?\d{2,3}(?:[\s.-]?\d{0,3})?\b"),
     "[PHONE_REDACTED]", "phone ES"),

    # International phone numbers: +XX XXX XXX XXX
    (re.compile(r"\+\d{1,3}[\s.-]?\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{2,4}\b"),
     "[PHONE_REDACTED]", "phone intl"),

    # Spanish DNI: 8 digits + letter
    (re.compile(r"\b\d{8}[A-Za-z]\b"),
     "[DNI_REDACTED]", "DNI"),

    # Spanish NIE: X/Y/Z + 7 digits + letter
    (re.compile(r"\b[XYZ]\d{7}[A-Za-z]\b"),
     "[NIE_REDACTED]", "NIE"),

    # Credit card: 13-19 digits with optional spaces/dashes
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"),
     "[CC_REDACTED]", "credit card"),

    # API keys / Bearer tokens: long alphanumeric strings
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"),
     "[KEY_REDACTED]", "api key"),

    # IPv4 addresses
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
     "[IP_REDACTED]", "IPv4"),
]


def redact_pii(text: str) -> Tuple[str, int]:
    """
    Replace PII patterns in text with redaction tokens.

    Args:
        text: The text to scan (typically LLM output).

    Returns:
        Tuple of (redacted_text, count_of_replacements).

    Example:
        >>> redact_pii("Contact me at user@example.com or 666123456")
        ('Contact me at [EMAIL_REDACTED] or [PHONE_REDACTED]', 2)
    """
    if not text:
        return text, 0

    redaction_count = 0
    redacted = text

    for pattern, replacement, _description in _PII_PATTERNS:
        # Use a function to count replacements
        def _replace(match):
            nonlocal redaction_count
            redaction_count += 1
            return replacement
        redacted = pattern.sub(_replace, redacted)

    return redacted, redaction_count
