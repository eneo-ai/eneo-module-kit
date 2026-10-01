import type { ReactNode } from "react";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Frame } from "./Frame";
import { SignIn } from "./pages/SignIn";
import { useSession, type User } from "./session";

/** A page that needs a session: it waits for the answer, shows the sign-in page without one, and the page with one. */
export function RequireSession({ children }: { children: (user: User) => ReactNode }) {
  const session = useSession();
  if (session.state === "loading") {
    return (
      <Frame>
        <Spinner size="lg" aria-label="Laddar" />
      </Frame>
    );
  }
  if (session.state === "signed-out") return <SignIn />;
  return <>{children(session.user)}</>;
}
