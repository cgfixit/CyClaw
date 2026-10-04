"""Native verification acceptance for CI; no software sandbox double is used."""
from __future__ import annotations

import os
import secrets
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentic.executor import Check, HardSandboxUnavailable, run_verification  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cyclaw-native-verification-") as temporary:
        root = Path(temporary)
        source = root / "source"
        source.mkdir()
        (source / ".git").mkdir()
        (source / ".git" / "config").write_text("trusted", encoding="utf-8")
        (source / "value").write_text("original", encoding="utf-8")
        baseline = root / "git-config-baseline.json"
        baseline.write_text("trusted", encoding="utf-8")
        cfg = {"logging": {"audit_file": str(root / "audit.jsonl"), "redact_patterns": []},
               "numbat": {"enabled": False}}
        if sys.platform == "win32":
            marker = root / "unconfined-child"
            try:
                run_verification(source, [Check("must-not-launch", (
                    sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('unsafe')",
                ))], cfg=cfg)
            except HardSandboxUnavailable:
                if marker.exists():
                    raise RuntimeError("Windows refusal launched an unconfined check") from None
                print("PASS: Windows verification refused; no check launched (filesystem/network boundary unavailable)")
                return 0
            raise RuntimeError("Windows verification unexpectedly accepted the incomplete boundary")

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            protected = [str(source / "value"), str(source / ".git" / "config"),
                         str(baseline), str(root / "parent-write")]
            host_pid_namespace = os.readlink("/proc/self/ns/pid") if sys.platform.startswith("linux") else None
            code = f"""import os,pathlib,socket
assert not pathlib.Path('.git').exists(), 'candidate copied git metadata'
assert 'CYCLAW_SANDBOX_CANARY_SECRET' not in os.environ, 'inherited parent credential'
if {host_pid_namespace!r} is not None:
    assert os.readlink('/proc/self/ns/pid') != {host_pid_namespace!r}, 'inherited host PID namespace'
pathlib.Path('value').write_text('candidate-only')
for target in {protected!r}:
    try: pathlib.Path(target).write_text('escaped')
    except OSError: pass
    else: raise AssertionError('write escaped candidate')
try: socket.create_connection(('127.0.0.1', {port}), timeout=2)
except OSError: pass
else: raise AssertionError('verification reached host loopback listener')
print('candidate writable; authoritative/git/baseline/parent writes and host network denied')
"""
            previous_canary = os.environ.get("CYCLAW_SANDBOX_CANARY_SECRET")
            os.environ["CYCLAW_SANDBOX_CANARY_SECRET"] = secrets.token_hex(16)
            try:
                report = run_verification(source, [Check("native-boundary", (sys.executable, "-c", code))], cfg=cfg)
            finally:
                if previous_canary is None:
                    os.environ.pop("CYCLAW_SANDBOX_CANARY_SECRET", None)
                else:
                    os.environ["CYCLAW_SANDBOX_CANARY_SECRET"] = previous_canary
            if not report.ok:
                raise RuntimeError(f"native sandbox failed: {report.results!r}")
        if (source / "value").read_text(encoding="utf-8") != "original":
            raise RuntimeError("verification writes copied back into the source")
        if baseline.read_text(encoding="utf-8") != "trusted":
            raise RuntimeError("verification changed the trusted baseline")
        print(f"PASS: {sys.platform} native confinement, credential exclusion, and gitless no-copyback")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
