"""
Development server entry point.

Sets asyncio.WindowsSelectorEventLoopPolicy BEFORE uvicorn touches the event
loop — required for psycopg async mode on Windows.  In Docker (Linux) the
default SelectorEventLoop is already used so the guard is a no-op.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402 — must come after the policy is set

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
