# `windows/` — generate-only Task Scheduler supervisors

Windows twin of `macos/generate_service_plist.py`, outside the core request
path (I6).

| Script | What it does |
|---|---|
| `generate_service_task.py` | Write XML + `.cmd` for `gate.py`. Refuses without `--confirm` and a non-empty `--reason`. Never calls `schtasks /Create`. |

From the repo root, using Windows Python 3.12 with PyYAML:

```powershell
python windows/generate_service_task.py --service gate `
  --api-key-target com.cgfixit.cyclaw.api-key `
  --confirm --reason "Start the gateway when I log in"
```

Writes `%USERPROFILE%\.CyClaw\tasks\CyClaw-gate.xml` and its `.cmd`, replacing
previous output. Review the printed registration command separately. Task settings:

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

`--config` selects only the printed port; `gate.py` reads the checkout's
`config.yaml`. This logon task requires a logged-in user. End it and remove
registration with `schtasks /End /TN "CyClaw gate"` and
`schtasks /Delete /TN "CyClaw gate" /F` respectively.

Installer / CredMan / fsconnect jail live in [`powershell/`](../powershell/README.md).
Trash, Telegram, and OpenTweet generators: `python -m agentic.fsconnect.cli trash-empty-task`,
`python -m telegram.cli poll-task` / `health-task`,
`python -m opentweet.cli schedule-task`.
