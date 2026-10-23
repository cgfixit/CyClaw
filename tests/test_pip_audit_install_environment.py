"""Exercise pip-audit's install setup against conflicting hosted-runner metadata."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/pip-audit.yml"


def test_install_verification_isolates_hosted_runner_packages(tmp_path: Path) -> None:
    runner = tmp_path / "runner-python"
    subprocess.run([sys.executable, "-m", "venv", str(runner)], check=True, capture_output=True, timeout=60)
    scripts_name = "Scripts" if os.name == "nt" else "bin"
    python_name = "python.exe" if os.name == "nt" else "python"
    runner_python = runner / scripts_name / python_name
    result = subprocess.run(
        [str(runner_python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    site_packages = Path(result.stdout.strip())
    # Model the observed pipx/filelock conflict without installing either package.
    for name, version, requires in [("runner_pipx", "1.18.4", "filelock>=4.2"), ("filelock", "4.0.10", "")]:
        metadata = site_packages / f"{name}-{version}.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + (f"Requires-Dist: {requires}\n" if requires else ""),
            encoding="utf-8",
        )
    polluted = subprocess.run(
        [str(runner_python), "-m", "pip", "check"], capture_output=True, text=True, timeout=30, check=False,
    )
    assert polluted.returncode != 0
    assert "filelock>=4.2" in polluted.stdout

    steps = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["verify-install"]["steps"]
    preparation = next((step for step in steps if step.get("id") == "install-env"), {})
    script = preparation.get("run", "").partition("<<'PY'\n")[2].partition("\nPY")[0]
    github_path = tmp_path / "github-path"
    github_path.touch()
    prepared = subprocess.run(
        [str(runner_python), "-c", script],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "GITHUB_PATH": str(github_path)},
        check=False, capture_output=True, text=True, timeout=60,
    )
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    added_paths = github_path.read_text(encoding="utf-8").splitlines()
    selected_python = Path(added_paths[0]) / python_name if added_paths else runner_python
    clean = subprocess.run(
        [str(selected_python), "-m", "pip", "check"], capture_output=True, text=True, timeout=30, check=False,
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    result = subprocess.run(
        [str(selected_python), "-c", "import json, sys; print(json.dumps([sys.prefix, sys.base_prefix]))"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    prefix, base_prefix = json.loads(result.stdout)
    assert prefix != base_prefix
    assert Path(prefix) == tmp_path / "verify-install"
    install_index = steps.index(preparation)
    assert install_index < next(i for i, step in enumerate(steps) if "pip install" in step.get("run", ""))
