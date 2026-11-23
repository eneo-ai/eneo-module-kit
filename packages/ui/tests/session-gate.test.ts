// The session client's screens in jsdom. What jsdom cannot show (a modal dialog's top layer, the backdrop, the
// accessibility tree) is proved in a browser; here: what is rendered when, what is called, and what stays reachable.
import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { createElement, useState } from "react";
import { button, cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(cleanup);

const anna = { id: "user-1", email: "anna@example.se", username: "Anna Berg" };
const erik = { id: "user-2", email: "erik@example.se", username: "Erik Lund" };
const signedIn = (user = anna, endsIn = 8 * 3600) => ({ authenticated: true, user, session_ends_in: endsIn });
const signedOutStatus = { authenticated: false, user: null };
const settle = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms));
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** The page's backend: `/api/auth/status` answers what `answer()` says, and every call is counted. */
function backend(t: import("node:test").TestContext, answer: () => Response | Promise<Response>) {
  const calls: string[] = [];
  const browserFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request) => {
    calls.push(String(url));
    return answer();
  }) as typeof fetch;
  t.after(() => {
    globalThis.fetch = browserFetch;
  });
  return calls;
}

async function gate(props: Record<string, unknown> = {}, children: unknown = "Sidan") {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { RequireSession } = await import("../src/session/RequireSession.js");
  const { createSessionState } = await import("../src/session/state.js");
  const state = createSessionState();
  const view = await mount(
    createElement(ModuleProviders, {
      children: createElement(RequireSession, { productName: "Testmodul", state, children, ...props } as never),
    }),
  );
  return { state, ...view };
}

// Booleans only in assertions on nodes: a failed comparison of DOM nodes makes node print them, which takes minutes under jsdom.
const dialog = () => document.body.querySelector<HTMLDialogElement>('[role="alertdialog"]');

test("the page is shown only after onIdentity has been awaited, called once with the user", async (t) => {
  backend(t, () => json(signedIn()));
  let release: () => void = () => {};
  const seen: string[] = [];
  const { act, container } = await gate({
    onIdentity: (user: { id: string }) => {
      seen.push(user.id);
      return new Promise<void>((resolve) => (release = resolve));
    },
  });
  await act(async () => settle());
  assert.deepEqual(seen, ["user-1"]);
  assert.doesNotMatch(container.textContent ?? "", /Sidan/, "not before it has answered");
  await act(async () => {
    release();
    await settle();
  });
  assert.match(container.textContent ?? "", /Sidan/);
  assert.deepEqual(seen, ["user-1"]);
});

test("a login that cannot be read says so and offers to try again; one that is not signed in shows the sign-in screen", async (t) => {
  backend(t, () => Promise.reject(new TypeError("offline")));
  const failed = await gate();
  await failed.act(async () => settle());
  assert.match(failed.container.textContent ?? "", /Kunde inte kontakta modulen/);
  assert.ok(button(failed.container, "Försök igen"));
  await failed.unmount();

  backend(t, () => json(signedOutStatus));
  const out = await gate({ signInTitle: "Gör möten till text" });
  await out.act(async () => settle());
  const login = out.container.querySelector<HTMLAnchorElement>('a[href^="/api/auth/login"]');
  assert.equal(login?.textContent?.trim(), "Logga in med Eneo", "a link: it takes the person to another page");
  assert.equal(login?.getAttribute("href"), `/api/auth/login?next=${encodeURIComponent(window.location.pathname)}`.replace("?next=%2F", ""), "back to the page the person was on");
  assert.match(out.container.textContent ?? "", /Gör möten till text/);
  assert.doesNotMatch(out.container.textContent ?? "", /Sidan/);
});

test("a failed login (?auth_error) is said once and taken off the address", async (t) => {
  backend(t, () => json(signedOutStatus));
  window.history.replaceState(null, "", "/?auth_error=exchange_failed&x=1");
  t.after(() => window.history.replaceState(null, "", "/"));
  const { act, container } = await gate();
  await act(async () => settle());
  assert.match(container.textContent ?? "", /Inloggningen kunde inte slutföras/);
  assert.equal(window.location.search, "?x=1");
});

test("an app with a route of its own for signing in is sent there, and shows no sign-in screen", async (t) => {
  backend(t, () => json(signedOutStatus));
  const went: string[] = [];
  const { act, container } = await gate({ navigate: (path: string) => went.push(path), signInPath: "/logga-in" });
  await act(async () => settle());
  assert.deepEqual(went, ["/logga-in"]);
  assert.ok(!/Logga in med Eneo/.test(container.textContent ?? ""), "no sign-in screen");
});

test("five minutes before the end the warning opens once and renews in a window of its own, bound to this user", async (t) => {
  backend(t, () => json(signedIn(anna, 200)));
  const opened: string[] = [];
  t.mock.method(window, "open", (url: string) => {
    opened.push(url);
    return {} as Window;
  });
  const { act } = await gate();
  await act(async () => settle(50));
  assert.ok(dialog()?.hasAttribute("open"), "open: less than five minutes are left");
  assert.match(dialog()?.textContent ?? "", /Du loggas snart ut/);
  assert.match(dialog()?.textContent ?? "", /Inloggningen upphör kl\. \d\d:\d\d/);
  assert.equal(dialog()?.tagName, "DIALOG", "a native dialog");
  assert.ok(button(dialog()!, "Stäng"), "it can be closed before the end");
  await act(async () => button(dialog()!, "Fortsätt arbeta")!.click());
  assert.deepEqual(opened, ["/api/auth/login?renew=1&next=%2Finloggad"]);
});

test("a login window that cannot be opened is said", async (t) => {
  backend(t, () => json(signedIn(anna, 200)));
  t.mock.method(window, "open", () => null);
  const { act } = await gate({ signedInAgainPath: "/klart" });
  await act(async () => settle(50));
  await act(async () => button(dialog()!, "Fortsätt arbeta")!.click());
  assert.match(dialog()?.textContent ?? "", /Fönstret kunde inte öppnas/);
});

