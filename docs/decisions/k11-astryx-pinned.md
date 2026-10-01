# K11. Astryx is pinned to an exact version

Purpose: record the decision why Astryx has an exact version and the house accessibility bar lives in the theme.
Read this when: you want to upgrade Astryx or to override one of its components.
Related: [decisions](README.md), [design.md](../design.md) section 3 (K11) and section 6.

Status: Accepted, 2026-10-01. Planned: `packages/ui` and the template.

## Context

Astryx is pre-1.0. A minor version can change a component's props or behaviour. The house bar is above its defaults: 44 px touch targets, a measured focus ring, a readable dark-mode error label.

## Decision

Astryx is pinned to an exact version in the UI package and the template, and its CLI runs only through the package script. The house bar is met once, in the theme. No ejected component and no authored StyleX.

## Consequences

- Upgrading Astryx is its own change, never part of a feature change.
- A design-system shortfall is fixed once in the theme, not per module.
- Menus and pickers are not anchored to their trigger on Safari before 26 and Firefox before 147: a known limit of this Astryx version.
