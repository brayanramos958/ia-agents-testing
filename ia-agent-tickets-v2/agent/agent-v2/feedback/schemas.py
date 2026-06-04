"""
Data models for AI assistant feedback.

IMPORTANT: This is NOT ticket CSAT (customer satisfaction).
This measures how helpful the AI agent was during the interaction.

- Ticket CSAT → managed natively by the enterprise system (satisfaction_rating field)
- AI feedback → stored here in feedback.db
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class AgentFeedbackRecord(BaseModel):
    id: Optional[int] = None
    # ticket_id is None when feedback is for a solution suggestion
    # (no ticket was created)
    ticket_id: Optional[int] = None
    ticket_name: Optional[str] = None  # e.g. "TCK-0001"
    user_id: int
    rating: int = Field(ge=1, le=5, description="1 = very unhelpful, 5 = very helpful")
    comment: str = ""
    # ticket_created: agent helped create a ticket
    # solution_suggested: agent suggested an existing solution (no ticket created)
    feedback_type: Literal["ticket_created", "solution_suggested"]
    created_at: Optional[datetime] = None
