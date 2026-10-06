import unittest
from unittest.mock import patch

from fastapi import FastAPI

import eneo_module_bff

PUBLIC_NAMES = {
    "__version__",
    "create_app",
    "serve",
    "Settings",
    "Organization",
    "load_settings",
    "ModuleSession",
    "ModuleUser",
    "ProxyRule",
    "rule",
    "RESOURCE_ID",
    "require_session",
    "require_same_origin",
    "upstream_auth_headers",
    "heavy_io_slot",
    "forward_upload",
    "stream_signed",
}


class ServeTests(unittest.TestCase):
    def test_serve_runs_one_worker_without_an_access_log_and_with_bounded_websockets(self) -> None:
        with patch("uvicorn.run") as run:
            eneo_module_bff.serve("main:app")

        run.assert_called_once_with(
            "main:app",
            host="0.0.0.0",
            port=3001,
            workers=1,
            access_log=False,
            ws_max_size=128 * 1024,
            ws_max_queue=16,
            timeout_graceful_shutdown=8,
        )

    def test_serve_takes_an_app_and_lets_host_port_and_other_options_be_chosen(self) -> None:
        app = FastAPI()

        with patch("uvicorn.run") as run:
            eneo_module_bff.serve(app, host="127.0.0.1", port=8080, log_level="warning")

        run.assert_called_once_with(
            app,
            host="127.0.0.1",
            port=8080,
            workers=1,
            access_log=False,
            ws_max_size=128 * 1024,
            ws_max_queue=16,
            timeout_graceful_shutdown=8,
            log_level="warning",
        )

    def test_serve_gives_open_connections_less_time_than_dockers_ten_seconds_to_close(self) -> None:
        # Without it uvicorn waits for every open stream, and docker kills the container after ten seconds.
        with patch("uvicorn.run") as run:
            eneo_module_bff.serve("main:app")

        self.assertLess(run.call_args.kwargs["timeout_graceful_shutdown"], 10)

    def test_the_graceful_shutdown_time_can_be_chosen(self) -> None:
        with patch("uvicorn.run") as run:
            eneo_module_bff.serve("main:app", timeout_graceful_shutdown=3)

        self.assertEqual(run.call_args.kwargs["timeout_graceful_shutdown"], 3)

    def test_workers_and_access_log_are_fixed(self) -> None:
        for overrides in ({"workers": 2}, {"access_log": True}, {"workers": 1}, {"access_log": False}):
            with self.subTest(overrides=overrides), patch("uvicorn.run") as run:
                with self.assertRaises(ValueError):
                    eneo_module_bff.serve("main:app", **overrides)
                run.assert_not_called()

    def test_the_package_exposes_exactly_its_public_names(self) -> None:
        self.assertEqual(set(eneo_module_bff.__all__), PUBLIC_NAMES)
        self.assertEqual(len(eneo_module_bff.__all__), len(PUBLIC_NAMES), "no name twice")
        for name in PUBLIC_NAMES:
            self.assertTrue(hasattr(eneo_module_bff, name), name)


if __name__ == "__main__":
    unittest.main()
