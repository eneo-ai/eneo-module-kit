# AGENTS

Project-specific guidance for AI coding agents.

<!-- ASTRYX:START -->
Astryx v0.7.12 · 174 components
CLI: run every command as `npx astryx <cmd>` (shown below as `astryx ...`).

SETUP (once, in app entry e.g. main.tsx) — without these, components render unstyled:
  import "@astryxdesign/core/reset.css";
  import "@astryxdesign/core/astryx.css";

WORKFLOW — start every page from a template, never from scratch:
1. `astryx build "<idea>"` — names the template to scaffold from and the parts it lacks.
2. `astryx template <name> <path>` — scaffold it; keep its frame, gap and padding; replace the content.
3. `astryx template <Block>` for parts it lacks; `astryx component <Name>` to read props before using one.
Changing an existing page? Keep it: skip step 2 and add blocks/components inside its sections.
Before you deliver a build, run `astryx doctor --built <dir>`; don't deliver it if it fails.

RULES:
- No <div> — components handle all layout and spacing.
- Read `astryx docs layout` before changing a template's frame.
- Dense data = rows (Table, List/Item), not Card-wrapped lists. Badge = counts only.
- Style with component props first, then tokens (var(--color-*|--spacing-*|--radius-*)). No raw hex/px. No StyleX/Tailwind compiler here — don't use xstyle/utility classes directly. Some templates use StyleX and need a compiler plugin; see `astryx docs styling-overview`.
- Palettes and custom colors go through the theme, never :root overrides. Run `astryx theme add <slug>` to import; `theme eject <slug>` only forks source. See `astryx docs theme`.
- SELF-CHECK: re-read the file; replace any raw <div>/<span>, imported .css/@apply, or hardcoded #hex/px with the component or a token.

`astryx help` lists every command. Key ones beyond the workflow:
  search "<query>"   find any component / hook / doc / template
  discover <words>   integrations you could add
  docs <topic>       getting-started, principles, tokens, theme … (`astryx docs` lists all)
  docs cli           commands and API reference
  docs authoring     build an integration package, and every field it holds
  upgrade --from <old version> --apply   run after a dependency bump

INTEGRATIONS:
- `@eneo-ai/module-kit`: Run Astryx through npm run astryx --; keep its core and CLI at the exact pinned version.
- `@eneo-ai/module-kit`: Read astryx docs eneo-module; start a page from eneo-module-page or eneo-signin and inspect every component prop.
- `@eneo-ai/module-kit`: Use ModuleProviders once; ModuleShell owns navigation, the skip link and the one main region. Cap content with Layout.
- `@eneo-ai/module-kit`: Private routes use RequireSession and fetchWithSession; close module-owned native dialogs while useSignedOut() is true.
- `@eneo-ai/module-kit`: Backend routes require require_session; writes and WebSockets also require require_same_origin, and writes require_expected_user. The module owns its allowlist.
- `@eneo-ai/module-kit`: Use Astryx components and Eneo theme tokens; no Next.js, Tailwind, authored StyleX or ejected components.
- `@eneo-ai/module-kit`: User-facing text is Swedish; fonts and scripts stay on the module origin. Keep 44 px touch targets and visible focus.
- `@eneo-ai/module-kit`: Add every page state to web/tests/e2e/screens.ts and run web build and test:e2e before finishing.
<!-- ASTRYX:END -->
