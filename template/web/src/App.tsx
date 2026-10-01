import { Navigate, Route, Routes } from "react-router";
import { Flows } from "./pages/Flows";
import { SignIn } from "./pages/SignIn";
import { RequireSession } from "./RequireSession";

/** The module's pages. Add yours as routes; a page that needs a session goes inside RequireSession. */
export function App() {
  return (
    <Routes>
      <Route path="/" element={<SignIn />} />
      <Route path="/flows" element={<RequireSession>{(user) => <Flows user={user} />}</RequireSession>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
