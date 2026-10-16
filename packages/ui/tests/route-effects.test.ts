// What a navigation gives the person (RouteEffects, useRouteReady) and the pages that stand in for one that cannot be
// shown (NotFoundPage, ErrorPage), under React Router's data router, wired as the template's App.tsx wires them. What
// jsdom cannot show (a screen reader's speech, the browser's own scroll) is proved in a browser (template/web/tests/e2e).
import assert from "node:assert/strict";
import test, { afterEach, type TestContext } from "node:test";
import { createElement, useEffect, useState, type ReactElement } from "react";
import { cleanup, installDom, mount } from "./test-dom.js";

const frames = (count: number) => new Promise<void>((resolve) => (function next(left: number) { left === 0 ? resolve() : requestAnimationFrame(() => next(left - 1)); })(count));

installDom();
afterEach(async () => {
  await cleanup();
  // What the design system's live region was given in a test's last frame is not the next test's.
  await frames(2);
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => (region.textContent = ""));
  document.title = "";
});
const said = () => document.querySelector('[data-astryx-live-region="polite"]')?.textContent ?? "";

/** The window's scroll, which jsdom does not have: where each call put it, and where it is. */
function windowScroll(t: TestContext) {
  const calls: number[] = [];
  let at = 0;
  const original = Object.getOwnPropertyDescriptor(window, "scrollY");
  Object.defineProperty(window, "scrollY", { get: () => at, configurable: true });
  const scrollTo = window.scrollTo;
  window.scrollTo = ((options: ScrollToOptions) => {
    at = options.top ?? 0;
    calls.push(at);
  }) as typeof window.scrollTo;
  t.after(() => {
    window.scrollTo = scrollTo;
    if (original) Object.defineProperty(window, "scrollY", original);
  });
  return {
    calls,
    /** The person scrolls the window to `top`. */
    to(top: number) {
      at = top;
      window.dispatchEvent(new window.Event("scroll"));
    },
  };
}

/** A page with a main region, a heading and a control, which says when it has its content. */
async function page(heading: string, ready = true): Promise<ReactElement> {
  const { useRouteReady } = await import("../src/routes.js");
  function Page() {
    useRouteReady(ready);
    return createElement("main", null, createElement("h1", null, heading), createElement("button", null, "Knapp"));
  }
  return createElement(Page);
}

/**
 * The frame, as the template's: the route's title from its `handle`, the location and how it was reached, and RouteEffects
 * around the page. `/flows` has its content only when the test says (`ready()`).
 */
async function open(entry: string) {
  const { createMemoryRouter, Outlet, RouterProvider, useLocation, useMatches, useNavigationType } = await import("react-router");
  const { RouteEffects, useRouteReady } = await import("../src/routes.js");
  function Frame() {
    const { pathname, key } = useLocation();
    const type = useNavigationType();
    const title = [...useMatches()].reverse().map((match) => (match.handle as { title?: string } | undefined)?.title).find(Boolean);
    return createElement(RouteEffects, { path: pathname, entry: key, type, title, children: createElement(Outlet) });
  }
  let makeReady = () => {};
  function Flows() {
    const [ready, setReady] = useState(false);
    makeReady = () => setReady(true);
    useRouteReady(ready);
    return createElement("main", null, createElement("h1", null, "Listan"));
  }
  function Flow() {
    // A page that names itself once it has what it needs, in an effect, as a page does.
    useEffect(() => {
      document.title = "Nämndmöte · Testmodul";
    }, []);
    useRouteReady(true);
    return createElement("main", null, createElement("h1", null, "Flödet"));
  }
  const router = createMemoryRouter(
    [
      {
        Component: Frame,
        children: [
          { index: true, handle: { title: "Logga in · Testmodul" }, element: await page("Start") },
          { path: "flows", handle: { title: "Välj ett flöde · Testmodul" }, Component: Flows },
          { path: "flows/:id", handle: { title: "Testmodul" }, Component: Flow },
          { path: "free", element: await page("Utan titel") },
        ],
      },
    ],
    { initialEntries: [entry] },
  );
  const view = await mount(createElement(RouterProvider, { router }));
  return { ...view, router, ready: () => view.act(async () => makeReady()) };
}
test("a page is titled by its route from the first frame", async () => {
  await open("/");
  assert.equal(document.title, "Logga in · Testmodul");
  await cleanup();
  await open("/flows");
  assert.equal(document.title, "Välj ett flöde · Testmodul");
});

test("a navigation retitles the page at once, and a page that names itself later has the last word", async () => {
  const { router, act } = await open("/flows");
  await act(async () => router.navigate("/flows/abc"));
  assert.equal(document.title, "Nämndmöte · Testmodul", "the flow page's own title, set after the route's");
});

test("Back to the list is titled the list, not the flow", async () => {
  const { router, act } = await open("/flows");
  await act(async () => router.navigate("/flows/abc"));
  await act(async () => router.navigate(-1));
  assert.equal(document.title, "Välj ett flöde · Testmodul");
});

test("a change of the address that keeps the path does not touch the title the page set", async () => {
  const { router, act } = await open("/flows/abc");
  await act(async () => router.navigate({ search: "?run=r1" }, { replace: true }));
  assert.equal(document.title, "Nämndmöte · Testmodul");
});

test("a route with no title leaves the title as it was", async () => {
  const { router, act } = await open("/flows");
  await act(async () => router.navigate("/free"));
  assert.equal(document.title, "Välj ett flöde · Testmodul");
});

