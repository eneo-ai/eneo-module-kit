import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { HStack } from "@astryxdesign/core/HStack";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { Brand } from "./branding.js";
import { ModuleShell } from "./ModuleShell.js";

/** How the history entry was reached: a link (PUSH), a redirect (REPLACE), Back or Forward (POP). */
type NavigationType = "PUSH" | "REPLACE" | "POP";

/** The navigation the person has made, until its page has its content and what follows it has been done. */
interface Navigation {
  path: string;
  /** The history entry's own key, under which its scroll offset is kept. */
  key: string;
  type: NavigationType;
  /** Its page has not yet had what follows a navigation done for it: the scroll offsets of the entry are not touched. */
  waiting: boolean;
  /** Its page has said it has its content, and the rest is set for the next frame. */
  scheduled: boolean;
}

const RouteContext = createContext<{ path: string; ready: (path: string) => void } | null>(null);

/** What takes the focus when a page appears: a phase's heading, or an h1 made focusable for it. */
const PHASE_HEADING = "[data-phase-heading], h1[tabindex]";

/**
 * The page's heading takes the focus when it is on no element: a phase's heading (`data-phase-heading`), else a heading
 * made focusable for it, else the first one. Focus that is on an element, the page's own or the person's, stays. It
 * scrolls nothing: the scroll is the navigation's own.
 */
function moveFocusToHeading() {
  if (document.activeElement && document.activeElement !== document.body) return;
  const main = document.querySelector<HTMLElement>('main, [role="main"]');
  const heading = main?.querySelector<HTMLElement>(PHASE_HEADING) ?? main?.querySelector<HTMLElement>("h1");
  if (!heading) return;
  if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
  heading.focus({ preventScroll: true });
}

/**
 * A page says it has its first real content (the list answered, the sign-in is no longer asking), not a spinner: the page,
 * not the router, knows when it is there. Outside `RouteEffects` it does nothing.
 */
export function useRouteReady(ready: boolean): void {
  const route = useContext(RouteContext);
  useEffect(() => {
    if (ready && route) route.ready(route.path);
  }, [ready, route]);
}

/**
 * What a navigation gives the person (WCAG 2.4.2, 2.4.3, 4.1.3), around the router's page (`children`). At once, the
 * route's `title`. When the page says it has its content (`useRouteReady`), in the next frame (a focus the page took
 * itself in its own effects has happened by then), once: its title said through a live region; the focus on its heading
 * when it is on no element (the control that had it left with the old page), unless the person pressed a key or the
 * pointer since and put the focus nowhere that the page removed; and the scroll, to the top for a link and to the entry's
 * own offset for Back. Only a new path is a navigation: a page that writes `?run=` into the address changes its own
 * state. The first load, and the redirect the first page sends the person on by before any page has its content, do none
 * of it. This is the one place that scrolls after a navigation: the app sets `history.scrollRestoration = "manual"`.
 * Router-free: the app's router gives the path, the entry's key and how it was reached.
 */