test("a login that ended covers the page, keeps it, and asks for a new login in a dialog nothing but that closes", async (t) => {
  backend(t, () => json(signedIn()));
  const opened: string[] = [];
  t.mock.method(window, "open", (url: string) => {
    opened.push(url);
    return {} as Window;
  });
  function Counter() {
    const [count, setCount] = useState(0);
    return createElement("button", { type: "button", onClick: () => setCount(count + 1) }, `Räknat ${count}`);
  }
  const { act, container, state } = await gate(
    { signedOutControls: createElement("p", null, "Det som får vara kvar"), signedOutNote: "en inspelning fortsätter och sparas på enheten." },
    createElement(Counter),
  );
  await act(async () => settle());
  await act(async () => button(container, "Räknat 0")!.click());
  const cover = () => container.querySelector<HTMLElement>(".eneo-session-cover")!;
  assert.equal(cover().hasAttribute("inert"), false);
  assert.ok(!dialog(), "no dialog in the tree while signed in");

  await act(async () => state.observe(signedOutStatus));
  assert.equal(cover().hasAttribute("inert"), true, "out of reach and out of the accessibility tree");
  assert.equal(cover().hasAttribute("data-signed-out"), true, "and not shown (base.css)");
  assert.ok(button(container, "Räknat 1"), "the page is still there, as it was");
  const d = dialog()!;
  assert.equal(d.tagName, "DIALOG");
  assert.ok(d.hasAttribute("open"));
  assert.match(d.textContent ?? "", /Du behöver logga in igen/);
  assert.match(d.textContent ?? "", /Inloggningen har upphört\./);
  assert.match(d.textContent ?? "", /Allt på den här sidan finns kvar, och en inspelning fortsätter och sparas på enheten\./);
  assert.match(d.textContent ?? "", /Det som får vara kvar/, "what the module keeps reachable is in the dialog");
  assert.equal(button(d, "Stäng"), null, "no way past it but the new login");
  assert.ok(d.contains(document.activeElement), "the focus is in it");
  await act(async () => {
    d.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
  assert.ok(dialog()?.hasAttribute("open"), "Escape keeps it open");

  await act(async () => button(dialog()!, "Logga in igen")!.click());
  assert.deepEqual(opened, ["/api/auth/login?next=%2Finloggad"], "after the end: a new login, no renewal bound to a user");
});

test("someone else signing in leaves the page covered and says whom to sign in as; the page's own user lifts it", async (t) => {
  backend(t, () => json(signedIn()));
  const { act, container, state } = await gate();
  await act(async () => settle());
  await act(async () => state.observe(signedIn(erik)));
  assert.match(dialog()?.textContent ?? "", /Du är inloggad som Erik Lund\. Logga in som Anna Berg för att fortsätta\./);
  assert.equal(container.querySelector(".eneo-session-cover")?.hasAttribute("inert"), true);
  await act(async () => state.observe(signedIn(anna)));
  assert.equal(container.querySelector(".eneo-session-cover")?.hasAttribute("inert"), false);
  assert.ok(!dialog(), "gone with the new login");
});

test("after the new login the focus is back where it was, or on the page's heading when that is gone", async (t) => {
  backend(t, () => json(signedIn()));
  let hide: (shown: boolean) => void = () => {};
  function Page() {
    const [shown, set] = useState(true);
    hide = set;
    return createElement("div", null, createElement("h2", { "data-phase-heading": "", tabIndex: -1 }, "Spelar in"), shown && createElement("button", { type: "button" }, "Pausa"));
  }
  const { act, container, state } = await gate({}, createElement(Page));
  await act(async () => settle());
  const out = async (whileOut = () => {}) => {
    await act(async () => state.observe(signedOutStatus));
    // As Chromium does once the page under the focus turns inert.
    await act(async () => (document.activeElement as HTMLElement | null)?.blur());
    await act(async () => whileOut());
    await act(async () => state.observe(signedIn()));
    await act(async () => settle());
  };
  const pausa = button(container, "Pausa")!;
  pausa.focus();
  await out();
  assert.ok(document.activeElement === pausa, "back on Pausa");

  pausa.focus();
  await out(() => hide(false));
  assert.ok(document.activeElement === container.querySelector("[data-phase-heading]"), "Pausa is gone: the page's heading");
});

test("a dialog that something closes is opened as a modal again while signed out, and stays closed with the new login", async (t) => {
  backend(t, () => json(signedIn()));
  const { act, state } = await gate();
  await act(async () => settle());
  await act(async () => state.observe(signedOutStatus));
  const d = dialog()!;
  for (let request = 1; request <= 2; request++) {
    await act(async () => d.close());
    assert.ok(d.hasAttribute("open"), `opened again after close request ${request}`);
    assert.ok(d.contains(document.activeElement), "the focus in it");
  }
  await act(async () => state.observe(signedIn()));
  assert.ok(!dialog());
  assert.equal(d.isConnected, false);
  d.close();
  assert.equal(d.hasAttribute("open"), false, "nothing opens it again");
});

/** Node's BroadcastChannel dispatches events of its own class, which installDom's Event replaced: a stand-in in memory. */
class FakeChannel {
  static all = new Set<FakeChannel>();
  listeners = new Set<(event: { data: unknown }) => void>();
  constructor(readonly name: string) {
    FakeChannel.all.add(this);
  }
  addEventListener(_type: string, listener: (event: { data: unknown }) => void) {
    this.listeners.add(listener);
  }
  removeEventListener(_type: string, listener: (event: { data: unknown }) => void) {
    this.listeners.delete(listener);
  }
  postMessage(data: unknown) {
    for (const other of FakeChannel.all) if (other !== this && other.name === this.name) other.listeners.forEach((listener) => listener({ data }));
  }
  close() {
    FakeChannel.all.delete(this);
  }
}

test("an answer that arrives after a later one's moves neither the end nor the keepalive; the page asks again when it is seen and when a login window says it is done", async (t) => {
  const held: Array<(response: Response) => void> = [];
  let calls = 0;
  const log = backend(t, () => {
    calls += 1;
    if (calls === 1) return json(signedIn()); // the first reading: the login ends in eight hours
    return new Promise<Response>((resolve) => held.push(resolve));
  });
  const nodeChannel = globalThis.BroadcastChannel;
  globalThis.BroadcastChannel = FakeChannel as unknown as typeof BroadcastChannel;
  t.after(() => {
    globalThis.BroadcastChannel = nodeChannel;
  });
  const { act, unmount } = await gate();
  await act(async () => settle());
  assert.equal(log.length, 1);

  await act(async () => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  assert.equal(log.length, 2, "asked again when the page is seen");
  const { SESSION_CHANNEL } = await import("../src/session/SignedInAgain.js");
  const other = new FakeChannel(SESSION_CHANNEL);
  await act(async () => {
    other.postMessage("signed-in");
    await settle();
  });
  other.close();
  assert.equal(log.length, 3, "and when a login window says it is done");

  // The later question is answered first: the login now ends in eight hours. The earlier answer, which says it ends
  // in 200 seconds, comes last and must change nothing: no warning.
  await act(async () => {
    held[1](json(signedIn(anna, 8 * 3600)));
    await settle();
  });
  await act(async () => {
    held[0](json(signedIn(anna, 200)));
    await settle(50);
  });
  assert.ok(!dialog(), "the old answer was not used");
  await unmount();
  const asked = log.length;
  await settle(30);
  assert.equal(log.length, asked, "nothing asks once the page has gone");
  assert.equal(FakeChannel.all.size, 0, "and the channel is closed");
});

test("while signed out what the page keeps reachable is pressed from the sign-in dialog, through its slot, without a login", async (t) => {
  backend(t, () => json(signedIn()));
  const { createPortal } = await import("react-dom");
  const { useSignedOutSlot } = await import("../src/session/RequireSession.js");
  const pressed: string[] = [];
  function Recorder({ phase }: { phase: "recording" | "ready" }) {
    const slot = useSignedOutSlot();
    if (!slot || phase !== "recording") return null;
    return createPortal(
      createElement("div", { role: "group", "aria-label": "Inspelningen" }, createElement("button", { type: "button", onClick: () => pressed.push("pausa") }, "Pausa"), createElement("button", { type: "button", onClick: () => pressed.push("stoppa") }, "Stoppa")),
      slot,
    );
  }
  let finish: () => void = () => {};
  function Page() {
    const [phase, set] = useState<"recording" | "ready">("recording");
    finish = () => set("ready");
    return createElement(Recorder, { phase });
  }
  const { act, state } = await gate({}, createElement(Page));
  await act(async () => settle());
  assert.ok(!dialog());
  await act(async () => state.observe(signedOutStatus));
  await act(async () => settle());
  await act(async () => button(dialog()!, "Pausa")!.click());
  await act(async () => button(dialog()!, "Stoppa")!.click());
  assert.deepEqual(pressed, ["pausa", "stoppa"]);
  await act(async () => finish());
  assert.equal(button(dialog()!, "Stoppa"), null, "nothing to stop once the recording is done");
});

test("the focus the warning found on the page is where it goes back after a login that ended under the open warning", async (t) => {
  // A second past the five minutes: the warning opens a second after the page.
  let endsIn = 5 * 60 + 1;
  backend(t, () => json(signedIn(anna, endsIn)));
  function Page() {
    return createElement("button", { type: "button" }, "Pausa");
  }
  const { act, container, state } = await gate({}, createElement(Page));
  // The page's own Pausa has the focus when the warning opens on its timer.
  const pausa = () => button(container, "Pausa");
  await act(async () => settle(30));
  assert.ok(!dialog(), "not yet");
  pausa()?.focus();
  await act(async () => settle(1_100));
  assert.ok(dialog()?.hasAttribute("open"), "the warning is open");
  assert.equal(document.activeElement?.tagName, "H2", "its title has the focus");
  await act(async () => state.observe(signedOutStatus));
  assert.match(dialog()?.textContent ?? "", /Du behöver logga in igen/, "the same dialog, now asking for the new login");
  assert.equal(button(dialog()!, "Stäng"), null, "and with no way past it");
  // The new login: the page asks again when it is seen, and the login now ends in eight hours.
  endsIn = 8 * 3600;
  await act(async () => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
  });
  assert.ok(!dialog(), "closed with the new login");
  assert.ok(document.activeElement === pausa(), "back on the control it left");
});

test("the window a login ends in tells the module's tabs and closes itself; a refused renewal says why and stays", async (t) => {
  backend(t, () => json(signedIn(anna)));
  const { SignedInAgain, SESSION_CHANNEL } = await import("../src/session/SignedInAgain.js");
  const FakeChannelClass = FakeChannel;
  const nodeChannel = globalThis.BroadcastChannel;
  globalThis.BroadcastChannel = FakeChannelClass as unknown as typeof BroadcastChannel;
  t.after(() => {
    globalThis.BroadcastChannel = nodeChannel;
  });
  const told: unknown[] = [];
  const listener = new FakeChannel(SESSION_CHANNEL);
  listener.addEventListener("message", (event) => told.push(event.data));
  const closed: number[] = [];
  t.mock.method(window, "close", () => closed.push(1));

  const done = await mount(createElement(SignedInAgain, { productName: "Testmodul", refusal: null }));
  assert.match(done.container.textContent ?? "", /Du är inloggad igen/);
  assert.deepEqual(told, ["signed-in"]);
  assert.equal(closed.length, 1);
  assert.equal(document.title, "Du är inloggad igen · Testmodul");
  assert.equal(done.container.querySelectorAll('main, [role="main"]').length, 1, "one main region in the window's page");
  await done.unmount();

  const wrong = await mount(createElement(SignedInAgain, { productName: "Testmodul", refusal: "annan-anvandare" }));
  await wrong.act(async () => settle());
  assert.match(wrong.container.textContent ?? "", /Du loggade in som en annan användare/);
  assert.match(wrong.container.textContent ?? "", /Stäng fönstret och logga in som Anna Berg för att fortsätta\./);
  assert.equal(told.length, 1, "it tells no tab it signed in");
  assert.equal(closed.length, 1, "and stays");
  await wrong.unmount();

  const ended = await mount(createElement(SignedInAgain, { productName: "Testmodul", refusal: "utgangen" }));
  assert.match(ended.container.textContent ?? "", /Inloggningen har redan gått ut/);
  assert.equal(told.length, 1);
  assert.equal(closed.length, 1);
  listener.close();
});

test("a refusal is read from the address the login window lands on", async () => {
  const { refusalOf } = await import("../src/session/SignedInAgain.js");
  assert.equal(refusalOf("?fel=annan-anvandare"), "annan-anvandare");
  assert.equal(refusalOf("?x=1&fel=utgangen"), "utgangen");
  assert.equal(refusalOf("?fel=nagot-annat"), null);
  assert.equal(refusalOf(""), null);
});

test("when onIdentity fails the page stays closed: someone else's data is not shown on a failed clean-up", async (t) => {
  backend(t, () => json(signedIn()));
  const { act, container } = await gate({ onIdentity: () => Promise.reject(new Error("could not clear")) });
  await act(async () => settle());
  assert.doesNotMatch(container.textContent ?? "", /Sidan/);
  assert.match(container.textContent ?? "", /Kunde inte kontakta modulen/);
});

const seen = () => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  document.dispatchEvent(new Event("visibilitychange"));
};

test("a status read begun before a request found the login ended does not uncover the page with its late answer", async (t) => {
  const late: Array<(response: Response) => void> = [];
  let status = 0;
  const browserFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request) => {
    if (String(url) === "/api/auth/status") {
      status += 1;
      return status === 1 ? json(signedIn()) : new Promise<Response>((resolve) => late.push(resolve));
    }
    // The module's own route: the backend says the login has ended.
    return new Response("{}", { status: 401, headers: { "X-Auth-Required": "session" } });
  }) as typeof fetch;
  t.after(() => {
    globalThis.fetch = browserFetch;
  });
  const { createFetchWithSession } = await import("../src/session/request.js");
  const { act, state } = await gate();
  await act(async () => settle());
  const fetchWithSession = createFetchWithSession(state);

  await act(async () => seen()); // a status question is out, its answer held
  assert.equal(late.length, 1);
  await act(async () => {
    void fetchWithSession("/api/eneo/runs/", { method: "POST" }).catch(() => undefined);
    await settle();
  });
  assert.equal(state.signedOut, true, "a request found the login ended");
  assert.ok(dialog()?.hasAttribute("open"), "and the page is covered");

  await act(async () => {
    late[0](json(signedIn())); // the answer to the earlier question: signed in
    await settle();
  });
  assert.equal(state.signedOut, true, "it is about the login before: the page stays covered");
  assert.ok(dialog()?.hasAttribute("open"));
});

