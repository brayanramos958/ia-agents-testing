from contextvars import ContextVar

# Holds the authenticated user_id for the duration of one agent invocation.
# Set in get_response() and stream_response() before ainvoke/astream_events.
# Tools read this value instead of trusting the user_id the LLM generates,
# preventing a malicious prompt from impersonating another user.
current_user_id: ContextVar[int] = ContextVar("current_user_id", default=0)

# Request tracking for structured logging.
# Set by RequestContextMiddleware at the start of every HTTP request.
current_thread_id: ContextVar[str] = ContextVar("current_thread_id", default="")
current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")

# JWT-authenticated user role. Set by JWTAuthMiddleware after token verification.
# Used by routes to validate body.user_rol matches the token's claim.
current_user_role: ContextVar[str] = ContextVar("current_user_role", default="")
