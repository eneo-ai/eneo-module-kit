/** The module's name, in the top bar and the browser tab: rename it for your module (and in index.html: the title and the noscript text). */
export const PRODUCT_NAME = "Eneo-modul";

/** A page's title in the browser tab: what it is, then the module's name, as the kit's own pages have it. */
export function documentTitle(page: string): string {
  return `${page} · ${PRODUCT_NAME}`;
}
