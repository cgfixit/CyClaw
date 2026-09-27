# Numbat 0.2.0 CLI as CyClaw’s secondary evaluator

> **Status update — 2026-09-26 (issue [#1458](https://github.com/cgfixit/CyClaw/issues/1458)):** this remains a reference doc, but two readings of it need correcting.
>
> - `numbat.enabled: true` turns on the NDJSON projection **and nothing else**. The pre-action hook (`policy.fallback.pre_action_hook`) and the CEL monitor (`numbat.cel`) ship off, and the Numbat CLI scores events only in CI. "Numbat ships on" means "the forensic file is written", not "Numbat enforces".
> - The live stream did not satisfy the pinned 0.2.0 CLI. Mainline `/query` events carried `content_preview` over the schema's 200-character cap, and redacted `/ops/*` commands held a bare `<redacted>` the CLI's shell parser rejects. CI had not noticed because it scored committed fixtures and one live executor-jail run, never mainline `/query` or `/ops/*` output. [#1466](https://github.com/cgfixit/CyClaw/pull/1466) (merged 2026-09-26) fixed both, and added a blocking CI job that scores representative events from each producer family, written by CyClaw's own emitter code.
>
> The phase-by-phase state is in `docs/plans/NUMBAT_AND_ALWAYS_ON_ROADMAP.md`.

**Audience:** operators and reviewers who need to know what Numbat is *for* in this repo, not how to reimplement it.

**Code and `config.yaml` win.** This note explains the Numbat **0.2.0 CLI** CyClaw’s fixture job actually runs. That CLI evaluates **schema 0.3.0**. The emitter (`utils/numbat_emitter.py`) writes the same wire version (`schema_version: "0.3.0"`, `source_agent: "unknown"`). Release version and schema version are independent in upstream Numbat.

Related: `config.yaml` `numbat:` block, `logs/numbat-events.ndjsonl`, `.github/workflows/numbat-rules.yml` (committed fixtures plus a live executor-jail `rules test`), `docs/THREAT_MODEL.md`. `audit.jsonl` stays authoritative. Numbat is never imported by `gate.py` / `graph.py` / `mcp_hybrid_server.py` (I6).

---

## ELI5

Numbat is a security notebook for AI helpers: it writes down “the helper ran this command” or “it tried to read this file.” CyClaw already has its own diary (`audit.jsonl`). Numbat is a second, simpler copy of that diary. It started as a copy of only the *optional* helper stuff (tools, files, checks); it now also copies the main Q&A trail, so one notebook describes CyClaw end to end. Version **0.2.0** is the Numbat program CyClaw’s tests actually run, to ask: “does this notebook look like someone stealing a key or sending a secret out?” It does not decide what CyClaw answers, and if Numbat breaks, CyClaw is supposed to keep working.

---

## Tech 101

In CyClaw, Numbat is a **detector over a derived stream**, never an authority. `utils/numbat_emitter.py` appends NDJSON to `logs/numbat-events.ndjsonl` from two producer planes:

* **Action plane** — direct `emit_numbat_event` / `emit_numbat_command` calls when the executor, ops_runner, real_repo_loop, fsconnect, or sqlconnect fire.
* **Mainline plane** — `project_audit_record`, which projects every `audit.jsonl` record, including `POST /query`. This plane is newer than the “side-channel only” framing this doc originally carried.

The mainline plane does put the emitter on the request path, but never in front of an answer: it runs inside `audit_log`, at the terminal `audit_logger` node (I4), after the response is computed, and is fail-soft throughout — a projection failure degrades to a `logger.warning`. `gate.py` / `graph.py` / MCP still never import it at module scope; the projection reaches it by a lazy call-time import from `utils/logger.py` (I6 holds — `utils/` is shared). Privacy is inherited, not re-implemented: the record is projected *after* query hashing and recursive PII redaction, so raw query text reaches neither stream. The endpoint object is the exception to "inherited": `build_endpoint()` constructs it fresh on every event with hostname, username, and uid (plus an optional `NUMBAT_DEVICE_ID`), and no redaction pass touches it — which is exactly why the stream is a second *sensitive* local log (see Risks below) and why `numbat.enabled: false` is the whole disable story; no HTTP sink exists to configure. CI pins the **Numbat 0.2.0** binary and runs `numbat rules test --fixture` against committed fixtures that `build_event` produced, looking for rules like `secrets.read_private_key` and `exfil.curl_post_file`. The same job then runs the executor-jail pytest with that binary on PATH so live emitter output is scored, not only the committed files. Benefit: you get a vendor-shaped “did the agent do something nasty?” check without putting Numbat on the RAG path.

`rules test` uses per-type allowlists stricter than the published JSON schema: `command.exec` cannot carry `exit_code` / `file_path` / `duration_ms`. The emitter strips those from `command.exec` and writes outcomes as `command.result`.

---

## Expert

Numbat 0.2.0 is the **on-device rules evaluator** CyClaw uses as a fail-soft **EDR-style projection** of agent telemetry: a closed schema (`additionalProperties: false`), `source_agent=unknown`, CyClaw identity only in tags, dual-written beside the authoritative SHA-256/PII-redacted `audit.jsonl`. Purpose in this integration is **detection and CI attestation**, not enforcement — the pre-action hook (`policy.fallback.pre_action_hook`) ships disabled, and `numbat hook ...` cannot serve as its command: that subcommand speaks other agents' hook protocols, drops the provider and URL from CyClaw's payload, and exits 0 on errors (issue #1458; a working `engine: numbat` is in [#1467](https://github.com/cgfixit/CyClaw/pull/1467)); emitter `enabled: true` never raises into the LangGraph topology. Benefit: independent, replayable matching of high-signal agent TTPs (secret-file read, curl file-exfil) against a stable fixture contract, without expanding I1–I4 attack surface. Risks: the fixture job is `continue-on-error`, so a real hit there would not gate merge (#1466 added a blocking job that scores CyClaw's own emitter output); the stream is host-local and can include command/path residue, so it is a second sensitive log, not a privacy improvement; and `--expect-none` on a fixture plus one executor-jail pytest is containment evidence, not a proof that a determined child process cannot exfiltrate over a raw socket.
