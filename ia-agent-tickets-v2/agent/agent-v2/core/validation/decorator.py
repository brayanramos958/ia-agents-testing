"""
``@validate_tool`` decorator — pre-execution validation for LangChain tools.

Wrapping a tool function with ``@validate_tool(SchemaClass)`` ensures that
arguments are validated against a Pydantic model BEFORE the tool touches
Odoo or any external system.

If validation fails, the decorator returns a structured error dict
(instead of raising an exception) so LangGraph can send it back to the
LLM as a ToolMessage. The LLM sees the validation errors and can correct
its arguments — no conversation crash, no broken graph state.

Usage::

    @tool
    @backend_retry
    @validate_tool(CreateTicketSchema)
    async def create_ticket(asunto: str, ...) -> dict:
        ...
"""

import functools
import logging

from pydantic import ValidationError

_log = logging.getLogger(__name__)


def validate_tool(schema):
    """
    Decorator that validates tool arguments against a Pydantic schema.

    Args:
        schema: A ``pydantic.BaseModel`` subclass that defines the expected
            shape and constraints of the tool's keyword arguments.

    Returns:
        A wrapper that validates ``**kwargs`` and either calls the
        original tool or returns an error dict.

    Behaviour on validation failure:
        Returns ``{"success": False, "error": ..., "validation_errors": [...]}``
        This is a valid ToolMessage payload — LangGraph passes it to the
        LLM which can interpret the errors and retry with corrected args.
    """
    def decorator(func):
        func_name = getattr(func, "name", func.__name__)

        @functools.wraps(func)
        async def wrapper(**kwargs):
            try:
                validated = schema(**kwargs)
            except ValidationError as exc:
                errors = []
                for err in exc.errors():
                    errors.append({
                        "field": " → ".join(str(x) for x in err["loc"]),
                        "value": str(err.get("input"))[:80],
                        "msg": err["msg"],
                    })
                _log.warning(
                    "Tool validation failed tool=%s errors=%d",
                    func_name, len(errors),
                )
                return {
                    "success": False,
                    "error": (
                        f"Los argumentos de '{func_name}' no son válidos. "
                        f"Corrige los errores y vuelve a intentar."
                    ),
                    "validation_errors": errors,
                    "hint": (
                        "Usa los IDs numéricos de los catálogos (números > 0), "
                        "no nombres. Los strings deben tener al menos 3 caracteres."
                    ),
                }

            # Validation passed — call the original tool with validated data
            return await func(**validated.model_dump())

        # Preserve tool metadata for LangChain
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        if hasattr(func, "name"):
            wrapper.name = func.name
        if hasattr(func, "description"):
            wrapper.description = func.description
        if hasattr(func, "args_schema"):
            # Replace LangChain's auto-generated args_schema with ours
            wrapper.args_schema = schema

        return wrapper
    return decorator
