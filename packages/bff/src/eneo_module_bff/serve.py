import uvicorn
from fastapi import FastAPI

WS_MAX_MESSAGE_BYTES = 128 * 1024
WS_MAX_QUEUE = 16
# Docker kills a container ten seconds after SIGTERM. Without this uvicorn waits for every open connection, and a
# file that is still streaming never ends by itself.
GRACEFUL_SHUTDOWN_SECONDS = 8


def serve(app: FastAPI | str, *, host: str = "0.0.0.0", port: int = 3001, **overrides: object) -> None:
    """Run the module: one worker (the session store is process-local), no access log (the callback URL
    carries a ticket), bounded WebSocket buffers, and a stop that does not wait for open streams past 8 s."""
    options: dict[str, object] = {
        "host": host,
        "port": port,
        "workers": 1,
        "access_log": False,
        "ws_max_size": WS_MAX_MESSAGE_BYTES,
        "ws_max_queue": WS_MAX_QUEUE,
        "timeout_graceful_shutdown": GRACEFUL_SHUTDOWN_SECONDS,
    }
    if "workers" in overrides or "access_log" in overrides:
        raise ValueError("workers and access_log are fixed: one replica, and no ticket in the logs")
    uvicorn.run(app, **{**options, **overrides})
