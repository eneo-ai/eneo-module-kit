import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";

/** What the person's answer leads to: the way off the page, and what staying undoes (a held navigation's reset). */
interface Pending {
  goOn: () => unknown;
  stay?: () => void;
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
 *
 * An answered "Lämna sidan" lets its own way off through: neither the browser nor the router asks again while it goes
 * on, and the hold is back if it did not leave (a sign-out that failed). The dialog is a native modal: the browser keeps
 * it above the page, and above the sign-in dialog when it was asked while signed out. Staying has the focus. Render
 * `question` once on the page.
 */
export function useLeaveQuestion(active: boolean, warning: string): { question: ReactNode; leaveFirst: (goOn: () => unknown, stay?: () => void) => void; holds: () => boolean } {
  const [pending, setPending] = useState<Pending | null>(null);
  // While an answered way off goes on.
  const allowed = useRef(false);
  // What `holds` and `leaveFirst` read when they are called, after the render that set it.
  const holding = useRef(active);
  useLayoutEffect(() => {
    holding.current = active;
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const ask = (event: BeforeUnloadEvent) => {
      if (allowed.current) return;
      event.preventDefault();
      // Browsers that ask only when it is set.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [active]);

  const holds = useCallback(() => holding.current && !allowed.current, []);
  const leaveFirst = useCallback((goOn: () => unknown, stay?: () => void) => {
    if (holding.current && !allowed.current) setPending({ goOn, stay });
    else void goOn();
  }, []);

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
    void (async () => {
      try {
        await answered.goOn();
      } finally {
        allowed.current = false;
      }
    })();
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
