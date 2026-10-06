"""A real uvicorn in a subprocess, for the tests that need a real HTTP parser or a real signal.

The process is started by a test and stopped by that test, by its own handle: nothing is looked up by name.
"""

import http.client
import socket
import subprocess
import sys
import time
import unittest
from contextlib import closing


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def start(test: unittest.TestCase, code: str) -> tuple[subprocess.Popen, int]:
    """Run ``code`` (it must serve on the port written as PORT) and return it once it answers."""
    port = free_port()
    process = subprocess.Popen([sys.executable, "-c", code.replace("PORT", str(port))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    test.addCleanup(stop, process)
    for _ in range(300):  # 30 s: a loaded machine takes several seconds to import the app
        try:
            with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=1)) as connection:
                connection.request("GET", "/nope")
                connection.getresponse().read()
            return process, port
        except OSError:
            time.sleep(0.1)
    test.fail("the server did not start")
