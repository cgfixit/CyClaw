# `config/` - supporting policy files

Runtime settings live in root [`config.yaml`](../config.yaml). `gate.py`
validates it at startup; restart after edits. Connector CLIs load their own blocks.

| Location | Consumer and purpose |
|---|---|
| [`config.yaml`](../config.yaml) | Models, retrieval/indexing, auth, privacy, logs, and subsystem settings; boot checks in `utils/config_validation.py`. |
| [`numbat/gate/`](numbat/gate/) | Pre-action rules and tests; `utils/numbat_gate.py` consumes them when `policy.fallback.pre_action_hook.enabled` is true. |
| [`numbat/README.md`](numbat/README.md) | Rules, validation, and distinctions between hook, CEL monitor, and event stream. |

Keep credential names in config and values in the OS credential store or
process environment. Local credentials use `models.local_llm.api_key_env`
and `models.local_llm.fallback.api_key_env`. Boot refuses non-empty literal
`api_key` values in either block, including a disabled fallback.
Credential loading: [`setup-guide.md`](../setup-guide.md).

From the repository root:

```bash
python3 .claude/skills/config-guard/check_config.py
```

`--strict` also asserts shipped defaults; omit it for deliberately customized
operator configurations.
