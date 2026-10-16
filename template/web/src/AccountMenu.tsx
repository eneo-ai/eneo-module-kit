import { useState } from "react";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { DropdownMenu, DropdownMenuDivider, DropdownMenuItem, DropdownMenuRadioGroup, DropdownMenuRadioItem } from "@astryxdesign/core/DropdownMenu";
import { Item } from "@astryxdesign/core/Item";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { useToast } from "@astryxdesign/core/Toast";
import { VStack } from "@astryxdesign/core/VStack";
import { useColorMode, VersionInfo, type ColorMode } from "@eneo-ai/module-kit";
import { useSignedOut, type SessionUser } from "@eneo-ai/module-kit/session";
import { PRODUCT_NAME } from "./config";
import { signOut } from "./session";

/**
 * Who is signed in, the colour mode, which version runs, and signing out: one icon-only button in the top bar, which
 * keeps the bar short enough for a 320 px screen (the design system's bar never shrinks the brand beside it). Signing out
 * ends the page's work: a page that holds some passes its leave question's `leaveFirst`, which asks first.
 */
export function AccountMenu({ user, leaveFirst = (goOn) => void goOn() }: { user: SessionUser; leaveFirst?: (goOn: () => unknown) => void }) {
  const { mode, setMode } = useColorMode();
  const [leaving, setLeaving] = useState(false);
  const toast = useToast();
  const name = user.username?.trim() || user.email;
  // The version dialog is native, so it is closed while the login has ended (the cover cannot reach it).
  const signedOut = useSignedOut();
  const [showingVersion, setShowingVersion] = useState(false);
  return (
    <>
      <DropdownMenu
        button={{ label: `Öppna konto för ${name}`, isIconOnly: true, variant: "ghost", icon: <Avatar name={name} size="md" tooltip={false} /> }}
        hasChevron={false}
        alignment="end"
        menuWidth="18rem"
      >
        {/* Who is signed in: words to read, not something to choose; one line each, the whole of it is in the trigger's name. */}
        <Item density="compact" label={name} labelLines={1} description={user.email && name !== user.email ? user.email : undefined} descriptionLines={1} />
        <DropdownMenuDivider />
        {/* The group is named for assistive technology; the words above it are for the eye. */}
        <Text type="supporting" aria-hidden>
          Tema
        </Text>
        <DropdownMenuRadioGroup label="Tema" value={mode} onChange={(next) => setMode(next as ColorMode)}>
          <DropdownMenuRadioItem value="light" label="Ljust" />
          <DropdownMenuRadioItem value="dark" label="Mörkt" />
          <DropdownMenuRadioItem value="system" label="System" />
        </DropdownMenuRadioGroup>
        <DropdownMenuDivider />
        <DropdownMenuItem label="Version" onClick={() => setShowingVersion(true)} />
        <DropdownMenuItem
          label={leaving ? "Loggar ut…" : "Logga ut"}
          isDisabled={leaving}
          // The menu stays open to say that it is signing out.
          hasCloseOnSelect={false}
          onClick={() =>
            leaveFirst(async () => {
              setLeaving(true);
              if (await signOut()) return;
              // Still signed in: the control is the person's to use again, the toast says what happened, and the page,
              // still here, asks again before it is left (`false`).
              setLeaving(false);
              toast({ type: "error", body: "Det gick inte att logga ut. Försök igen.", uniqueID: "sign-out-failed" });
              return false;
            })
          }
        />
      </DropdownMenu>
      <Dialog
        isOpen={showingVersion && !signedOut}
        onOpenChange={setShowingVersion}
        aria-label="Version"
        // The whole height of the screen but its gutters, as the width has: a short screen shows as much as it can.
        maxHeight="calc(100dvh - 2 * var(--spacing-4))"
      >
        {/* One region holds the title and the details, so that what does not fit a short screen scrolls as a whole. */}
        <Layout
          content={
            <LayoutContent padding={0}>
              <DialogHeader title="Version" onOpenChange={setShowingVersion} />
              <VStack padding={4}>
                <VersionInfo productName={PRODUCT_NAME} />
              </VStack>
            </LayoutContent>
          }
        />
      </Dialog>
    </>
  );
}