test("a write that finds someone else's session (409 user_changed) covers the page and says at once whom to sign in as", async (t) => {
  const log = scripted(t, [() => json(signedIn()), () => json(signedIn(erik))], () => json({ detail: "user_changed" }, 409));
  const { createFetchWithSession } = await import("../src/session/request.js");
  const { act, state } = await gate();
  await act(async () => settle());

  await act(async () => {
    await createFetchWithSession(state)("/api/eneo/runs/", { method: "POST" }).catch(() => undefined);
    await settle();
  });

  assert.equal(state.signedOut, true);
  assert.match(dialog()?.textContent ?? "", /Du är inloggad som Erik Lund\. Logga in som Anna Berg för att fortsätta\./);
  assert.equal(log.filter((url) => url === "/api/auth/status").length, 2, "the status is read again at once, not when the page is next seen");
});

test("a renewal between two short sessions resets the dialog: the warning of the new end, not the words of the ended one", async (t) => {
  let answer: () => Response = () => json(signedIn(anna, 30));
  backend(t, () => answer());
  const { act, state } = await gate();
  await act(async () => settle(50));
  assert.match(dialog()?.textContent ?? "", /Du loggas snart ut/, "30 seconds left: the warning is open");
  await act(async () => state.observe(signedOutStatus));
  assert.match(dialog()?.textContent ?? "", /Du behöver logga in igen/);

  // The new login lives 45 seconds: its end is under a minute from the old one, which the page's smoothing keeps.
  answer = () => json(signedIn(anna, 45));
  await act(async () => {
    seen();
    await settle(60);
  });
  assert.equal(state.signedOut, false);
  assert.match(dialog()?.textContent ?? "", /Du loggas snart ut/, "the warning for the new session");
  assert.doesNotMatch(dialog()?.textContent ?? "", /Du behöver logga in igen/, "the ended latch is gone");
});

