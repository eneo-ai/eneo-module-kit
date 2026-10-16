/** Where drafts are kept: the tab's sessionStorage, or a stand-in for a test. */
export type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;

export interface Drafts {
  /**
   * The person's draft `name` in the shape its reader needs, or null. The storage holds what an earlier page wrote, which
   * may be of an older shape or not a draft at all: `isDraft` is the reader's own check. A draft that fails it, or is not
   * JSON, is removed and counts as none, so it does not fail again at the next reload.
   */
  read<T>(ownerId: string, name: string, isDraft: (value: unknown) => value is T): T | null;
  /** Keeps it. False when it could not be kept: the page alone holds what was typed, and `unstored()` says so. */
  write(ownerId: string, name: string, value: unknown): boolean;
  /** Sent, saved or thrown away: it goes. */
  clear(ownerId: string, name: string): void;
  /** Someone signed in here: every other person's drafts go (`RequireSession`'s `onIdentity`). */
  keepOnly(ownerId: string): void;
  /** Whether typed work is kept nowhere but the page, which leaving would lose: a write the storage refused. */
  unstored(): boolean;
  /** Heard when `unstored()` changes. */
  subscribe(listener: () => void): () => void;
  /** The page that held what could not be kept is gone, and that with it. */
  forget(): void;
}

/** The tab's sessionStorage, or null where the page may not use it. */
function tabStorage(): DraftStorage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * What someone has typed but not yet sent, kept per person in this tab, under keys that start with `prefix` (the
 * module's own: `"min-modul"`), so a reload after a lost login, or a tab the browser put to sleep, gives it back. Only to
 * the same person: someone else signing in here clears the others' drafts (`keepOnly`). In the tab's sessionStorage, not
 * localStorage: a shared computer keeps nothing of it once the tab is closed. Create one per module and share it.
 */
export function createDrafts(prefix: string, storage: DraftStorage | null = tabStorage()): Drafts {
  const key = (ownerId: string, name: string) => `${prefix}:${ownerId}:${name}`;
  // Drafts this page could not keep, by key, until they are stored, sent or thrown away.
  const unkept = new Set<string>();
  const listeners = new Set<() => void>();
  const keep = (draft: string, kept: boolean) => {
    const before = unkept.size > 0;
    if (kept) unkept.delete(draft);
    else unkept.add(draft);
    if (before !== unkept.size > 0) listeners.forEach((listener) => listener());
  };

  return {
    read(ownerId, name, isDraft) {
      try {
        const raw = storage?.getItem(key(ownerId, name));
        if (!storage || !raw) return null;
        try {
          const value: unknown = JSON.parse(raw);
          if (isDraft(value)) return value;
        } catch {
          // Not JSON.
        }
        storage.removeItem(key(ownerId, name));
        return null;
      } catch {
        return null;
      }
    },
    write(ownerId, name, value) {
      let kept = false;
      try {
        if (storage) {
          storage.setItem(key(ownerId, name), JSON.stringify(value));
          kept = true;
        }
      } catch {
        // A full or refused storage.
      }
      keep(key(ownerId, name), kept);
      return kept;
    },
    clear(ownerId, name) {
      keep(key(ownerId, name), true);
      try {
        storage?.removeItem(key(ownerId, name));
      } catch {
        // Nothing kept, nothing to clear.
      }
    },
    keepOnly(ownerId) {
      try {
        if (!storage) return;
        for (let index = storage.length - 1; index >= 0; index -= 1) {
          const name = storage.key(index);
          if (name?.startsWith(`${prefix}:`) && !name.startsWith(`${prefix}:${ownerId}:`)) storage.removeItem(name);
        }
      } catch {
        // A refused storage holds nothing.
      }
    },
    unstored: () => unkept.size > 0,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    forget() {
      if (unkept.size === 0) return;
      unkept.clear();
      listeners.forEach((listener) => listener());
    },
  };
}
