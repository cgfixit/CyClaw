# `static/` — browser console

Static HTML/JS served by `gate.py`. No build step, no framework, no external
CDN — everything ships in this directory and uses the gateway's configured
bind (loopback by default).

| File | Served by | What it is |
|---|---|---|
| `terminal.html` + `terminal.js` | `gate.py` at `GET /` (plus the `/static` mount), default `127.0.0.1:8787` | Operator console for `/query`, the first-run build panel (a slot above the log that persists until `index_ready`; a locked `POST /index/build` opens the unlock dialog and retries), the Library/Engine health chips, console-session credentials, and authenticated soul/ops endpoints. |
| `auth_admin.js` | the `/static` mount; referenced by `terminal.html` | Users panel (`/auth/users` list/create/role-change/password-reset/delete; the `disabled` flag is displayed but the `/disable`/`/enable` routes are not wired to buttons) — one script, no inline script. |

`gate.py`'s CSP has no nonce source, so no page here may carry an inline
`<script>` block: `tests/test_gate.py::test_no_static_page_relies_on_inline_script`
walks every `*.html` under this directory and fails on one.

## Operator behavior

The console supports first-run admin password setup and login when
`auth.enabled` is true. Operator access uses a separate HttpOnly console
session obtained with the ops key or a launcher's one-time pairing code;
an enabled admin login can also authorize operator endpoints. Write requests
carry the CSRF token for the credential being used. The `/query` flow uses
session authentication when enabled, independently of the ops console key.

After a vault miss, provider buttons come from the response's
`available_providers`; confirmation applies to one query. Answers display
their route and `llm_model` tag, and generation failures use the response's
`error` field. The browser reads query/sync deadlines from `/health` so its
fetch timeout does not hide the server's own timeout response.

There is no memory-management panel here. The optional `/memory/*` API and
HTML export are documented in
[`docs/memory/README.md`](../docs/memory/README.md).

## The console contract

`tests/test_terminal_contract.py` extracts the routes from `terminal.html`
and `terminal.js` and compares them against `gate.py`'s route table — any new
POST endpoint called by those files must be added to that test's `_POST_PATHS`, and
any route the console calls must really exist. Treat `terminal.html` as a
tested artifact, not free-form UI.

Security posture for anything added here: same-origin only, no third-party
script/font/CDN references (the server is loopback-bound by default and offline-first
— an external reference would both leak and break), and any
`target="_blank"` link needs `rel="noopener noreferrer"`.

## Related

- Route table and auth requirements per endpoint: `CLAUDE.md` §2 "All HTTP routes"
