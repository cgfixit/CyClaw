"""Bounded offline lock/input freshness and wheel metadata checks (#1526).

This detects changed inputs, pins, hashes and output sets. It does not claim
that a new resolver run against today's index would choose identical versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?(?:==([^ ;\\]+))?$")


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirements(path: Path) -> dict[str, str | None]:
    """Parse the maintained single-requirement-per-line, exact-pin inputs."""
    result = {}
    for line in path.read_text().splitlines():
        value = line.split("#", 1)[0].strip().rstrip("\\").strip()
        if not value or value.startswith("--hash="):
            continue
        match = PIN.fullmatch(value)
        if not match:
            raise ValueError(f"unsupported requirement syntax in {path.name}: {value}")
        name = normalized(match[1])
        if name in result:
            raise ValueError(f"duplicate requirement in {path.name}: {name}")
        result[name] = match[2]
    return result


def catalog(group: str) -> dict[str, str]:
    mapping = {}
    if group == "runtime":
        for platform in ("linux", "windows", "macos"):
            mapping[f"requirements-lock-{platform}.txt"] = "requirements.txt"
            mapping[f"requirements-torch-lock-{platform}.txt"] = "requirements-torch.txt"
    else:
        for platform in ("linux", "windows", "macos"):
            mapping[f"requirements-test-lock-{platform}.txt"] = "requirements-test.txt"
            mapping[f"requirements-ci-deepagents-lock-{platform}.txt"] = "scripts/ci-lock-inputs/deepagents.txt"
        for name in ("smoke", "yaml", "ruff", "cel", "numbat", "postgres", "bandit"):
            source = "postgres-job" if name == "postgres" else name
            mapping[f"requirements-ci-{name}-lock-linux.txt"] = f"scripts/ci-lock-inputs/{source}.txt"
        for name in ("postgres", "pgvector", "mssql", "dev", "agentic-deepagents", "agentic-deepagents-cloud"):
            mapping[f"requirements-extra-lock-{name}-linux.txt"] = f"scripts/ci-lock-inputs/extra-{name}.txt"
    return mapping


def contract(root: Path, group: str, lock_dir: Path) -> dict:
    """Validate every output against its input and every applicable constraint."""
    mapping = catalog(group)
    constraints = requirements(root / "constraints.txt")
    for filename, source in mapping.items():
        path = lock_dir / filename
        pins = requirements(path)
        if any(pin is None for pin in pins.values()):
            raise ValueError(f"unpinned requirement in {filename}")
        text = path.read_text()
        for block in re.split(r"\n(?=[A-Za-z0-9])", text):
            if re.search(r"(?m)^[A-Za-z0-9].*==", block) and not re.search(r"--hash=sha256:[0-9a-f]{64}\b", block):
                raise ValueError(f"missing package hash in {filename}")
        for name, pin in requirements(root / source).items():
            if name not in pins:
                raise ValueError(f"{filename} lacks input {name}")
            wanted = pin or constraints.get(name)
            actual = pins[name]
            if name == "torch" and wanted:
                wanted = wanted.removesuffix("+cpu") + ("" if filename.endswith("macos.txt") else "+cpu")
            if wanted is not None and actual != wanted:
                raise ValueError(f"{filename}: {name} is {actual}, input requires {wanted}")
        for name, actual in pins.items():
            wanted = constraints.get(name)
            if name == "torch" and wanted and filename.endswith("macos.txt"):
                wanted = wanted.removesuffix("+cpu")
            if wanted is not None and actual != wanted:
                raise ValueError(f"{filename}: {name} is {actual}, constraint requires {wanted}")
    inputs = sorted({*mapping.values(), "constraints.txt", "pyproject.toml",
                     f"scripts/refresh-{'runtime-lock' if group == 'runtime' else 'ci-locks'}.sh",
                     "scripts/check_lock_contract.py"})
    def digest(path: Path) -> str:
        if path.name == "pyproject.toml" and path.parent == root:
            # Only the dependency tables feed locks. Hashing raw bytes made a
            # coverage-source, ruff or version edit fail CI until a macOS re-lock.
            project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
            tables = {key: project.get(key) for key in ("requires-python", "dependencies", "optional-dependencies")}
            return "sha256:" + hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
        # Every catalog entry is text. Git's Windows checkout conversion is
        # not dependency drift; compare canonical LF bytes on every platform.
        return "sha256:" + hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return {"version": 1, "inputs": {p: digest(root / p) for p in inputs},
            "outputs": {p: digest(lock_dir / p) for p in sorted(mapping)}}


def check(root: Path) -> None:
    expected = set(catalog("runtime")) | set(catalog("ci"))
    actual = {p.name for p in (root / "locks").glob("requirements-*.txt")}
    if actual != expected:
        raise ValueError(f"uncatalogued or missing locks: {sorted(actual ^ expected)}")
    for group in ("runtime", "ci"):
        recorded = json.loads((root / "locks" / f"{group}-inputs.json").read_text())
        if recorded != contract(root, group, root / "locks"):
            raise ValueError(f"{group} lock inputs/outputs changed; regenerate the entire {group} set")


def publish(root: Path, group: str, staged: Path) -> None:
    """Publish only a complete validated set; roll back ordinary I/O failures."""
    stamp = contract(root, group, staged)
    name = f"{group}-inputs.json"
    (staged / name).write_text(json.dumps(stamp, indent=2) + "\n")
    paths = [*catalog(group), name]
    backups = {p: (root / "locks" / p).read_bytes() if (root / "locks" / p).exists() else None for p in paths}
    changed = []
    try:
        for p in paths:
            os.replace(staged / p, root / "locks" / p)
            changed.append(p)
    except OSError:
        for p in reversed(changed):
            target = root / "locks" / p
            old = backups[p]
            if old is None:
                target.unlink(missing_ok=True)
            else:
                rollback = staged / p
                rollback.write_bytes(old)
                os.replace(rollback, target)
        raise


def wheel_contract(root: Path, wheel_path: Path) -> None:
    """Compare all base Requires-Dist entries, including extras and markers."""
    from packaging.requirements import Requirement

    def key(value: str) -> tuple:
        req = Requirement(value)
        return normalized(req.name), tuple(sorted(req.extras)), str(req.specifier), str(req.marker or ""), req.url

    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    with zipfile.ZipFile(wheel_path) as wheel:
        names = [n for n in wheel.namelist() if n.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("wheel must have exactly one METADATA")
        metadata = BytesParser().parsebytes(wheel.read(names[0]))
    expected = {key(value) for value in project["dependencies"]}
    # Preserve all platform markers on base dependencies. Optional entries
    # cannot substitute for a base requirement: their extra markers exclude
    # them from this comparison.
    actual = {key(value) for value in metadata.get_all("Requires-Dist", [])
              if not re.search(r"\bextra\b", str(Requirement(value).marker or ""))}
    if actual != expected:
        raise ValueError(f"wheel Requires-Dist mismatch: missing={expected - actual}, extra={actual - expected}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--publish", choices=("runtime", "ci"))
    parser.add_argument("--staged", type=Path)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    if args.publish:
        if args.staged is None:
            parser.error("--publish requires --staged")
        publish(args.root, args.publish, args.staged)
    elif args.wheel:
        wheel_contract(args.root, args.wheel)
    else:
        check(args.root)
    print("lock contract passed")


if __name__ == "__main__":
    main()
