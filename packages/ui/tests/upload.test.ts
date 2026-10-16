// `uploadWithProgress` over a stand-in XMLHttpRequest: the same session rules and typed errors as `fetchWithSession`.
import assert from "node:assert/strict";
import test from "node:test";
import { createOnlineStatus } from "../src/online-status.js";
import { errorAdvice } from "../src/session/errors.js";
import { REQUEST_TIMEOUT_MS, RequestTimeoutError, SessionExpiredError } from "../src/session/request.js";
import { createSessionState } from "../src/session/state.js";
import { createUploadWithProgress, type UploadProgress } from "../src/session/upload.js";

const anna = { id: "user-1", email: "anna@example.se", username: "Anna Berg" };
const settle = () => new Promise((resolve) => setImmediate(resolve));
const is401 = (error: unknown) => error instanceof SessionExpiredError && error.status === 401;

/** The browser's XMLHttpRequest, as far as an upload uses it; the test answers it. */
class FakeXhr {
  static made: FakeXhr[] = [];
  method = "";
  url = "";
  sentBody: unknown = undefined;
  withCredentials = false;
  responseType = "";
  readyState = 0;
  status = 0;
  statusText = "";
  response: unknown = null;
  aborted = false;
  readonly headers = new Headers();
  answerHeaders = new Headers();
  upload: { onprogress: ((event: { loaded: number; total: number; lengthComputable: boolean }) => void) | null; onload: (() => void) | null } = {
    onprogress: null,
    onload: null,
  };
  onreadystatechange: (() => void) | null = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXhr.made.push(this);
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
    this.readyState = 1;
  }
  setRequestHeader(name: string, value: string) {
    this.headers.set(name, value);
  }
  send(body: unknown) {
    this.sentBody = body;
  }
  abort() {
    this.aborted = true;
    this.readyState = 4;
    this.onreadystatechange?.();
    this.onabort?.();
    this.readyState = 0;
  }
  getResponseHeader(name: string) {
    return this.answerHeaders.get(name);
  }
  getAllResponseHeaders() {
    return [...this.answerHeaders].map(([name, value]) => `${name}: ${value}\r\n`).join("");
  }

  // What the network does.
  progress(loaded: number, total: number | null) {
    this.upload.onprogress?.({ loaded, total: total ?? 0, lengthComputable: total !== null });
  }
  uploaded() {
    this.upload.onload?.();
  }
  begin(status: number, headers: Record<string, string> = {}) {
    this.status = status;
    this.answerHeaders = new Headers(headers);
    this.readyState = 2;
    this.onreadystatechange?.();
  }
  answer(status: number, body = "", headers: Record<string, string> = {}) {
    if (this.readyState < 2) this.begin(status, headers);
    this.response = new Blob([body]);
    this.readyState = 4;
    this.onreadystatechange?.();
    this.onload?.();
  }
  fail() {
    this.readyState = 4;
    this.onreadystatechange?.();
    this.onerror?.();
  }
}

/** A signed-in page (the gate has begun it) whose uploads go to the stand-in. */
function signedInPage(t: import("node:test").TestContext) {
  const state = createSessionState();
  const online = createOnlineStatus();
  FakeXhr.made = [];
  const globals = globalThis as { XMLHttpRequest?: unknown };
  const before = globals.XMLHttpRequest;
  globals.XMLHttpRequest = FakeXhr;
  const end = state.begin(anna);
  t.after(() => {
    end();
    globals.XMLHttpRequest = before;
  });
  return { state, online, upload: createUploadWithProgress(state, online), sent: () => FakeXhr.made };
}

test("an upload says how far it has come, names the page's user, and gives the answer as fetch would", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { upload, sent } = signedInPage(t);
  const progress: UploadProgress[] = [];
  const file = new FormData();
  file.append("upload_file", new Blob(["hello"]), "hej.txt");
  const uploading = upload("/api/files/", file, { headers: { "Idempotency-Key": "file:f1" }, onProgress: (p) => progress.push(p) });
  const [xhr] = sent();
  assert.equal(xhr.method, "POST");
  assert.equal(xhr.url, "/api/files/");
  assert.equal(xhr.sentBody, file, "the body goes as it was");
  assert.equal(xhr.withCredentials, true);
  assert.equal(xhr.headers.get("X-Expected-User"), "user-1", "a write names the page's user");
  assert.equal(xhr.headers.get("Idempotency-Key"), "file:f1", "the page's own headers go as they were");
  assert.equal(xhr.headers.get("X-Upload-Timeout-Seconds"), "90", "the backend waits for Eneo no longer than the page waits");

  xhr.progress(50, 100);
  xhr.progress(50, 100);
  xhr.progress(100, 100);
  xhr.uploaded();
  xhr.answer(201, JSON.stringify({ id: "f1" }), { "content-type": "application/json" });
  const answer = await uploading;
  assert.deepEqual(progress, [
    { loaded: 50, total: 100 },
    { loaded: 100, total: 100 },
  ]);
  assert.equal(answer.status, 201);
  assert.equal(answer.headers.get("content-type"), "application/json");
  assert.deepEqual(await answer.json(), { id: "f1" }, "parsing it is the module's");
  t.mock.timers.tick(10 * REQUEST_TIMEOUT_MS);
  assert.equal(xhr.aborted, false, "an answered upload leaves no timer behind");
});

