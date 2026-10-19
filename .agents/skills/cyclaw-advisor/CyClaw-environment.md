# CyClaw environment source map

Use this reference for install/runtime/platform advice. Read the current source
instead of copying dependency pins or hardware assumptions into new guidance.

| Surface | Source and limits |
|---|---|
| Python and install profiles | `pyproject.toml`, `constraints.txt`, `requirements*.txt`, `locks/README.md`, `environment.yml`, `setup-guide.md`. Python 3.12; platform-correct Torch first. |
| Apple Silicon model sizing | `docs/m5-48gb-coding-expectations.md`, `macos/ollama-mlx.env`, `config.yaml`. Do not infer the active user's hardware from these reference profiles. |
| Container host model | `docs/DOCKER.md`, `models.local_llm.trusted_hosts`, and `assert_local_destination`. Trust is exact by hostname/IP, not DNS pinning. |
| macOS dotenv | `macos/invoke-cyclaw.sh`, `macos/setup-from-clone.sh`, `macos/setup-cyclaw.sh`: BSD `/usr/bin/stat`, mode 600/400, source-status fallback, restore allexport. |
| Windows launcher | `powershell/`, Windows installer jobs in `.github/workflows/ci.yml`. PowerShell 5.1 must be tested natively; Git Bash does not prove that contract. |
| Telemetry | `utils/telemetry_kill.py`, `utils/onnx_telemetry.py`, maintained otel checker. Pre-import environment suppression plus ONNX load seams; not a firewall. |

CyClaw ships no process sandbox: the `agentic/executor/` verification
sandbox (Seatbelt/bubblewrap) was removed on 2026-10-18, so do not claim
one. Native filesystem, scheduler, key store, and platform install claims
need matching native evidence.

Use the actual selected checkout and installed tools. Host-specific paths or
external git-hook stamps may exist, but are not tracked CyClaw dependencies.
