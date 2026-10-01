import { useCallback, useEffect, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Heading, Text } from "@astryxdesign/core/Text";
import { List, ListItem } from "@astryxdesign/core/List";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { VStack } from "@astryxdesign/core/VStack";
import { Frame } from "../Frame";
import { ApiError, getJson, signOut, type User } from "../session";

interface Flow {
  id: string;
  name: string;
  description: string | null;
}

type Load = { state: "loading" } | { state: "failed" } | { state: "ended" } | { state: "done"; flows: Flow[] };

/**
 * The module's one page: the flows the user can run in Eneo, through the backend's proxy (/api/eneo/flows/, the one
 * route its allowlist names), and a greeting from the module's own route (/api/example).
 */
export function Flows({ user }: { user: User }) {
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
      .catch((error) => current && setLoad(error instanceof ApiError && error.status === 401 ? { state: "ended" } : { state: "failed" }));
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

  // The login ended while the page was open: back to the sign-in page, which returns here afterwards.
  useEffect(() => {
    if (load.state === "ended") window.location.assign("/api/auth/login?next=%2Fflows");
  }, [load.state]);

  return (
    <Frame brandHref="/flows" end={<Button label="Logga ut" variant="secondary" onClick={() => void signOut()} />}>
      <VStack gap={6} paddingBlockStart={4}>
        <VStack gap={1}>
          <Heading level={1}>Välj ett flöde</Heading>
          <Text as="p" color="secondary">
            {greeting ?? `Inloggad som ${user.username ?? user.email}.`}
          </Text>
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
    </Frame>
  );
}
