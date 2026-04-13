"""
Request and response schemas for the /agent/invoke endpoint (A2A).

Designed for machine-to-machine calls from an orchestrating agent.
Input is structured (intent + parameters), output is structured JSON.
No conversational state — each call is stateless.
"""

from pydantic import BaseModel
from typing import Literal


class InvokeRequest(BaseModel):
    intent: str       # See INTENT_MAP in api/routes/invoke.py for valid values
    parameters: dict  # Intent-specific parameters
    user_id: int
    user_rol: str     # "creador" | "resueltor" | "supervisor"
    context: str = "" # Optional extra context from the orchestrating agent


class InvokeResponse(BaseModel):
    status: Literal["success", "error", "needs_more_info"]
    result: dict
    message: str      # Natural language explanation for the caller agent
