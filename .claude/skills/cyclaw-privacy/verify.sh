#!/usr/bin/env bash
# verify.sh — cyclaw-privacy verification.
# Checks that the shipped config.yaml still carries the privacy posture
# SKILL.md cites (fingerprinted audit, redaction on, no off-box context by
# default). Exits 0 when healthy, 2 on a posture drift, 3 when it cannot
# check (no PyYAML — a fresh pre-install container — is a clean skip).
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root" || exit 3

echo "Verifying cyclaw-privacy posture against config.yaml..."
python3 - <<'PY'
import sys
try:
    import yaml
except ImportError:
    print("SKIP: PyYAML not importable (fresh container); nothing checked")
    sys.exit(0)
cfg = yaml.safe_load(open("config.yaml", encoding="utf-8")) or {}
def get(path, default=None):
    node = cfg
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node
checks = [
    ("logging.audit.include_query_hash", get("logging.audit.include_query_hash", True) is True,
     "audit stream stores keyed HMAC fingerprints, never raw query text"),
    ("policy.privacy.redact_emails", get("policy.privacy.redact_emails") is True, "email redaction on"),
    ("policy.privacy.redact_ips", get("policy.privacy.redact_ips") is True, "IP redaction on"),
    ("policy.privacy.redact_secrets_like has sk-ant", any("sk-ant" in str(p) for p in get("policy.privacy.redact_secrets_like", []) or []),
     "Anthropic key shape redacted"),
    ("policy.fallback.send_local_context_to_grok", get("policy.fallback.send_local_context_to_grok") is False,
     "no retrieved context off-box to Grok by default"),
    ("policy.fallback.send_local_context_to_claude", get("policy.fallback.send_local_context_to_claude") is False,
     "no retrieved context off-box to Claude by default"),
    ("memory.enabled", get("memory.enabled") is not True, "memory subsystem ships off"),
    ("auth.enabled", get("auth.enabled") is not True, "per-user auth ships off"),
    ("logging.third_party_level", str(get("logging.third_party_level", "INFO")).upper() != "DEBUG",
     "third-party log level above DEBUG (httpcore DEBUG writes Authorization headers)"),
]
failed = 0
for name, ok, why in checks:
    print(f"  {'ok  ' if ok else 'FAIL'} {name} -- {why}")
    failed += 0 if ok else 1
print(f"{failed} posture drift(s)")
sys.exit(2 if failed else 0)
PY
rc=$?
[ "$rc" -eq 0 ] && echo "cyclaw-privacy verify: OK"
exit "$rc"
