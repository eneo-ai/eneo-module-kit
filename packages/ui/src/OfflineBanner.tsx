import { Banner } from "@astryxdesign/core/Banner";
import { onlineStatus, useConnection, type OnlineStatus } from "./online-status.js";

/**
 * Says that the device has no network, or that the module does not answer, and neither blames the other. Nothing, and no
 * room taken, while the page is online. A notice for the whole page: put it in the shell's `banner` (above the bar). It is
 * the design system's warning banner, an alert, mounted when the connection goes, so a screen reader says it once.
 */
export function OfflineBanner({
  productName,
  message,
  status = onlineStatus,
}: {
  /** The module's name, for "… svarar inte just nu." */
  productName: string;
  /** What the page adds after the cause: what waits, and when it goes on ("Det du har skrivit finns kvar."). */
  message?: string;
  /** For tests; the page's own is the one its requests report to. */
  status?: OnlineStatus;
}) {
  const connection = useConnection(status);
  if (connection === "online") return null;
  const cause = connection === "offline" ? "Ingen anslutning." : `${productName} svarar inte just nu.`;
  return <Banner status="warning" container="section" title={message ? `${cause} ${message}` : cause} />;
}
