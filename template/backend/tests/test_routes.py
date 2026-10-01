import unittest

from fastapi import APIRouter, Depends

from eneo_module_bff import require_session

from routes import router
from tests.guards import unguarded_routes


class EveryRouteIsGuardedTests(unittest.TestCase):
    """The test a module author who forgets a guard fails: add a route to ``router`` without ``require_session``
    (and, for a write, ``require_same_origin``) and this reports it."""

    def test_every_route_of_the_module_needs_a_session_and_a_write_needs_the_same_origin(self) -> None:
        self.assertEqual(unguarded_routes(router), [])

    def test_the_walker_does_report_a_route_without_its_guards(self) -> None:
        careless = APIRouter()

        @careless.get("/api/open")
        async def open_route() -> None: ...

        @careless.post("/api/write", dependencies=[Depends(require_session)])
        async def write_route() -> None: ...

        self.assertEqual(
            unguarded_routes(careless),
            ["GET /api/open: no require_session", "POST /api/write: no require_same_origin"],
        )


if __name__ == "__main__":
    unittest.main()
