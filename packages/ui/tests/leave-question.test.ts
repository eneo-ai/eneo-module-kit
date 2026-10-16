// Leaving a page that holds work asks first (useLeaveQuestion): the browser's own question for a reload or a closed tab,
// the page's own dialog for an action that ends the work, and, with React Router's blocker in the shape the template's
// web/src/leave.ts gives it, for a navigation the router sees. The dialog's modality and the browser's prompt are proved
// in a browser (template/web/tests/e2e/flow.spec.ts).
import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { createElement, useEffect, type ReactElement } from "react";
import { button, cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(cleanup);

const WARNING = "Det du har skrivit kunde inte sparas i webbläsaren och försvinner om du lämnar sidan.";
// The open question: the design system keeps a closed dialog in the document. Booleans and text only in assertions: a
// failed comparison of DOM nodes makes node print them, which under jsdom takes minutes and gigabytes.
const question = () => document.querySelector<HTMLElement>('[role="alertdialog"][open]');
const asked = () => question() !== null;
/** Whether the page asked the browser to ask before it unloads. */
const unloadAsks = () => !window.dispatchEvent(new window.Event("beforeunload", { cancelable: true }));

type Leaving = ReturnType<typeof import("../src/leave-question.js").useLeaveQuestion>;

/** A page that holds work while `active`, inside the providers, with its question rendered. */
async function page(active: boolean) {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { useLeaveQuestion } = await import("../src/leave-question.js");
  let leaving!: Leaving;
  function Page({ active }: { active: boolean }) {
    leaving = useLeaveQuestion(active, WARNING);
    return leaving.question as ReactElement;
  }
  const tree = (next: boolean) => createElement(ModuleProviders, { children: createElement(Page, { active: next }) });
  const view = await mount(tree(active));
  return { ...view, leaving: () => leaving, set: (next: boolean) => view.act(async () => view.rerender(tree(next))) };
}

test("a page that holds nothing lets every way off it go at once, and the browser asks nothing", async () => {
  const { act, leaving } = await page(false);
  let left = 0;
  await act(async () => leaving().leaveFirst(() => void (left += 1)));
  assert.equal(left, 1);
  assert.equal(asked(), false);
  assert.equal(unloadAsks(), false);
  assert.equal(leaving().holds(), false);
});

test("while the page holds work the browser asks before a reload or a closed tab, and no longer once it holds none", async () => {
  const { set } = await page(true);
  assert.equal(unloadAsks(), true);
  await set(false);
  assert.equal(unloadAsks(), false);
});

test("an action that ends the work asks first in the page's dialog: Stanna kvar keeps it, Lämna sidan goes on", async () => {
  const { act, leaving } = await page(true);
  let left = 0;
  let stayed = 0;
  await act(async () => leaving().leaveFirst(() => void (left += 1), () => void (stayed += 1)));
  assert.match(question()?.textContent ?? "", /Lämna sidan\?/);
  assert.match(question()?.textContent ?? "", /kunde inte sparas i webbläsaren/);
  assert.equal(left, 0, "nothing ends before the answer");

  await act(async () => button(question()!, "Stanna kvar")!.click());
  assert.deepEqual([left, stayed], [0, 1]);
  assert.equal(asked(), false, "the question closes with the answer");

  await act(async () => leaving().leaveFirst(() => void (left += 1)));
  await act(async () => button(question()!, "Lämna sidan")!.click());
  assert.equal(left, 1);
  assert.equal(asked(), false);
});

test("an answered Lämna sidan lets its own way off through: no second question from the browser while it goes, and the hold is back if it stays", async () => {
  const { act, leaving } = await page(true);
  let release = () => {};
  const seen: [boolean, boolean][] = [];
  await act(async () =>
    leaving().leaveFirst(
      () =>
        new Promise<void>((resolve) => {
          // While the action goes on (signing out, then a load of the sign-in page): neither asks again.
          seen.push([unloadAsks(), leaving().holds()]);
          release = resolve;
        }),
    ),
  );
  await act(async () => button(question()!, "Lämna sidan")!.click());
  assert.deepEqual(seen, [[false, false]]);
  await act(async () => release());
  assert.equal(unloadAsks(), true, "an action that did not leave (a sign-out that failed) holds the page again");
  assert.equal(leaving().holds(), true);
});

/** The template's web/src/leave.ts: the router's blocker holds a navigation to another path while the page holds work. */
async function routed(active: boolean) {
  const { createMemoryRouter, RouterProvider, useBlocker, useNavigate } = await import("react-router");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { useLeaveQuestion } = await import("../src/leave-question.js");
  let leaving!: Leaving;
  let navigate!: ReturnType<typeof useNavigate>;
  function Page() {
    leaving = useLeaveQuestion(active, WARNING);
    navigate = useNavigate();
    const blocker = useBlocker(({ currentLocation, nextLocation }) => leaving.holds() && currentLocation.pathname !== nextLocation.pathname);
    const { leaveFirst } = leaving;
    useEffect(() => {
      if (blocker.state === "blocked") leaveFirst(blocker.proceed, blocker.reset);
    }, [blocker, leaveFirst]);
    return leaving.question as ReactElement;
  }
  const router = createMemoryRouter(
    [{ path: "/sida", element: createElement(ModuleProviders, { children: createElement(Page) }) }, { path: "*", element: null }],
    { initialEntries: ["/start", "/sida"], initialIndex: 1 },
  );
  const view = await mount(createElement(RouterProvider, { router }));
  return { ...view, router, leaving: () => leaving, navigate: () => navigate };
}

test("a navigation the router sees (a link, Back) is held for the question: Stanna kvar stays where it was, Lämna sidan goes", async () => {
  const { act, router } = await routed(true);
  await act(async () => void router.navigate(-1));
  assert.equal(router.state.location.pathname, "/sida", "held");
  assert.equal(asked(), true, "and asked");
  await act(async () => button(question()!, "Stanna kvar")!.click());
  assert.equal(router.state.location.pathname, "/sida");
  assert.equal(asked(), false);

  await act(async () => void router.navigate("/annan"));
  await act(async () => button(question()!, "Lämna sidan")!.click());
  assert.equal(router.state.location.pathname, "/annan");
});

test("a change of the address that keeps the path is no departure, and a page that holds nothing is not held", async () => {
  const held = await routed(true);
  await held.act(async () => void held.router.navigate({ search: "?run=r1" }, { replace: true }));
  assert.equal(held.router.state.location.search, "?run=r1");
  assert.equal(asked(), false);
  await cleanup();

  const free = await routed(false);
  await free.act(async () => void free.router.navigate("/annan"));
  assert.equal(free.router.state.location.pathname, "/annan");
  assert.equal(asked(), false);
});

test("an action asked first that then navigates in the app goes through the blocker it was asked for", async () => {
  const { act, router, leaving, navigate } = await routed(true);
  await act(async () => leaving().leaveFirst(() => navigate()("/")));
  await act(async () => button(question()!, "Lämna sidan")!.click());
  assert.equal(router.state.location.pathname, "/");
  assert.equal(asked(), false, "asked once");
});
