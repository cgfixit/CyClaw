"""Pin both pytest CI lanes' --cov targets to pyproject's coverage source list.

pyproject.toml's ``[tool.coverage.run] source`` is the authoritative list of
what the ``fail_under = 80`` gate measures. Both lanes that run pytest with
coverage -- ci.yml's ``test`` job and python-package-conda.yml's ``ci`` job --
have to pass that same set, or a lane silently measures a different denominator
than the one the gate is calibrated against.

History this replaces: the lanes used to enumerate ``utils.*``/``retrieval.*``
module-by-module (53 flags each, hand-copied between the two). That granularity
let a single module go unmeasured while every package-level check still passed,
which is how ``utils.win_schtasks`` shipped with its own test file and was never
added to either lane, and how the conda lane silently lost ``gate_ops``. Package
granularity makes both drift classes structurally impossible -- coverage.py
walks the package -- so the only thing left worth asserting is that each lane's
set is exactly the source list, which is what this module does.

Equality is deliberately bidirectional. A missing entry understates the lane's
denominator; an extra one measures something the gate was never calibrated for.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The two lanes that actually run pytest with coverage. Kept in sync with
# dep-guard's _CI_COV_FILES.
_COV_LANES = (
    ".github/workflows/ci.yml",
    ".github/workflows/python-package-conda.yml",
)

# Requires at least one name character, so a bare flag with an empty value in
# prose does not register as a measured target. Both lanes carry a comment
# warning against writing a literal flag=name token for this same reason.
_COV_FLAG_RE = re.compile(r"--cov=([A-Za-z0-9_.]+)")


def _cov_flags(rel: str) -> set[str]:
    return set(_COV_FLAG_RE.findall((_REPO_ROOT / rel).read_text(encoding="utf-8")))


def _pyproject_source() -> set[str]:
    with (_REPO_ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    source = data["tool"]["coverage"]["run"]["source"]
    assert source, "[tool.coverage.run] source is empty -- nothing gates coverage"
    return set(source)


@pytest.mark.parametrize("lane", _COV_LANES)
def test_lane_measures_exactly_the_pyproject_source_list(lane: str) -> None:
    flags = _cov_flags(lane)
    source = _pyproject_source()
    assert flags == source, (
        f"{lane}'s --cov targets do not match [tool.coverage.run] source. "
        f"Missing from the lane (measured by the gate but not by this lane): "
        f"{sorted(source - flags)}. Extra in the lane (measured here but not "
        f"part of the gate's calibrated denominator): {sorted(flags - source)}."
    )


def test_cov_lanes_agree_with_each_other() -> None:
    """Both lanes must measure the same set -- the original drift class.

    Implied by the per-lane equality above, but asserted directly so a failure
    names the two lanes rather than pointing each separately at pyproject.
    """
    first, second = _COV_LANES
    assert _cov_flags(first) == _cov_flags(second), (
        f"--cov targets differ between lanes: "
        f"only in {first}: {sorted(_cov_flags(first) - _cov_flags(second))}; "
        f"only in {second}: {sorted(_cov_flags(second) - _cov_flags(first))}"
    )
