import type { ComponentType, ReactNode } from "react";
import { createBrowserRouter, Link, Outlet, useLocation, useMatches, useNavigationType, useRouteError } from "react-router";
import { BrandingProvider, ErrorPage, LoadingShell, ModuleProviders, NotFoundPage, RouteEffects } from "@eneo-ai/module-kit";
import { RequireSession, SignInScreen, SignedInAgain } from "@eneo-ai/module-kit/session";
import { documentTitle, PRODUCT_NAME } from "./config";
import { drafts } from "./drafts";

const SIGN_IN_TEXT = "Logga in med ditt Eneo-konto för att fortsätta.";

/** What a route says about itself beside its page: its title, which the page may name more closely. */
interface RouteHandle {
  title: string;
}

/** What every page stands in: the colour mode, the design system's providers, the router's links and the organisation. */
function Providers({ children }: { children: ReactNode }) {
  return (
    // The design system's links to a page of the app (the brand in the top bar) go to the router; the kit keeps the rest
    // (a file under /api, another origin, a new tab, a download) plain anchors.
    <ModuleProviders linkComponent={Link}>
      {/* defaultLogo: the module's own copy of the bundled logo (public/brand/...), for an organisation whose logo is "default". */}
      <BrandingProvider>{children}</BrandingProvider>
    </ModuleProviders>
  );
}

/** The frame of every page: the providers, and what a navigation gives the person (title, announcement, focus, scroll). */
function Root() {
  const { pathname, key } = useLocation();
  const type = useNavigationType();
  // The innermost route's title (`handle`).
  const title = [...useMatches()].reverse().map((match) => (match.handle as RouteHandle | undefined)?.title).find(Boolean);
  return (
    <Providers>
      <RouteEffects path={pathname} entry={key} type={type} title={title}>
        <Outlet />
      </RouteEffects>
    </Providers>
  );
}

/** While the first page's code arrives: the shell with its bar, so no frame is blank. */
function RootLoading() {
  return (
    <Providers>
      <LoadingShell productName={PRODUCT_NAME} />
    </Providers>
  );
}

/** A page that cannot be shown (its code is gone after a release, or it threw): what happened, a reload and the way home. */
function RouteError() {
  return <ErrorPage productName={PRODUCT_NAME} error={useRouteError()} homeHref="/flows" />;
}

/**
 * The pages that need a session. The kit's gate shows the sign-in screen without one, keeps the login, and covers the
 * page with a dialog that asks for a new login in place when it ends. Before the pages are shown to someone, what another
 * person typed in this tab goes.
 */
function Private() {
  return (
    <RequireSession productName={PRODUCT_NAME} signInTitle={PRODUCT_NAME} signInDescription={SIGN_IN_TEXT} onIdentity={(user) => drafts.keepOnly(user.id)}>
      <Outlet />
    </RequireSession>
  );
}

/** A page whose code is fetched when its route is first entered: a person on the sign-in page does not download it. */
function page(load: () => Promise<ComponentType>) {
  return async () => ({ Component: await load() });
}

/**
 * The module's pages. Add yours as routes, with a title (`handle`); a page that needs a session goes under `Private`.
 * `/inloggad` is where a login in a window of its own ends: it tells this module's tabs and closes itself.
 */
export const router = createBrowserRouter([
  {
    Component: Root,
    HydrateFallback: RootLoading,
    children: [
      {
        ErrorBoundary: RouteError,
        children: [
          {
            index: true,
            handle: { title: documentTitle("Logga in") } satisfies RouteHandle,
            element: <SignInScreen productName={PRODUCT_NAME} title={PRODUCT_NAME} description={SIGN_IN_TEXT} next="/flows" />,
          },
          { path: "inloggad", handle: { title: documentTitle("Inloggad igen") } satisfies RouteHandle, element: <SignedInAgain productName={PRODUCT_NAME} /> },
          {
            Component: Private,
            children: [
              {
                path: "flows",
                handle: { title: documentTitle("Välj ett flöde") } satisfies RouteHandle,
                lazy: page(async () => (await import("./pages/Flows")).Flows),
              },
            ],
          },
          // Any other address: the page says it does not exist, with the way to the start.
          { path: "*", handle: { title: documentTitle("Sidan finns inte") } satisfies RouteHandle, element: <NotFoundPage productName={PRODUCT_NAME} homeHref="/flows" /> },
        ],
      },
    ],
  },
]);
