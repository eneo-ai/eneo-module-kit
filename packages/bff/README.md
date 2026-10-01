# eneo-module-bff

The Eneo module contract for a FastAPI BFF: the login handoff, a server-side session with token refresh, a
deny-by-default proxy to Eneo, upload forwarding and signed-file streaming, security headers and the built UI.
It is the security boundary between a browser and Eneo, so it holds no module-specific route.

```python
# main.py
from pathlib import Path

from eneo_module_bff import RESOURCE_ID, create_app, rule

app = create_app(
    title="My module",
    proxy_rules=[
        rule("GET", r"flows/$"),
        rule({"GET", "POST"}, rf"flows/{RESOURCE_ID}/runs/$"),
    ],
    static_dir=Path(__file__).parent / "web" / "dist",
)

# Run it: python -c "from eneo_module_bff import serve; serve('main:app')"
```

The proxy exposes nothing until a module names a route with `rule(...)`. A path is matched as written, against the
path after `/api/eneo/`. `forward_upload` and `stream_signed` are functions for a module's own routes, behind
`Depends(require_session)` (and `require_same_origin` for a write).

## Configuration

`create_app()` reads the environment when it is not given a `Settings`.

| Variable | Default | |
|---|---|---|
| `ENEO_BACKEND_URL` | | Eneo's address from the module's network |
| `ENEO_PUBLIC_URL` | | Eneo's address from the browser |
| `MODULE_PUBLIC_URL` | | This module's address from the browser |
| `MODULE_KEY` | | Lowercase kebab-case, as registered in Eneo |
| `ENEO_API_KEY` | | The module's service key |
| `SESSION_SECRET` | | At least 32 characters |
| `ENEO_API_KEY_HEADER_NAME` | `X-API-Key` | |
| `COOKIE_SECURE` | `true` | `false` only for local development over http |
| `SESSION_MAX_AGE_MINUTES` | `480` | The session also ends at Eneo's own ceiling |
| `UPLOAD_PROXY_TIMEOUT_SECONDS` | `1800` | |
| `SHOW_ORGANIZATION`, `ORGANIZATION_NAME`, `ORGANIZATION_LOGO`, `ORGANIZATION_LOGO_DARK` | | The organisation shown beside the product name |

## Limits

- One process, one replica: sessions live in memory. `serve()` fixes one worker and turns the access log off,
  because the callback URL carries a login ticket.
- Nothing in the package configures logging: a module sets up its own.

The contract with Eneo and the HTTP surface are in `docs/design.md`, sections 2 and 5, of the repository.
