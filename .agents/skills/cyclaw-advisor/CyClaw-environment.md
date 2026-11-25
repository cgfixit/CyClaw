# CyClaw environment source map

| Surface | Current source |
| --- | --- |
| Install profiles | `setup-guide.md`, `locks/README.md`, `pyproject.toml`, `constraints.txt`, `environment.yml`. Select platform Torch first. |
| Apple Silicon model sizing | `docs/m5-48gb-coding-expectations.md`, `macos/ollama-mlx.env`, `config.yaml`. Verify actual hardware. |
| Container host model | `docs/DOCKER.md`, `models.local_llm.trusted_hosts` and `assert_local_destination`. Host/IP matching does not pin DNS. |
| macOS dotenv | `macos/invoke-cyclaw.sh`, `macos/setup-from-clone.sh` and `macos/setup-cyclaw.sh`. Check BSD stat, source status and allexport restoration. |
| Windows launcher | `powershell/` and native installer jobs in `.github/workflows/ci.yml`. Verify PowerShell 5.1 on Windows. |
| Telemetry | `utils/telemetry_kill.py`, `utils/onnx_telemetry.py` and the maintained OTel checker. Check pre-import and ONNX post-import behavior. |

Use matching native evidence for filesystem, scheduler, keystore and installer claims. Consult `docs/THREAT_MODEL.md` for process isolation and deployment limits.
