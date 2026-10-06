import { Navigate, Route, Routes } from "react-router";
import { RequireSession, SignInScreen, SignedInAgain } from "@eneo-ai/module-kit/session";
import { PRODUCT_NAME } from "./config";
import { Flows } from "./pages/Flows";

const SIGN_IN_TEXT = "Logga in med ditt Eneo-konto för att fortsätta.";

/**
 * The module's pages. Add yours as routes; a page that needs a session goes inside RequireSession, which shows the
 * sign-in screen without one, keeps the login, and covers the page with a dialog that asks for a new login in place
 * when it ends. `/inloggad` is where a login in a window of its own ends: it tells this module's tabs and closes itself.
 */
export function App() {
  return (
    <Routes>
      <Route path="/" element={<SignInScreen productName={PRODUCT_NAME} title={PRODUCT_NAME} description={SIGN_IN_TEXT} next="/flows" />} />
      <Route path="/inloggad" element={<SignedInAgain productName={PRODUCT_NAME} />} />
      <Route
        path="/flows"
        element={
          <RequireSession productName={PRODUCT_NAME} signInTitle={PRODUCT_NAME} signInDescription={SIGN_IN_TEXT}>
            <Flows />
          </RequireSession>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
