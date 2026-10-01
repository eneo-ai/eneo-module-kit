# The UI package

Purpose: say how a module installs `@eneo-ai/module-kit`, wires it up, and what each export does.
Read this when: you build a module's pages, change the colour mode, the page shell or the brand lockup, or touch the theme.
Related: [new module](new-module.md), [architecture](../architecture.md#the-ui-app-and-its-layers), [decisions K9](../decisions/k09-colour-mode-in-the-ui-package.md), [K10](../decisions/k10-branding-without-templating.md), [K11](../decisions/k11-astryx-pinned.md), [package README](../../packages/ui/README.md), [BFF README](../../packages/bff/README.md).

`@eneo-ai/module-kit` (`packages/ui`, version 0.1.0, not released) is the UI half of a module, for a static Vite + React app: the Eneo theme for [Astryx](https://astryx.atmeta.com), the colour mode, the providers a page needs, the page shell and the brand lockup. It imports nothing from a router or a meta-framework (a test pins this). Built: those. Planned: the session client (sign-in screen, the warning before the login ends, the cover while signed out) and the Astryx integration.

## Install

The package is not on npm yet. Pack it from a checkout of this repository and install the tarball:

```bash
# in the kit checkout
npm ci
npm run -w packages/ui build
npm pack -w packages/ui --pack-destination /path/to/dir      # writes eneo-ai-module-kit-0.1.0.tgz

# in the module's web/ folder
npm install /path/to/dir/eneo-ai-module-kit-0.1.0.tgz
```

Install the tarball, not the folder (`npm install file:../eneo-module-kit/packages/ui`). A folder install is a symlink, and the package then finds `react` in the kit's `node_modules`, the module finds its own: two copies of React, and hooks fail. (Checked: the two paths resolve to different files.) Inside this repository the template's `web/` is an npm workspace, which hoists one copy, so the template needs no tarball. The Dockerfile of the template uses the tarball too: see [new module](new-module.md).

Peer dependencies, all exact except React: `@astryxdesign/core` `0.6.3`, `@stylexjs/stylex` `0.19.1`, `react` and `react-dom` `>=19`. The module lists them itself (the template's `web/package.json` does).

## Wire it up

The package imports no stylesheet from its code; the module imports five, in this order:

```tsx
// web/src/main.tsx (from the template)
import "@eneo-ai/module-kit/layers.css";   // first: declares the cascade layers
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@eneo-ai/module-kit/theme.css";    // the built Eneo theme
import "@eneo-ai/module-kit/base.css";     // what the theme cannot say
import { BrandingProvider, ModuleProviders } from "@eneo-ai/module-kit";

createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <ModuleProviders linkComponent={RouterLink}>
      <BrandingProvider defaultLogo="/brand/logo.svg">
        <App />
      </BrandingProvider>
    </ModuleProviders>
  </BrowserRouter>,
);
```

A page is a `ModuleShell` with the brand in its heading:

```tsx
<ModuleShell label="Min modul" heading={<Brand productName="Min modul" href="/flows" />} end={<AccountMenu />}>
  <Layout height="auto" contentWidth={960} padding={4}>…</Layout>
</ModuleShell>
```

The template wraps that once in `web/src/Frame.tsx`, so a page renders `<Frame>`.

## The four exports of the package

| Import | What it is |
|---|---|
| `@eneo-ai/module-kit` | The code, below. |
| `@eneo-ai/module-kit/layers.css` | `@layer reset, astryx-base, astryx-theme;` Import it first, so the layers have their order. |
| `@eneo-ai/module-kit/theme.css` | The built Eneo theme. Generated from `packages/ui/src/theme/eneo.theme.ts` by `npm run theme:build` (in `packages/ui`), committed in `src/theme/built/`, and CI fails when it is stale. |
| `@eneo-ai/module-kit/base.css` | What the theme cannot say: the shell's bar scrolls away with the page, the brand's mark sizing and colour-mode swap, forced-colour edges for buttons and the slider, no ring on a heading that takes focus (`data-phase-heading`). Unlayered on purpose: it wins over the design system's layered styles. |

## The code

| Name | What it is |
|---|---|
| `ModuleProviders({ children, linkComponent? })` | The colour mode, Astryx's `<Theme>` with the built Eneo theme, Astryx's own words in Swedish (`sv-SE`), and, with `linkComponent`, Astryx's `LinkProvider`. |
| `ColorModeProvider` | The colour mode alone. `ModuleProviders` has one; use it directly only outside `ModuleProviders`. |
| `useColorMode()` | `{ mode, resolved, setMode }`. `mode` is the choice (`light`, `dark`, `system`), `resolved` is what is shown (the operating system's for `system`), `setMode(next)` applies and stores it. Throws outside a `ColorModeProvider`. |
| `readStoredColorMode(storage?)` | The stored choice, or `system` when there is none, it is not one of the three, or storage throws. |
| `COLOR_MODE_KEY` | `"theme"`. |
| `ModuleShell({ label, heading, start?, end?, banner?, height?, children })` | The page frame: top bar, skip link, one `role="main"` region. `label` names the navigation landmark; `heading` is the brand; `start` follows it and may wrap; `end` is the account menu; `banner` is a notice above the bar; `height` is `"auto"` (the page grows, the window scrolls) or `"fill"` (the shell is the window's height and the main region scrolls itself). |
| `BrandingProvider({ children, defaultLogo?, deadlineMs?, fetchImpl? })` | Asks `GET /api/branding` once, when the app starts. `defaultLogo` is the module's own copy of its bundled logo. `deadlineMs` defaults to `BRANDING_DEADLINE_MS` (2000). `fetchImpl` is for tests. |
| `BRANDING_DEADLINE_MS` | `2000`. |
| `Brand({ productName, href?, onClickCapture? })` | The header lockup: the organisation's mark, a divider and the product's name; without an organisation the name alone. With `href` it is a link, named for both. |
| `eneoTheme` | The built theme object, for `<Theme>` outside `ModuleProviders`. |
| `Branding`, `ColorMode` | Types: the answer of `/api/branding`, and `"light" \| "dark" \| "system"`. |

## Colour mode

- The key is `localStorage["theme"]` with the values `light`, `dark`, `system`: the key and values next-themes used, so a person's choice made in an app on it carries over ([K9](../decisions/k09-colour-mode-in-the-ui-package.md)).
- It is read when the provider first renders, so the first paint is already in the right mode, and passed to Astryx's `<Theme mode>`, which sets `data-theme` on the document for `light` and `dark` (for `system` it sets none, and the browser's preference decides).
- There is no inline script and no cookie: the page's Content-Security-Policy has no `unsafe-inline` ([K4](../decisions/k04-static-ui-served-by-the-bff.md)). A module must not add one to fix a flash of the wrong mode.
- `system` follows `prefers-color-scheme` and its changes. A choice made in another tab reaches this one (the `storage` event).
- Storage that is missing or throws is not an error: no choice is `system`, and a choice still applies for the visit.
- A module's own menu uses `useColorMode()`: the template's `AccountMenu` has the three choices.

## Links

The package imports no router. Astryx draws some links itself (the brand in the top bar, a link button); `ModuleProviders linkComponent={...}` makes them the app's router links, through Astryx's `LinkProvider`. The component receives `href` and the usual anchor props. React Router's `Link` takes `to`, so the template adapts it once:

```tsx
function RouterLink({ href, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  return <Link to={href} {...rest} />;
}
```

Without `linkComponent` the links are plain anchors and a click reloads the page. A link that leaves the app for another origin or for the BFF (`/api/auth/login`) is a plain `<a>`, as the template's sign-in page does.

## Branding

- `BrandingProvider` asks `/api/branding` once. It is optional: there is one deadline, and on a slow or failing answer the header shows the product name alone (the failure goes to the console). Until it has answered nothing of an organisation is shown, so no page shows one municipality's mark before another's ([K10](../decisions/k10-branding-without-templating.md)).
- The organisation is a deployment setting of the BFF (`ORGANIZATION_NAME`, `ORGANIZATION_LOGO`, `ORGANIZATION_LOGO_DARK`, `SHOW_ORGANIZATION`: see [configuration](configuration.md)). Its `logo` is `custom` (the deployment's own, served by `/api/branding/logo/light` and `/dark`), `default`, or none.
- **The kit ships no organisation's mark.** `default` means the logo the module bundles in its own frontend: the module passes its URL as `defaultLogo` (a file under its `public/`). Without `defaultLogo`, an organisation whose logo is `default` shows its name as text. The BFF serves no file for `default`.
- `Brand` takes the product's name as a prop: it is the page's own, never the kit's.
- Sizing and the choice between a deployment's two logos are CSS in `base.css`, by the attribute `data-brand-logo` on the mark: `default`, `light`, `dark`, `plain` (one logo for both modes), `name` (no logo). The mode that decides is the document's `data-theme`.

## The shell

- A page renders no `<main>` and no skip link: `ModuleShell` has them.
- Cap a page's content with Astryx's `Layout contentWidth`: a stack stretches its children to the window's whole width.
- A page that must not be left (a recording, a sending) passes less in `end` and `heading`; the shell decides nothing.
- The bar scrolls away with the page (`base.css`): stuck to the top it would hide a focused control (WCAG 2.4.11).

## Fix a shortfall once

A design-system shortfall (a target under 44 px, a missing focus ring, a label that cannot be read in dark mode) is fixed once, in `packages/ui/src/theme/eneo.theme.ts`, then `npm run theme:build` in `packages/ui`, and the regenerated `src/theme/built/` is committed. Astryx is pinned to an exact version in the package and in the template ([K11](../decisions/k11-astryx-pinned.md)); an upgrade is its own change. No ejected Astryx component and no authored StyleX.

## Develop the package

From the repository root:

```bash
npm ci
npm run -w packages/ui lint       # tsc --noEmit
npm test -w packages/ui           # node:test with jsdom
npm run -w packages/ui build      # tsc to dist/, the stylesheets beside it, and a check that dist/index.js loads with its names
npm run -w packages/ui theme:build && git diff --exit-code -- packages/ui/src/theme/built    # what CI's `ui` job also runs
```

Tests are in `packages/ui/tests/`, one file per concern: colour mode, providers, shell, branding, theme, and the package itself (no router import, no CSS import from code, exact pins, every export is built).