test("signed out, an upload fails at once and nothing leaves the page: the person sends it again once signed in", async (t) => {
  const { state, upload, sent } = signedInPage(t);
  state.ended();
  await assert.rejects(upload("/api/files/", new Blob(["x"])), is401);
  assert.equal(sent().length, 0);
});

test("the backend's mark that the login ended ends it, and the upload fails as fetchWithSession's would", async (t) => {
  const { state, upload, sent } = signedInPage(t);
  const uploading = upload("/api/files/", new Blob(["x"]));
  sent()[0].answer(401, "{}", { "X-Auth-Required": "session" });
  await assert.rejects(uploading, is401);
  assert.equal(state.signedOut, true, "the sign-in dialog opens over the page");
});

test("Eneo's own 401 is an answer to show", async (t) => {
  const { state, upload, sent } = signedInPage(t);
  const uploading = upload("/api/files/", new Blob(["x"]));
  sent()[0].answer(401, "{}");
  assert.equal((await uploading).status, 401, "returned as it came");
  assert.equal(state.signedOut, false);
});

test("someone else's session under the page (409 user_changed) covers it as an end", async (t) => {
  const { state, upload, sent } = signedInPage(t);
  const uploading = upload("/api/files/", new Blob(["x"]));
  sent()[0].answer(409, JSON.stringify({ detail: "user_changed" }), { "content-type": "application/json" });
  await assert.rejects(uploading, is401);
  assert.equal(state.signedOut, true);
});

test("nothing moving for 90 s is a timeout, which says nothing of the connection; each byte that goes up starts the wait again", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { online, upload, sent } = signedInPage(t);
  const uploading = upload("/api/files/", new Blob(["x"]));
  const failed = assert.rejects(uploading, (error: unknown) => error instanceof RequestTimeoutError && error.status === 408);
  const [xhr] = sent();
  t.mock.timers.tick(REQUEST_TIMEOUT_MS - 1);
  xhr.progress(10, 100);
  t.mock.timers.tick(REQUEST_TIMEOUT_MS - 1);
  await settle();
  assert.equal(xhr.aborted, false, "still moving");
  t.mock.timers.tick(1);
  await failed;
  assert.equal(xhr.aborted, true, "the stalled upload is ended");
  assert.equal(online.connection, "online");
});

test("once every byte is up, the answer may take as long as the page gives it, and the backend is told", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { upload, sent } = signedInPage(t);
  const uploading = upload("/api/files/", new Blob(["x"]), { answerTimeoutMs: 600_000 });
  const failed = assert.rejects(uploading, (error: unknown) => error instanceof RequestTimeoutError);
  const [xhr] = sent();
  assert.equal(xhr.headers.get("X-Upload-Timeout-Seconds"), "600");
  xhr.uploaded();
  t.mock.timers.tick(REQUEST_TIMEOUT_MS);
  await settle();
  assert.equal(xhr.aborted, false, "Eneo may still be working on it");
  t.mock.timers.tick(600_000 - REQUEST_TIMEOUT_MS);
  await failed;
});

test("an answer that has begun is read untimed, as fetch reads it, also when bytes go up after it", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { upload, sent } = signedInPage(t);
  const uploading = upload("/api/files/", new Blob(["x"]));
  const [xhr] = sent();
  xhr.begin(413);
  t.mock.timers.tick(10 * REQUEST_TIMEOUT_MS);
  xhr.progress(10, 100);
  xhr.uploaded();
  t.mock.timers.tick(10 * REQUEST_TIMEOUT_MS);
  assert.equal(xhr.aborted, false);
  xhr.answer(413, "{}");
  assert.equal((await uploading).status, 413);
});

test("an upload that does not reach the module fails as fetch does, and the page hears that the module does not answer", async (t) => {
  const { online, upload, sent } = signedInPage(t);
  const uploading = upload("/api/files/", new Blob(["x"]));
  sent()[0].fail();
  const error = await uploading.then(
    () => null,
    (failure: unknown) => failure,
  );
  assert.equal(error instanceof TypeError, true);
  assert.equal(errorAdvice(error).message, "Anslutningen avbröts. Kontrollera nätverket och försök igen.");
  assert.equal(online.connection, "unreachable");

  const again = upload("/api/files/", new Blob(["x"]));
  sent()[1].answer(201);
  await again;
  assert.equal(online.connection, "online", "an answer says the module is there again");
});

test("the page's own abort ends the upload as an abort, also before it has left", async (t) => {
  const { upload, sent } = signedInPage(t);
  const own = new AbortController();
  const uploading = upload("/api/files/", new Blob(["x"]), { signal: own.signal });
  own.abort();
  await assert.rejects(uploading, (error: unknown) => (error as Error).name === "AbortError" && !(error instanceof RequestTimeoutError));
  assert.equal(sent()[0].aborted, true);

  await assert.rejects(upload("/api/files/", new Blob(["x"]), { signal: own.signal }), (error: unknown) => (error as Error).name === "AbortError");
  assert.equal(sent().length, 1, "an aborted signal sends nothing");
});
