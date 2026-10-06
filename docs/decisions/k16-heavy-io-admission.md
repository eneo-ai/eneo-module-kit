# K16. Shared admission for heavy operations

Purpose: bound upload spooling and long-lived upstream connections before allocating them.
Read this when: you add a long-lived module protocol, change concurrency or upload reception, or size temporary storage.
Related: [configuration](../guides/configuration.md), [build a module](../guides/build-a-module.md), [K14](k14-body-limits-and-stream-cap.md).

Status: Implemented, 2026-10-06. Extends K14's stream-only admission. Source: `packages/bff/src/eneo_module_bff/limits.py`, `transport.py`, `settings.py`, `app.py`, `upstream.py`.

## Context

A file-size limit bounds one temporary file. Concurrent uploads can still fill the spool, and a client sending occasional bytes can keep a partial file indefinitely. A stream-only cap also leaves uploads and module-owned connections free to occupy the rest of the shared HTTP pool, delaying token renewal.

## Decision

Use app-owned admission shared by uploads, signed-file streams and module protocols. `heavy_io_slot(request_or_websocket)` yields admission without queueing; each long-lived upstream connection takes one slot. The module owns its protocol and overload response. The kit's upload and stream functions acquire admission before parsing or minting and hold it through cleanup. Uploads also have a concurrent-upload limit; streams retain their own limit.

The HTTP pool has 100 connections. The heavy-operation ceiling cannot exceed 96, leaving at least four for short API and auth calls. This does not reserve capacity against arbitrary short API traffic. An injected client and a module's other upstream connections remain the module's responsibility.

Bound upload reception by both a total deadline and inactivity between chunks. A timeout returns 408 `upload_receive_timeout`; busy uploads return 503 `uploads_busy` with `Retry-After`. Validate the final multipart boundary before forwarding. Starlette closes partial files on parse failure or cancellation; completed forms close under a cancellation shield before admission is released. No new runtime dependency is needed.

## Consequences

Size the spool for `MAX_CONCURRENT_UPLOADS × MAX_UPLOAD_BYTES`, plus filesystem and other application use. Raising concurrency also raises this storage bound. Reception deadlines need to fit the deployment's slowest supported network; resumable upload protocols remain module-owned. The configuration page owns defaults and validation.

Tests cover refusal before reading, total and inactivity deadlines, immediate file cleanup, shared module/file/upload admission and capacity held through upstream closure. `packages/bff/tests/test_heavy_io.py` holds 32 uploads and 63 file streams over real TCP connections at the maximum shared ceiling while a token refresh and authenticated API call complete.
