# CyClaw environment source map

Use this reference for install/runtime/platform advice. Read the current source
instead of copying dependency pins or hardware assumptions into new guidance.
Refreshed against `origin/main` `cb9a0128` (2026-10-08). Hardware profiles are
still not the active user's machine.

| Surface | Source and limits |
|---|---|
| Python and install profiles | `pyproject.toml`, `constraints.txt`, `requirements*.txt`, `environment.yml`, `setup-guide.md`. Python 3.12; platform-correct Torch first. Constraints-only and platform runtime pip installs require hashes (#1570, #1548). |
| Apple Silicon model sizing | `docs/m5-48gb-coding-expectations.md`, `macos/ollama-mlx.env`, `config.yaml`. Do not infer the active user's hardware from these reference profiles. |
| Container host model | `docs/DOCKER.md`, `models.local_llm.trusted_hosts`, and `assert_local_destination`. Trust is exact by hostname/IP, not DNS pinning. Bind directories must be prepared before use (#1537). |
| macOS dotenv | `macos/invoke-cyclaw.sh`, `setup-from-clone.sh`, `setup-cyclaw.sh`: BSD `/usr/bin/stat`, mode 600/400, source-status fallback, restore allexport. Secret-scan helpers must receive the dotenv path (`$1`); an empty path skips scrubbing (#1575). |
| Windows launcher | `powershell/`, Windows installer jobs in `ci.yml`. PowerShell 5.1 must be tested natively; Git Bash does not prove that contract. `Write-CyClawHost` writes the information stream so `6>&1` and `Start-Transcript` capture operator warnings (#1582). Six copies stay identical. |
| Executor sandbox | `agentic/executor/hard_sandbox.py`: Windows Job Object, Darwin Seatbelt, Linux netns; missing capability refuses. Verify actual platform probes before claiming enforcement. bwrap on stock Ubuntu 24.04 is a bwrap-scoped AppArmor profile, not a global sysctl (#1554). |
| Telemetry | `utils/telemetry_kill.py`, `utils/onnx_telemetry.py`, maintained otel checker. Pre-import environment suppression plus ONNX load seams; not a firewall. |
| Git hooks | `scripts/ensure-githooks.sh` sets local `core.hooksPath` for this checkout. Do not set a global relative hooksPath (#1577 follow-up). Pre-push scans each tag in a chain and treats a ref moved onto a blob or tree as a rewrite. |
| Linux API key | Generated into libsecret or a mode-0600 file; pairing URL prints only on a TTY (#1561). |
| Script lint | `.github/workflows/script-lint.yml`: ShellCheck 0.11.0, PSScriptAnalyzer 1.23.0, no rule exclusions (#1575). |

Production executor verification must not fall back to the test-only
`ArgvListSandbox` or an unconstrained subprocess. Windows process-tree controls
do not imply network isolation. Native filesystem, scheduler, key store, and
platform install claims need matching native evidence.

Use the actual selected checkout and installed tools. Host-specific paths or
external git-hook stamps may exist, but are not tracked CyClaw dependencies.
