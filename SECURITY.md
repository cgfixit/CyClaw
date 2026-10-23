# CyClaw Security Policy

> **Two files, one policy.** This copy owns the **security model summary** and the **Accepted Dependency Risks** register below — the acceptances `requirements.txt`, `.trivyignore.yaml`, `.osv-scanner.toml`, and the `pip-audit` workflow all encode. The full reporting, triage, severity, and coordinated-disclosure process lives in [`.github/SECURITY.md`](.github/SECURITY.md), which is the copy GitHub displays (`.github/` wins the community-health precedence). Update the file that owns the section rather than copying it across.

## Reporting a Vulnerability

Open a private security advisory on GitHub ([cgfixit/CyClaw](https://github.com/cgfixit/CyClaw/security/advisories)) or contact the maintainer via [cgfixit.com](https://cgfixit.com). Do not open public issues for exploitable findings — on a public repository every issue is public the moment it is filed. Full process: [`.github/SECURITY.md`](.github/SECURITY.md).

## Security Model (Summary)

CyClaw is an **offline-first, loopback-only** local AI gateway. Items 1–6 are the pinned security invariants, each with its test in [`INVARIANTS.md`](INVARIANTS.md) and its history in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md); items 7–9 are supplementary controls that sit beside them, not invariants:

1. **RAG-first** — `retrieve` is the unconditional LangGraph entry node; no bypass edge exists.
2. **Topology = policy** — routing is done by score gates in graph edges, never by prompts.
3. **Triple-gated external access** — Grok/Claude require `app.mode=="hybrid"` AND `models.<provider>.enabled` AND per-query human confirmation. The shipped config satisfies the first two gates for both providers; the per-query confirmation cannot be pre-set, and a usable provider key is still required at the call site.
4. **Audit convergence** — every path terminates in `audit_logger` (keyed HMAC-SHA256 query fingerprints, PII + secret redaction, append-only JSONL).
5. **Soul governance** — identity evolution requires a human-authored reason; atomic writes; SHA-256 drift detection on startup.
6. **Out-of-band connectors** — `agentic/`, `sync/`, `guardrails/`, `telegram/`, and `opentweet/` are never imported by the core six (`gate.py`, `gate_ops.py`, `gate_auth.py`, `gate_memory.py`, `graph.py`, `mcp_hybrid_server.py`), and never import them. `sync/` and `agentic/` ship disabled and run via audited argv-list subprocess shims. Guardrails ships enabled with a required NeMo dependency. Missing or failed live NeMo checks run deterministic input and soul-leak checks on every answer route and record `guardrail_degraded`. Grounding remains local-only. A fallback refusal also records `guardrail_blocked`; an unexpected wrapper error ends generation without replay. These checks cannot grant a route. Explicit `guardrails.enabled: false`, or an absent block, leaves the graph guards as pass-through. The agentic verification executor, its process sandbox, the GitHub coding loop and the SQL connector were removed in October 2026; `agentic/` now holds only the filesystem and passive network connectors, neither of which executes repository code (`docs/THREAT_MODEL.md`, nineteenth amendment).
7. **No unsolicited secondary telemetry** — every vendor telemetry/analytics path is disabled before the dependency that reads it initializes: canonical env maps (`utils/telemetry_kill.py`) applied at import time by every Python entry point AND delivered as literal environment at every process boundary (Docker ENV, launchers, generated launchd plists / Windows tasks / cron lines, `/ops/*`, rclone and pre-action-hook children), plus the post-import ONNX Runtime API call at the load seams. `gate.py` prints a verification table at startup; the other appliers enforce silently and are pinned by tests + the `otel-hardening` checker. Stated precisely: these controls silence telemetry readers — they are **not** a general network kill switch, and CyClaw's *intentional* egress is governed by its own gates (see **Egress classification** below).
8. **Loopback binding** — `127.0.0.1:8787` (gateway) and `127.0.0.1:11434` (Ollama); request bodies capped at `security.max_request_body_bytes` (1 MiB, 413 above it); per-IP rate limiting; strict security headers + TrustedHost. Operator routes (`/soul/*`, `/ops/*`, `/audit/summary`, `/memory/*`, `/query/export/html`) need `require_api_key`'s credentials: Bearer `CYCLAW_API_KEY` or the console cookie, both of which fail closed while the key is unset, or (with `auth.enabled`) an enabled admin's login, the one credential that works without the key; `/query`, `/index/build` (loopback peer + same-origin + no forwarding header, plus the key once set), `/console/session`, and the session-governed `/auth/*` routes have their own gates ([`INVARIANTS.md`](INVARIANTS.md) Rule 6, threat-model amendments fourteen, fifteen, and eighteen).
9. **Commit-time gate** — the tracked `.githooks/` (`_security.sh` + `security.conf`, installed by `scripts/ensure-githooks.sh`) refuse commits that carry secrets, private data, or protected-path edits, and refuse pushes that carry secrets or private data or rewrite a protected branch, unless an explicit operator override is set; a protected-path edit that reaches `pre-push` without the pre-commit hook gets a reminder only ([`docs/GITHOOKS.md`](docs/GITHOOKS.md)). A speed bump for people and agents, not a boundary: `gitleaks.yml` and the `main` ruleset are the controls.

## Accepted Dependency Risks

These are tracked, deliberate exceptions — re-reviewed at every release.
Python exceptions are encoded in the relevant pip-audit/OSV/Trivy configuration;
Debian image exceptions are encoded only in `.trivyignore.yaml` for Trivy.

### Debian 12 container libraries — issue #1629, expires 2026-11-01

- **Reviewed 2026-10-13:** the pinned `python:3.12-slim-bookworm` manifest
  `sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3`
  (linux/amd64) reproduces all 11 package findings with Trivy 0.72.0.
  Its installed dpkg metadata establishes the dependency chains below.
  These are temporary risk acceptances, not patched packages or proof that
  every possible use of these libraries is safe.

| Findings | Installed packages | Retaining dependency | Fixed version / decision |
| --- | --- | --- | --- |
| CVE-2026-88647, CVE-2026-88648, CVE-2026-67693 | `libgnutls30 3.7.9-2+deb12u7` | `apt` directly depends on GnuTLS | No bookworm or trixie fix; retain the base and time-limit the exception |
| CVE-2026-107708, CVE-2026-107778 (four packages each) | `libgssapi-krb5-2`, `libk5crypto3`, `libkrb5-3`, `libkrb5support0`, all `1.20.1-2+deb12u5` | `libnsl2` → `libtirpc3` → `libgssapi-krb5-2` → krb5 libraries | No bookworm or trixie fix; retain Python's native dependency chain and time-limit the exception |

- **Upstream status:** Debian lists all five as unfixed in both releases.
  For the GnuTLS [hostname](https://security-tracker.debian.org/tracker/CVE-2026-88647),
  [certificate constraints](https://security-tracker.debian.org/tracker/CVE-2026-88648),
  and [key usage](https://security-tracker.debian.org/tracker/CVE-2026-67693)
  reports, Debian also records that upstream does not consider them security
  issues under its policy. This is disputed classification, not a fix.
  The krb5 [KDC crash](https://security-tracker.debian.org/tracker/CVE-2026-107708)
  and [GSS-API acceptor crash](https://security-tracker.debian.org/tracker/CVE-2026-107778)
  are postponed in bookworm. CyClaw neither runs a Kerberos KDC nor accepts
  Kerberos/GSS-API credentials.
- **Why retain the packages:** the base contains neither curl nor libldap;
  removing those would not remove these findings. APT needs GnuTLS, and the
  Python base ships the `nis` extension alongside libnsl/libtirpc. Purging the
  libraries without checking native linkage can break the supplied interpreter.
  Both container healthchecks already use Python/httpx. Moving to trixie does
  not supply fixes for these advisories. Keep the matching builder/runtime
  digests, pinned CA bundle, and no-blanket-`apt-get upgrade` contract.
- **Scope and review:** `.trivyignore.yaml` limits each exception to the exact
  Debian package name and installed version, with expiry **2026-11-01**, aligned
  with the existing dependency review window. Review earlier on any base,
  authentication, native-library, or upstream-fix change. Remove an exception
  when its finding disappears; do not renew it without fresh image evidence.
  Trivy's `--show-suppressed --format json` exposes ignored findings for review;
  a green SARIF upload alone proves neither their absence nor remediation.
- **Tracking:** [#1629](https://github.com/cgfixit/CyClaw/issues/1629). Its GitHub
  alerts were already dismissed as false positives before this change; that
  state is not the evidence for this acceptance. Closing the sweep issue after
  merge records completed triage and an expiring exception, not an upstream fix.

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
- **Review date:** next chromadb release or 2026-11-01 (when the OSV-Scanner and Trivy suppressions expire), whichever comes first.

### nltk 3.10.3 — pin bump (closes the 3.10.2 CVE cluster)

- **Pin:** `nltk==3.10.3` in `pyproject.toml`, `requirements.txt`, `constraints.txt`, and `environment.yml`. Dockerfile installs from those manifests.
- **Why bumped:** [#1256](https://github.com/cgfixit/CyClaw/issues/1256). CyClaw-reachable finding is [CVE-2026-81722](https://osv.dev/vulnerability/CVE-2026-81722) (PorterStemmer O(n²) DoS on a long run of `y` plus a matching suffix). `retrieval/stemmer.py` calls `PorterStemmer.stem()` on every keyword query and at index time. The rest of the 3.10.2 cluster (CVE-2026-79675 / 78680 / 79657 / 79676 / 79674 / 78682 / 81726) is the same unpatched pin; those APIs (Stanford JVM wrappers, Graphviz `dot`, pickle loaders, corpus readers, `nltk.data.load` / downloader) are not imported here.
- **Still true:** CyClaw never calls `nltk.data.load()` and never loads punkt. Tokenization stays on `_WORD_RE`. The old punkt path-traversal (CVE-2026-12243 / PYSEC-2026-597) remains unreachable; `.trivyignore.yaml` / `pip-audit` entries for it stay until a post-bump scan proves they are dead.
- **Defense in depth:** `retrieval/stemmer.py` caps tokens at 256 chars (`_MAX_TOKEN_CHARS` + bounded `_WORD_RE`) before `PorterStemmer.stem()`. That is not a substitute for the 3.10.3 pin.
- **Guardrails:** any future change introducing `nltk.data.load()`, `nltk.download()`, `punkt`/`word_tokenize`, or the model-artifact APIs below MUST be treated as a security regression and re-open this assessment.
- **Accepted 2026-09-04; reviewed 2026-10-04:** [PYSEC-2026-3740](https://osv.dev/vulnerability/PYSEC-2026-3740) (alias [CVE-2026-81726](https://nvd.nist.gov/vuln/detail/CVE-2026-81726) / [GHSA-8mgp-746c-j5xp](https://github.com/advisories/GHSA-8mgp-746c-j5xp)). The OSV API still reports this as the sole finding for `nltk==3.10.3`, with no fixed version. Surface is unused model-artifact I/O (`TransitionParser.train`/`parse`, `AveragedPerceptron.save`/`load`, `PerceptronTagger.save_to_json`, `save_maxent_params`), not `PorterStemmer`. `pip-audit.yml` ignores the PYSEC id only (the id that scanner prints). OSV-Scanner suppresses `GHSA-8mgp-746c-j5xp` until 2026-11-01 (`.osv-scanner.toml`); Trivy does not suppress it. Drop the pip-audit ignore and the OSV ignore when a patched nltk ships.
- **Review date:** next nltk release or 2026-11-01 (when the OSV-Scanner suppression expires), whichever comes first.

### pillow 12.3.0 — 35 image-codec advisories (fix blocked by fastembed)

- **What they are:** decoder and encoder bugs that fire only when pillow opens or saves a crafted image: OOB reads/writes and a double free in TIFF/libImaging, GIF/APNG/PDF/XBM DoS and ReDoS, EPS Ghostscript command construction, BMP/MSP/Spider decompression-bomb bypasses, a quadratic PNG eXIf parse, Windows EMF/WMF sizing, `TarIO` negative size, and a heap overflow in the bundled libopenjp2 ([GHSA-78g4-xqwv-q3g8](https://github.com/advisories/GHSA-78g4-xqwv-q3g8)). All are fixed in pillow 13.0.0.
- **Why not bumped:** `fastembed` (via `nemoguardrails`) requires `pillow<13.0` in 0.8.1 and in 0.9.0, its latest release as of 2026-10-23. #1742 tried `pillow==13.0.0`; every install leg failed with `ResolutionImpossible`.
- **Only known attack vector: an image attachment.** CyClaw has no path that decodes one. The indexer reads `.md` files only (`corpus.extensions`), no CyClaw module imports `PIL`, and pillow is present only as an import-time transitive of fastembed and sentence-transformers, which CyClaw runs on text models. The one way an image can enter, Telegram media staging (`telegram.media`, shipped off), writes the attachment's bytes through the fsconnect CLI without decoding or indexing them.
- **Encoded in:** `pip-audit.yml` `PILLOW_IGNORES` (the 35 ids pip-audit printed on #1739, matching PyPI's advisory list for 12.3.0). OSV-Scanner and Trivy did not report them on #1739, so no suppression is added there.
- **Guardrails:** any change that decodes an attachment (for example a thumbnail, OCR, or EXIF strip in Telegram media staging or fsconnect), adds an image or PDF corpus extension, feeds images to a model, or imports `PIL` MUST re-open this assessment.
- **Review date:** next fastembed release (drop the ignores and take pillow 13 once its cap allows) or 2026-11-23, whichever comes first.

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

- `GROK_API_KEY=dummy python -m pytest tests/ -q` — full suite (mocked externals; no live services needed). CI runs it; agents verify per `CLAUDE.md` §5 instead
- `pip-audit -r requirements.txt -r requirements-test.txt` — dependency CVE sweep (also runs in CI)
- `python3 .claude/skills/invariant-guard/check_invariants.py`, `python3 .claude/skills/config-guard/check_config.py`, `python3 .claude/skills/dotenv-guard/check_dotenv.py` — static invariant, config, and secrets-handling checks; `tests/test_due_diligence_invariants.py` and `tests/test_terminal_contract.py` pin the gate, soul, scanner, and console contracts
- Network audit: zero non-loopback connections expected in offline mode (see telemetry kill-switch docs in `docs/security-philosophy/cyclaw_telemetry_kill.env`)
- `python3 .claude/skills/otel-hardening/check_otel.py --strict` — telemetry-kill value oracle, boundary delivery, and egress-classification sweep; `bash .claude/skills/otel-hardening/verify.sh` runs its mutation self-test

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
   usage telemetry (`GH_TELEMETRY=false` in every governed environment, so a
   `gh` the operator runs from one inherits it), and
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
   cloud fallbacks, Telegram and OpenTweet
   (first-party httpx clients performing intentional remote API operations;
   there is no installed vendor SDK and therefore no SDK telemetry key to
   set), rclone/Dropbox corpus sync, and
   the one-time embedding-model bootstrap fetch (`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` stay conditional
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
   embedding fetch), git's local subcommands (documented out of the overlay:
   it reads none of the canonical names), and the core web/runtime/dev
   libraries. The operator install and setup
   surface's own fetches are category 3, not here: the installers' `git
   clone`/`pull` of the repository, `pip` and `uv` index access in the installers, the Dockerfile,
   the lock-refresh scripts and the cloud venv driver, the Dockerfile's
   build-stage `apt-get` install, the setup script's `gh auth` calls (gh's own
   telemetry and update checks stay in categories 1 and 2), the confirmed Homebrew
   Python install, the confirmed Ollama model pull and the Ollama
   installer/download page, and the loopback readiness probes (`curl`, the
   Windows smoke suite's PowerShell HTTP cmdlets) -- all operator- or
   sandbox-initiated, never telemetry, pinned to their spawn sites by the
   `otel-hardening` checker.

`CYCLAW_TELEMETRY_KILL` no longer exists: it was set in the Docker surfaces
but read by no code — a decorative marker advertising enforcement that
Python-side maps actually provided. The real canonical values now ride the
image ENV instead.

## Sensitive paths and hook limits

Sensitive paths are listed in `.github/CODEOWNERS`; changes there are review-requested automatically.

Bidi and tag-character checks in `.githooks/_security.sh` skip a hit only when the file name matches the media-only `SEC_MEDIA_GLOBS` list (raster images, audio/video, fonts and PDF), the line is invalid UTF-8, and `iconv` is available. Archives, Office documents and executables are not exempt; valid UTF-8 media-looking text is reported too. Filename colons are encoded as `%3A` in scan records so they cannot spoof a media suffix; tag messages and raw-blob refs never receive the media exception. Renames scan destination bytes, so an unchanged media blob renamed to an executable or archive is checked under its new name. Secret patterns still run on every file. These are raw-byte scans, not archive unpacking or media decoding. Hooks remain a speed bump; CI remains the enforcement layer.

## Issue #1526 residual decisions (2026-10-12)

This register records the closure scope of [#1526](https://github.com/cgfixit/CyClaw/issues/1526).
It is not a new exhaustive security scan. Merge the linked implementation drafts
and require their platform checks before closing the umbrella.

| Concern | Disposition and boundary |
|---|---|
| TLS cookie deletion and public paths | Correct secure deletion attributes; redact paths containing spaces and UNC paths; retain distinct Windows corpus-relative citations. Implemented by [#1635](https://github.com/cgfixit/CyClaw/pull/1635); see [authentication design](docs/AUTHENTICATION_DESIGN.md). |
| Git origin and helper lifetime | **Moot since 2026-10-18:** the agentic clone workspace this row covered was removed (`docs/THREAT_MODEL.md`, nineteenth amendment); kept as the closure record. Independent origin pin and bounded helper-tree lifetime are owned by [#1630](https://github.com/cgfixit/CyClaw/pull/1630) (including startup/cleanup corrections), linked to [#1558](https://github.com/cgfixit/CyClaw/issues/1558). Require its checks and review; this umbrella does not duplicate that implementation. Global/system Git config and credential helpers remain operator-trusted. |
| Lock and wheel truthfulness ([#1631](https://github.com/cgfixit/CyClaw/pull/1631)) | Validate every maintained runtime/CI lock against its inputs, constraints and recorded hashes; stage whole refresh groups before publication; compare base wheel metadata. This detects drift, not reproducibility against a changing package index. Abrupt host failure during multi-file publication is detected by the stamp; it is not a filesystem transaction. |
| Codex patch publication (#1631) | Bound the patch before upload and after download; require the exact approved old head at the remote update and a single child commit. Same-repository gating is already present. Workflow trust/ruleset governance and alert 1726 remain recorded in #1558 and the workflow-risk register above; accepted alert status is not remediation. |
| Encrypted scheduled sync ([#1632](https://github.com/cgfixit/CyClaw/pull/1632)) | Retrieve only `RCLONE_CONFIG_PASS` at execution time from macOS Keychain or Windows Credential Manager; never write it into a schedule. Missing interactive unlock, inaccessible credentials or unavailable rclone must fail noninteractively. Linux automatic keystore retrieval is unsupported; secure operator-managed environment injection remains available. See [sync setup](docs/SYNC_README.md). |
| Verification confinement | **Moot since 2026-10-18:** the verification executor was removed (nineteenth amendment); kept as the closure record. Accept host-readable files and detached macOS descendants as documented limits; use trusted worktrees. Windows verification remains refused. No native isolation parity or hostile multi-tenant execution claim. Mirror preparation's cooperative time/disk limitation was dispositioned in #1557. |
| MSSQL read-only behavior | **Moot since 2026-10-18:** the SQL connector was removed (nineteenth amendment); kept as the closure record. Least-privilege DB roles are mandatory. ODBC access-mode hints and SQL screening are defense in depth; no deployed MSSQL enforcement evidence is claimed. Native integration validation is follow-up before expanding deployment claims. |
| Windows TLS private keys | [#1635](https://github.com/cgfixit/CyClaw/pull/1635) applies an owner-only protected DACL to temporary outputs before writing secret bytes; fail if restriction fails. Native Windows CI must validate the descriptor before merge. Administrator/backup privileges and pre-existing copies are outside this per-file control. |
| Cookie transmission to other ports | Accepted browser limitation: cookies cannot be port-scoped. Use a dedicated hostname and TLS when other local services are untrusted. Origin-bound tokens do not prevent theft and replay. |
| `key_configured` / 401 setup-state disclosure | Accepted low-impact configuration-state disclosure for the single-operator loopback service; no key value is disclosed. Revisit for remote or multi-tenant deployments. |
| `GET /auth/whoami` CSRF rotation | Accepted session-local behavior; clients must use the latest returned token. Multi-tab token ergonomics are optional research, not a bypass of CSRF checks. |
| CSP `style-src 'unsafe-inline'` | Accepted styling compatibility; `script-src 'self'`, output escaping and other headers remain required. A style nonce/hash migration is optional hardening. |
| Chroma and scanner acceptances | Existing time-bounded dependency register above remains authoritative; [#1255](https://github.com/cgfixit/CyClaw/issues/1255) owns the Chroma replacement/retention decision. #1556's DevSkim and scanner work is already closed. Do not renew advisory dates without a new review. |

Original F1–F14 mitigations and the remaining low-severity fixes landed in the
preceding linked PRs: shared secret policy and redaction, Unicode/SQL guards,
proxy/cross-site checks, bounded auth/graph pools, current-password verification,
external attempt budgets, private audit logs and HMAC fingerprints, COOP/no-store,
nonblocking protected filesystem reads, corpus size caps, scheduled OpenTweet
screening, private curl headers and temporary launcher logs. These controls retain
their documented limits: pattern screening is heuristic; attempt ceilings do not
measure dollar spend; operator configuration and code review remain trust inputs.
Request bodies are counted while streaming, including absent/false Content-Length.

Optional follow-up research: idle/reboot keystore availability under real
service identities, CSP styling migration, and browser multi-tab CSRF
ergonomics. (Host-read isolation, a Windows verification sandbox and MSSQL role
verification left this list when the executor and SQL connector were removed.) A live-provider transfer or installed-service
reboot test is not implied by disposable local-config or hosted CI evidence.
