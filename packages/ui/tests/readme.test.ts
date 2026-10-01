import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(cleanup);

const readme = readFileSync("README.md", "utf8");

test("the README's example passes React Router's Link as it is, and says what a link component is given", () => {
  const example = readme.match(/```tsx\n([\s\S]*?)```/)?.[1] ?? "";
  assert.match(example, /import \{ Link \} from "react-router"/);
  assert.match(example, /linkComponent=\{Link\}/);
  assert.match(readme, /`linkComponent` is given the props of an anchor, `href` first/);
  assert.match(readme, /and with `to`, the same address/);
});

test("what the README says a link component is given is what the design system gives it: href, and to, the same address", async () => {
  const { Link } = await import("@astryxdesign/core/Link");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const received: Record<string, unknown>[] = [];
  const Recorder = (props: Record<string, unknown>) => {
    received.push(props);
    return createElement("a", { href: props.href as string }, props.children as never);
  };
  await mount(createElement(ModuleProviders, { linkComponent: Recorder as never, children: createElement(Link, { href: "/flows", children: "Flöden" }) }));
  const props = received.at(-1) ?? {};
  assert.equal(props.href, "/flows");
  assert.equal(props.to, "/flows", "for a router that takes `to`");
});

test("so React Router's own Link, passed as the README does, links inside the app: a real address, and a press moves the router, not the page", async () => {
  const { Link: RouterLink, MemoryRouter, useLocation } = await import("react-router");
  const { Link } = await import("@astryxdesign/core/Link");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  let where = "";
  function Where() {
    where = useLocation().pathname;
    return null;
  }
  const view = await mount(
    createElement(MemoryRouter, {
      initialEntries: ["/"],
      children: createElement(ModuleProviders, {
        linkComponent: RouterLink as never,
        children: [createElement(Link, { key: "link", href: "/flows", children: "Flöden" }), createElement(Where, { key: "where" })],
      }),
    }),
  );
  const anchor = view.container.querySelector("a")!;
  assert.equal(anchor.getAttribute("href"), "/flows", "the address the router makes, not Astryx's props left as they came");
  assert.equal(where, "/");
  await view.act(async () => void anchor.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
  assert.equal(where, "/flows", "the router navigated in place");
});
