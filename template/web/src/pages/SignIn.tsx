import type { AnchorHTMLAttributes } from "react";
import { useLocation } from "react-router";
import { Button } from "@astryxdesign/core/Button";
import { Heading, Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { HStack } from "@astryxdesign/core/HStack";
import { Frame } from "../Frame";
import { PRODUCT_NAME } from "../config";

// Signing in leaves the app for Eneo's login: a plain link, not the router's.
const Anchor = (props: AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props} />;

/** The page without a session. Signing in returns to where the person was (`next` is a path of this module). */
export function SignIn() {
  const { pathname } = useLocation();
  const next = pathname === "/" ? "/flows" : pathname;
  return (
    <Frame>
      <VStack gap={4} paddingBlockStart={4}>
        <Heading level={1}>{PRODUCT_NAME}</Heading>
        <Text as="p">Logga in med ditt Eneo-konto för att fortsätta.</Text>
        <HStack>
          <Button as={Anchor} href={`/api/auth/login?next=${encodeURIComponent(next)}`} label="Logga in med Eneo" variant="primary" size="lg" />
        </HStack>
      </VStack>
    </Frame>
  );
}
