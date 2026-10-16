import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { HStack } from "@astryxdesign/core/HStack";
import { Text } from "@astryxdesign/core/Text";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { VStack } from "@astryxdesign/core/VStack";

/** How long a wait with no answer goes on before the page says so and offers a way on. */
const SLOW_WAIT_MS = 15_000;

/**
 * What a page shows beside a wait that has no end in sight (a list, a document being read): nothing while it is short,
 * then, once it has lasted 15 seconds since this was mounted, that it takes longer than usual and the ways on: trying
 * again, and what the page passes as `children` (a way back). Trying again keeps the button where it was and judges the
 * wait afresh.
 */
export function SlowWait({ onRetry, children }: { onRetry: () => void; children?: ReactNode }) {
  const [stage, setStage] = useState<"quiet" | "slow" | "retrying">("quiet");
  const [round, setRound] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => setStage("slow"), SLOW_WAIT_MS);
    return () => clearTimeout(timer);
  }, [round]);
  const said = stage === "quiet" ? "" : stage === "slow" ? "Det tar längre tid än vanligt." : "Försöker igen.";
  return (
    <>
      {/* There from the start, empty: a region that arrives with its words is not reliably read out. */}
      <VisuallyHidden as="p" role="status">
        {said}
      </VisuallyHidden>
      {stage !== "quiet" && (
        <VStack gap={3}>
          {/* Read once, by the region above. */}
          <Text as="p" aria-hidden>
            {said}
          </Text>
          <HStack gap={3} wrap="wrap">
            <Button
              label="Försök igen"
              variant="primary"
              onClick={() => {
                setStage("retrying");
                setRound((n) => n + 1);
                onRetry();
              }}
            />
            {children}
          </HStack>
        </VStack>
      )}
    </>
  );
}