test("a renewal before the end that the login window announced resets the warning, though its end moved by under a minute", async (t) => {
  let endsIn = 200;
  backend(t, () => json(signedIn(anna, endsIn)));
  const nodeChannel = globalThis.BroadcastChannel;
  globalThis.BroadcastChannel = FakeChannel as unknown as typeof BroadcastChannel;
  t.after(() => {
    globalThis.BroadcastChannel = nodeChannel;
  });
  t.mock.method(window, "open", () => null);
  const { act } = await gate();
  await act(async () => settle(50));
  await act(async () => button(dialog()!, "Fortsätt arbeta")!.click());
  assert.match(dialog()?.textContent ?? "", /Fönstret kunde inte öppnas/, "the popup was blocked: said in the warning");

  endsIn = 230;
  const { SESSION_CHANNEL } = await import("../src/session/SignedInAgain.js");
  const other = new FakeChannel(SESSION_CHANNEL);
  await act(async () => {
    other.postMessage("signed-in");
    await settle(60);
  });
  other.close();
  await act(async () => settle(30)); // the warning is set again for the new end on a timer of its own
  assert.ok(dialog()?.hasAttribute("open"), "the new end is inside the five minutes too: the warning is there for it");
  assert.doesNotMatch(dialog()?.textContent ?? "", /Fönstret kunde inte öppnas/, "the old warning's problem is gone with the renewal");
});

