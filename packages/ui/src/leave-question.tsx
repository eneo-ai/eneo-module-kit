import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";

/** What the person's answer leads to: the way off the page, and what staying undoes (a held navigation's reset). */
interface Pending {
  goOn: () => unknown;
  stay?: () => void;
}

/**
 * A menu (or another popover) the question is asked from closes first. A modal dialog closes it in Chromium and Firefox
 * as it opens; WebKit hides it without its `toggle` event, so the design system takes the next press on the menu's
 * trigger for a close. Closed by the page, it says so in every engine.
 */
function closePopovers() {
  try {
    document.querySelectorAll<HTMLElement>(":popover-open").forEach((open) => open.hidePopover());
  } catch {
    // An engine without popovers has none open.
  }
}

/**
 * While `active` (the page holds work that leaving would lose), leaving asks first. Router-free; the app's router holds a
 * navigation with it (the template's `web/src/leave.ts` wraps React Router's `useBlocker`).
 *
 * - The browser's own question (`beforeunload`) covers what no navigation of the app reaches: a reload, a closed tab,
 *   another site.
 * - `leaveFirst(goOn, stay?)` asks in the page's own dialog, "Lämna sidan?" with `warning`, before an action that ends
 *   the work without a navigation (signing out), and for a navigation the router held (`blocker.proceed`, `blocker.reset`).
 *   Not active, it goes on at once.
 * - `holds()` says, at the moment the router asks, whether a navigation must be held.
 * - `isActive`, when given, is called each time `holds`, `leaveFirst` or the browser's question asks, and reads where
 *   the page keeps its work (a store, a ref): a handler that stores the work and leaves in one go is let through before
 *   the page has rendered `active` false. Without it they read the last render's `active`.
 *
 * An answered "Lämna sidan" lets its own way off through: neither the router nor the browser asks again, also when the
 * page is unloaded after the action (WebKit asks `beforeunload` only after a `location.assign` has returned). A `goOn`
 * that runs at once (the router's `proceed`) is past the hold when it returns, and the hold is back. An action that
 * finishes later and did not leave (a sign-out that failed) returns `false`, and the hold is back; once the page holds no
 * work (`active` false) it is back too, for the next. The dialog is a native modal: the browser keeps it above the page,
 * and above the sign-in dialog when it was asked while signed out. Staying has the focus. Render `question` once on the
 * page.
 */
export function useLeaveQuestion(
  active: boolean,
  warning: string,
  isActive?: () => boolean,
): {
  question: ReactNode;
  leaveFirst: (goOn: () => unknown, stay?: () => void) => void;
  holds: () => boolean;
} {
  const [pending, setPending] = useState<Pending | null>(null);
  // While an answered way off goes on.
  const allowed = useRef(false);
  // The last render's `active` and `isActive`, which `holds` and `leaveFirst` read when they are called. A page that holds
  // no work any more holds the next from the start.
  const holding = useRef(active);
  const reads = useRef(isActive);
  useLayoutEffect(() => {
    holding.current = active;
    reads.current = isActive;
    if (!active) allowed.current = false;
  }, [active, isActive]);
  // Whether the page holds work at this moment.
  const holdsWork = useCallback(() => reads.current?.() ?? holding.current, []);

  useEffect(() => {
    if (!active) return;
    const ask = (event: BeforeUnloadEvent) => {
      if (allowed.current || !holdsWork()) return;
      event.preventDefault();
      // Browsers that ask only when it is set.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [active, holdsWork]);

  const holds = useCallback(() => holdsWork() && !allowed.current, [holdsWork]);
  const leaveFirst = useCallback((goOn: () => unknown, stay?: () => void) => {
    if (!holdsWork() || allowed.current) {
      void goOn();
      return;
    }
    closePopovers();
    setPending({ goOn, stay });
  }, [holdsWork]);

  const stay = () => {
    const answered = pending;
    setPending(null);
    answered?.stay?.();
  };
  const leave = () => {
    const answered = pending;
    setPending(null);
    if (!answered) return;
    allowed.current = true;
    let result: unknown;
    try {
      result = answered.goOn();
    } catch (error) {
      allowed.current = false;
      throw error;
    }
    if (!(result instanceof Promise)) {
      allowed.current = false;
      return;
    }
    // Still here when it is done, and it says so: the hold is back.
    result.then(
      (left) => {
        if (left === false) allowed.current = false;
      },
      () => {
        allowed.current = false;
      },
    );
  };

  const question = (
    <AlertDialog
      isOpen={pending !== null}
      onOpenChange={(open) => !open && stay()}
      title="Lämna sidan?"
      description={warning}
      cancelLabel="Stanna kvar"
      actionLabel="Lämna sidan"
      // Answered: the question closes with the answer, whether or not the way off the page then goes through.
      onAction={leave}
    />
  );
  return { question, leaveFirst, holds };
}
