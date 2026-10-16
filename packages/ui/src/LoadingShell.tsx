import { Center } from "@astryxdesign/core/Center";
import { Spinner } from "@astryxdesign/core/Spinner";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { Brand } from "./branding.js";
import { ModuleShell } from "./ModuleShell.js";

/**
 * The page while it waits: the bar, a heading that names the module, and a spinner that says so. The session's gate shows
 * it until the login has answered, and a router while a page's code arrives, so no frame is without the bar. Most answers
 * come within a moment: the spinner shows only after it (`eneo-wait` in base.css), so a quick one leaves no blink of it.
 */
export function LoadingShell({ productName }: { productName: string }) {
  return (
    <ModuleShell label={productName} heading={<Brand productName={productName} />}>
      <VisuallyHidden as="h1">{productName}</VisuallyHidden>
      <Center minHeight="60dvh" className="eneo-wait">
        <Spinner size="lg" aria-label="Laddar" />
      </Center>
    </ModuleShell>
  );
}
