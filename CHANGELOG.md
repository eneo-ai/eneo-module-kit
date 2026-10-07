# Changelog

Purpose: describe changes in the two packages a module installs.
Read this when: choosing or upgrading a package version.
Related: [README](README.md), [new module](docs/guides/new-module.md), [UI package](packages/ui/README.md), [BFF package](packages/bff/README.md).

## 0.1.0 — unreleased

- `eneo-module-bff`: the Eneo SSO handoff, server-side sessions and renewal, a deny-by-default proxy, guarded transport helpers, bounded uploads and signed-file streams, shared heavy-I/O admission, branding and static UI serving.
- Deployment accent settings validate contrast against the Eneo theme and derive a dark-mode colour when omitted. The template loads their same-origin stylesheet from the BFF before themed content appears; no custom theme or inline script is needed.
- `@eneo-ai/module-kit`: the pinned Astryx theme, colour mode, providers, shell, branding and session client. Its Astryx integration adds two reference page templates, a documentation topic and generated agent guidance.
- Shared form fields have one focus frame along their rounded edge, supporting text follows a 14 px default, and error text and control edges meet AA contrast. Dialog headings receive initial focus without a control frame.
- The module template supplies a guarded backend, Swedish UI, stub Eneo, browser and accessibility checks, one-process image, local development and CI configuration.

Both packages use AGPL-3.0-only. Their 0.x APIs remain provisional until a second module has used them. Registry publication and release tags are pending; use the packed UI package and built BFF wheel for local acceptance.
