import { useState } from "react";
import { Button, type ButtonProps } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { useAnnounce, useClipboard } from "@astryxdesign/core/hooks";

/**
 * Copies `text` as plain text, and confirms it with a check in place of the copy icon and, once, "Kopierat" to a screen
 * reader. The words stay, so the button keeps its width and its neighbours stay where they are. A copy that fails (no
 * clipboard, no permission) says so in words, until the next press tries again.
 */
export function CopyButton({
  text,
  label,
  name,
  variant = "secondary",
}: {
  text: string;
  /** The visible words. */
  label: string;
  /** What the button is called when that says more than its words ("Kopiera supportinformationen"); it starts with them. */
  name?: string;
  variant?: ButtonProps["variant"];
}) {
  const { copy, isCopied } = useClipboard({ announce: "Kopierat" });
  const announce = useAnnounce();
  const [failed, setFailed] = useState(false);
  const words = failed ? "Kunde inte kopiera" : label;
  return (
    <Button
      variant={variant}
      icon={<Icon icon={isCopied && !failed ? "check" : "copy"} />}
      label={failed ? words : (name ?? label)}
      onClick={async () => {
        const copied = await copy(text);
        setFailed(!copied);
        if (!copied) announce("Det gick inte att kopiera.");
      }}
    >
      {words}
    </Button>
  );
}
