#!/usr/bin/env python3
"""Check Codex manifests, UI policy, references and syntax without imports."""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

import yaml


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys rather than silently taking the last value."""


def unique_mapping(loader: UniqueLoader, node: yaml.MappingNode) -> dict:
    """Construct one unambiguous mapping."""
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def validate(root: Path) -> tuple[int, list[str]]:
    """Return skill count and structural errors for the selected repository."""
    errors = []
    names = set()
    skills = root / ".agents/skills"
    directories = sorted(p for p in skills.iterdir() if p.is_dir()) if skills.is_dir() else []
    if not directories:
        errors.append("no repository skills in .agents/skills")
    try:
        inventory = (root / ".codex/README.md").read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"inventory unavailable: {exc}")
        inventory = ""
    for directory in directories:
        try:
            manifests = [p for p in directory.iterdir() if p.name.casefold() == "skill.md"]
            if len(manifests) != 1 or manifests[0].name != "SKILL.md":
                raise ValueError("require exactly one canonical SKILL.md")
            text = manifests[0].read_text(encoding="utf-8")
            match = re.fullmatch(r"---\r?\n(.*?)\r?\n---\r?\n(.+)", text, re.DOTALL)
            if not match:
                raise ValueError("missing frontmatter or skill body")
            manifest = yaml.load(match[1], Loader=UniqueLoader)
            if not isinstance(manifest, dict) or set(manifest) != {"name", "description"}:
                raise ValueError("frontmatter requires name and description only")
            name = manifest["name"]
            if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
                raise ValueError("name must be lower-case kebab-case")
            if len(name) > 64 or name != directory.name or name in names:
                raise ValueError("name must be unique, <=64 characters and match folder")
            names.add(name)
            description = manifest["description"]
            if not isinstance(description, str) or not description.strip() or len(description) > 1024:
                raise ValueError("description must be nonempty text <=1024 characters")
            metadata = yaml.load((directory / "agents/openai.yaml").read_text(encoding="utf-8"), Loader=UniqueLoader)
            if not isinstance(metadata, dict) or not isinstance(metadata.get("interface"), dict):
                raise ValueError("metadata requires an interface mapping")
            interface = metadata["interface"]
            for field in ("display_name", "short_description", "default_prompt"):
                if not isinstance(interface.get(field), str) or not interface[field].strip():
                    raise ValueError(f"missing interface.{field}")
            if not 25 <= len(interface["short_description"]) <= 64:
                raise ValueError("short_description must contain 25-64 characters")
            if not re.search(r"\$" + re.escape(name) + r"(?![a-z0-9-])", interface["default_prompt"]):
                raise ValueError(f"default_prompt must mention exact ${name}")
            policy = metadata.get("policy")
            if not isinstance(policy, dict) or type(policy.get("allow_implicit_invocation")) is not bool:
                raise ValueError("implicit invocation policy must be an explicit YAML boolean")
            mode = "Implicit" if policy["allow_implicit_invocation"] else "Explicit"
            if not re.search(r"^\| `" + re.escape(name) + r"` \|[^\n]*\| " + mode + r" \|$", inventory, re.MULTILINE):
                raise ValueError(f"inventory inconsistent with {mode} selection")
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", match[2]):
                if "://" not in link and not link.startswith("#"):
                    if not (directory / link.split("#", 1)[0]).exists():
                        raise ValueError(f"missing reference: {link}")
            for script in directory.rglob("*.py"):
                ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        except (OSError, ValueError, TypeError, yaml.YAMLError, SyntaxError) as exc:
            errors.append(f"{directory.name}: {exc}")
    listed = set(re.findall(r"^\| `([a-z0-9-]+)` \|[^\n]*\| (?:Implicit|Explicit) \|$", inventory, re.MULTILINE))
    errors.extend(f"inventory lists unknown skill: {name}" for name in sorted(listed - names))
    return len(directories), errors


def main() -> int:
    """Check the checkout or an explicitly selected disposable fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    count, errors = validate(args.repo_root.resolve())
    for error in errors:
        print(f"FAIL: {error}")
    print(f"{count} skills checked, {len(errors)} errors")
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
