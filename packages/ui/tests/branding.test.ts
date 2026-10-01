import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { createElement } from "react";
import { cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(cleanup);

type Organization = { name: string; logo: "default" | "custom" | null; dark_logo: boolean };

/** What /api/branding answers, with a way to hold the answer back. */
function backend(answer: { organization: Organization | null } | "fail" | "slow" | number) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  let release: (response: Response) => void = () => {};
  const fetchImpl = ((url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (answer === "fail") return Promise.reject(new Error("network down"));
    if (answer === "slow") return new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(new Error("deadline"))));
    if (typeof answer === "number") return Promise.resolve(new Response("{}", { status: answer }));
    return new Promise<Response>((resolve) => (release = resolve)).then((response) => response);
  }) as typeof fetch;
  return {
    calls,
    fetchImpl,
    answer: (body: { organization: Organization | null }) => release(new Response(JSON.stringify(body), { status: 200 })),
  };
}

async function lockup(props: { backend: ReturnType<typeof backend>; brand?: Record<string, unknown>; provider?: Record<string, unknown> }) {
  const { BrandingProvider, Brand } = await import("../src/branding.js");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  return mount(
    createElement(ModuleProviders, {
      children: createElement(BrandingProvider, { fetchImpl: props.backend.fetchImpl, ...props.provider, children: createElement(Brand, { productName: "Tal till text", ...props.brand }) }),
    }),
  );
}

const marks = (container: ParentNode) => [...container.querySelectorAll("[data-brand-logo]")];

test("until the answer comes the lockup is the product name alone, with no organisation's mark", async () => {
  const server = backend({ organization: { name: "Sundsvalls kommun", logo: "custom", dark_logo: false } });
  const view = await lockup({ backend: server });
  assert.match(view.container.textContent ?? "", /Tal till text/);
  assert.deepEqual(marks(view.container), [], "no mark of any organisation yet");
  assert.doesNotMatch(view.container.textContent ?? "", /Sundsvalls kommun/);
  assert.equal(server.calls.length, 1, "asked once");
  assert.equal(server.calls[0].url, "/api/branding");
  assert.equal(server.calls[0].init?.cache, "no-store", "a replaced logo shows after a reload");
});

test("the organisation's own logo, one that serves both modes, is one image from the module", async () => {
  const server = backend({ organization: { name: "Kommunen", logo: "custom", dark_logo: false } });
  const view = await lockup({ backend: server });
  await view.act(async () => server.answer({ organization: { name: "Kommunen", logo: "custom", dark_logo: false } }));
  const images = [...view.container.querySelectorAll("img[data-brand-logo]")];
  assert.equal(images.length, 1);
  assert.equal(images[0].getAttribute("src"), "/api/branding/logo/light");
  assert.equal(images[0].getAttribute("alt"), "Kommunen");
  assert.equal(images[0].getAttribute("data-brand-logo"), "plain");
});

test("an organisation with a logo for each mode brings both, marked so the stylesheet shows the right one", async () => {
  const server = backend({ organization: null });
  const view = await lockup({ backend: server });
  await view.act(async () => server.answer({ organization: { name: "Kommunen", logo: "custom", dark_logo: true } }));
  const images = [...view.container.querySelectorAll("img[data-brand-logo]")];
  assert.deepEqual(images.map((image) => [image.getAttribute("data-brand-logo"), image.getAttribute("src")]), [
    ["light", "/api/branding/logo/light"],
    ["dark", "/api/branding/logo/dark"],
  ]);
});

test("the bundled logo is the module's own file; without one the organisation is its name as text", async () => {
  const withLogo = backend({ organization: null });
  const view = await lockup({ backend: withLogo, provider: { defaultLogo: "/brand/logo.svg" } });
  await view.act(async () => withLogo.answer({ organization: { name: "Sundsvalls kommun", logo: "default", dark_logo: false } }));
  const image = view.container.querySelector("img[data-brand-logo]");
  assert.equal(image?.getAttribute("src"), "/brand/logo.svg");
  assert.equal(image?.getAttribute("data-brand-logo"), "default");
  await view.unmount();

  const without = backend({ organization: null });
  const bare = await lockup({ backend: without });
  await bare.act(async () => without.answer({ organization: { name: "Sundsvalls kommun", logo: "default", dark_logo: false } }));
  assert.equal(bare.container.querySelector("img"), null);
  const name = bare.container.querySelector('[data-brand-logo="name"]');
  assert.equal(name?.textContent, "Sundsvalls kommun");
});