/** The page's backend, answer by answer: `/api/auth/status` calls are answered by `answers` in turn (a held one is a promise); other calls by `other`. */
function scripted(t: import("node:test").TestContext, answers: Array<() => Response | Promise<Response>>, other?: () => Response) {
  const log: string[] = [];
  const browserFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request) => {
    log.push(String(url));
    if (String(url) === "/api/auth/status") return (answers.shift() ?? (() => json(signedIn())))();
    return other ? other() : json({});
  }) as typeof fetch;
  t.after(() => {
    globalThis.fetch = browserFetch;
  });
  return log;
}
const heldAnswer = () => {
  let release: (response: Response) => void = () => {};
  return { answer: () => new Promise<Response>((resolve) => (release = resolve)), arrive: (response: Response) => release(response) };
};
const withRefresh = (endsIn: number, refreshIn: number) => json({ ...signedIn(anna, endsIn), refresh_in: refreshIn });

/** A gate whose login window can say it is done (the channel is in memory), and the way to say it. */
async function gateWithWindow(t: import("node:test").TestContext) {
  const nodeChannel = globalThis.BroadcastChannel;
  globalThis.BroadcastChannel = FakeChannel as unknown as typeof BroadcastChannel;
  t.after(() => {
    globalThis.BroadcastChannel = nodeChannel;
  });
  const view = await gate();
  const { SESSION_CHANNEL } = await import("../src/session/SignedInAgain.js");
  const announce = async () => {
    const window = new FakeChannel(SESSION_CHANNEL);
    await view.act(async () => {
      window.postMessage("signed-in");
      await settle();
    });
    window.close();
  };
  return { ...view, announce };
}

test("an old signed-out status that arrives after the login window said it is done, before the confirmation, does not cover the renewed page", async (t) => {
  const oldRead = heldAnswer();
  const freshRead = heldAnswer();
  const log = scripted(t, [() => json(signedIn()), oldRead.answer, freshRead.answer, () => withRefresh(8 * 3600, 0)]);
  const { act, state, announce } = await gateWithWindow(t);
  await act(async () => settle());
  await act(async () => seen()); // a status question goes out and is held: the old login's
  await announce(); // the renewal replaced the cookie: the check that confirms it goes out and is held
  assert.equal(log.length, 3);

  await act(async () => {
    oldRead.arrive(json(signedOutStatus));
    await settle();
  });
  assert.equal(state.signedOut, false, "an answer to a question asked before the word covers nothing");
  await act(async () => {
    freshRead.arrive(withRefresh(8 * 3600, 0));
    await settle();
  });
  assert.equal(state.signedOut, false);
  assert.ok(!dialog(), "the renewed page is as it was");
  await act(async () => settle(1_200));
  assert.equal(log.length, 4, "the keepalive of the new login runs");
});

test("an old marked 401 that arrives after the login window said it is done, before the confirmation, does not cover the renewed page", async (t) => {
  const freshRead = heldAnswer();
  const log = scripted(t, [() => json(signedIn()), freshRead.answer, () => withRefresh(8 * 3600, 0)], () => new Response("{}", { status: 401, headers: { "X-Auth-Required": "session" } }));
  const { act, state, announce } = await gateWithWindow(t);
  await act(async () => settle());
  const { createFetchWithSession } = await import("../src/session/request.js");
  // Sent under the old login; its refusal arrives after the word.
  const late = heldAnswer();
  const stubbed = globalThis.fetch;
  let slow = true;
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => (slow && String(url) === "/api/eneo/runs/" ? late.answer() : stubbed(url, init))) as typeof fetch;
  t.after(() => {
    globalThis.fetch = stubbed;
  });
  const writing = createFetchWithSession(state)("/api/eneo/runs/", { method: "POST" }).catch(() => undefined);
  await act(async () => settle());
  await announce();
  slow = false;
  await act(async () => {
    late.arrive(new Response("{}", { status: 401, headers: { "X-Auth-Required": "session" } }));
    await writing;
    await settle();
  });
  assert.equal(state.signedOut, false, "the refusal belongs to the login before the word");
  await act(async () => {
    freshRead.arrive(withRefresh(8 * 3600, 0));
    await settle();
  });
  assert.equal(state.signedOut, false);
  assert.ok(!dialog());
  await act(async () => settle(1_200));
  assert.ok(log.filter((url) => url === "/api/auth/status").length >= 3, "and the keepalive of the new login runs");
});

test("the old deadline that passes after the login window said it is done, before the confirmation, does not cover the renewed page", async (t) => {
  const freshRead = heldAnswer();
  scripted(t, [() => json(signedIn(anna, 1)), freshRead.answer]);
  const { act, state, announce } = await gateWithWindow(t);
  await act(async () => settle());
  await announce();
  await act(async () => settle(1_300)); // the first login's end, a second after it began, passes while the check is out
  assert.equal(state.signedOut, false, "the old login's deadline is not the new login's");
  await act(async () => {
    freshRead.arrive(json(signedIn(anna, 8 * 3600)));
    await settle();
  });
  assert.equal(state.signedOut, false, "the confirmation is taken");
  assert.ok(!dialog(), "no warning, no cover: the new login ends in eight hours");
});

/** The address of the page under test, until the test ends. */
function at(t: import("node:test").TestContext, path: string) {
  window.history.replaceState(null, "", path);
  t.after(() => window.history.replaceState(null, "", "/"));
}

const MARK = "eneo-module:login-window";
const markedWindow = (t: import("node:test").TestContext) => {
  window.sessionStorage.setItem(MARK, "1");
  t.after(() => window.sessionStorage.clear());
};

