"""A real uvicorn, started by serve(), told to stop while files are still streaming."""

import http.client
import signal
import socket
import subprocess
import sys
import time
import unittest

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


serve(app, host="127.0.0.1", port={port}, timeout_graceful_shutdown={grace})
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ShutdownTests(unittest.TestCase):
    def serve(self, grace: int) -> tuple[subprocess.Popen, int]:
        port = free_port()
        process = subprocess.Popen(
            [sys.executable, "-c", APP.format(port=port, grace=grace)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self.addCleanup(self.stop, process)
        for _ in range(100):
            try:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                connection.request("GET", "/nope")
                connection.getresponse().read()
                return process, port
            except OSError:
                time.sleep(0.1)
        self.fail("the server did not start")

    @staticmethod
    def stop(process: subprocess.Popen) -> None:
        # Only the process this test started, by its own handle.
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)

    def test_sigterm_with_open_streams_stops_the_process_within_the_graceful_time(self) -> None:
        process, port = self.serve(grace=1)
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
