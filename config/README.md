# `config/` — supporting policy files

Runtime settings live in the repository-root [`config.yaml`](../config.yaml),
not in this directory. `gate.py` loads and validates that file at startup;
restart the gateway after changing it. Connector CLIs load their own blocks
through their subsystem config loaders.

| Location | Consumer and purpose |
|---|---|
| [`config.yaml`](../config.yaml) | Models, retrieval/indexing, authentication, privacy, logging, and optional subsystem settings. `utils/config_validation.py` checks the gateway's boot contract. |
| [`numbat/gate/`](numbat/gate/) | Maintained Numbat pre-action rules and companion tests, consumed by `utils/numbat_gate.py` only when `policy.fallback.pre_action_hook.enabled` is true. |
| [`numbat/README.md`](numbat/README.md) | Rule inventory, validation command, and the distinction between the hook, CEL monitor, and event stream. |

Keep credential **names** in configuration and credential **values** in the
OS credential store or the environment supplied to the process. Local model
credentials use `models.local_llm.api_key_env` and
`models.local_llm.fallback.api_key_env`; gateway boot validation refuses
non-empty literal `api_key` values in either block, including a disabled
fallback. Setup and platform-specific credential loading:
[`setup-guide.md`](../setup-guide.md).

For configuration checks from the repository root, use the existing guard:

```bash
python3 .claude/skills/config-guard/check_config.py
```

Its `--strict` mode also asserts the shipped defaults; it is not the right
mode for validating an intentionally customized operator configuration.
