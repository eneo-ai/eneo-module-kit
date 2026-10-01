/** The session screens' words, Swedish like the rest of a module's text (the module's own sentence is `signedOutNote`). */

export const messages = {
  warningTitle: "Du loggas snart ut",
  endedTitle: "Du behöver logga in igen",
  renewBefore: "Fortsätt arbeta",
  renewAfter: "Logga in igen",
  popupBlocked: "Fönstret kunde inte öppnas. Tillåt popup-fönster för den här sidan och försök igen.",
  loading: "Laddar",
  signInHint: "Logga in via Eneo för att fortsätta.",
  signIn: "Logga in med Eneo",
  signingIn: "Öppnar Eneo…",
  signInFailed: "Inloggningen kunde inte slutföras. Försök igen.",
  unreachable: "Kunde inte kontakta modulen. Försök igen.",
  tryAgain: "Försök igen",
  signedInAgainTitle: "Du är inloggad igen",
  signedInAgainHint: "Du kan stänga det här fönstret och fortsätta där du var.",
  wrongUserTitle: "Du loggade in som en annan användare",
  endedAlreadyTitle: "Inloggningen har redan gått ut",
  endedAlreadyHint:
    "Stäng fönstret. Om det finns osparat arbete i den andra fliken: spara det innan du loggar in igen. Uppgifter och ändringar som inte är sparade behöver fyllas i igen.",
} as const;

/** The words under the title of the warning and of the sign-in dialog. */
export function sessionDialogText(input: {
  ended: boolean;
  /** "13:45": when the login ends. */
  time: string;
  /** Someone else is signed in; `ownerName` is the one to sign in as. */
  otherName: string | null;
  ownerName: string | null;
  /** What this module promises stays when the login ended (a recording that goes on, say). */
  note?: string;
}): string {
  const action = input.ended ? messages.renewAfter : messages.renewBefore;
  const first =
    input.otherName && input.ownerName
      ? `Du är inloggad som ${input.otherName}. Logga in som ${input.ownerName} för att fortsätta. `
      : input.ended
        ? "Inloggningen har upphört. "
        : `Inloggningen upphör kl. ${input.time}. `;
  const last = input.ended
    ? input.note
      ? `Allt på den här sidan finns kvar, och ${input.note}`
      : "Allt på den här sidan finns kvar."
    : "Allt på den här sidan finns kvar.";
  return `${first}${action} loggar in dig igen i ett nytt fönster. ${last}`;
}

export function wrongUserText(name: string | null): string {
  return `Stäng fönstret och logga in som ${name ?? "den som arbetar på sidan"} för att fortsätta.`;
}
