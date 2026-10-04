# K5. SSO only

Purpose: record the decision why the kit has no access-code login.
Read this when: someone wants a local or demo login in the BFF.
Related: [decisions](README.md), [local development](../guides/local-development.md), [design.md](../design.md) section 2.

Status: Accepted, 2026-10-01. Built.

## Context

Speech-to-text has a temporary access-code login for testing without Eneo's SSO. It is not part of the module contract.

## Decision

The kit supports the Eneo handoff only. Local development uses a stub Eneo that implements the handoff.

## Consequences

- `AUTH_MODE`, `APP_ACCESS_CODE`, the access-code session and `DEMO_SPACE_ID` are not in `packages/bff`.
- `ENEO_PUBLIC_URL` is always required.
- A module needs a stub or a real Eneo to sign in: see the local development guide.
