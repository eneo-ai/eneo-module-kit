# K1. One repository, three parts

Purpose: record the decision why the kit is one repository with an imported BFF package, an imported UI package and a copied template.
Read this when: you are deciding where a piece of shared or per-module code belongs.
Related: [decisions](README.md), [K2](k02-one-stack.md), [architecture](../architecture.md#parts-and-package-structure), [new module](../guides/new-module.md#what-ci-proves).

Status: Accepted, 2026-10-01. Built: `packages/bff`, `packages/ui`, `template/`, and the CI jobs that build the template against both packages (`bff`, `ui`, `template-backend`, `template-web`, `template-image`). Released: 0.1.0 of both packages, as GitHub release assets (2026-11-08).

## Context

Every module needs the same things: the login handoff, a session, a proxy that sends the right credentials, a themed accessible UI shell, a container image. Copying that code into each module means a fix reaches one module at a time.

## Decision

One repository with three parts: `packages/ui` (npm), `packages/bff` (Python), and `template/` (copied by a new module). One CI builds the template against both packages on every commit.

## Consequences

- Shared code is fixed in one place and arrives in a module as a version bump.
- The template is always proven to work with the current packages: its CI jobs install the packages of the same commit, not published ones.
- A module owns only the thin glue: its allowlist, its routes, its pages, its copy.
- The kit is carved from one module, so its abstractions are unproven until a second module uses it (versions stay 0.x).
- Because of this the template keeps a checkout's packages after a release: 0.1.0 is released as GitHub release assets, and the template moves to the release's pins later ([new module](../guides/new-module.md#where-the-packages-come-from)).
