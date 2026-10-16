import { useEffect } from "react";
import { useBlocker } from "react-router";
import { useLeaveQuestion } from "@eneo-ai/module-kit";

/**
 * While `active`, leaving the page asks first, in the page's own dialog (the kit's useLeaveQuestion, whose `question` the
 * page renders): for every departure the router sees (a link, the brand, Back and Forward), which its blocker holds, and
 * through `leaveFirst` for an action that ends the page's work without a navigation (signing out). A change of the
 * address that keeps the path (a page that writes `?run=`) is no departure. The browser's own question covers what no
 * navigation of the app reaches: a reload, a closed tab. `isActive` reads where the work is kept, when one of them asks.
 */
export function useLeaveGuard(active: boolean, warning: string, isActive?: () => boolean) {
  const leaving = useLeaveQuestion(active, warning, isActive);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => leaving.holds() && currentLocation.pathname !== nextLocation.pathname);
  const { leaveFirst } = leaving;
  useEffect(() => {
    if (blocker.state === "blocked") leaveFirst(blocker.proceed, blocker.reset);
  }, [blocker, leaveFirst]);
  return leaving;
}
