import uvicorn
from fastapi import FastAPI

WS_MAX_MESSAGE_BYTES = 128 * 1024
WS_MAX_QUEUE = 16


def serve(app: FastAPI | str, *, host: str = "0.0.0.0", port: int = 3001, **overrides: object) -> None:
    """Run the module: one worker (the session store is process-local), no access log (the callback URL
    carries a ticket), and bounded WebSocket buffers."""
    options: dict[str, object] = {
        "host": host,
        "port": port,
        "workers": 1,
        "access_log": False,
        "ws_max_size": WS_MAX_MESSAGE_BYTES,
        "ws_max_queue": WS_MAX_QUEUE,
    }
    if "workers" in overrides or "access_log" in overrides:
        raise ValueError("workers and access_log are fixed: one replica, and no ticket in the logs")
    uvicorn.run(app, **{**options, **overrides})
