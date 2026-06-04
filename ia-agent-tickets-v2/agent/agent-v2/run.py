"""
Entry point for Windows.

psycopg3 AsyncConnectionPool is incompatible with ProactorEventLoop (Windows default).
Solution: create a SelectorEventLoop explicitly and run uvicorn inside it,
bypassing asyncio.run() which would normally pick up the system default.

Usage:
    uv run python run.py
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from uvicorn import Config, Server
from config.settings import settings

config = Config("main:app", host="0.0.0.0", port=settings.port, log_level="info")
server = Server(config)

if sys.platform == "win32":
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.serve())
else:
    asyncio.run(server.serve())
