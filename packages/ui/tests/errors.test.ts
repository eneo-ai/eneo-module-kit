import assert from "node:assert/strict";
import test from "node:test";

/** An error that carries the status the backend answered, as a module's own request helper throws (the template's ApiError). */
class ApiError extends Error {
  constructor(readonly status: number) {
    super(`The backend answered ${status}`);
  }
}

// Words of English messages that must never reach the page.
const ENGLISH = /\b(the|failed|error|request|network|backend|answered|timeout)\b/i;

test("a request the login's end refused says to try again, not to log in: it is read after the new login", async () => {
  const { errorAdvice, SessionExpiredError } = await import("../src/session/index.js");
  assert.deepEqual(errorAdvice(new SessionExpiredError()), { message: "Inloggningen hade gått ut och det här skickades inte. Försök igen.", retry: true });
});

test("a request no answer began for says so in its own words, and trying again can help", async () => {
  const { errorAdvice, RequestTimeoutError } = await import("../src/session/index.js");
  assert.deepEqual(errorAdvice(new RequestTimeoutError()), { message: "Det tog för lång tid att få svar. Försök igen.", retry: true });
});

test("a connection that dropped, in each engine's words, is one to try again", async () => {
  const { errorAdvice } = await import("../src/session/index.js");
  // Chromium's, Firefox's and Safari's TypeError for a fetch that got no answer.
  for (const message of ["Failed to fetch", "NetworkError when attempting to fetch resource.", "Load failed"]) {
    assert.deepEqual(errorAdvice(new TypeError(message)), { message: "Anslutningen avbröts. Kontrollera nätverket och försök igen.", retry: true }, message);
  }
});

test("an answer's status decides the sentence, and Försök igen is offered only where trying again can help", async () => {
  const { errorAdvice } = await import("../src/session/index.js");
  const expected: [number, string, boolean][] = [
    [401, "Tjänsten har inte behörighet till det här. Kontakta den som ansvarar för Eneo i din verksamhet.", false],
    [403, "Du har inte behörighet till det här. Kontakta den som ansvarar för Eneo i din verksamhet om du behöver det.", false],
    [404, "Det du letade efter finns inte längre.", false],
    [408, "Svaret dröjde för länge. Försök igen om en stund.", true],
    [413, "Det som skickades är större än tjänsten tar emot.", false],
    [415, "Filtypen stöds inte.", false],
    [429, "Det är många förfrågningar just nu. Försök igen om en stund.", true],
    [500, "Tjänsten svarade med ett fel. Försök igen om en stund.", true],
    [502, "Servern kunde inte nås just nu. Försök igen om en stund.", true],
    [503, "Servern kunde inte nås just nu. Försök igen om en stund.", true],
    [504, "Servern svarade inte i tid. Försök igen om en stund.", true],
    [422, "Det gick inte att genomföra. Kontakta den som ansvarar för tjänsten om det fortsätter.", false],
  ];
  for (const [status, message, retry] of expected) assert.deepEqual(errorAdvice(new ApiError(status)), { message, retry }, String(status));
  // An answer itself carries its status too.
  assert.deepEqual(errorAdvice(new Response(null, { status: 503 })), { message: "Servern kunde inte nås just nu. Försök igen om en stund.", retry: true });
});

test("what nothing tells is not a dead end, and no English reaches the page", async () => {
  const { errorAdvice } = await import("../src/session/index.js");
  for (const raised of [new Error("Something broke in the backend"), new DOMException("The quota has been exceeded.", "QuotaExceededError"), new TypeError("x is undefined"), "not an error", null]) {
    const advice = errorAdvice(raised);
    assert.deepEqual(advice, { message: "Ett okänt fel uppstod. Försök igen. Kontakta den som ansvarar för tjänsten om det fortsätter.", retry: true }, String(raised));
    assert.doesNotMatch(advice.message, ENGLISH);
  }
});
