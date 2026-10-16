/**
 * What the backend sends with the built UI (eneo_module_bff/web.py): the security headers on every answer, an error's
 * too; the page asked for again each time, with an ETag, and the files under /assets kept for a year; the scripts and
 * stylesheets compressed for a browser that accepts it; and no banner that names the server.
 */
import type { APIRequestContext, APIResponse } from "@playwright/test";
import { expect, test } from "../e2e/fixtures";

const SECURITY = ["content-security-policy", "referrer-policy", "x-content-type-options", "x-frame-options", "permissions-policy"];

/** The page's own script and stylesheet: under /assets, named by their content. */
async function built(request: APIRequestContext) {
  const page = await (await request.get("/")).text();
  return { script: /\/assets\/index-[\w-]+\.js/.exec(page)![0], stylesheet: /\/assets\/index-[\w-]+\.css/.exec(page)![0] };
}

const header = (response: APIResponse, name: string) => response.headers()[name];

test("every answer carries the page's security headers: the page, its files, the API and an error", async ({ request }) => {
  const page = await request.get("/");
  const policy = header(page, "content-security-policy");
  expect(policy).toContain("script-src 'self'");
  expect(policy).toContain("frame-ancestors 'none'");
  expect(policy).not.toContain("unsafe-inline");
  expect([header(page, "x-content-type-options"), header(page, "x-frame-options"), header(page, "referrer-policy")]).toEqual(["nosniff", "DENY", "no-referrer"]);
  expect(header(page, "permissions-policy")).toBeTruthy();

  const { script, stylesheet } = await built(request);
  const answers: [string, number][] = [
    ["/flows", 200],
    [script, 200],
    [stylesheet, 200],
    ["/api/auth/status", 200],
    ["/health", 200],
    ["/api/eneo/flows/", 401],
    ["/api/nope", 404],
    ["/assets/index-0ldbui1d.js", 404],
  ];
  for (const [path, status] of answers) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(status);
    for (const name of SECURITY) expect(header(response, name), `${name} of ${path}`).toBe(header(page, name));
  }
});

test("the page is asked for again each time and answers 304 while it is the same; a file under /assets is kept for a year", async ({ request }) => {
  const page = await request.get("/");
  const etag = header(page, "etag");
  expect(header(page, "cache-control")).toBe("no-cache");
  expect(etag).toBeTruthy();
  const again = await request.get("/", { headers: { "If-None-Match": etag } });
  expect(again.status()).toBe(304);
  expect(header(again, "etag")).toBe(etag);

  const { script, stylesheet } = await built(request);
  for (const path of [script, stylesheet]) expect(header(await request.get(path), "cache-control"), path).toBe("public, max-age=31536000, immutable");
});

test("the scripts and stylesheets go compressed to a browser that accepts it, and no answer names the server", async ({ request }) => {
  const { script, stylesheet } = await built(request);
  for (const path of [script, stylesheet]) {
    for (const [accepted, sent] of [["br, gzip", "br"], ["gzip, deflate", "gzip"], ["identity", undefined]]) {
      const response = await request.get(path, { headers: { "Accept-Encoding": accepted! } });
      expect(header(response, "content-encoding"), `${path} for ${accepted}`).toBe(sent);
      expect(header(response, "vary"), path).toContain("Accept-Encoding");
    }
  }
  for (const path of ["/", script, "/api/nope", "/health"]) {
    const response = await request.get(path);
    expect(header(response, "server"), path).toBeUndefined();
    expect(header(response, "x-powered-by"), path).toBeUndefined();
  }
});
