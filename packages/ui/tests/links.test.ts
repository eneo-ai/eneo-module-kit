// Which of the design system's links go to the app's router (`ModuleProviders linkComponent`), and which stay the plain
// anchors they are. A click that the router handled is one whose default it prevented (it navigates itself); a plain
// anchor leaves the default alone. Both are cancelled at the document, since jsdom cannot load a page.
import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { createElement } from "react";
import { cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(cleanup);

/** One of the design system's links, with React Router's own Link given to the providers, under a router at `/`. */
async function press(props: Record<string, unknown>) {
  const { createMemoryRouter, Link: RouterLink, RouterProvider } = await import("react-router");
  const { Link } = await import("@astryxdesign/core/Link");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const page = createElement(ModuleProviders, { linkComponent: RouterLink as never, children: createElement(Link, { ...props, children: "Länk" } as never) });
  const router = createMemoryRouter([{ path: "*", element: page }], { initialEntries: ["/"] });
  const { container, act } = await mount(createElement(RouterProvider, { router }));
  const anchor = container.querySelector("a")!;
  let handledByRouter: boolean | null = null;
  const seen = (event: Event) => {
    handledByRouter = event.defaultPrevented;
    event.preventDefault();
  };
  document.addEventListener("click", seen);
  await act(async () => anchor.click());
  document.removeEventListener("click", seen);
  return { anchor, router, handledByRouter };
}

test("a link to a page of the app is the router's: the click navigates without loading a document", async () => {
  const { anchor, router, handledByRouter } = await press({ href: "/flows" });
  assert.equal(anchor.getAttribute("href"), "/flows");
  assert.equal(handledByRouter, true, "the router took the click");
  assert.equal(router.state.location.pathname, "/flows");
});

test("the path keeps its query and its hash", async () => {
  const { router, handledByRouter } = await press({ href: "/flows/abc?run=1#top" });
  assert.equal(handledByRouter, true);
  assert.equal(router.state.location.pathname, "/flows/abc");
  assert.equal(router.state.location.search, "?run=1");
  assert.equal(router.state.location.hash, "#top");
});

test("a link to a page with target _self is still the router's", async () => {
  const { handledByRouter, router } = await press({ href: "/flows", target: "_self" });
  assert.equal(handledByRouter, true);
  assert.equal(router.state.location.pathname, "/flows");
});

for (const [name, props] of [
  ["a fragment", { href: "#x" }],
  ["mailto:", { href: "mailto:stod@example.se" }],
  ["another origin", { href: "https://example.se/" }],
  ["a protocol-relative address", { href: "//example.se/flows" }],
  ["an address the browser reads as another origin", { href: "/\\example.se/flows" }],
  ["the login, which leaves for Eneo", { href: "/api/auth/login?next=%2Fflows" }],
  ["a file of the API", { href: "/api/eneo/flows/abc/runs/def/artifacts/ghi/content" }],
  ["a file of the API in a new tab", { href: "/api/eneo/flows/abc/runs/def/artifacts/ghi/content", target: "_blank" }],
  ["a download", { href: "/flows", download: "anteckningar.docx" }],
  ["a page in a new tab", { href: "/flows", target: "_blank" }],
] as const) {
  test(`${name} is a plain anchor that the router never sees`, async () => {
    const { anchor, router, handledByRouter } = await press(props);
    assert.equal(anchor.getAttribute("href"), props.href, "the address as given");
    assert.equal(handledByRouter, false, "the router left the click alone");
    assert.equal(router.state.location.pathname, "/", "the router did not move");
  });
}

test("`to`, which the design system passes beside `href` for routers that read it, never reaches a plain anchor", async () => {
  for (const href of ["/api/healthz", "https://example.se/"]) {
    const { anchor } = await press({ href });
    assert.equal(anchor.hasAttribute("to"), false, href);
    await cleanup();
  }
});

test("the name and the other attributes of a link come through, either way", async () => {
  for (const href of ["/flows", "https://example.se/"]) {
    const { anchor } = await press({ href, label: "Till flödena", rel: "nofollow" });
    assert.equal(anchor.textContent, "Länk", href);
    assert.equal(anchor.getAttribute("aria-label"), "Till flödena", href);
    assert.match(anchor.getAttribute("rel") ?? "", /nofollow/, href);
    await cleanup();
  }
});
