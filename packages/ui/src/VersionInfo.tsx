import { useEffect, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Code } from "@astryxdesign/core/Code";
import { HStack } from "@astryxdesign/core/HStack";
import { Icon } from "@astryxdesign/core/Icon";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Text } from "@astryxdesign/core/Text";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { VStack } from "@astryxdesign/core/VStack";
import { CopyButton } from "./CopyButton.js";

/** Which build runs, as the BFF's GET /api/healthz says it: each value null when it is not known. */
export interface BuildIdentity {
  /** The release the deployment names, a version tag such as v1.2.3. */
  release: string | null;
  /** The commit the image was built from. */
  revision: string | null;
  /** When the image was built, in UTC. */
  build_date: string | null;
  /** The repository the image was built from. */
  source: string | null;
}

/** How long the page waits for the answer before it says that the version could not be shown. */
const READ_DEADLINE_MS = 10_000;

/** What Kopiera supportinformation copies: plain lines to paste into a message, each value whole, and where the page runs. */
function supportText(productName: string, build: BuildIdentity, origin: string): string {
  return [
    productName,
    `Utgåva: ${build.release ?? "okänd"}`,
    `Commit: ${build.revision ?? "okänd"}`,
    `Byggd: ${build.build_date ?? "okänd"}`,
    `Källkod: ${build.source ?? "okänd"}`,
    `Adress: ${origin}`,
  ].join("\n");
}

/**
 * Which build of the module runs, for a person whom support asks: the release, the commit and when it was built, a
 * button that copies them as support details, and the release's and the commit's pages where the repository is known.
 * The page has no version of its own: the module ships as one image, so it shows what the BFF answers. The answer is
 * read when this is shown, so put it where a person opens it (a dialog, a section that unfolds), not on every page.
 */
export function VersionInfo({ productName }: { productName: string }) {
  const [build, setBuild] = useState<BuildIdentity | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    void (async () => {
      try {
        const response = await fetch("/api/healthz", { cache: "no-store", signal: AbortSignal.timeout(READ_DEADLINE_MS) });
        if (!response.ok) throw new Error(`answered ${response.status}`);
        const body = (await response.json()) as BuildIdentity;
        if (current) setBuild(body);
      } catch {
        if (current) setFailed(true);
      }
    })();
    return () => {
      current = false;
    };
  }, [attempt]);

  if (build) return <BuildDetails productName={productName} build={build} />;
  if (failed) {
    return (
      <Banner
        status="error"
        title="Versionen kunde inte visas."
        collapsible={false}
        endContent={
          <Button
            label="Försök igen"
            variant="secondary"
            onClick={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          />
        }
      />
    );
  }
  return <Text type="supporting">Hämtar versionen…</Text>;
}

function BuildDetails({ productName, build }: { productName: string; build: BuildIdentity }) {
  const { release, revision, build_date: built, source } = build;
  return (
    <VStack gap={4}>
      <MetadataList>
        <MetadataListItem label="Utgåva">{release ?? "Okänd"}</MetadataListItem>
        <MetadataListItem label="Commit">{revision ? <Code>{revision.slice(0, 7)}</Code> : "Okänd"}</MetadataListItem>
        <MetadataListItem label="Byggd">{built ? <Timestamp value={built} format="date_time" type="inherit" color="inherit" /> : "Okänd"}</MetadataListItem>
      </MetadataList>
      <HStack gap={3} wrap="wrap">
        <CopyButton text={supportText(productName, build, window.location.origin)} label="Kopiera supportinformation" />
        {source && release && <PageLink href={`${source}/releases/tag/${release}`} words="Visa utgåvan på GitHub" />}
        {source && revision && <PageLink href={`${source}/commit/${revision}`} words="Visa commiten på GitHub" />}
      </HStack>
    </VStack>
  );
}

/** A page of the repository, in a new tab, which its name says after its words. */
function PageLink({ href, words }: { href: string; words: string }) {
  return (
    <Button href={href} target="_blank" rel="noopener noreferrer" icon={<Icon icon="externalLink" />} label={`${words} i en ny flik`}>
      {words}
    </Button>
  );
}
