import type { AnchorHTMLAttributes } from "react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link } from "react-router";
// The order matters: the cascade layers first, the design system's own styles, the Eneo theme, then the kit's base.
import "@eneo-ai/module-kit/layers.css";
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@eneo-ai/module-kit/theme.css";
import "@eneo-ai/module-kit/base.css";
import { BrandingProvider, ModuleProviders } from "@eneo-ai/module-kit";
import { App } from "./App";

// The design system's links (the brand in the top bar) go to the router, not the server.
function RouterLink({ href, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  return <Link to={href} {...rest} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ModuleProviders linkComponent={RouterLink}>
        {/* defaultLogo: the module's own copy of the bundled logo (public/brand/...), for an organisation whose logo is "default". */}
        <BrandingProvider>
          <App />
        </BrandingProvider>
      </ModuleProviders>
    </BrowserRouter>
  </StrictMode>,
);
