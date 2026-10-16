import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { HStack } from "@astryxdesign/core/HStack";
import { Text } from "@astryxdesign/core/Text";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";

/** One piece of code that a page fetches when it first needs it: kept once it has arrived, so the next use has it at once. */
export interface Loader<T> {
  /** The code, if it has arrived. */
  readonly loaded: T | null;
  /**
   * Gets it. Pages that ask while it is on its way share the one request. A failure is kept too: a browser keeps a failed
   * fetch of a module per address, so asking again could not fetch it.
   */
  load(): Promise<T>;
}

/** A loader for `get` (`() => import("./Editor")`), which is called once, when a page first asks. */
export function lazyLoader<T>(get: () => Promise<T>): Loader<T> {
  let loaded: T | null = null;
  let pending: Promise<T> | null = null;
  return {
    get loaded() {
      return loaded;
    },
    load() {
      pending ??= get().then((code) => (loaded = code));
      return pending;
    },
  };
}

/**
 * The code of a loader, for a page that shows something else until it has arrived (a plain field, the text as it was
 * written). If the code cannot be fetched (a tab older than the release that replaced its files, a connection that
 * dropped) `failed` says so, and the page offers the person's own reload (`LoadFailure`): never a reload by itself, since
 * the page may hold work that is not saved, and never a retry, which could not fetch it.
 */
export function useLoaded<T>(loader: Loader<T>): { value: T | null; failed: boolean } {
  const [value, setValue] = useState<T | null>(() => loader.loaded);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (value) return;
    let current = true;
    setFailed(false);
    loader.load().then(
      // A function (a component) given to setState would be called as an update: wrapped, it is stored.
      (code) => current && setValue(() => code),
      () => current && setFailed(true),
    );
    return () => {
      current = false;
    };
  }, [loader, value]);
  return { value, failed };
}

/**
 * What a page says where code it fetches when needed could not be fetched: what happened (`children`), and one action,
 * the person's own reload, which gets the module's files as they are now. Nothing reloads by itself: the page may hold
 * work. `keeps` says what a reload gives back, only where it does.
 */
export function LoadFailure({ children, keeps, reload = () => window.location.reload() }: { children: ReactNode; keeps?: string; reload?: () => void }) {
  // Said from the next frame on, into a region there before it: a region that arrives with its words is not reliably read out.
  const [said, setSaid] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setSaid(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  const text = (
    <>
      {children}
      {keeps ? ` ${keeps}` : null}
    </>
  );
  return (
    <HStack vAlign="center" wrap="wrap" gap={2}>
      <VisuallyHidden as="p" role="status">
        {said ? text : null}
      </VisuallyHidden>
      {/* Read once, by the region above. */}
      <Text as="p" type="supporting" aria-hidden>
        {text}
      </Text>
      <Button size="sm" label="Ladda om sidan" onClick={() => reload()} />
    </HStack>
  );
}
