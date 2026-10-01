import { createContext, useContext, useEffect, useState, type ComponentProps, type ReactNode } from "react";
import { Divider } from "@astryxdesign/core/Divider";
import { HStack } from "@astryxdesign/core/HStack";
import { Text } from "@astryxdesign/core/Text";
import { TopNavHeading } from "@astryxdesign/core/TopNav";

/** What GET /api/branding answers: the organisation beside the product's name, or none. */
export interface Branding {
  organization: {
    name: string;
    /** "default": the module's bundled logo; "custom": the deployment's own, served by /api/branding/logo/{light,dark}; none: the name as text. */
    logo: "default" | "custom" | null;
    /** A custom logo comes in two files, one for each colour mode. */
    dark_logo: boolean;
  } | null;
}

/** How long the page waits for the optional branding before it shows the product name alone. */
export const BRANDING_DEADLINE_MS = 2_000;

type Organization = NonNullable<Branding["organization"]>;

interface BrandingState {
  /** Null until the answer, and after an answer that is none. */
  organization: Organization | null;
  defaultLogo?: string;
}

const BrandingContext = createContext<BrandingState>({ organization: null });

/**
 * The deployment's branding, asked of the module's backend once, when the app starts. It is optional, so a backend
 * that is slow, refuses or fails must not hold the page: the read has one deadline, and without an answer the lockup
 * is the product name alone (design K10). Until it has answered nothing of an organisation is shown, so no page
 * shows one municipality's mark before another's.
 */
export function BrandingProvider({
  children,
  defaultLogo,
  deadlineMs = BRANDING_DEADLINE_MS,
  fetchImpl,
}: {
  children: ReactNode;
  /** The module's own copy of the bundled logo, for an organisation whose `logo` is "default". Without it, that organisation is its name as text. */
  defaultLogo?: string;
  deadlineMs?: number;
  /** For tests. */
  fetchImpl?: typeof fetch;
}) {
  const [organization, setOrganization] = useState<Organization | null>(null);
  useEffect(() => {
    let current = true;
    const get = fetchImpl ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
    (async () => {
      try {
        const response = await get("/api/branding", { cache: "no-store", signal: AbortSignal.timeout(deadlineMs) });
        if (!response.ok) throw new Error(`answered ${response.status}`);
        const body = (await response.json()) as Branding;
        if (current) setOrganization(body.organization ?? null);
      } catch (error) {
        console.error(`GET /api/branding failed (${String(error)}); the header shows the product name alone.`);
      }
    })();
    return () => {
      current = false;
    };
    // Once: the answer is the deployment's, and does not change while the page is open.
  }, []);
  return <BrandingContext.Provider value={{ organization, defaultLogo }}>{children}</BrandingContext.Provider>;
}

/**
 * The organisation's mark: its logo (a plain <img>, same-origin), or its name as text. Sizing and the colour mode's
 * choice of logo are base.css's, by data-brand-logo: default is the bundled mark, light and dark are an organisation's
 * two logos, plain one logo that serves both modes, name no logo at all.
 */
function OrganizationMark({ organization, defaultLogo }: { organization: Organization; defaultLogo?: string }) {
  const { name, logo, dark_logo: darkLogo } = organization;
  if (logo === "default" && defaultLogo) {
    return <img src={defaultLogo} alt={name} data-brand-logo="default" />;
  }
  if (logo === "custom") {
    return (
      <>
        <img src="/api/branding/logo/light" alt={name} data-brand-logo={darkLogo ? "light" : "plain"} />
        {darkLogo && <img src="/api/branding/logo/dark" alt={name} data-brand-logo="dark" />}
      </>
    );
  }
  return (
    <Text weight="semibold" data-brand-logo="name">
      {name}
    </Text>
  );
}

/**
 * The header lockup: the organisation's mark, a divider and the product's name; without an organisation the product's
 * name alone. With `href` it is a link (through the app's link component, see ModuleProviders), named for both.
 */
export function Brand({
  productName,
  href,
  onClickCapture,
}: {
  /** The module's name: the page's own, never the kit's. */
  productName: string;
  /** Where the lockup goes; leave it out for one that goes nowhere (the sign-in page). */
  href?: string;
  /** Asked before the link leaves the page; call preventDefault to stay. */
  onClickCapture?: ComponentProps<typeof TopNavHeading>["onClickCapture"];
}) {
  const { organization, defaultLogo } = useContext(BrandingContext);
  const mark = organization && (
    <HStack gap={4} vAlign="center">
      <OrganizationMark organization={organization} defaultLogo={defaultLogo} />
      {/* A vertical rule takes the height of a box that has one; it is decoration. */}
      <HStack height="2rem" aria-hidden>
        <Divider orientation="vertical" variant="strong" />
      </HStack>
    </HStack>
  );
  return (
    <TopNavHeading
      logo={mark}
      heading={productName}
      headingHref={href}
      // A link says where it goes and for whom; a lockup that goes nowhere is just words.
      aria-label={href ? (organization ? `${productName} – ${organization.name}` : productName) : undefined}
      onClickCapture={onClickCapture}
    />
  );
}
