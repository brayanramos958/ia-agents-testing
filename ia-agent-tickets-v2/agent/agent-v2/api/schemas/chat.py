"""
Request and response schemas for the /agent/chat endpoint.

user_rol field name is intentional (matches v1 API contract so the
existing frontend requires zero changes).
"""

from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    user_id: int
    user_rol: str          # "creador" | "resueltor" | "supervisor"
    message: str
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
