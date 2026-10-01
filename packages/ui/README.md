# @eneo-ai/module-kit

The UI of an Eneo module, for a static Vite + React app: the Eneo theme for [Astryx](https://astryx.atmeta.com), the
colour mode, the providers a page needs, the page shell and the brand lockup. It imports nothing from a router or a
meta-framework. Version 0.x: the API may change until a second module has used it.

```tsx
// main.tsx
import "@eneo-ai/module-kit/layers.css"; // first: the order of the cascade layers
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@eneo-ai/module-kit/theme.css";
import "@eneo-ai/module-kit/base.css";
import { BrandingProvider, ModuleProviders } from "@eneo-ai/module-kit";
import { Link } from "react-router"; // the app's own router, if it has one

createRoot(document.getElementById("root")!).render(
  <ModuleProviders linkComponent={Link}>
    <BrandingProvider defaultLogo="/brand/logo.svg">
      <App />
    </BrandingProvider>
  </ModuleProviders>,
);

// a page
<ModuleShell label="Tal till text" heading={<Brand productName="Tal till text" href="/flows" />} end={<AccountMenu />}>
  …
</ModuleShell>
```

| Export | What it is |
|---|---|
| `ModuleProviders` | Colour mode, the built Eneo theme, Astryx's words in Swedish, and (with `linkComponent`) the app's router link for Astryx's links. |
| `ColorModeProvider`, `useColorMode()`, `readStoredColorMode()` | The mode is `localStorage["theme"]` (`light`, `dark`, `system`; the key and values next-themes used), read before the first render and written back by `setMode`. `useColorMode()` returns `{ mode, resolved, setMode }`. No inline script and no cookie. |
| `ModuleShell` | The page frame: top bar, skip link, one `role="main"` region. A page renders no `<main>` of its own. |
| `BrandingProvider`, `Brand` | The organisation beside the product's name, from `GET /api/branding`, asked once. Until it answers (or when it fails) the lockup is the product name alone. `defaultLogo` is the module's own copy of the bundled logo. |
| `eneoTheme` | The built theme object, for `<Theme>` outside `ModuleProviders`. |

Stylesheets: `layers.css`, `theme.css` (generated from `src/theme/eneo.theme.ts` by `npm run theme:build`, committed in
`src/theme/built/`, and checked for freshness in CI) and `base.css` (what the theme cannot say: the shell's bar, the
brand's mark, forced-colour edges, no ring on a programmatically focused heading).

A design-system shortfall is fixed once, in `src/theme/eneo.theme.ts`, then `npm run theme:build`. Astryx is pinned to an
exact version, here and in the peers.
