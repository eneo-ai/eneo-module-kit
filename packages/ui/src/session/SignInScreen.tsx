import { useEffect, useState, type ReactNode } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { Brand } from "../branding.js";
import { ModuleShell } from "../ModuleShell.js";
import { messages } from "./messages.js";

/**
 * The sign-in screen: one button that starts Eneo's login (the backend's `/api/auth/login`) and, when the callback
 * failed (`/?auth_error=…`), says so once. SSO only.
 */
export function SignInScreen({
  productName,
  title,
  description,
  unreachable = false,
  loginPath = "/api/auth/login",
  next,
  children,
}: {
  /** The module's name, for the bar and the landmark. */
  productName: string;
  /** The page's heading: what this module does. */
  title: ReactNode;
  /** One line under it; Eneo's own words when absent. */
  description?: ReactNode;
  /** The module's backend did not answer: the screen says so and offers to try again, instead of the login button. */
  unreachable?: boolean;
  loginPath?: string;
  /** Where the login returns to; the page the person was on when none is given. */
  next?: string;
  children?: ReactNode;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [failed, setFailed] = useState(false);

  // The callback sends a failed login to the home page with `auth_error`; it is said once and taken off the address.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (!params.has("auth_error")) return;
    setFailed(true);
    params.delete("auth_error");
    const rest = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}`);
  }, []);

  function startLogin() {
    setSubmitting(true);
    const target = next ?? `${window.location.pathname}${window.location.search}`;
    const query = target === "/" ? "" : `?next=${encodeURIComponent(target)}`;
    window.location.assign(`${loginPath}${query}`);
  }

  return (
    <ModuleShell label={productName} heading={<Brand productName={productName} />}>
      <Layout height="auto" contentWidth={640} padding={4}>
        <LayoutContent isScrollable={false}>
          <VStack gap={6} paddingBlockStart={6}>
            <VStack gap={2}>
              <Heading level={1}>{title}</Heading>
              <Text as="p" color="secondary">
                {description ?? messages.signInHint}
              </Text>
            </VStack>
            {failed && <Banner status="error" title={messages.signInFailed} collapsible={false} />}
            {unreachable && <Banner status="error" title={messages.unreachable} collapsible={false} />}
            <HStack>
              {unreachable ? (
                <Button label={messages.tryAgain} onClick={() => window.location.reload()} />
              ) : (
                <Button
                  label={submitting ? messages.signingIn : messages.signIn}
                  variant="primary"
                  isLoading={submitting}
                  onClick={startLogin}
                />
              )}
            </HStack>
            {children}
          </VStack>
        </LayoutContent>
      </Layout>
    </ModuleShell>
  );
}
