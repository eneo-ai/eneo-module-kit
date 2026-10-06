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
  assert.ok(done.container.querySelector('[role="main"]'), "one main region in a window with no shell");
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
