import { useEffect, useState } from "react";
import { Heading } from "@astryxdesign/core/Heading";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { messages, wrongUserText } from "./messages.js";
import type { SessionStatus } from "./types.js";
import { userDisplayName } from "./user.js";

/** Where a login that is shared between a module's windows and tabs is announced: every tab of the module listens. */
export const SESSION_CHANNEL = "eneo-module:session";

/** Why the backend refused a renewal (`?fel=`); the page's own login stays as it was. */
export type Refusal = "annan-anvandare" | "utgangen";

/** The refusal an address carries (`?fel=annan-anvandare` or `?fel=utgangen`), or null. */
export function refusalOf(search: string): Refusal | null {
  const fel = new URLSearchParams(search).get("fel");
  return fel === "annan-anvandare" || fel === "utgangen" ? fel : null;
}

const TITLE: Record<Refusal | "ok", string> = {
  ok: messages.signedInAgainTitle,
  "annan-anvandare": messages.wrongUserTitle,
  utgangen: messages.endedAlreadyTitle,
};

/**
 * Where a login renewed in its own window lands ("Fortsätt arbeta" before the session ends): it tells the module's
 * tabs, which read the new end, and closes itself. A refused renewal says why and stays: `annan-anvandare` when it
 * signed in someone else, `utgangen` when the login had already ended, so there was no user left to renew. A popup
 * window: no top bar and no account menu, so the page's own main region and one readable column. Route it at the
 * `signedInAgainPath` that `RequireSession` is given.
 */
export function SignedInAgain({ productName, refusal = refusalOf(window.location.search) }: { productName: string; refusal?: Refusal | null }) {
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    document.title = `${TITLE[refusal ?? "ok"]} · ${productName}`;
  }, [refusal, productName]);

  useEffect(() => {
    if (refusal === "annan-anvandare") {
      // The page's own login is still the one in the cookie: its user is the one to sign in as.
      fetch("/api/auth/status", { credentials: "include" })
        .then((res) => res.json() as Promise<SessionStatus>)
        .then((s) => s.user && setName(userDisplayName(s.user)), () => undefined);
      return;
    }
    if (refusal) return;
    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(SESSION_CHANNEL);
      channel.postMessage("signed-in");
      channel.close();
    }
    window.close();
  }, [refusal]);

  return (
    <Layout height="auto" contentWidth={640}>
      <LayoutContent role="main" padding={6} isScrollable={false}>
        <VStack gap={3} hAlign="start">
          <Heading level={1}>{TITLE[refusal ?? "ok"]}</Heading>
          <Text as="p" color="secondary">
            {refusal === "annan-anvandare" ? wrongUserText(name) : refusal === "utgangen" ? messages.endedAlreadyHint : messages.signedInAgainHint}
          </Text>
        </VStack>
      </LayoutContent>
    </Layout>
  );
}
