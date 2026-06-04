from contextvars import ContextVar

# Holds the authenticated user_id for the duration of one agent invocation.
# Set in get_response() and stream_response() before ainvoke/astream_events.
# Tools read this value instead of trusting the user_id the LLM generates,
# preventing a malicious prompt from impersonating another user.
current_user_id: ContextVar[int] = ContextVar("current_user_id", default=0)

# Holds the current thread_id for structured logging.
# Set at the start of each request handler (chat.py, stream.py).
# Injected automatically into every log line via ContextFilter (core/logging.py).
# Default "?" means "no active request" (e.g. startup, background tasks).
current_thread_id: ContextVar[str] = ContextVar("current_thread_id", default="?")
