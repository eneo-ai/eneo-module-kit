import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";
// The order matters: the cascade layers first, the design system's own styles, the Eneo theme, then the kit's base.
import "@eneo-ai/module-kit/layers.css";
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@eneo-ai/module-kit/theme.css";
import "@eneo-ai/module-kit/base.css";
import { router } from "./App";

// The kit's RouteEffects owns the scroll after a navigation; the browser must not restore it first.
history.scrollRestoration = "manual";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
