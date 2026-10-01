# K13. The HTTP client is httpx2, not httpx

Purpose: record the decision why `packages/bff` uses `httpx2` and what that changes for a module.
Read this when: you consider switching HTTP client, or a module calls Eneo over HTTPS with a private CA.
Related: [decisions](README.md), [K14](k14-body-limits-and-stream-cap.md), [design.md](../design.md) section 6, `packages/bff/pyproject.toml`.

Status: Accepted, 2026-10-01 (decided with measurements). Built.

## Context

`httpx` has had no release since 0.28.1 (2024-12). It still builds a request with both `Content-Length` and `Transfer-Encoding`, and still lets a line break in a file's content type inject a multipart part header (both reproduced; `httpx2` fixed them in 2.11.0). Starlette's test client deprecates it. `httpx2` (`pydantic/httpx2`, 16 releases since May 2026) passes the same suite and the same adversary scripts with identical output. Against a slow fake Eneo, peak memory stays flat at 64 to 65 MB through a 1 GB upload on both clients, and event-loop latency and 20 concurrent Range streams are the same within noise (11 runs each).

## Decision

Use `httpx2`, with the floor `>=2.12.0`, where its five advisories are all fixed.

## Consequences

- `httpx2` pins `httpcore2` to its own version.
- It uses the operating system's trust store (`truststore`) instead of `certifi`: a module that calls Eneo over HTTPS with a private CA installs that CA in its image.
- The package declares ranges with security floors, not exact pins, because it is a library; CI runs the suite at the lowest versions the ranges allow and at the newest, with `pip-audit` on both (`.github/workflows/ci.yml`). A module pins and locks its own.
