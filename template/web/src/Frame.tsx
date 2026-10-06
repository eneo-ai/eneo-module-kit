import type { ReactNode } from "react";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { Brand, ModuleShell } from "@eneo-ai/module-kit";
import { PRODUCT_NAME } from "./config";

/**
 * Every page of the module: the shell (top bar, skip link, the one main region) and the page's width. A page renders no
 * <main> of its own, and caps its content here: a stack stretches its children to the window's whole width.
 */
export function Frame({ brandHref, end, children }: { brandHref?: string; end?: ReactNode; children: ReactNode }) {
  return (
    <ModuleShell label={PRODUCT_NAME} heading={<Brand productName={PRODUCT_NAME} href={brandHref} />} end={end}>
      <Layout height="auto" contentWidth={960} padding={4}>
        <LayoutContent isScrollable={false}>{children}</LayoutContent>
      </Layout>
    </ModuleShell>
  );
}