export function RouteEffects({
  path,
  entry,
  type,
  title,
  children,
}: {
  /** The path of the page shown (React Router: `useLocation().pathname`). */
  path: string;
  /** The history entry's key, under which its scroll offset is kept (`useLocation().key`). */
  entry: string;
  /** How it was reached (`useNavigationType()`). */
  type: NavigationType;
  /** The route's title, set at once. A page that names itself more closely does so in an effect, and has the last word. */
  title?: string;
  children: ReactNode;
}) {
  const announce = useAnnounce();
  const navigation = useRef<Navigation>({ path, key: entry, type, waiting: false, scheduled: false });
  const loaded = useRef(false);
  const offsets = useRef(new Map<string, number>());
  // Since the page changed: whether the person pressed a key or the pointer, and the element they last focused.
  const acted = useRef(false);
  const focusedSince = useRef<EventTarget | null>(null);
  // The frame that does it, which a RouteEffects that is gone does not leave behind.
  const frame = useRef(0);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  // A layout effect, so the route's title is set before the page's own effects, which name it more closely. A route
  // without a title leaves the title as it was. Only a new path retitles and waits.
  useLayoutEffect(() => {
    if (title) document.title = title;
    if (navigation.current.path === path) return;
    navigation.current = { path, key: entry, type, waiting: loaded.current || type !== "REPLACE", scheduled: false };
    acted.current = false;
    focusedSince.current = null;
  }, [path]);

  const ready = useCallback(
    (readyPath: string) => {
      const arrived = navigation.current;
      if (arrived.path !== readyPath) return;
      loaded.current = true;
      if (!arrived.waiting || arrived.scheduled) return;
      arrived.scheduled = true;
      cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => {
        // Left before its frame came: the frame is the page's that is gone, not the one that is loading now.
        if (navigation.current !== arrived) return;
        announce(document.title);
        // A person who acted keeps the focus where they put it; one the page removed from under them gets the heading.
        const removed = focusedSince.current instanceof Node && !focusedSince.current.isConnected;
        if (!acted.current || removed) moveFocusToHeading();
        const top = arrived.type === "POP" ? (offsets.current.get(arrived.key) ?? 0) : 0;
        window.scrollTo({ left: 0, top, behavior: "instant" });
        arrived.waiting = false;
      });
    },
    [announce],
  );

  useEffect(() => {
    const note = () => {
      acted.current = true;
    };
    const focused = (event: FocusEvent) => {
      focusedSince.current = event.target;
    };
    document.addEventListener("keydown", note, true);
    document.addEventListener("pointerdown", note, true);
    document.addEventListener("focusin", focused, true);
    return () => {
      document.removeEventListener("keydown", note, true);
      document.removeEventListener("pointerdown", note, true);
      document.removeEventListener("focusin", focused, true);
    };
  }, []);

  // Where each entry is scrolled to, for Back. Not while an entry is waiting for its page: a page that is shorter than it
  // was moves the window itself, and that is not where the person left the entry.
  useEffect(() => {
    const remember = () => {
      const current = navigation.current;
      if (!current.waiting) offsets.current.set(current.key, Math.round(window.scrollY));
    };
    window.addEventListener("scroll", remember, { passive: true });
    return () => window.removeEventListener("scroll", remember);
  }, []);

  const route = useMemo(() => ({ path, ready }), [path, ready]);
  return <RouteContext.Provider value={route}>{children}</RouteContext.Provider>;
}

/**
 * What stands where the page asked for cannot: what happened and the ways on, in the shell. A page like any other: its
 * own title, over the title of the route it stands in for, and, reached by a navigation, said with the focus in its
 * heading. In the column of the sign-in screen.
 */
function StandIn({ productName, heading, text, children }: { productName: string; heading: string; text: string; children: ReactNode }) {
  const path = useContext(RouteContext)?.path;
  // Again at each address it stands at: the route's own title is set first, at every new path (RouteEffects).
  useEffect(() => {
    document.title = `${heading.replace(/\.$/, "")} · ${productName}`;
  }, [heading, productName, path]);
  useRouteReady(true);
  return (
    <ModuleShell label={productName} heading={<Brand productName={productName} />}>
      <Layout height="auto" contentWidth={640} padding={4}>
        <LayoutContent isScrollable={false}>
          <VStack gap={4} paddingBlockStart={6}>
            <Heading level={1}>{heading}</Heading>
            <Text as="p" color="secondary">
              {text}
            </Text>
            <HStack gap={3} wrap="wrap">
              {children}
            </HStack>
          </VStack>
        </LayoutContent>
      </Layout>
    </ModuleShell>
  );
}

/** An address that is no page of the module: it says so, and the way to the start (`homeHref`). Route it at `*`. */
export function NotFoundPage({ productName, homeHref = "/" }: { productName: string; homeHref?: string }) {
  return (
    <StandIn productName={productName} heading="Sidan finns inte." text="Kontrollera adressen, eller gå till startsidan.">
      <Button label="Till startsidan" variant="primary" href={homeHref} />
    </StandIn>
  );
}

/**
 * A page that cannot be shown: its code could not be fetched (a tab that was open across a release asks for files that
 * are gone), or it threw. The router's error boundary renders it with the error, which goes to the console. Nothing
 * reloads by itself: a person may be in the middle of something on a page that is still open, and a reload is theirs to
 * choose.
 */
export function ErrorPage({ productName, error, homeHref = "/" }: { productName: string; error: unknown; homeHref?: string }) {
  useEffect(() => console.error("A page could not be shown:", error), [error]);
  return (
    <StandIn productName={productName} heading="Sidan kunde inte visas." text={`${productName} kan ha uppdaterats sedan sidan öppnades. Ladda om sidan.`}>
      <Button label="Ladda om sidan" variant="primary" onClick={() => window.location.reload()} />
      <Button label="Till startsidan" variant="secondary" href={homeHref} />
    </StandIn>
  );
}
