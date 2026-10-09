"""Wrong-typed config values must fail as typed errors, never as crashes.

Walks every key of the shipped config.yaml, swaps in each wrong-typed value one
at a time (a YAML typo: a dropped list marker, an empty key, a stray -1), and
runs every boot validator in utils/config_validation.py plus the loader that
owns the section. A typed ``RAGError`` -- or ``ValueError``, which the endpoint
and pydantic checks raise -- is a correct refusal; a bare AttributeError,
TypeError, KeyError and the like means the code trusted the YAML's shape
(the class of bug fixed in #1608 and #1610). New keys and new ``validate_*``
functions are picked up automatically.

This catches crashes only: a wrong value that loads and then silently
misbehaves needs its own test.
"""

from __future__ import annotations

import copy
import importlib
import inspect
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

import utils.config_validation as config_validation
from utils.errors import RAGError

_SHIPPED: dict[str, Any] = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8")
)

_WRONG_VALUES: dict[str, object] = {
    "null": None,
    "empty_str": "",
    "str": "x",
    "negative": -1,
    "zero": 0,
    "bool": True,
    "list": [],
    "dict": {},
}

# section -> (module, loader). Each loader reads through its module's
# _get_config, which the test replaces, so nothing touches disk.
_LOADERS: dict[str, tuple[str, str]] = {
    "agentic": ("agentic.config", "load_agentic_config"),
    "fsconnect": ("agentic.fsconnect.config", "load_fsconnect_config"),
    "guardrails": ("guardrails.config", "load_guardrails_config"),
    "netconnect": ("agentic.netconnect.config", "load_netconnect_config"),
    "opentweet": ("opentweet.config", "load_opentweet_config"),
    "sqlconnect": ("agentic.sqlconnect.config", "load_sqlconnect_config"),
    "sync": ("sync.config", "load_sync_config"),
    "telegram": ("telegram.config", "load_telegram_config"),
}

_VALIDATORS: dict[str, Callable[[dict[str, Any]], object]] = {
    name: fn
    for name, fn in inspect.getmembers(config_validation, inspect.isfunction)
    if name.startswith("validate_") and list(inspect.signature(fn).parameters) == ["cfg"]
}


def _key_paths(node: object, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield (*prefix, key)
            yield from _key_paths(value, (*prefix, key))


def _mutations(section: str | None = None) -> Iterator[tuple[str, dict[str, Any]]]:
    for path in _key_paths(_SHIPPED):
        if section is not None and path[0] != section:
            continue
        for label, value in _WRONG_VALUES.items():
            cfg = copy.deepcopy(_SHIPPED)
            parent = cfg
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = copy.deepcopy(value)
            yield f"{'.'.join(map(str, path))}={label}", cfg


def _crashes(call: Callable[[dict[str, Any]], object], section: str | None) -> list[str]:
    crashes: list[str] = []
    for case, cfg in _mutations(section):
        try:
            call(cfg)
        except (RAGError, ValueError):
            continue
        except Exception as exc:  # noqa: BLE001 -- any other type is the finding
            crashes.append(f"{case}: {type(exc).__name__}: {exc}")
    return crashes


def test_every_validator_and_loader_is_exercised() -> None:
    assert len(_VALIDATORS) >= 10
    assert set(_LOADERS) <= set(_SHIPPED), "a loader's section is missing from config.yaml"


@pytest.mark.parametrize("name", sorted(_VALIDATORS))
def test_boot_validator_refuses_wrong_types_with_typed_errors(name: str) -> None:
    assert _crashes(_VALIDATORS[name], None) == []


@pytest.mark.parametrize("section", sorted(_LOADERS))
def test_section_loader_refuses_wrong_types_with_typed_errors(
    section: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_name, loader_name = _LOADERS[section]
    module = importlib.import_module(module_name)
    loader = getattr(module, loader_name)
    current: dict[str, Any] = {}
    monkeypatch.setattr(module, "_get_config", lambda *_a, **_k: current["cfg"])

    def call(cfg: dict[str, Any]) -> object:
        current["cfg"] = cfg
        return loader("config.yaml")

    assert _crashes(call, section) == []