test("an organisation without a logo is its name as text, and none at all is the product name alone", async () => {
  const named = backend({ organization: null });
  const view = await lockup({ backend: named });
  await view.act(async () => named.answer({ organization: { name: "Kommunen", logo: null, dark_logo: false } }));
  assert.equal(view.container.querySelector('[data-brand-logo="name"]')?.textContent, "Kommunen");
  await view.unmount();

  const none = backend({ organization: null });
  const alone = await lockup({ backend: none });
  await alone.act(async () => none.answer({ organization: null }));
  assert.deepEqual(marks(alone.container), []);
  assert.match(alone.container.textContent ?? "", /Tal till text/);
});

test("a backend that fails, refuses or stalls leaves the product name alone, and says why in the console", async () => {
  const errors: string[] = [];
  const consoleError = console.error;
  console.error = (...args: unknown[]) => void errors.push(args.join(" "));
  try {
    for (const [answer, deadlineMs] of [["fail", 2_000], [503, 2_000], ["slow", 20]] as const) {
      const server = backend(answer);
      const view = await lockup({ backend: server, provider: { deadlineMs } });
      await view.act(async () => new Promise((resolve) => setTimeout(resolve, 80)));
      assert.deepEqual(marks(view.container), [], `${answer}: no mark`);
      assert.match(view.container.textContent ?? "", /Tal till text/, `${answer}: the product name`);
      await view.unmount();
    }
    assert.equal(errors.length, 3, "each failure is logged once");
    assert.ok(errors.every((line) => /\/api\/branding/.test(line)));
  } finally {
    console.error = consoleError;
  }
});

test("the product name is the page's, not the kit's", async () => {
  const server = backend({ organization: null });
  const view = await lockup({ backend: server, brand: { productName: "Mötesassistenten" } });
  assert.match(view.container.textContent ?? "", /Mötesassistenten/);
  assert.doesNotMatch(view.container.textContent ?? "", /Tal till text/);
});

test("a lockup that goes somewhere is a link named for the product and the organisation, through the app's link component", async () => {
  const { BrandingProvider, Brand } = await import("../src/branding.js");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const server = backend({ organization: null });
  const Custom = ({ href, children, ...rest }: { href: string; children?: unknown }) =>
    createElement("a", { ...rest, href, "data-custom-link": "" }, children as never);
  const view = await mount(
    createElement(ModuleProviders, {
      linkComponent: Custom as never,
      children: createElement(BrandingProvider, { fetchImpl: server.fetchImpl, children: createElement(Brand, { productName: "Tal till text", href: "/flows" }) }),
    }),
  );
  const alone = view.container.querySelector('a[data-custom-link][href="/flows"]');
  assert.ok(alone, "the link is the app's own");
  assert.equal(alone.getAttribute("aria-label"), "Tal till text");
  await view.act(async () => server.answer({ organization: { name: "Kommunen", logo: null, dark_logo: false } }));
  assert.equal(view.container.querySelector('a[href="/flows"]')?.getAttribute("aria-label"), "Tal till text – Kommunen");
});

test("a lockup with nowhere to go is not a link", async () => {
  const server = backend({ organization: null });
  const view = await lockup({ backend: server });
  assert.equal(view.container.querySelector("a"), null);
});

test("without a provider above it the lockup is the product name alone", async () => {
  const { Brand } = await import("../src/branding.js");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const view = await mount(createElement(ModuleProviders, { children: createElement(Brand, { productName: "Tal till text" }) }));
  assert.match(view.container.textContent ?? "", /Tal till text/);
  assert.deepEqual(marks(view.container), []);
});
