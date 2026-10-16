import { createDrafts } from "@eneo-ai/module-kit";

/**
 * What a person has typed and not sent, kept in this tab for that person only (the kit's createDrafts), so a reload or a
 * new login gives it back. The prefix is the module's own: rename it with the module. App.tsx clears another person's
 * drafts when someone signs in.
 */
export const drafts = createDrafts("eneo-modul");
