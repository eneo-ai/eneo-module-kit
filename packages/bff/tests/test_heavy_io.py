"""Mixed admission over the kit's real TCP connection pool, including token renewal."""

import asyncio
import time
import unittest

import httpx2
from fastapi import APIRouter, Depends, Request

from eneo_module_bff import create_app, forward_upload, heavy_io_slot, require_same_origin, require_session, rule, stream_signed
from eneo_module_bff.auth import SESSION_COOKIE
from eneo_module_bff.settings import Settings
from .real_server import start
from .test_auth import token_payload
from .test_transport import make_settings, module_session


class MixedPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_uploads_files_and_module_operations_leave_room_for_a_real_token_refresh(self) -> None:
        # The largest accepted ceiling: 95 real connections held, plus a module
        # operation. Auth must use the connections the ceiling leaves available.
        code = '''
import asyncio, time, uvicorn
from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse
app = FastAPI()
release = asyncio.Event()
counts = {"uploads": 0, "files": 0, "refreshes": 0}
TOKEN = TOKEN_JSON
@app.get("/state")
async def state(): return counts
@app.post("/release")
async def finish(): release.set(); return {}
@app.post("/api/v1/flows/{flow}/files/")
async def upload(request: Request):
    await request.body()
    counts["uploads"] += 1
    await release.wait()
    return {"ok": True}
@app.post("/api/v1/mint/")
async def mint(): return {"url": "http://127.0.0.1:PORT/file", "expires_at": time.time()+900}
@app.get("/file")
async def file():
    async def body():
        counts["files"] += 1
        yield b"x"
        await release.wait()
        yield b"y"
    return StreamingResponse(body(), media_type="audio/wav")
@app.post("/api/v1/module-auth/speech-to-text/token/refresh/")
async def refresh(): counts["refreshes"] += 1; return TOKEN
@app.get("/api/v1/things/")
async def things(request: Request): return {"authorization": request.headers.get("authorization")}
uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False)
'''.replace("TOKEN_JSON", repr(token_payload("renewed-token")))
        _, port = await asyncio.to_thread(start, self, code)
        base = f"http://127.0.0.1:{port}"
        settings = Settings(**(make_settings().model_dump() | {
            "eneo_backend_url": base, "max_concurrent_heavy_io": 96, "max_concurrent_uploads": 32,
        }))
        router = APIRouter()

        @router.post("/upload", dependencies=[Depends(require_session), Depends(require_same_origin)])
        async def upload(request: Request):
            return await forward_upload(request, "flows/flow-1/files/")

        @router.get("/audio", dependencies=[Depends(require_session)])
        async def audio(request: Request):
            return await stream_signed(request, mint_path="mint/", unavailable="unavailable")

        app = create_app(settings, routers=[router], proxy_rules=[rule("GET", r"things/$")])
        self.addAsyncCleanup(app.state.http.aclose)
        session = module_session().model_copy(update={"expires_at": int(time.time()) + 600, "refresh_at": int(time.time()) + 300})
        session_id = app.state.module_auth.sessions.create(session)
        browser = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=settings.module_public_url,
                                    cookies={SESSION_COOKIE: session_id})
        control = httpx2.AsyncClient(base_url=base, timeout=10)
        self.addAsyncCleanup(browser.aclose)
        self.addAsyncCleanup(control.aclose)
        request = Request({"type": "http", "app": app, "headers": []})
        tasks = []
        with heavy_io_slot(request) as admitted:
            self.assertTrue(admitted)
            tasks = [asyncio.create_task(browser.post("/upload", files={"upload_file": ("a.bin", b"small file")},
                                                      headers={"Origin": settings.module_public_url})) for _ in range(32)]
            tasks += [asyncio.create_task(browser.get("/audio")) for _ in range(63)]
            try:
                async with asyncio.timeout(15):
                    while True:
                        counts = (await control.get("/state")).json()
                        if counts["uploads"] == 32 and counts["files"] == 63:
                            break
                        await asyncio.sleep(0.02)
                self.assertEqual(app.state.heavy_io_slots.borrowed_tokens, 96)
                self.assertEqual((await browser.get("/audio")).status_code, 503)
                self.assertEqual((await browser.post("/upload", files={"upload_file": ("extra.bin", b"extra")},
                                                     headers={"Origin": settings.module_public_url})).status_code, 503)
                # The token remains valid but is now due for renewal.
                session.refresh_at = int(time.time()) - 1
                async with asyncio.timeout(3):
                    renewed = await browser.get("/api/eneo/things/")
                    status = await browser.get("/api/auth/status")
                self.assertEqual(renewed.status_code, 200)
                self.assertEqual(renewed.json(), {"authorization": "Bearer renewed-token"})
                self.assertTrue(status.json()["authenticated"])
                self.assertEqual((await control.get("/state")).json()["refreshes"], 1)
            finally:
                await control.post("/release")
                results = await asyncio.gather(*tasks, return_exceptions=True)
            self.assertTrue(all(isinstance(result, httpx2.Response) and result.status_code == 200 for result in results),
                            [str(result) for result in results if not isinstance(result, httpx2.Response) or result.status_code != 200])
        self.assertEqual(app.state.heavy_io_slots.borrowed_tokens, 0)


if __name__ == "__main__":
    unittest.main()
