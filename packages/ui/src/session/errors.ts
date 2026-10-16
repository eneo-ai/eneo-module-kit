import { RequestTimeoutError, SessionExpiredError } from "./request.js";

/** What a failed request means to the person: a plain Swedish sentence with the way on, and whether trying again can help. */
export interface ErrorAdvice {
  message: string;
  /** Trying the same again can help: the network, a busy or failing server, a login that has been renewed since. */
  retry: boolean;
}

const ASK_ENEO_OWNER = "Kontakta den som ansvarar för Eneo i din verksamhet";
const ASK_OWNER = "Kontakta den som ansvarar för tjänsten om det fortsätter.";

// The sentence for a status the backend answered with, and whether trying again can help.
const STATUSES: Record<number, ErrorAdvice> = {
  // The module's own login's end is never a status here (fetchWithSession fails with SessionExpiredError): this is Eneo's.
  401: { message: `Tjänsten har inte behörighet till det här. ${ASK_ENEO_OWNER}.`, retry: false },
  403: { message: `Du har inte behörighet till det här. ${ASK_ENEO_OWNER} om du behöver det.`, retry: false },
  404: { message: "Det du letade efter finns inte längre.", retry: false },
  408: { message: "Svaret dröjde för länge. Försök igen om en stund.", retry: true },
  413: { message: "Det som skickades är större än tjänsten tar emot.", retry: false },
  415: { message: "Filtypen stöds inte.", retry: false },
  429: { message: "Det är många förfrågningar just nu. Försök igen om en stund.", retry: true },
  502: { message: "Servern kunde inte nås just nu. Försök igen om en stund.", retry: true },
  503: { message: "Servern kunde inte nås just nu. Försök igen om en stund.", retry: true },
  504: { message: "Servern svarade inte i tid. Försök igen om en stund.", retry: true },
};

// "Failed to fetch" in Chromium, "NetworkError when attempting to fetch resource." in Firefox, "Load failed" in Safari.
function looksLikeNetworkError(message: string): boolean {
  const m = message.toLowerCase();
  return m.includes("failed to fetch") || m.includes("network") || m.includes("load failed");
}

/**
 * The one owner of what a failed request says to the person, for the errors the session client fails with and an error
 * that carries the status the backend answered (`{ status }`: a module's own error class, or a `Response`). What the
 * browser or the backend said in English is never shown: it is for the console. Nothing that tells what it was rules out
 * that trying again helps, so an unknown failure offers it.
 */
export function errorAdvice(error: unknown): ErrorAdvice {
  if (error instanceof SessionExpiredError) return { message: "Inloggningen hade gått ut och det här skickades inte. Försök igen.", retry: true };
  if (error instanceof RequestTimeoutError) return { message: error.message, retry: true };
  const status = (error as { status?: unknown } | null)?.status;
  if (typeof status === "number" && status >= 400) {
    if (STATUSES[status]) return STATUSES[status];
    if (status >= 500) return { message: "Tjänsten svarade med ett fel. Försök igen om en stund.", retry: true };
    return { message: `Det gick inte att genomföra. ${ASK_OWNER}`, retry: false };
  }
  if (error instanceof TypeError && looksLikeNetworkError(error.message)) {
    return { message: "Anslutningen avbröts. Kontrollera nätverket och försök igen.", retry: true };
  }
  return { message: `Ett okänt fel uppstod. Försök igen. ${ASK_OWNER}`, retry: true };
}
