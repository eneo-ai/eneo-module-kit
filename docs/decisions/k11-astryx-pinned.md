# K11. Astryx is pinned to an exact version

Purpose: record the decision why Astryx has an exact version and the house accessibility bar lives in the theme.
Read this when: you want to upgrade Astryx or to override one of its components.
Related: [decisions](README.md), [UI package](../guides/ui-package.md#fix-a-shortfall-once), [design.md](../design.md) section 3 (K11) and section 6.

Status: Accepted, 2026-10-01. Built: exact pins in `packages/ui/package.json` and `template/web/package.json`, the `astryx` script in both, and the house bar in `packages/ui/src/theme/eneo.theme.ts`.

## Context

Astryx is pre-1.0. A minor version can change a component's props or behaviour. The house bar is above its defaults: 44 px touch targets, a measured focus ring, a readable dark-mode error label.

## Decision

Astryx is pinned to an exact version in the UI package (its peers and what it builds against) and in the template, and its CLI runs only through the package script (`npm run astryx -- <command>`). The house bar is met once, in the theme. No ejected component and no authored StyleX.

## Consequences

- A test in `packages/ui/tests/package.test.ts` fails when `@astryxdesign/core`, `@stylexjs/stylex` or the CLI is not an exact version, or when the CLI is not the core's own version.
- Upgrading Astryx is its own change, never part of a feature change.
- A design-system shortfall is fixed once in the theme, not per module; `npm run theme:build` regenerates `src/theme/built/`, and CI fails on a stale one.
- The theme's text, error, control-edge and focus colours are checked on their actual surfaces in `packages/ui/tests/contrast.test.ts`. The template verifies supporting-text size and field/dialog focus in a browser.
- Menus and pickers are not anchored to their trigger on Safari before 26 and Firefox before 147: a known limit of this Astryx version.
