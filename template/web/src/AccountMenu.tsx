import { useState } from "react";
import { Avatar } from "@astryxdesign/core/Avatar";
import { DropdownMenu, DropdownMenuDivider, DropdownMenuItem, DropdownMenuRadioGroup, DropdownMenuRadioItem } from "@astryxdesign/core/DropdownMenu";
import { Item } from "@astryxdesign/core/Item";
import { Text } from "@astryxdesign/core/Text";
import { useColorMode, type ColorMode } from "@eneo-ai/module-kit";
import { signOut, type User } from "./session";

/**
 * Who is signed in, the colour mode, and signing out: one icon-only button in the top bar, which keeps the bar short
 * enough for a 320 px screen (the design system's bar never shrinks the brand beside it).
 */
export function AccountMenu({ user }: { user: User }) {
  const { mode, setMode } = useColorMode();
  const [leaving, setLeaving] = useState(false);
  const name = user.username?.trim() || user.email;
  return (
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
      <DropdownMenuItem
        label={leaving ? "Loggar ut…" : "Logga ut"}
        isDisabled={leaving}
        // The menu stays open to say that it is signing out.
        hasCloseOnSelect={false}
        onClick={() => {
          setLeaving(true);
          void signOut();
        }}
      />
    </DropdownMenu>
  );
}
