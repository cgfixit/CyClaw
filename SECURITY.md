# CyClaw Security Policy

> **Two files, one policy.** This copy owns the **security model summary** and the **Accepted Dependency Risks** register below — the acceptances `requirements.txt`, `.trivyignore.yaml`, `.osv-scanner.toml`, and the `pip-audit` workflow all encode. The full reporting, triage, severity, and coordinated-disclosure process lives in [`.github/SECURITY.md`](.github/SECURITY.md), which is the copy GitHub displays (`.github/` wins the community-health precedence). Update the file that owns the section rather than copying it across.

## Reporting a Vulnerability

Open a private security advisory on GitHub ([CGFixIT/CyClaw](https://github.com/CGFixIT/CyClaw/security/advisories)) or contact the maintainer via [cgfixit.com](https://cgfixit.com). Do not open public issues for exploitable findings — on a public repository every issue is public the moment it is filed. Full process: [`.github/SECURITY.md`](.github/SECURITY.md).

## Security Model (Summary)

CyClaw is an **offline-first, loopback-only** local AI gateway. The enforced invariants:

1. **RAG-first** — `retrieve` is the unconditional LangGraph entry node; no bypass edge exists.
2. **Topology = policy** — routing is done by score gates in graph edges, never by prompts.
3. **Triple-gated external access** — Grok/Claude require `app.mode=="hybrid"` AND `models.<provider>.enabled` AND per-query human confirmation. The shipped config satisfies the first two gates for both providers; the per-query confirmation cannot be pre-set, and a usable provider key is still required at the call site.
4. **Audit convergence** — every path terminates in `audit_logger` (keyed HMAC-SHA256 query fingerprints, PII + secret redaction, append-only JSONL).
5. **Soul governance** — identity evolution requires a human-authored reason; atomic writes; SHA-256 drift detection on startup.
6. **Out-of-band connectors** — `agentic/`, `sync/`, `guardrails/` are never imported by `gate.py`, `graph.py`, or `mcp_hybrid_server.py`. `sync/` and `agentic/` ship disabled and run via audited argv-list subprocess shims. Guardrails ships enabled with a required NeMo dependency. Missing or failed live NeMo checks run deterministic input and soul-leak checks on every answer route and record `guardrail_degraded`. Grounding remains local-only. A fallback refusal also records `guardrail_blocked`; an unexpected wrapper error ends generation without replay. These checks cannot grant a route. Explicit `guardrails.enabled: false`, or an absent block, leaves the graph guards as pass-through. Agentic verification containment is **best-effort** software (`agentic/executor/runner.py`), not a network namespace.
7. **No unsolicited secondary telemetry** — every vendor telemetry/analytics path is disabled before the dependency that reads it initializes: canonical env maps (`utils/telemetry_kill.py`) applied at import time by every Python entry point AND delivered as literal environment at every process boundary (Docker ENV, launchers, generated launchd plists / Windows tasks / cron lines, verifier and `gh` children), plus the post-import ONNX Runtime API call at the load seams. `gate.py` prints a verification table at startup; the other appliers enforce silently and are pinned by tests + the `otel-hardening` checker. Stated precisely: these controls silence telemetry readers — they are **not** a general network kill switch, and CyClaw's *intentional* egress is governed by its own gates (see **Egress classification** below).
8. **Loopback binding** — `127.0.0.1:8787` (gateway) and `127.0.0.1:11434` (Ollama); API-key gate on all mutating endpoints; per-IP rate limiting; strict security headers + TrustedHost.

## Accepted Dependency Risks

These are tracked, deliberate exceptions — re-reviewed at every release and enforced via the `pip-audit` CI workflow.

### chromadb 1.5.9 — CVE-2026-45829 / [PYSEC-2026-311](https://osv.dev/vulnerability/PYSEC-2026-311) (Critical) and siblings CVE-2026-45830 / CVE-2026-45831 / CVE-2026-45833

- **What they are:** the Chroma **Python FastAPI server** (`chroma run` / `HttpClient` / `/api/v2`) surface. No upstream patch available for 1.5.9 as of 2026-08-26.
  - CVE-2026-45829: pre-auth RCE — embedding-function config is instantiated before the auth check (`trust_remote_code` passthrough).
  - CVE-2026-45830 ([GHSA-2wm9-hf6c-p5cr](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr)): authenticated IDOR — any authenticated HTTP user can read/write/update/delete any collection.
  - CVE-2026-45831: SimpleRBACAuthorizationProvider evaluates permissions without verifying tenant/database/collection scope.
  - CVE-2026-45833: authenticated code injection via embedding-function config for a caller with `UPDATE_COLLECTION` (post-auth sibling of 45829).
- **Why accepted:** CyClaw never runs the Chroma server. It uses the **embedded `PersistentClient`** exclusively (path from `config.yaml`), in-process, with `anonymized_telemetry=False` and no `trust_remote_code`. There is no Chroma network listener, no SimpleRBAC, and no `/api/v2` to attack; the vulnerable code paths are unreachable in this deployment. pip-audit on main first reported 45830/45831/45833 on 2026-08-25; they share the already-accepted 45829 HTTP-server surface.
- **Last reviewed:** 2026-10-04 against the OSV API for `chromadb==1.5.9`. All four advisories remain active with no fixed version. OSV-Scanner and Trivy suppressions expire on 2026-11-01.
- **Telemetry at this pin:** chromadb 1.5.9's PostHog product-telemetry path is **dead code** (the `posthog` extra is no longer a dependency; `Settings(anonymized_telemetry=False)` is belt-and-suspenders). The live kill for Chroma's *separate* OTel exporter path is `CHROMA_OTEL_GRANULARITY=none` in `utils/telemetry_kill.py`. A chromadb bump that reintroduces a live PostHog SDK is an explicit re-review trigger, not "the flag is still false so we are fine."
- **Guardrails:** any future change introducing `chromadb.HttpClient` or a standalone Chroma server MUST be treated as a security regression and re-open this assessment.
- **Review date:** next chromadb release or 2026-10-01, whichever comes first.

### nltk 3.10.3 — pin bump (closes the 3.10.2 CVE cluster)

- **Pin:** `nltk==3.10.3` in `pyproject.toml`, `requirements.txt`, `constraints.txt`, and `environment.yml`. Dockerfile installs from those manifests.
- **Why bumped:** [#1256](https://github.com/cgfixit/CyClaw/issues/1256). CyClaw-reachable finding is [CVE-2026-81722](https://osv.dev/vulnerability/CVE-2026-81722) (PorterStemmer O(n²) DoS on a long run of `y` plus a matching suffix). `retrieval/stemmer.py` calls `PorterStemmer.stem()` on every keyword query and at index time. The rest of the 3.10.2 cluster (CVE-2026-79675 / 78680 / 79657 / 79676 / 79674 / 78682 / 81726) is the same unpatched pin; those APIs (Stanford JVM wrappers, Graphviz `dot`, pickle loaders, corpus readers, `nltk.data.load` / downloader) are not imported here.
- **Still true:** CyClaw never calls `nltk.data.load()` and never loads punkt. Tokenization stays on `_WORD_RE`. The old punkt path-traversal (CVE-2026-12243 / PYSEC-2026-597) remains unreachable; `.trivyignore` / `pip-audit` entries for it stay until a post-bump scan proves they are dead.
- **Defense in depth:** `retrieval/stemmer.py` caps tokens at 256 chars (`_MAX_TOKEN_CHARS` + bounded `_WORD_RE`) before `PorterStemmer.stem()`. That is not a substitute for the 3.10.3 pin.
- **Guardrails:** any future change introducing `nltk.data.load()`, `nltk.download()`, `punkt`/`word_tokenize`, or the model-artifact APIs below MUST be treated as a security regression and re-open this assessment.
- **Accepted 2026-09-04; reviewed 2026-10-04:** [PYSEC-2026-3740](https://osv.dev/vulnerability/PYSEC-2026-3740) (alias [CVE-2026-81726](https://nvd.nist.gov/vuln/detail/CVE-2026-81726) / [GHSA-8mgp-746c-j5xp](https://github.com/advisories/GHSA-8mgp-746c-j5xp)). The OSV API still reports this as the sole finding for `nltk==3.10.3`, with no fixed version. Surface is unused model-artifact I/O (`TransitionParser.train`/`parse`, `AveragedPerceptron.save`/`load`, `PerceptronTagger.save_to_json`, `save_maxent_params`), not `PorterStemmer`. `pip-audit.yml` ignores the PYSEC id only (the id that scanner prints). OSV-Scanner and Trivy do not suppress it. Drop the pip-audit ignore when a patched nltk ships.
- **Review date:** next nltk release or 2026-10-01, whichever comes first.

## Accepted Workflow Risks

These are deliberate GitHub Actions exceptions — documented so a dismissed code-scanning alert is not the only record.

### Alert 1726 — `actions/untrusted-checkout` in `codex-apply-fixes.yml` (won't fix, 2026-10-04)

- **What it is:** CodeQL `actions/untrusted-checkout/high` on the candidate job's checkout of the approved PR head (`ref: needs.gate.outputs.head_sha`) inside a workflow that can later execute code on that tree. Trigger surface includes `issue_comment` / `pull_request_review_comment` (privileged relative to a plain `pull_request` workflow).
- **Why accepted:** Codex must run against the exact owner-approved head to apply fixes. The job cannot substitute the default branch for the candidate tree.
- **Mitigations in place:**
  - Owner-only + same-repo gates before any checkout (`github.actor == github.repository_owner`, head repo must equal `github.repository`).
  - Candidate checkout uses `persist-credentials: false` and a read-only `contents: read` job token.
  - Apply-fixes prompt is loaded from a **second** checkout of the default branch into `$RUNNER_TEMP`, never from the PR tree.
  - Publication runs on a **separate** job/runner and consumes only a data patch — never candidate `.git` state, hooks, or local action definitions (see workflow header).
- **Residual:** A future workflow edit that re-introduces credentialed checkout of untrusted code, drops the owner/same-repo gate, or executes PR-supplied actions/scripts under a write token voids this acceptance. Re-open alert 1726 (or a successor) rather than dismissing again without updating this section.
- **Related standing control:** `pr-review.yml` documents its `pull_request_target` trigger with an inline `zizmor: ignore[dangerous-triggers]` rationale (trusted base; owner-only same-repo; candidate code never executed).
- **Last reviewed:** 2026-10-05 against alert [1726](https://github.com/cgfixit/CyClaw/security/code-scanning/1726) on main `b6ecf6ae`.
- **Review date:** next change to `codex-apply-fixes.yml` gate/candidate/publish jobs, or 2026-11-01, whichever comes first.


## Verification

- `python -m pytest tests/ -q` — full suite (mocked externals; no live services needed)
- `pip-audit -r requirements.txt -r requirements-test.txt` — dependency CVE sweep (also runs in CI)
- `python scripts`/swarm verification harness — config invariants, telemetry kill, due-diligence invariants, terminal contract
- Network audit: zero non-loopback connections expected in offline mode (see telemetry kill-switch docs in `docs/security-philosophy/cyclaw_telemetry_kill.env`)
- `python3 .claude/skills/otel-hardening/check_otel.py --strict` — telemetry-kill value oracle, boundary delivery, and egress-classification sweep; `bash .claude/skills/otel-hardening/verify.sh` runs its 21-scenario mutation self-test

## Egress classification

Every component that can touch a network carries exactly one class — the full
machine-readable inventory (with official source URLs, affected versions, and
review dates) lives in `.claude/skills/otel-hardening/check_otel.py`, whose
strict mode fails when a new dependency, executable, connector, scheduled job,
or launcher lands unclassified:

1. **Unsolicited telemetry/analytics, disabled via an official control** —
   LangSmith/LangChain tracing, ChromaDB PostHog + legacy 1.5.9 `CHROMA_OTEL_*`
   OTel, huggingface_hub's telemetry ping, NeMo Guardrails usage stats,
   ONNX Runtime (env `ORT_DISABLE_TELEMETRY=1` pre-import for the
   non-Windows 1DS path added in v1.29.0, plus
   `onnxruntime.disable_telemetry_events()` at the load seams — on Windows the
   ETW path only leaves the box when an external trace session collects it,
   the API cannot undo an init-time event, and absolute suppression requires a
   `--no_telemetry` private build CyClaw does not claim), the generic OTel SDK
   (with `OTEL_CONFIG_FILE`/`OTEL_EXPERIMENTAL_CONFIG_FILE` removed outright
   because declarative config outranks the SDK-disable values), GitHub CLI
   usage telemetry (`GH_TELEMETRY=false` forced on every `gh` child), and
   PowerShell host telemetry (`POWERSHELL_TELEMETRY_OPTOUT=1`, which pwsh
   reads once at its own startup — the installed cmd shim and generated task
   wrappers set it *before* the `powershell` line; setting it inside a running
   host cannot un-send that host's startup event).
2. **Ancillary update/version checks (egress, not telemetry)** — gh update
   notifiers, PowerShell update check, pip's version check, the hf CLI's
   update check and Homebrew analytics (both shell-only: no CyClaw code
   launches those programs; `macos/setup-from-clone.sh` exports
   `HOMEBREW_NO_ANALYTICS=1` before its own `brew` calls). Kept in a separate
   map (`UPDATE_CHECK_OPT_OUT`) so no report counts them as telemetry.
3. **Intentional, policy-gated feature traffic** — triple-gated Grok/Claude
   cloud fallbacks, the gated cloud-planner adapters, Telegram and OpenTweet
   (first-party httpx clients performing intentional remote API operations;
   there is no installed vendor SDK and therefore no SDK telemetry key to
   set), rclone/Dropbox corpus sync, operator-configured SQL endpoints, the
   and the one-time embedding-model
   bootstrap fetch (`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` stay conditional
   on the model being cached, or on the opt-in
   `models.embeddings.offline_after_index` flag plus a completed retrieval
   index already on disk — #1255 Phase B, default `false`). Never mislabeled
   as telemetry, never blocked by the kill maps.
4. **Local-only observability/storage** — `audit.jsonl`, `spend.jsonl`, and
   the Numbat projection (`logs/numbat-events.ndjsonl`): a **second sensitive
   local log**, not telemetry — every event carries hostname/username/uid
   endpoint metadata; it ships `numbat.enabled: true` and is disabled with
   `numbat.enabled: false`; no runtime HTTP sink exists or is implicitly
   configured, and it never belongs in the env kill map. Ollama traffic is
   loopback inference; the daemon's own cloud/web features are daemon policy —
   local-only mode requires `OLLAMA_NO_CLOUD=1` (or `disable_ollama_cloud`)
   set on the independently-running daemon, then a daemon restart.
5. **No mechanism found (negative findings, dated in the inventory)** — LM
   Studio (no documented telemetry env switch; its updater/model/cloud
   operations remain app-level policy), fastembed (no telemetry of its own;
   its first-use CDN model fetch is functional egress when a NeMo
   feature invokes that loader; active gateway check flows need no
   embedding fetch), uv, git (documented out of the overlay: it reads none of the
   canonical names), the vendored Unslop scanners, and the core
   web/runtime/dev libraries.

`CYCLAW_TELEMETRY_KILL` no longer exists: it was set in the Docker surfaces
but read by no code — a decorative marker advertising enforcement that
Python-side maps actually provided. The real canonical values now ride the
image ENV instead.
