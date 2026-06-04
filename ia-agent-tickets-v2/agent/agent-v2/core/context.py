from contextvars import ContextVar

# Holds the authenticated user_id for the duration of one agent invocation.
# Set in get_response() and stream_response() before ainvoke/astream_events.
# Tools read this value instead of trusting the user_id the LLM generates,
# preventing a malicious prompt from impersonating another user.
current_user_id: ContextVar[int] = ContextVar("current_user_id", default=0)
