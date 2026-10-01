# Configuration

Purpose: list every setting the BFF reads, its default and what start-up refuses.
Read this when: you are setting up a module's environment, adding a setting, or a start-up fails with a `RuntimeError`.
Related: [build a module](build-a-module.md), [local development](local-development.md), [security checklist](security-checklist.md), source `packages/bff/src/eneo_module_bff/settings.py`.

`create_app()` calls `load_settings()` when it is not given a `Settings`. `load_settings()` reads the environment and refuses to start on a missing or invalid value, with a message that names the variable.

## Environment variables

| Variable | Default | Check at start-up | Meaning |
|---|---|---|---|
| `ENEO_BACKEND_URL` | required | absolute http(s) URL, no query or fragment, trailing `/` removed | Eneo's address from the module's network. The token exchange, session check, refresh, proxy, uploads and signed-URL requests go here. |
| `ENEO_PUBLIC_URL` | required | same | Eneo's address from the browser. The login redirect goes here. |
| `MODULE_PUBLIC_URL` | required | same | This module's address from the browser. The callback is `{MODULE_PUBLIC_URL}/api/auth/callback`. The `Origin` of every write is compared with its origin (scheme, host, default port dropped, so `https://Mod.Example.SE:443` equals `https://mod.example.se`). |
| `MODULE_KEY` | required | lowercase kebab-case | The module's name as registered in Eneo. |
| `ENEO_API_KEY` | required | not empty | The module's service key. |
| `SESSION_SECRET` | required | at least 32 characters | Signs the login-state cookie. The session cookie is a random id and does not use it. |
| `ENEO_API_KEY_HEADER_NAME` | `X-API-Key` | a valid HTTP header name that is not a credential or framing header (`Authorization`, `Cookie`, `Host`, `Content-Length`, `Transfer-Encoding`, `Connection`, ...) | The header that carries the service key to Eneo. The module sets `Authorization` from the session after it, so a key sent under that name would never arrive: it is refused at start, and by `Settings` itself when a module builds it. |
| `COOKIE_SECURE` | `true` | `true`, `1`, `yes`, `on`, `false`, `0`, `no`, `off` | `false` only for local development over http. |
| `SESSION_MAX_AGE_MINUTES` | `480` | integer above zero | The most a login lasts. The session also ends at Eneo's own ceiling, whichever comes first. |
| `UPLOAD_PROXY_TIMEOUT_SECONDS` | `1800` | number above zero | The read and write budget of one upload to Eneo. A request's `X-Upload-Timeout-Seconds` header can lower it, never below 60 s. |
| `MAX_BODY_BYTES` | `10485760` (10 MiB) | integer above zero | The most of any request body, but an upload that `forward_upload` reads. A body of this size costs 21 MiB (42 MiB as a JSON model) for one request, and 13 to 16 MiB (17 to 26) each when 50 arrive at once: a module that is public to the internet sets it for its own largest JSON body. |
| `MAX_UPLOAD_BYTES` | `1073741824` (1 GiB) | integer above zero | The most one upload may declare. |
| `MAX_RESPONSE_BYTES` | `33554432` (32 MiB) | integer above zero | The most of an answer from Eneo that the proxy and an upload read, decoded; a larger one is a 502 `upstream_too_large`, read no further. Not for a file that streams. The answers that carry a token or a URL are limited to 1 MiB. |
| `MAX_CONCURRENT_STREAMS` | `64` | integer above zero | How many files may stream at once through `stream_signed`. |
| `SHOW_ORGANIZATION` | `true` | boolean, as `COOKIE_SECURE` | `false` shows no organisation at all. |
| `ORGANIZATION_NAME` | none | at most 100 characters, white space collapsed | The organisation shown beside the product name. It is also the logo's text alternative. |
| `ORGANIZATION_LOGO` | none | path to an `.svg` or `.png` of at most 1 MiB, whose content matches its name. Needs `ORGANIZATION_NAME` | The organisation's logo, served at `/api/branding/logo/light`. A file that cannot be used is logged once and the name is shown instead. |
| `ORGANIZATION_LOGO_DARK` | none | as `ORGANIZATION_LOGO` | The logo for dark mode, at `/api/branding/logo/dark`. Used only when `ORGANIZATION_LOGO` is usable. |

With none of the `ORGANIZATION_*` variables set, the organisation is the `default_organization` the module passed to `load_settings` (none by default: the product name alone).

## Not environment variables

| Argument of `load_settings` | Default | Meaning |
|---|---|---|
| `home_path` | `/` | Where the callback lands when login was started without a usable `next`. |
| `default_organization` | none | `Organization(name=..., logo=...)` when no `ORGANIZATION_*` is set. `logo` is `"default"` (the logo the module bundles in its own frontend: the kit serves no file for it, `/api/branding/logo/*` is a 404), `"custom"` (served by the kit, from `ORGANIZATION_LOGO`) or none (the name as text). |

`create_app()` loads with the defaults of these two. A module that sets one builds the settings itself:

```python
app = create_app(load_settings(home_path="/flows"), routers=[router])
```

## Check the table against the code

The code wins. This prints every field of `Settings` with its default (run from the repository root, after `pip install -e "packages/bff[test]"` as in the [README](../../README.md#quick-start-the-bff)):

```bash
.venv/bin/python - <<'EOF'
from eneo_module_bff.settings import Settings
for name, field in Settings.model_fields.items():
    print(f"{name} = {'(required)' if field.is_required() else repr(field.default)}")
EOF
```

`session_max_age_seconds` is `SESSION_MAX_AGE_MINUTES` times 60. The variables and their checks are in `load_settings`.
