"""A real uvicorn, started by serve(), told to stop while files are still streaming."""

import http.client
import signal
import time
import unittest

from . import real_server

APP = """
import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from eneo_module_bff import serve

app = FastAPI()


async def never_ending():
    while True:
        yield b"x" * 1024
        await asyncio.sleep(0.05)


@app.get("/slow")
async def slow():
    return StreamingResponse(never_ending())


serve(app, host="127.0.0.1", port=PORT, timeout_graceful_shutdown=1)
"""


class ShutdownTests(unittest.TestCase):
    def test_sigterm_with_open_streams_stops_the_process_within_the_graceful_time(self) -> None:
        process, port = real_server.start(self, APP)
        streams = []
        for _ in range(5):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("GET", "/slow")
            response = connection.getresponse()
            response.read(1024)  # the stream is open, and will not end by itself
            streams.append(connection)
        started = time.monotonic()

        process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)

        self.assertLess(time.monotonic() - started, 5, "it waited for streams that never end")
        # uvicorn re-raises the signal once it has shut down, so the status is 0 or "killed by SIGTERM".
        self.assertIn(process.returncode, (0, -signal.SIGTERM))
        for connection in streams:
            connection.close()


if __name__ == "__main__":
    unittest.main()
