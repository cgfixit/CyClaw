# `static/` — browser console

Static HTML/JS served by `gate.py`. No build step, no framework, no external
CDN — everything ships in this directory and is served from loopback only.

| File | Served by | What it is |
|---|---|---|
| `terminal.html` + `terminal.js` | `gate.py` at `GET /` (plus the `/static` mount) on `127.0.0.1:8787` | The CyClaw Terminal — the operator console for `/query` and the authenticated soul/ops endpoints. |
| `auth_admin.js` | the `/static` mount; referenced by `terminal.html` | Users panel (`/auth/users` list/create/role-change/password-reset/delete; the `disabled` flag is displayed but the `/disable`/`/enable` routes are not wired to buttons) — one script, no inline script. |

`gate.py`'s CSP has no nonce source, so no page here may carry an inline
`<script>` block: `tests/test_gate.py::test_no_static_page_relies_on_inline_script`
walks every `*.html` under this directory and fails on one.

## The console contract

`tests/test_terminal_contract.py` extracts the routes `terminal.html`
actually calls and compares them against `gate.py`'s route table — any new
state-changing POST endpoint must be added to that test's `_POST_PATHS`, and
any route the console calls must really exist. Treat `terminal.html` as a
tested artifact, not free-form UI.

Security posture for anything added here: same-origin only, no third-party
script/font/CDN references (the server is loopback-bound and offline-first
— an external reference would both leak and break), and any
`target="_blank"` link needs `rel="noopener noreferrer"`.

## Related

- Route table and auth requirements per endpoint: `CLAUDE.md` §2 "All HTTP routes"
