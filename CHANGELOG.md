# Changelog

Purpose: describe changes in the two packages a module installs.
Read this when: choosing or upgrading a package version.
Related: [README](README.md), [new module](docs/guides/new-module.md), [UI package](packages/ui/README.md), [BFF package](packages/bff/README.md).

## 0.1.0 — unreleased

- `eneo-module-bff`: the Eneo SSO handoff, server-side sessions and renewal, a deny-by-default proxy, guarded transport helpers, bounded uploads and signed-file streams, shared heavy-I/O admission, branding and static UI serving.
- Deployment accent settings validate contrast against the Eneo theme and derive a dark-mode colour when omitted. The template loads their same-origin stylesheet from the BFF before themed content appears; no custom theme or inline script is needed.
- The built UI is served fast: its hashed files under `/assets` are kept for a year, the page and the files beside it are asked for again with an ETag (304 while they are the same), and a `.br` or `.gz` the build writes beside a file goes to a browser that accepts it. `HEAD` is answered like `GET`. A JSON answer of Eneo's of 1 KiB or more goes gzipped to a browser that accepts it.
- `GET /health` says which build runs: the commit, the build time and the repository the image was built from, and the release the deployment names, each `null` when not known.
- `@eneo-ai/module-kit`: the pinned Astryx theme, colour mode, providers, shell, branding, session client, and `VersionInfo` with `CopyButton`: which build runs, from `/api/healthz`, with copyable support details. `base.css` lets a menu longer than Astryx's 300 px cap take the window below the top bar, so the account menu's last row is not hidden behind a scroll. Its Astryx integration adds two reference page templates, a documentation topic and generated agent guidance.
- The top bar has the brand mark's height from the first frame, so a page does not move down when the organisation arrives.
- `BrandingProvider` asks for the organisation when the first `Brand` shows. A page without a lockup, such as the login window that closes itself, asks nothing and leaves no cut-off read.
- The top bar's brand link and the slider's thumb have the design system's focus ring in every engine; Safari's own ring on the link was under 3:1.
- Shared form fields have one focus frame along their rounded edge, supporting text follows a 14 px default, and error text and control edges meet AA contrast. Dialog headings receive initial focus without a control frame.
- The module template supplies a guarded backend, Swedish UI, stub Eneo, browser and accessibility checks, one-process image, local development and CI configuration.
- The template's browser tests run in two workers: each test has a scope of its own in the stub Eneo, so one that ends its login ends no other's. CI runs them in shards. Its build writes a `.br` and a `.gz` beside each asset; `npm test` runs its unit tests and guards (no network call outside `src/session.ts`, none in a unit test); `npm run test:prod` checks what the backend sends with the built UI: headers, caching, compression, routes, page weight, a release that took away an open page's files.
- The template's CI builds its image once, runs it as the compose file does and publishes it as `sha-<commit>` after every job passed; a tag `vX.Y.Z` gives that image its version without rebuilding it and creates the GitHub Release. Its production compose file runs the image read-only, without capabilities, chosen by `MODULE_VERSION`, and a Traefik overlay adds HTTPS, HSTS and a read timeout for uploads. The account menu's Version opens the build's details in a dialog.

Both packages use AGPL-3.0-only. Their 0.x APIs remain provisional until a second module has used them. Registry publication and release tags are pending; use the packed UI package and built BFF wheel for local acceptance.
