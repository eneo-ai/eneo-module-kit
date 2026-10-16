import { useMemo, type AnchorHTMLAttributes, type ComponentProps, type ElementType, type ReactNode } from "react";
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
 * A path of the app's own pages: absolute (a relative address stays an anchor), not another origin (`//host`, and
 * `/\\host`, which a browser reads the same way), and not the backend's `/api`, which answers files and the login, not pages.
 */
function isPage(href: unknown): href is string {
  if (typeof href !== "string" || !href.startsWith("/") || href.startsWith("//") || href.startsWith("/\\")) return false;
  return !/^\/api(?:[/?#]|$)/.test(href);
}

/**
 * The link for every link the design system draws: the app's own (a router's `Link`) for a page of the app opened in this
 * tab, so opening it is no page load, and a plain anchor for everything else: a fragment, `mailto:`, another origin, a
 * file or the login under `/api`, a new tab, a download. A router link to `/api/...` would be a navigation to a path the
 * router has no page for. Astryx gives the component `href` and, for routers that read it, `to`, the same address.
 */
function appLinks(App: ElementType) {
  return function AppLink({ to: _to, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { to?: unknown }) {
    const ownTab = props.target === undefined || props.target === "_self";
    if (isPage(props.href) && ownTab && props.download === undefined) return <App to={props.href} {...props} />;
    return <a {...props} />;
  };
}

/**
 * What every page needs above it: the colour mode (stored, applied on the first render), the built Eneo theme, and
 * the design system's own words in Swedish, and the place its toasts appear. With `linkComponent` the design system's links (a top bar's brand, a
 * link button) to a page of the app are the app's router links.
 */
export function ModuleProviders({
  children,
  linkComponent,
}: {
  children: ReactNode;
  /**
   * The app's link component (a router's `Link`), for links that go to a page of the app. Every other link stays a plain
   * anchor: one under `/api`, to another origin, with a `target` other than `_self`, or a `download`.
   */
  linkComponent?: ComponentProps<typeof LinkProvider>["component"];
}) {
  // One component per link component given, so the links are not mounted anew at every render.
  const link = useMemo(() => (linkComponent ? appLinks(linkComponent) : null), [linkComponent]);
  const themed = <Themed>{children}</Themed>;
  return <ColorModeProvider>{link ? <LinkProvider component={link}>{themed}</LinkProvider> : themed}</ColorModeProvider>;
}
