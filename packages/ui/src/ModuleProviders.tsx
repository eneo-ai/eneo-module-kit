import type { ComponentProps, ReactNode } from "react";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import { LayerProvider } from "@astryxdesign/core/Layer";
import { LinkProvider } from "@astryxdesign/core/Link";
import sv from "@astryxdesign/core/locales/sv-SE.json" with { type: "json" };
import { Theme } from "@astryxdesign/core/theme";
import { ColorModeProvider, useColorMode } from "./color-mode.js";
import { eneoTheme } from "./theme/built/eneo.js";

const MESSAGES = { "sv-SE": sv };

function Themed({ children }: { children: ReactNode }) {
  const { mode } = useColorMode();
  return (
    <InternationalizationProvider locale="sv-SE" messages={MESSAGES}>
      <Theme theme={eneoTheme} mode={mode}>
        {/* The design system's toasts are hosted here, in the theme and in Swedish: without it `useToast` mounts a root of its own that speaks English. */}
        <LayerProvider>{children}</LayerProvider>
      </Theme>
    </InternationalizationProvider>
  );
}

/**
 * What every page needs above it: the colour mode (stored, applied on the first render), the built Eneo theme, and
 * the design system's own words in Swedish, and the place its toasts appear. With `linkComponent` the design system's links (a top bar's brand, a
 * link button) are the app's router links.
 */
export function ModuleProviders({
  children,
  linkComponent,
}: {
  children: ReactNode;
  /** The app's link component (a router's `Link`), for links that go to a page of the app. */
  linkComponent?: ComponentProps<typeof LinkProvider>["component"];
}) {
  const themed = <Themed>{children}</Themed>;
  return <ColorModeProvider>{linkComponent ? <LinkProvider component={linkComponent}>{themed}</LinkProvider> : themed}</ColorModeProvider>;
}
