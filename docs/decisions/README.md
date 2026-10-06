# Decisions

Purpose: list the decisions behind the kit, one short page each.
Read this when: you want to know why something is the way it is, or before you change it.
Related: [docs index](../README.md), [design.md](../design.md) (the long form of K1 to K12), [architecture](../architecture.md).

One decision per page: status, context, decision, consequences. The numbers K1 to K12 are those of [design.md](../design.md) section 3, which keeps the full text and the module contract with Eneo; K13 and K14 were added later. A new decision gets the next number. A decision that changes is superseded by a new page, and the old page says so.

| ID | Decision | Built? |
|---|---|---|
| [K1](k01-one-repository-three-parts.md) | One repository, three parts | Partly built |
| [K2](k02-one-stack.md) | One stack | Partly built |
| [K3](k03-fastapi-not-hono.md) | FastAPI, not Hono | Built |
| [K4](k04-static-ui-served-by-the-bff.md) | The UI is a static app served by the BFF | Partly built |
| [K5](k05-sso-only.md) | SSO only | Built |
| [K6](k06-deny-by-default.md) | Deny by default | Built |
| [K7](k07-primitives-for-uploads-and-files.md) | Primitives, not routes, for uploads and files | Built |
| [K8](k08-application-factory.md) | An application factory | Built |
| [K9](k09-colour-mode-in-the-ui-package.md) | Colour mode is the UI package's own | Planned |
| [K10](k10-branding-without-templating.md) | Branding without templating | Partly built |
| [K11](k11-astryx-pinned.md) | Astryx is pinned to an exact version | Planned |
| [K12](k12-agent-setup.md) | For agents: AGENTS.md, the pinned Astryx CLI, and the UI package as an Astryx integration | Partly built |
| [K13](k13-httpx2.md) | The HTTP client is httpx2, not httpx | Built |
| [K14](k14-body-limits-and-stream-cap.md) | Body limits and a cap on streaming files | Built |
| [K15](k15-heavy-io-admission.md) | Shared admission and upload reception deadlines | Built |

"Built" means the code is in the repository and tested. "Planned" means the part it concerns (`packages/ui`, `template/`) is not in the repository yet. "Partly built" means the part in `packages/bff` is built and the rest is planned.