/** What the module's tabs are told (each with whether the window was marked then), and how often the window closed itself. */
function watchWindow(t: import("node:test").TestContext) {
  const nodeChannel = globalThis.BroadcastChannel;
  globalThis.BroadcastChannel = FakeChannel as unknown as typeof BroadcastChannel;
  const listener = new FakeChannel("eneo-module:session");
  const told: Array<{ data: unknown; marked: boolean }> = [];
  listener.addEventListener("message", (event) => told.push({ data: event.data, marked: window.sessionStorage.getItem(MARK) === "1" }));
  const closed: number[] = [];
  t.mock.method(window, "close", () => closed.push(1));
  t.after(() => {
    listener.close();
    globalThis.BroadcastChannel = nodeChannel;
  });
  return { told, closed };
}

test("the login window is opened with the mark in the page's storage, which is gone after the call, whatever the call does; a page marked before stays marked", async (t) => {
  const { openLoginWindow, isLoginWindow } = await import("../src/session/SignedInAgain.js");
  t.after(() => window.sessionStorage.clear());
  const login = {} as Window;
  let outcome: "opened" | "blocked" | "thrown" = "opened";
  const markedAtCall: boolean[] = [];
  t.mock.method(window, "open", () => {
    markedAtCall.push(isLoginWindow());
    if (outcome === "thrown") throw new Error("no window");
    return outcome === "opened" ? login : null;
  });
  for (const result of ["opened", "blocked", "thrown"] as const) {
    for (const before of [false, true]) {
      const kind = `${result}, ${before ? "on a page marked before" : "on a page"}`;
      outcome = result;
      window.sessionStorage.clear();
      if (before) window.sessionStorage.setItem(MARK, "1");
      markedAtCall.length = 0;
      if (result === "thrown") assert.throws(() => openLoginWindow("/api/auth/login?next=%2Finloggad"), /no window/, `${kind}: the error is the caller's`);
      else assert.equal(openLoginWindow("/api/auth/login?next=%2Finloggad"), result === "opened" ? login : null, kind);
      assert.deepEqual(markedAtCall, [true], `${kind}: one call, marked while the window is made`);
      assert.equal(isLoginWindow(), before, `${kind}: after the call the page is as it was`);
    }
  }
});

test("storage that refuses a write, or cannot be read at all, does not stop the window: it is opened once, unmarked", async (t) => {
  const { openLoginWindow, isLoginWindow } = await import("../src/session/SignedInAgain.js");
  t.after(() => window.sessionStorage.clear());
  const markedAtCall: boolean[] = [];
  t.mock.method(window, "open", () => {
    markedAtCall.push(isLoginWindow());
    return {} as Window;
  });
  const proto = Object.getPrototypeOf(window.sessionStorage) as Storage;
  const write = t.mock.method(proto, "setItem", () => {
    throw new DOMException("The quota has been exceeded.", "QuotaExceededError");
  });
  const remove = t.mock.method(proto, "removeItem");
  openLoginWindow("/api/auth/login?next=%2Finloggad");
  assert.deepEqual(markedAtCall, [false], "a write refused: opened once, unmarked");
  assert.equal(remove.mock.callCount(), 0, "a write refused: nothing removed");
  write.mock.restore();
  remove.mock.restore();

  // A storage the browser refuses (blocked site data): reading it throws.
  const storage = Object.getOwnPropertyDescriptor(window, "sessionStorage");
  Object.defineProperty(window, "sessionStorage", {
    configurable: true,
    get() {
      throw new DOMException("The operation is insecure.", "SecurityError");
    },
  });
  try {
    openLoginWindow("/api/auth/login?next=%2Finloggad");
  } finally {
    if (storage) Object.defineProperty(window, "sessionStorage", storage);
    else Reflect.deleteProperty(window, "sessionStorage");
  }
  assert.deepEqual(markedAtCall, [false, false], "no storage: opened once, unmarked");
});

test("the dialog opens its window marked, without a name, straight on the login, back to the window's page whole; a renewal only before the end", async (t) => {
  backend(t, () => json(signedIn(anna, 200)));
  const { isLoginWindow } = await import("../src/session/SignedInAgain.js");
  const opened: Array<[string, string, string, boolean]> = [];
  t.mock.method(window, "open", (url: string, name: string, features: string) => {
    opened.push([url, name, features, isLoginWindow()]);
    return {} as Window;
  });
  for (const page of ["/inloggad", "/klart?lang=sv#resultat"]) {
    for (const renew of [true, false]) {
      const kind = `${page}, ${renew ? "before the end" : "after the end"}`;
      opened.length = 0;
      const view = await gate({ signedInAgainPath: page });
      await view.act(async () => settle(50));
      if (!renew) await view.act(async () => view.state.observe(signedOutStatus));
      await view.act(async () => button(dialog()!, renew ? "Fortsätt arbeta" : "Logga in igen")!.click());
      const next = encodeURIComponent(page);
      assert.deepEqual(opened, [[renew ? `/api/auth/login?renew=1&next=${next}` : `/api/auth/login?next=${next}`, "_blank", "popup,width=520,height=700", true]], kind);
      assert.equal(isLoginWindow(), false, `${kind}: the page is not marked after the call`);
      await view.unmount();
    }
  }
});

test("a second press opens a new window, then closes the one the dialog opened before; a blocked press leaves that one open and says so", async (t) => {
  backend(t, () => json(signedIn(anna, 200)));
  const events: string[] = [];
  let blocked = false;
  let made = 0;
  t.mock.method(window, "open", () => {
    if (blocked) {
      events.push("blocked");
      return null;
    }
    const n = made++;
    events.push(`open ${n}`);
    return { close: () => events.push(`close ${n}`) } as unknown as Window;
  });
  const { act } = await gate();
  await act(async () => settle(50));
  const press = () => act(async () => button(dialog()!, "Fortsätt arbeta")!.click());
  await press();
  await press();
  assert.deepEqual(events, ["open 0", "open 1", "close 0"], "the new window first, then the old one closed");
  blocked = true;
  await press();
  assert.deepEqual(events.slice(3), ["blocked"], "the window it has stays open");
  assert.match(dialog()?.textContent ?? "", /Fönstret kunde inte öppnas/);
  blocked = false;
  await press();
  assert.deepEqual(events.slice(4), ["open 2", "close 1"], "the next window closes the last one the dialog opened");
  assert.doesNotMatch(dialog()?.textContent ?? "", /Fönstret kunde inte öppnas/);
});

