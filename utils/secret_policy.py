"""Shared, inert secret-name policy used by runtime and maintenance tools."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

POLICY_PATH = Path(__file__).with_name("secret-policy.tsv")
_HEADER = "# cyclaw-secret-policy-v1"


@dataclass(frozen=True)
class SecretPolicy:
    suffixes: tuple[str, ...]
    services: dict[str, str]
    exact_names: frozenset[str]

    def is_secret_name(self, name: str) -> bool:
        if not name or not name.replace("_", "A").isalnum() or not name[0].isalpha():
            return False
        upper = name.upper()
        return upper in self.exact_names or any(
            len(upper) > len(suffix) + 1 and upper.endswith("_" + suffix) for suffix in self.suffixes
        )

    def service_for(self, name: str) -> str | None:
        return self.services.get(name.upper())


@lru_cache(maxsize=1)
def load_secret_policy(path: Path = POLICY_PATH) -> SecretPolicy:
    suffixes: list[str] = []
    exact: set[str] = set()
    services: dict[str, str] = {}
    lines = path.read_text(encoding="ascii").splitlines()
    if not lines or lines[0] != _HEADER:
        raise ValueError("unsupported or missing CyClaw secret-policy version")
    seen: set[tuple[str, str]] = set()
    for line_no, line in enumerate(lines[1:], 2):
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 3 or fields[0] not in {"suffix", "exact"}:
            raise ValueError(f"invalid secret-policy record at line {line_no}")
        kind, raw_name, service = fields
        name = raw_name.upper()
        key = (kind, name)
        if key in seen or not name or not name.replace("_", "A").isalnum():
            raise ValueError(f"duplicate or invalid secret-policy name at line {line_no}")
        seen.add(key)
        if kind == "suffix":
            if service:
                raise ValueError(f"suffix service is not supported at line {line_no}")
            suffixes.append(name)
        else:
            exact.add(name)
            if service:
                services[name] = service
    return SecretPolicy(tuple(suffixes), services, frozenset(exact))


SECRET_POLICY = load_secret_policy()


def is_secret_name(name: str) -> bool:
    return SECRET_POLICY.is_secret_name(name)
