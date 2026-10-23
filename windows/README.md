# `windows/` — generate-only Task Scheduler supervisors

Windows twin of `macos/generate_service_plist.py`. Not request-path code
(`gate.py` / `graph.py` / `mcp_hybrid_server.py` never import this; I6).

| Script | What it does |
|---|---|
| `generate_service_task.py` | Write XML + `.cmd` for `gate.py`. Refuses without `--confirm` and a non-empty `--reason`. Never calls `schtasks /Create`. |

Run from the repository root on Windows with the runtime's Python 3.12
environment (including PyYAML):

```powershell
python windows/generate_service_task.py --service gate `
  --api-key-target com.cgfixit.cyclaw.api-key `
  --confirm --reason "Start the gateway when I log in"
```

This writes `%USERPROFILE%\.CyClaw\tasks\CyClaw-gate.xml` and its `.cmd`
launcher, then prints the registration command for separate review and use.
Re-running generation replaces those files. The generated task uses:

- a logon trigger and an `InteractiveToken` / `LeastPrivilege` principal;
- crash-only `RestartOnFailure`, at most five restarts, with a 30-second
  interval by default (`--throttle-sec` must be positive);
- no execution time limit and `IgnoreNew` for overlapping starts;
- the generator's Python interpreter and checkout as its working directory.

It runs `gate.py` directly, so it does not run the interactive launcher's
dotenv loading, first-run key generation, or browser pairing. The optional
`--api-key-target` wraps startup with `CyClaw-CredMan-Env.ps1`; the credential
value is read at runtime and is not embedded in either generated file. Other
provider credentials are not automatically loaded by this generator.

`--config` changes only the configuration inspected for the printed port.
`gate.py` still reads the checkout's `config.yaml`. This is a user logon task,
not a Windows service or an unattended boot task; registration does not prove
it will run while the user is logged out. To end a running task and remove its
registration, use `schtasks /End /TN "CyClaw gate"` and
`schtasks /Delete /TN "CyClaw gate" /F` respectively.

Installer / CredMan / fsconnect jail live in [`powershell/`](../powershell/README.md).
Trash, Telegram, and OpenTweet generators: `python -m agentic.fsconnect.cli trash-empty-task`,
`python -m telegram.cli poll-task` / `health-task`,
`python -m opentweet.cli schedule-task`.
