# K9. Colour mode is the UI package's own

Purpose: record the decision why the UI package reads and stores the colour mode itself.
Read this when: you work on the UI package's providers or on how a module chooses light, dark or system.
Related: [decisions](README.md), [K4](k04-static-ui-served-by-the-bff.md), [design.md](../design.md) section 3 (K9).

Status: Accepted, 2026-10-01. Planned: `packages/ui` is not built yet.

## Context

A static app has no server render, so nothing can put the stored colour mode into the first HTML. An inline script would fix that and would break the strict CSP ([K4](k04-static-ui-served-by-the-bff.md)).

## Decision

The stored choice is read before React renders and passed to Astryx's `<Theme mode>` directly. The storage key is `theme` with the values `light`, `dark` and `system`, the same key and values next-themes uses, so speech-to-text's saved preferences carry over.

## Consequences

- No inline script, no cookie, no extra dependency for colour mode.
- A module that stores the mode under another key would lose users' choices once.
