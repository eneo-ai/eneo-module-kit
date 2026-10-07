import { useCallback, useEffect, useState } from "react";
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
import { useSessionUser, useSignedOut } from "@eneo-ai/module-kit/session";
import { Frame } from "../Frame";
import { AccountMenu } from "../AccountMenu";
import { getJson } from "../session";

interface Flow {
  id: string;
  name: string;
  description: string | null;
}

type Load = { state: "loading" } | { state: "failed" } | { state: "done"; flows: Flow[] };

/**
 * The module's one page: the flows the user can run in Eneo, through the backend's proxy (/api/eneo/flows/, the one
 * route its allowlist names), and a greeting from the module's own route (/api/example).
 */
export function Flows() {
  const user = useSessionUser();
  // A dialog of the page is native, so it must be closed while the login has ended (the cover cannot reach it); what is
  // typed in it lives here, above the dialog, so it is back as it was after the new login.
  const signedOut = useSignedOut();
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [greeting, setGreeting] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => {
    setLoad({ state: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    let current = true;
    getJson<{ items: Flow[] }>("/api/eneo/flows/")
      .then((body) => current && setLoad({ state: "done", flows: body.items }))
      .catch(() => current && setLoad({ state: "failed" }));
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
    <Frame brandHref="/flows" end={<AccountMenu user={user} />}>
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
            description="Eneo svarade inte som väntat."
            collapsible={false}
            endContent={<Button label="Försök igen" variant="secondary" onClick={retry} />}
          />
        ) : load.state === "done" && load.flows.length === 0 ? (
          <EmptyState headingLevel={2} title="Det finns inga publicerade flöden som du kan använda än." description="När ett flöde publiceras i Eneo visas det här." />
        ) : load.state === "done" ? (
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
        ) : (
          <>
            <VisuallyHidden as="p" role="status">
              Laddar flödena…
            </VisuallyHidden>
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
          <TextInput label="Anteckning" value={note} onChange={setNote} />
          <HStack hAlign="end">
            <Button label="Klar" variant="primary" onClick={() => setNoting(false)} />
          </HStack>
        </VStack>
      </Dialog>
    </Frame>
  );
}