test("a navigation is said, focused and scrolled once its page has its content, not before; the first load is none", async (t) => {
  const scroll = windowScroll(t);
  const { router, act, ready } = await open("/");
  await act(async () => frames(3));
  assert.equal(said(), "", "the first load says nothing");
  assert.deepEqual(scroll.calls, [], "and scrolls nothing");

  scroll.to(400);
  await act(async () => router.navigate("/flows"));
  await act(async () => frames(3));
  assert.equal(said(), "", "a page that is still loading is not said");
  assert.deepEqual(scroll.calls, []);

  await ready();
  await act(async () => frames(3));
  assert.equal(said(), "Välj ett flöde · Testmodul", "its title, through the live region");
  assert.equal(document.activeElement?.textContent, "Listan", "the focus is in its heading, which was on no element");
  assert.equal(document.activeElement?.getAttribute("tabindex"), "-1", "made focusable for it, not a Tab stop");
  assert.deepEqual(scroll.calls, [0], "a link starts at the top");
});

test("Back goes to where the person left the page, and focus that is on an element stays there", async (t) => {
  const scroll = windowScroll(t);
  const { router, act, ready } = await open("/flows");
  await ready();
  scroll.to(600);
  await act(async () => router.navigate("/flows/abc"));
  await act(async () => frames(3));
  assert.deepEqual(scroll.calls, [0]);

  const button = document.createElement("button");
  document.body.append(button);
  t.after(() => button.remove());
  button.focus();
  await act(async () => router.navigate(-1));
  await ready();
  await act(async () => frames(3));
  assert.deepEqual(scroll.calls, [0, 600], "the entry's own offset for Back");
  assert.equal(document.activeElement, button, "focus that is on an element stays there");
});

test("a page that cannot be found says so, with the way to the start, in the frame; its title is its own", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { NotFoundPage } = await import("../src/routes.js");
  const { container } = await mount(createElement(ModuleProviders, { children: createElement(NotFoundPage, { productName: "Testmodul", homeHref: "/flows" }) }));
  assert.deepEqual([...container.querySelectorAll("h1")].map((heading) => heading.textContent), ["Sidan finns inte."]);
  assert.match(container.textContent ?? "", /Kontrollera adressen, eller gå till startsidan\./);
  const home = [...container.querySelectorAll("a")].find((link) => link.textContent === "Till startsidan");
  assert.equal(home?.getAttribute("href"), "/flows");
  assert.ok(container.querySelector('nav[aria-label="Testmodul"]'), "the bar");
  assert.equal(container.querySelectorAll('main, [role="main"]').length, 1, "one main region");
  assert.equal(document.title, "Sidan finns inte · Testmodul");
});

/** The template's route table around one lazy page: the providers in the frame, and ErrorPage as the boundary. */
async function failing(t: TestContext, load: () => Promise<{ Component: () => ReactElement }>, entries = ["/"]) {
  const { createMemoryRouter, Link, Outlet, RouterProvider, useLocation, useNavigationType, useRouteError } = await import("react-router");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { ErrorPage, RouteEffects } = await import("../src/routes.js");
  const logged = t.mock.method(console, "error", () => undefined);
  function Frame() {
    const { pathname, key } = useLocation();
    return createElement(ModuleProviders, {
      linkComponent: Link,
      children: createElement(RouteEffects, { path: pathname, entry: key, type: useNavigationType(), children: createElement(Outlet) }),
    });
  }
  function RouteError() {
    return createElement(ErrorPage, { productName: "Testmodul", error: useRouteError() });
  }
  const router = createMemoryRouter(
    [{ Component: Frame, children: [{ ErrorBoundary: RouteError, children: [{ path: "/", element: await page("Start") }, { path: "/sida", lazy: load }] }] }],
    { initialEntries: entries },
  );
  const view = await mount(createElement(RouterProvider, { router }));
  return { ...view, router, logged };
}

const headings = (within: ParentNode) => [...within.querySelectorAll("h1")].map((heading) => heading.textContent);

test("a page whose code cannot be fetched is replaced in the frame by what happened, a reload to press and a way home", async (t) => {
  const { container, logged, router } = await failing(t, async () => {
    throw new TypeError("Failed to fetch dynamically imported module");
  }, ["/sida"]);
  assert.deepEqual(headings(container), ["Sidan kunde inte visas."]);
  assert.match(container.textContent ?? "", /Testmodul kan ha uppdaterats sedan sidan öppnades\. Ladda om sidan\./);
  assert.ok([...container.querySelectorAll("button")].some((button) => button.textContent === "Ladda om sidan"), "a reload, when a person presses it");
  const home = [...container.querySelectorAll("a")].find((link) => link.textContent === "Till startsidan");
  assert.equal(home?.getAttribute("href"), "/", "a link to the start page");
  assert.ok(container.querySelector('nav[aria-label="Testmodul"]'), "the bar is still there");
  assert.equal(container.querySelectorAll('main, [role="main"]').length, 1, "one main region");
  assert.equal(router.state.location.pathname, "/sida", "at the address the page had");
  assert.equal(document.title, "Sidan kunde inte visas · Testmodul", "its own title, over the failed route's");
  assert.ok(logged.mock.calls.some((call) => String(call.arguments.join(" ")).includes("A page could not be shown")), "the error is logged for whoever looks");
});

test("a page that throws is replaced the same way; reached by a navigation, it is said and its heading has the focus", async (t) => {
  const { container, router, act } = await failing(t, async () => ({
    Component: () => {
      throw new Error("the page broke");
    },
  }));
  await act(async () => frames(2));
  await act(async () => router.navigate("/sida"));
  await act(async () => frames(3));
  assert.deepEqual(headings(container), ["Sidan kunde inte visas."]);
  assert.equal(said(), "Sidan kunde inte visas · Testmodul");
  assert.equal(document.activeElement?.textContent, "Sidan kunde inte visas.");
});