test("the window's page decides on the backend's refusal in its address, over the prop; the last recognised refusal counts", async (t) => {
  backend(t, () => json(signedIn(anna)));
  const { SignedInAgain, refusalOf } = await import("../src/session/SignedInAgain.js");
  const { told, closed } = watchWindow(t);
  const TITLE = { utgangen: "Inloggningen har redan gått ut", "annan-anvandare": "Du loggade in som en annan användare" } as const;
  const TEXT = { utgangen: /^Stäng fönstret\. Om det finns osparat arbete/, "annan-anvandare": /^Stäng fönstret och logga in som Anna Berg för att fortsätta\.$/ } as const;
  for (const fel of ["utgangen", "annan-anvandare"] as const) {
    for (const refusal of [null, fel === "utgangen" ? "annan-anvandare" : "utgangen"] as const) {
      const kind = `?fel=${fel}, refusal=${refusal}`;
      at(t, `/inloggad?fel=${fel}`);
      const view = await mount(createElement(SignedInAgain, { productName: "Testmodul", refusal }));
      await view.act(async () => settle());
      assert.equal(view.container.querySelector("h1")?.textContent, TITLE[fel], kind);
      assert.match(view.container.querySelector("p")?.textContent ?? "", TEXT[fel], kind);
      await view.unmount();
    }
  }
  // A configured `fel=` before the one the backend adds after the return address's query.
  at(t, "/inloggad?fel=&lang=sv&fel=utgangen");
  const configured = await mount(createElement(SignedInAgain, { productName: "Testmodul" }));
  assert.equal(configured.container.querySelector("h1")?.textContent, TITLE.utgangen);
  assert.match(configured.container.querySelector("p")?.textContent ?? "", TEXT.utgangen);
  await configured.unmount();
  assert.deepEqual(told, [], "nothing told");
  assert.equal(closed.length, 0, "nothing closed");

  assert.equal(refusalOf("?fel=annan-anvandare&fel=utgangen"), "utgangen");
  assert.equal(refusalOf("?fel=utgangen&fel=nagot"), "utgangen");
  assert.equal(refusalOf("?fel=&fel="), null);
});

test("the window's page with a failure in its address signs in as with any other query: it is the failure view's page that says a sign-in failed", async (t) => {
  const { SignedInAgain, isLoginWindow } = await import("../src/session/SignedInAgain.js");
  const { told, closed } = watchWindow(t);
  markedWindow(t);
  at(t, "/inloggad?auth_error=x");
  const view = await mount(createElement(SignedInAgain, { productName: "Testmodul" }));
  assert.match(view.container.textContent ?? "", /Du är inloggad igen/);
  assert.deepEqual(told, [{ data: "signed-in", marked: false }]);
  assert.equal(closed.length, 1);
  assert.equal(isLoginWindow(), false);
});

test("a failed sign-in in the login window says so and stays: no word to the tabs, no close, the same after a reload, and no code shown", async (t) => {
  const calls = backend(t, () => json(signedIn()));
  const { told, closed } = watchWindow(t);
  markedWindow(t);
  for (const [code, words] of [
    ["exchange_failed", "Stäng fönstret och försök igen från sidan."],
    ["invalid_state", "Inloggningen tog för lång tid eller avbröts. Stäng fönstret och försök igen från sidan."],
  ]) {
    // Where the backend sends a failed callback, under the module's gate.
    at(t, `/?auth_error=${code}`);
    for (const load of ["first", "after a reload"]) {
      const view = await gate();
      await view.act(async () => settle());
      const main = view.container.querySelector('main, [role="main"]');
      assert.equal(main?.querySelector("h1")?.textContent, "Inloggningen kunde inte slutföras", `${code}, ${load}`);
      assert.equal(main?.querySelector("p")?.textContent, words, `${code}, ${load}`);
      assert.doesNotMatch(view.container.textContent ?? "", new RegExp(code));
      assert.equal(document.title, "Inloggningen kunde inte slutföras · Testmodul");
      assert.equal(window.location.search, `?auth_error=${code}`, "the address keeps what the view is made of");
      await view.unmount();
    }
  }
  assert.deepEqual(told, []);
  assert.equal(closed.length, 0);
  assert.equal(calls.length, 0, "it asks nothing");
});

test("a sign-in screen in a marked window shows the window's failure view, with or without auth_error, and never a sign-in", async (t) => {
  const { SignInScreen } = await import("../src/session/SignInScreen.js");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  markedWindow(t);
  for (const address of ["/?auth_error=invalid_state", "/"]) {
    at(t, address);
    const view = await mount(createElement(ModuleProviders, { children: createElement(SignInScreen, { productName: "Testmodul", title: "Testmodul", next: "/flows" }) }));
    await view.act(async () => settle());
    assert.equal(view.container.querySelector("h1")?.textContent, "Inloggningen kunde inte slutföras", address);
    assert.equal(view.container.querySelector('a[href^="/api/auth/login"]'), null, "no sign-in in a login window");
    assert.equal(window.location.search, address.slice(1), "the address stays, so a reload says the same");
    await view.unmount();
  }
});

test("a completed sign-in in a marked window removes the mark, then tells the tabs and closes", async (t) => {
  const { SignedInAgain, isLoginWindow } = await import("../src/session/SignedInAgain.js");
  const { told, closed } = watchWindow(t);
  markedWindow(t);
  at(t, "/inloggad");
  await mount(createElement(SignedInAgain, { productName: "Testmodul" }));
  assert.deepEqual(told, [{ data: "signed-in", marked: false }], "unmarked before the word goes out");
  assert.equal(isLoginWindow(), false);
  assert.equal(closed.length, 1);
});

