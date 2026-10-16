import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Heading, Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { List, ListItem } from "@astryxdesign/core/List";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { HStack } from "@astryxdesign/core/HStack";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { VStack } from "@astryxdesign/core/VStack";
import { SlowWait, useRouteReady } from "@eneo-ai/module-kit";
import { errorAdvice, useSessionUser, useSignedOut, type ErrorAdvice } from "@eneo-ai/module-kit/session";
import { Frame } from "../Frame";
import { AccountMenu } from "../AccountMenu";
import { drafts } from "../drafts";
import { useLeaveGuard } from "../leave";
import { getJson } from "../session";

interface Flow {
  id: string;
  name: string;
  description: string | null;
}

type Load = { state: "loading" } | { state: "failed"; advice: ErrorAdvice } | { state: "done"; flows: Flow[]; truncated: boolean };

/** The note's draft, and the shape it is read in. */
const NOTE = "anteckning";
const isText = (value: unknown): value is string => typeof value === "string";
const UNSTORED = "Det du har skrivit kunde inte sparas i webbläsaren och försvinner om du lämnar sidan.";

/** One page of Eneo's list: at most this many flows, and `has_more` says whether another page follows. */
const PAGE_SIZE = 200;
// ponytail: 1 000 flows is far more than a person runs; the page says where it stops, raise the cap if that ever shows.
const PAGE_CAP = 5;

/** Every published flow the user can run, page by page until Eneo has no more, or the cap (`truncated`). */
async function discoverFlows(): Promise<{ flows: Flow[]; truncated: boolean }> {
  const flows: Flow[] = [];
  for (let page = 0; page < PAGE_CAP; page += 1) {
    const query = new URLSearchParams({ published_only: "true", limit: String(PAGE_SIZE), offset: String(flows.length) });
    const body = await getJson<{ items: Flow[]; has_more: boolean }>(`/api/eneo/flows/?${query}`);
    flows.push(...body.items);
    if (!body.has_more) return { flows, truncated: false };
  }
  return { flows, truncated: true };
}

/**
 * The module's one page: the flows the user can run in Eneo, through the backend's proxy (/api/eneo/flows/, the one
 * route its allowlist names), read page by page, and a greeting from the module's own route (/api/example).
 */
export function Flows() {
  const user = useSessionUser();
  // A dialog of the page is native, so it must be closed while the login has ended (the cover cannot reach it); what is
  // typed in it lives here, above the dialog, so it is back as it was after the new login, and is kept as the person's
  // draft in this tab, so it is back after a reload too.
  const signedOut = useSignedOut();
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState(() => drafts.read(user.id, NOTE, isText) ?? "");
  const write = (next: string) => {
    setNote(next);
    if (next) drafts.write(user.id, NOTE, next);
    else drafts.clear(user.id, NOTE);
  };
  // What the browser could not keep is the page's alone: leaving asks first (a link, Back, a reload, signing out).
  const unstored = useSyncExternalStore(drafts.subscribe, drafts.unstored);
  const leaving = useLeaveGuard(unstored, UNSTORED, drafts.unstored);
  // Left: what the browser could not keep is gone with the page.
  useEffect(() => () => drafts.forget(), []);
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [greeting, setGreeting] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => {
    setLoad({ state: "loading" });
    setAttempt((n) => n + 1);
  }, []);
  // The page has its content once the list has answered: a navigation to it is said and focused then (RouteEffects).
  useRouteReady(load.state !== "loading");

  useEffect(() => {
    let current = true;
    discoverFlows()
      .then(({ flows, truncated }) => current && setLoad({ state: "done", flows, truncated }))
      // What went wrong, in words, and whether trying again can help (the kit's errorAdvice).
      .catch((error) => current && setLoad({ state: "failed", advice: errorAdvice(error) }));
    return () => {
      current = false;
    };
  }, [attempt]);

  useEffect(() => {
    let current = true;
    getJson<{ greeting: string }>("/api/example")
      .then((body) => current && setGreeting(body.greeting))
      .catch(() => current && setGreeting(null));
    return () => {
      current = false;
    };
  }, []);

  return (
    <Frame brandHref="/flows" end={<AccountMenu user={user} leaveFirst={leaving.leaveFirst} />}>
      <VStack gap={6} paddingBlockStart={4}>
        <VStack gap={1}>
          <Heading level={1}>Välj ett flöde</Heading>
          <Text as="p" color="secondary">
            {greeting ?? `Inloggad som ${user.username ?? user.email}.`}
          </Text>
          <HStack>
            <Button label="Anteckning" onClick={() => setNoting(true)} />
          </HStack>
        </VStack>
        {load.state === "failed" ? (
          <Banner
            status="error"
            title="Flödena kunde inte visas."
            description={load.advice.message}
            collapsible={false}
            endContent={load.advice.retry ? <Button label="Försök igen" variant="secondary" onClick={retry} /> : undefined}
          />
        ) : load.state === "done" && load.flows.length === 0 ? (
          <EmptyState headingLevel={2} title="Det finns inga publicerade flöden som du kan använda än." description="När ett flöde publiceras i Eneo visas det här." />
        ) : load.state === "done" ? (
          <>
            <List hasDividers aria-label="Flöden">
              {load.flows.map((flow) => (
                // Nodes, not strings: a string is cut to one line with an ellipsis, and a name is never cut.
                <ListItem
                  key={flow.id}
                  label={<Text weight="semibold">{flow.name}</Text>}
                  description={flow.description ? <Text type="supporting">{flow.description}</Text> : undefined}
                />
              ))}
            </List>
            {load.truncated && (
              <Text as="p" type="supporting">
                Visar de första {(PAGE_SIZE * PAGE_CAP).toLocaleString("sv-SE")} flödena.
              </Text>
            )}
          </>
        ) : (
          <>
            <VisuallyHidden as="p" role="status">
              Laddar flödena…
            </VisuallyHidden>
            {/* After 15 seconds without an answer: that it takes longer than usual, and Försök igen. */}
            <SlowWait onRetry={retry} />
            <List hasDividers aria-hidden>
              {[0, 1, 2].map((row) => (
                <ListItem key={row} label={<Skeleton width="50%" height={16} index={row} />} description={<Skeleton width="80%" height={14} index={row} />} />
              ))}
            </List>
          </>
        )}
      </VStack>
      <Dialog isOpen={noting && !signedOut} onOpenChange={setNoting} purpose="form" aria-label="Anteckning">
        <DialogHeader title="Anteckning" onOpenChange={setNoting} />
        <VStack gap={3} padding={4}>
          <TextInput label="Anteckning" value={note} onChange={write} />
          <HStack hAlign="end">
            <Button label="Klar" variant="primary" onClick={() => setNoting(false)} />
          </HStack>
        </VStack>
      </Dialog>
      {leaving.question}
    </Frame>
  );
}
