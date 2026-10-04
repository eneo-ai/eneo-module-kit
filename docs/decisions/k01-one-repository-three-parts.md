# K1. One repository, three parts

Purpose: record the decision why the kit is one repository with an imported BFF package, an imported UI package and a copied template.
Read this when: you are deciding where a piece of shared or per-module code belongs.
Related: [decisions](README.md), [K2](k02-one-stack.md), [architecture](../architecture.md#parts-and-package-structure).

Status: Accepted, 2026-10-01. Built: `packages/bff` and its CI job. Planned: `packages/ui`, `template/`, and the CI job that builds the template against both packages.

## Context

Every module needs the same things: the login handoff, a session, a proxy that sends the right credentials, a themed accessible UI shell, a container image. Copying that code into each module means a fix reaches one module at a time.

## Decision

One repository with three parts: `packages/ui` (npm), `packages/bff` (Python), and `template/` (copied by a new module). One CI builds the template against both packages on every commit.

## Consequences

- Shared code is fixed in one place and arrives in a module as a version bump.
- The template is always proven to work with the current packages.
- A module owns only the thin glue: its allowlist, its routes, its copy.
- The kit is carved from one module, so its abstractions are unproven until a second module uses it (versions stay 0.x).
