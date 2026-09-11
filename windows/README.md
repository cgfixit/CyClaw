# `windows/` — generate-only Task Scheduler supervisors

>https://github.com/cgfixit/CyClaw/tree/main/powershell

Windows twin of `macos/generate_service_plist.py`. Not request-path code
(`gate.py` / `graph.py` / `mcp_hybrid_server.py` never import this; I6).

| Script | What it does |
|---|---|
| `generate_service_task.py` | Write XML + `.cmd` for `gate.py`. Refuses without `--confirm` and a non-empty `--reason`. Never calls `schtasks /Create`. |

Installer / CredMan / fsconnect jail live in [`powershell/`](../powershell/README.md).
Trash, Telegram, and OpenTweet generators: `python -m agentic.fsconnect.cli trash-empty-task`,
`python -m telegram.cli poll-task` / `health-task`,
`python -m opentweet.cli schedule-task`.
