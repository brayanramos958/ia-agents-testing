"""
Reusable field validators for Pydantic schemas.

Each validator is a ``@field_validator`` or plain function that enforces
one constraint (type, range, non-empty, existing catalog ID). They are
composed into tool schemas in ``schemas.py``.

All validators return the validated value or raise ``ValueError`` with
a message the LLM can understand and act on to correct its tool calls.
"""

from typing import Any


def ensure_positive_int(v: Any, field_name: str = "valor") -> int:
    """
    Validate that a value is a positive integer.

    The LLM often passes strings ("123"), floats (3.0), or negative numbers
    (-1). This normalises to int and rejects invalid ranges.
    """
    if isinstance(v, str):
        try:
            v = int(v)
        except (ValueError, TypeError):
            raise ValueError(
                f"'{field_name}' debe ser un número entero positivo, "
                f"pero se recibió '{v}' (string). "
                f"Ejemplo válido: 5"
            )
    if isinstance(v, float):
        if v != int(v):
            raise ValueError(
                f"'{field_name}' debe ser un número entero, "
                f"pero se recibió {v} (decimal). Usa el ID numérico del catálogo."
            )
        v = int(v)
    if not isinstance(v, int) or v <= 0:
        raise ValueError(
            f"'{field_name}' debe ser un número positivo, "
            f"pero se recibió {v}. Los IDs de catálogo son números > 0."
        )
    return v


def ensure_non_empty_str(v: Any, field_name: str = "texto", min_len: int = 3) -> str:
    """
    Validate that a value is a non-empty string with minimum length.

    The LLM sometimes passes None, empty strings, or numeric values
    for string fields like ``asunto`` or ``motivo_resolucion``.
    """
    if v is None:
        raise ValueError(
            f"'{field_name}' es requerido y no puede estar vacío. "
            f"Proporciona un texto descriptivo de al menos {min_len} caracteres."
        )
    if isinstance(v, (int, float, bool)):
        raise ValueError(
            f"'{field_name}' debe ser texto, pero se recibió un número ({v}). "
            f"Describe el campo con palabras."
        )
    s = str(v).strip()
    if len(s) < min_len:
        raise ValueError(
            f"'{field_name}' es demasiado corto ({len(s)} caracteres). "
            f"Mínimo requerido: {min_len} caracteres. "
            f"Proporciona más detalle."
        )
    return s


def ensure_dict(v: Any, field_name: str = "fields") -> dict:
    """
    Validate that a value is a dict.

    The LLM sometimes passes JSON strings, lists, or None for dict fields
    like ``update_ticket.fields``.
    """
    if v is None:
        raise ValueError(
            f"'{field_name}' es requerido y debe ser un diccionario, "
            f"pero se recibió None. Ejemplo válido: {{\"asunto\": \"Nuevo título\"}}"
        )
    if isinstance(v, str):
        import json
        try:
            parsed = json.loads(v)
            if not isinstance(parsed, dict):
                raise ValueError(
                    f"'{field_name}' se recibió como string JSON pero no es un "
                    f"diccionario. Recibido: {v[:100]}"
                )
            return parsed
        except json.JSONDecodeError:
            raise ValueError(
                f"'{field_name}' debe ser un diccionario, pero se recibió un "
                f"string que no es JSON válido: '{v[:80]}'"
            )
    if not isinstance(v, dict):
        raise ValueError(
            f"'{field_name}' debe ser un diccionario, pero se recibió "
            f"{type(v).__name__}: {str(v)[:80]}"
        )
    return v


def ensure_optional_str(v: Any, field_name: str = "texto", max_len: int = 200) -> str | None:
    """Validate optional string fields (None OK, but non-empty if provided)."""
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return str(v)[:max_len]
    s = str(v).strip()
    return s[:max_len] if s else None


def ensure_ticket_id(v: Any) -> int:
    """
    Validate a ticket_id — strip INC- prefix, ensure positive int.

    The LLM often passes ticket names like 'INC-002920' instead of numeric IDs.
    """
    if isinstance(v, str):
        v_lower = v.lower().strip()
        for prefix in ("inc-", "sr-", "tck-", "ticket-", "#"):
            if v_lower.startswith(prefix):
                v = v[len(prefix):]
                break
    return ensure_positive_int(v, field_name="ticket_id")
