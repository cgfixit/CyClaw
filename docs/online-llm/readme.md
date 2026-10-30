# Online LLM Fallbacks

CyClaw retrieves locally first. After a vault miss, a human can send the
question to Grok or Claude.

## Provider gates

Both providers ship **enabled** with `app.mode: hybrid`. External generation
requires all three gates: hybrid mode, provider enablement, and request
`user_confirmed_online: true`. A missing key independently makes the client
unavailable and keeps routing local. The separate `/health` provider probe
ships off; see "Quick Local Check".

## API Keys

Store API keys with the operating system's credential tool. Do not paste keys
into a shell command, the terminal UI, `config.yaml`, or a tracked file.

On macOS, run the interactive key bootstrap. The script prompts without putting
the value in shell history or a child process's arguments:

```bash
bash macos/setup-cyclaw-keys.sh
```

On Windows, store each provider key with the interactive Credential Manager
helper:

```powershell
.\powershell\CyClaw-CredMan-Set.ps1 com.cgfixit.cyclaw.grok-api-key
.\powershell\CyClaw-CredMan-Set.ps1 com.cgfixit.cyclaw.anthropic-api-key
```

If the key is missing, CyClaw stays local and reports that the online provider
is unavailable.

## Config Settings

In `config.yaml`:

```yaml
app:
  mode: "hybrid"  # SHIPPED DEFAULT — online fallback choices reachable; set "offline" to hard-disable them
```

Grok has its own provider switch:

```yaml
models:
  grok:
    enabled: true    # shipped default; set false to disable Grok regardless of mode
    base_url: "https://api.x.ai/v1"
    model: "grok-4.5"
```

Claude has its own provider switch:

```yaml
models:
  claude:
    enabled: true    # shipped default; set false to disable Claude regardless of mode
    base_url: "https://api.anthropic.com/v1"
    model: "claude-sonnet-5"
```

Model ids drift; re-check `config.yaml` and the vendor model catalogs before
enabling either provider in production.

Privacy defaults stay conservative:

```yaml
policy:
  fallback:
    require_user_confirm: true
    send_local_context_to_grok: false
    send_local_context_to_claude: false
```

That means CyClaw asks first, and by default it does not send local vault
context to either online provider. The soul/personality preamble is never
forwarded by the external fallback nodes. Enabling a context-forwarding flag
sends a bounded selection of retrieved text and reports those sources; treat
that flag as a separate privacy decision.

Confirmation is necessary but does not guarantee a provider call. The graph
pins online destinations to the provider's API host, and the optional
[`pre-action hook`](../security-philosophy/numbat_pre_action_gate.md) can deny
a confirmed call. `policy.external_call_limits` also caps the combined
Grok/Claude POST attempts in durable UTC daily/monthly windows. Retries
consume attempts; exhausted limits or an unavailable ledger refuse egress.
The attempt ledger is separate from provider-reported token usage in
[`spend/README.md`](../../spend/README.md).

## When to Use Online Fallback

Confirm online fallback after a vault miss only when the question is safe to
send, the user understands the disclosure, and the selected provider has a key.

Prefer offline best effort when the question includes private client material,
credentials, internal notes, sensitive business details, or anything that should
stay local.

## What the Buttons Mean

When CyClaw cannot confidently answer from the vault, the terminal offers:

- **No — Stay Offline** (labelled just **Stay Offline** when no online
  provider button is available): keep everything local and answer as well as
  possible.
- **Send to Grok**: confirm this question for Grok.
- **Send to Claude**: confirm this question for Claude.

Provider buttons come from the gateway's `available_providers` response, so
disabled providers and providers without a key are not offered. The remaining
destination, hook, budget, and transport checks still apply after a click.

Choosing an online provider is a one-query decision. It does not permanently
turn on online mode.

## Safety Rules That Still Apply

- Retrieval happens before any local or online model is used.
- Online providers are never used without explicit user confirmation.
- All paths still write to the audit log.
- Soul/personality changes still require a human reason and are not performed by
  online fallback.
- CyClaw still binds to `127.0.0.1` for local use.

## Quick Local Check

After changing settings, `/health` shows `mode` and local-backend health. It
does **not** report Grok/Claude status unless you opt in with
`api.health_probe_external_providers: true` (ships `false` — `/health` is
unauthenticated and unrate-limited, so probing there is operator-triggerable
third-party egress). With the probe enabled, a missing key surfaces as
`grok_api`/`claude_api` unavailable — never as the key value.
