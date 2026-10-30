"""Contract for .github/dependabot.yml: coverage, hand-managed pins, cooldown."""

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / ".github" / "dependabot.yml"

# Each ecosystem and the manifest it must find in its directory, or Dependabot
# opens nothing and the entry silently rots.
_MANIFESTS = {
    "pip": "pyproject.toml",
    "docker": "Dockerfile",
    "docker-compose": "docker-compose.yml",
    "github-actions": ".github/workflows",
}


@pytest.fixture(scope="module")
def updates() -> list[dict]:
    data = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    assert data["version"] == 2
    return data["updates"]


def _entry(updates: list[dict], ecosystem: str) -> dict:
    matches = [u for u in updates if u["package-ecosystem"] == ecosystem]
    assert len(matches) == 1, f"expected exactly one {ecosystem} entry, got {len(matches)}"
    return matches[0]


def test_ecosystem_directory_pairs_are_unique_and_known(updates: list[dict]) -> None:
    """Dependabot rejects a config that repeats an (ecosystem, directory) pair."""
    pairs = [(u["package-ecosystem"], u["directory"]) for u in updates]
    assert len(pairs) == len(set(pairs))
    assert {e for e, _ in pairs} == set(_MANIFESTS)


@pytest.mark.parametrize("ecosystem", sorted(_MANIFESTS))
def test_each_entry_points_at_a_real_manifest(updates: list[dict], ecosystem: str) -> None:
    entry = _entry(updates, ecosystem)
    base = _ROOT / entry["directory"].lstrip("/")
    assert (base / _MANIFESTS[ecosystem]).exists(), f"{ecosystem}: no {_MANIFESTS[ecosystem]} under {entry['directory']}"


def test_compose_images_are_covered_by_the_compose_ecosystem(updates: list[dict]) -> None:
    """The docker ecosystem reads Dockerfiles only; the digest-pinned Falco
    image in docker-compose.yml went without updates until this entry existed."""
    compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "falcosecurity/falco:" in compose
    _entry(updates, "docker-compose")


def test_own_image_is_never_a_compose_update_candidate(updates: list[dict]) -> None:
    ignored = {i["dependency-name"] for i in _entry(updates, "docker-compose").get("ignore", [])}
    assert "ghcr.io/cgfixit/cyclaw" in ignored


def test_pip_never_rewrites_the_hashed_locks(updates: list[dict]) -> None:
    """Dependabot cannot regenerate hashes or the locks/*-inputs.json records;
    scripts/check_lock_contract.py fails any PR that edits locks without them."""
    assert "locks/**" in _entry(updates, "pip")["exclude-paths"]


def test_hand_managed_pins_stay_ignored(updates: list[dict]) -> None:
    """torch (+cpu local version), pydantic/pydantic-core (lock-step) move by
    hand; numpy stays below 2 (chromadb/onnxruntime). CLAUDE.md section 4."""
    ignore = {i["dependency-name"]: i for i in _entry(updates, "pip")["ignore"]}
    for name in ("torch", "pydantic", "pydantic-core"):
        assert name in ignore, f"{name} must stay ignored"
        assert "versions" not in ignore[name], f"{name} is moved by hand entirely, not by version range"
    assert ">=2.0.0" in ignore["numpy"]["versions"]


@pytest.mark.parametrize("ecosystem", sorted(_MANIFESTS))
def test_every_ecosystem_waits_a_week_before_proposing_a_release(updates: list[dict], ecosystem: str) -> None:
    """Mirrors the .githooks security gate's "prefer releases older than a
    week". Dependabot exempts security updates from the cooldown."""
    assert _entry(updates, ecosystem)["cooldown"]["default-days"] >= 7


def test_pip_majors_stay_in_their_own_group(updates: list[dict]) -> None:
    """Majors are grouped, not ignored: ignore rules also suppress security updates."""
    groups = _entry(updates, "pip")["groups"]
    assert groups["pip-major"]["update-types"] == ["major"]
    assert "major" not in groups["pip-minor-patch"]["update-types"]
