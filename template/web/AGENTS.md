# AGENTS

Project-specific guidance for AI coding agents.

<!-- ASTRYX:START -->
Astryx v0.6.3 · 164 components
CLI: run every command as `npx astryx <cmd>` (shown below as `astryx ...`).

SETUP (once, in your app entry e.g. main.tsx) — without these, components render unstyled:
  import "@astryxdesign/core/reset.css";
  import "@astryxdesign/core/astryx.css";

WORKFLOW — discover, don't guess. Before writing UI:
1. `astryx build "<idea>"` — START HERE: returns a kit (closest [page] + [block]s + [component]s). No args = full playbook.
2. `astryx template <name> [--skeleton]` — scaffold the [page]/[block]s it named, or study their layout. Templates are reference code.
3. `astryx component <Name>` — props + examples for every component you use.

RULES:
- No <div> — components do all layout/spacing, page frame included.
- Frame first: read `astryx docs layout` before writing any page or screen — page frame, region widths, breakpoint behavior.
- Dense data = rows (Table, List/Item), never Card-wrapped list items; Card is for standalone widgets. Status = StatusDot/Token; Badge = counts only.
- Custom styling: component props first; else style/className with tokens — var(--color-*|--spacing-*|--radius-*). No raw hex/px. (No StyleX/Tailwind compiler here — don't use xstyle/utility classes.)
- Tokens for every value (`astryx docs tokens`). Brand/accent belongs in the theme (`astryx theme list` / `theme add <slug>`, or `astryx theme template` for a custom one) — never override --color-* in :root.
- SELF-CHECK before you finish: re-read the file and replace any raw <div>/<span> layout, imported .css/@apply, or hardcoded value (#hex, 16px) with the component or a token (var(--color-*|--spacing-*|…)). If unsure a component/prop exists, run `astryx component <Name>` / `astryx search "<thing>"`; don't hand-roll CSS.

MORE CLI:
  search "<query>"   find any component / hook / doc / template / block
  component --list   164 components by category
  template --list    page + block recipes
  docs <topic>       browser-support, cli-integrations, color, elevation, getting-started, icons, illustrations, internationalization, layout, migration, motion, principles, shape, spacing, styling-libraries, styling, theme, tokens, typography, working-with-ai, eneo-module
  swizzle <Name>     eject component source for deep customization
  upgrade --apply    run after any Astryx or integration dependency bump

INTEGRATIONS:
- `@eneo-ai/module-kit`: Run Astryx through npm run astryx --; keep its core and CLI at the exact pinned version.
- `@eneo-ai/module-kit`: Read astryx docs eneo-module; start a page from eneo-module-page or eneo-signin and inspect every component prop.
- `@eneo-ai/module-kit`: Use ModuleProviders once; ModuleShell owns navigation, the skip link and the one main region. Cap content with Layout.
- `@eneo-ai/module-kit`: Private routes use RequireSession and fetchWithSession; close module-owned native dialogs while useSignedOut() is true.
- `@eneo-ai/module-kit`: Backend routes require require_session; writes and WebSockets also require require_same_origin. The module owns its allowlist.
- `@eneo-ai/module-kit`: Use Astryx components and Eneo theme tokens; no Next.js, Tailwind, authored StyleX or ejected components.
- `@eneo-ai/module-kit`: User-facing text is Swedish; fonts and scripts stay on the module origin. Keep 44 px touch targets and visible focus.
- `@eneo-ai/module-kit`: Add every page state to web/tests/e2e/screens.ts and run web build and test:e2e before finishing.
<!-- ASTRYX:END -->
