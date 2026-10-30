# `static/` — browser console

HTML/JS served by `gate.py` on its configured bind (default loopback).
No build step, framework, or external CDN.

| File | Served by | What it is |
|---|---|---|
| `terminal.html` + `terminal.js` | `gate.py` at `GET /` (plus the `/static` mount), default `127.0.0.1:8787` | Queries, first-run build panel until `index_ready`, Library/Engine health chips, console credentials, and soul/ops tools. A locked build opens the unlock dialog and retries. |
| `auth_admin.js` | the `/static` mount; referenced by `terminal.html` | Users list/create/role/password/delete. Displays `disabled` but has no enable/disable buttons. |

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

`tests/test_terminal_contract.py` compares console routes with the gateway.
Add new console POST calls to its `_POST_PATHS`; every called route must exist.

Security posture for anything added here: same-origin only, no third-party
script/font/CDN references (the server is loopback-bound by default and offline-first
— an external reference would both leak and break), and any
`target="_blank"` link needs `rel="noopener noreferrer"`.

## Related

- Route table and auth requirements per endpoint: `CLAUDE.md` §2 "All HTTP routes"