test("in a marked window the gate is only the failure view, also on the window's page: a completed return inside the gate tells the page nothing and reads no status", async (t) => {
  const calls = backend(t, () => json(signedIn()));
  const { SignedInAgain, isLoginWindow } = await import("../src/session/SignedInAgain.js");
  const { told, closed } = watchWindow(t);
  markedWindow(t);
  at(t, "/inloggad");
  const view = await gate({}, createElement(SignedInAgain, { productName: "Testmodul" }));
  await view.act(async () => settle());
  assert.equal(view.container.querySelector("h1")?.textContent, "Inloggningen kunde inte slutföras");
  assert.equal(isLoginWindow(), true, "the mark is still there");
  assert.deepEqual(told, [], "nothing told");
  assert.equal(closed.length, 0, "nothing closed");
  assert.equal(calls.length, 0, "the status is never read");
});

test("in a marked window on `/` with the backend's failure, a gate given `/` as the window's page opens no warning over the failure view", async (t) => {
  const calls = backend(t, () => json(signedIn(anna, 200)));
  const { SignedInAgain } = await import("../src/session/SignedInAgain.js");
  const { told, closed } = watchWindow(t);
  markedWindow(t);
  at(t, "/?auth_error=exchange_failed");
  const view = await gate({ signedInAgainPath: "/" }, createElement(SignedInAgain, { productName: "Testmodul" }));
  await view.act(async () => settle(50));
  assert.equal(view.container.querySelector("h1")?.textContent, "Inloggningen kunde inte slutföras");
  assert.ok(!dialog(), "no warning: less than five minutes are left, and the gate does not run");
  assert.deepEqual(told, [], "nothing told");
  assert.equal(closed.length, 0, "nothing closed");
  assert.equal(calls.length, 0, "the marked window reads no status");
});

test("in a marked window an ordinary page with a live session is the failure view: the page is not rendered and the status is never read", async (t) => {
  const calls = backend(t, () => json(signedIn()));
  markedWindow(t);
  at(t, "/flows");
  const view = await gate({}, "Flödeslistan");
  await view.act(async () => settle());
  assert.equal(view.container.querySelector("h1")?.textContent, "Inloggningen kunde inte slutföras");
  assert.doesNotMatch(view.container.textContent ?? "", /Flödeslistan/);
  assert.equal(calls.length, 0, "the status is never read");
});

test("the gate in a marked window never shows a sign-in, whatever `signIn` or `navigate` the module gives; an unmarked tab is the gate as before", async (t) => {
  let answer = () => json(signedIn());
  const calls = backend(t, () => answer());
  const tab = await gate();
  await tab.act(async () => settle());
  assert.match(tab.container.textContent ?? "", /Sidan/, "an unmarked tab with a live session shows the page");
  assert.equal(calls.length, 1);
  await tab.unmount();

  answer = () => json(signedOutStatus);
  markedWindow(t);
  const went: string[] = [];
  const out = await gate({ signIn: "Modulens inloggning", navigate: (path: string) => went.push(path) });
  await out.act(async () => settle());
  assert.equal(out.container.querySelector("h1")?.textContent, "Inloggningen kunde inte slutföras");
  assert.doesNotMatch(out.container.textContent ?? "", /Modulens inloggning/, "not the module's sign-in");
  assert.deepEqual(went, [], "not sent to the module's sign-in");
  assert.equal(calls.length, 1, "the marked window reads no status");
});

test("the backend's failure landing on the home path is never done, also where the window's page is the home path: the failure view, marked or not", async (t) => {
  const { SignedInAgain, isLoginWindow } = await import("../src/session/SignedInAgain.js");
  const { told, closed } = watchWindow(t);
  t.after(() => window.sessionStorage.clear());
  at(t, "/?auth_error=exchange_failed");
  for (const marked of [true, false]) {
    window.sessionStorage.clear();
    if (marked) window.sessionStorage.setItem(MARK, "1");
    for (const load of ["first", "mounted again"]) {
      const kind = `${marked ? "marked" : "unmarked"}, ${load}`;
      const view = await mount(createElement(SignedInAgain, { productName: "Testmodul" }));
      await view.act(async () => settle());
      assert.equal(view.container.querySelector("h1")?.textContent, "Inloggningen kunde inte slutföras", kind);
      assert.equal(isLoginWindow(), marked, `${kind}: the mark as it was`);
      await view.unmount();
    }
  }
  assert.deepEqual(told, [], "nothing told");
  assert.equal(closed.length, 0, "nothing closed");

  // A completed return to the home path finishes: the rule reads the query key, not the text.
  for (const address of ["/", "/?next=auth_error#auth_error"]) {
    window.sessionStorage.setItem(MARK, "1");
    at(t, address);
    const done = await mount(createElement(SignedInAgain, { productName: "Testmodul" }));
    await done.act(async () => settle());
    assert.match(done.container.textContent ?? "", /Du är inloggad igen/, address);
    await done.unmount();
  }
  assert.deepEqual(told, Array(2).fill({ data: "signed-in", marked: false }));
  assert.equal(closed.length, 2);
});

test("a page marked already keeps its mark when its first read of storage throws: one window, nothing written, nothing removed", async (t) => {
  const { openLoginWindow } = await import("../src/session/SignedInAgain.js");
  markedWindow(t);
  const proto = Object.getPrototypeOf(window.sessionStorage) as Storage;
  const read = proto.getItem;
  let reads = 0;
  t.mock.method(proto, "getItem", function (this: Storage, key: string) {
    if (reads++ === 0) throw new DOMException("The operation is insecure.", "SecurityError");
    return read.call(this, key);
  });
  const write = t.mock.method(proto, "setItem");
  const remove = t.mock.method(proto, "removeItem");
  const open = t.mock.method(window, "open", () => ({}) as Window);
  openLoginWindow("/api/auth/login?next=%2Finloggad");
  assert.equal(open.mock.callCount(), 1);
  assert.equal(write.mock.callCount(), 0, "nothing written");
  assert.equal(remove.mock.callCount(), 0, "nothing removed");
  assert.equal(read.call(window.sessionStorage, MARK), "1", "the page's own mark is still there");
});
