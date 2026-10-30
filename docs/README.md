# `docs/` — documentation map

Current guides, dated evidence, and proposals. Code outranks prose;
`config.yaml` owns runtime tunables.

## Start here

| Document | Owns |
|---|---|
| `THREAT_MODEL.md` | Trusted-operator, loopback, single-tenant scope and amendments. Read before security changes. |
| `../setup-guide.md` | Canonical install/run guide (Windows · macOS · Linux). `! How-To-Guides/setup-guide.md` and `work/SETUP.md` are pointers only. |
| `../CLAUDE.md` / `../AGENTS.md` | Operating contract for agents (invariants, traps, commands). |
| `../INVARIANTS.md` (repo root) | Which guarantee is enforced by code vs. convention, and the test pinning each. |
| `changelog.txt` | Change history over time. |
| `GITHOOKS.md` | Tracked hook setup, commit/push blocks, operator overrides, private patterns, and reuse. |

## Subsystem deep-dives

| Document | Owns |
|---|---|
| `SYNC_README.md` | Dropbox corpus sync design + setup. |
| `channels/TELEGRAM_DESIGN.md` | Telegram channel architecture, T1–T4 phase gates. |
| `channels/OPENTWEET_DESIGN.md` | OpenTweet X channel: weekly OOB poster, draft-default, I6 isolation. |
| `agentic/AGENTIC_README.md`, `agentic/FSCONNECT_WRITE_ENABLEMENT_PLAYBOOK.md`, `agentic/FSCONNECT_SECURITY_REVIEW_CHECKLIST.md` | Out-of-band connectors (fsconnect, netconnect): user guide, fsconnect write enablement and its security sign-off (binding). |
| `AUTHENTICATION_DESIGN.md` | Per-user sessions, `/auth/*`, `/query` credentials, TLS/bind guard, and admin/operator/audit RBAC. |
| `memory/` | Optional memory subsystem plan and README. |
| [`../spend/README.md`](../spend/README.md) | Online-LLM token ledger: what `logs/spend.jsonl` records, why dollars are derived at read time, and how `cyclaw-metrics` reports them. |
| `EVALS.md` | Retrieval gate, dogfood, cloud/local judges, calibration, and measured limits. Run records: `audits/`. |
| `DOCKER.md`, `SECCOMP_EBPF_HARDENING.md`, `POSTGRES_BACKEND.md` | Deployment: containers, hardening (see also `../deploy/README.md`), Postgres backends. |
| `m5-48gb-coding-expectations.md` | Local-model doctrine for the shipped Ollama tag: context budget, timeouts, and the no-stall arithmetic. The only doc `doc-sync`'s D7 check cross-references against `config.yaml` + `macos/ollama-mlx.env`. |
| `ARCHIVE_AND_ROADMAP.md` | Retirement decisions and exact historical versions; [remaining work](plans/remaining_work.md) separates active tracking from deferred proposals. |
| [`online-llm/readme.md`](online-llm/readme.md) | Provider contracts, consent, and billing. |
| [`NeMo/README.md`](NeMo/README.md), [`../guardrails/README.md`](../guardrails/README.md) | Default-enabled guardrails, required NeMo installation, deterministic fallback, route scope, and inactive model-assisted rails. The dated [Track B record](audits/2026-10-03-nemo-track-b.md) separates runtime, Computer Use, and CI evidence. |
| [`security-philosophy/numbat_pre_action_gate.md`](security-philosophy/numbat_pre_action_gate.md), [`security-philosophy/numbat_secondary_evaluator.md`](security-philosophy/numbat_secondary_evaluator.md) | The default-off deny-only external-call hook and the separate default-on observation stream. |
| [`security-philosophy/pillow-risk-acceptance.md`](security-philosophy/pillow-risk-acceptance.md) | Historical record of the Pillow 12.3.0 acceptance, retired by pillow 13.0.0 / fastembed 0.9.1. The live register is `../SECURITY.md`. |
| [`../retrieval/README.md`](../retrieval/README.md), [`audits/2026-09-26-reranker-bakeoff.md`](audits/2026-09-26-reranker-bakeoff.md) | Token chunking, paired index generations, context-window gating, and the evidence for leaving reranker scores in shadow mode. |
| [`input-boundaries.md`](input-boundaries.md), [`../utils/unicode_data/README.md`](../utils/unicode_data/README.md) | Corpus file-size, symlink and decode limits, plus the normalization probes used to detect concealed instructions without rewriting accepted text. |
| [`../macos/README.md`](../macos/README.md), [`../powershell/README.md`](../powershell/README.md) | Native installer, launcher, credential-store and scheduler entry points; check the platform-specific guide before changing an installed service. |
| [`../tests/README.md`](../tests/README.md), [`../scripts/README.md`](../scripts/README.md), [`../.codex/README.md`](../.codex/README.md) | Verification lanes, contributor tooling, and the maintained Codex skill inventory. |

## Working / historical trees

| Tree | Convention |
|---|---|
| `audits/` | Historical evidence, scoped to each recorded revision and environment; not current acceptance. The [2026-10-23 reconciliation](audits/2026-10-23-docs-reconciliation.md) records cleanup provenance. |
| `memories/` | Ignored local agent memory plus a retained tracked June 30 audit. Ignore rules do not untrack historical content; obsolete zOld copies were removed. |
| `work/` | Planning and session records, including historical plans for removed agentic features. Check each record against current code before treating it as active work. |
| `plans/` | [Current tracking and proposal dispositions](plans/remaining_work.md), platform status notes, and historical design material. No plan grants implementation approval. |
| `mailtag/IMPLEMENTATION_PLAN.md` | **DRAFT** mailtag (provider-neutral email tagging) plan. Not shipped, not a graph node, not approved. Do not implement from this file without an explicit owner sign-off. |
| `analysis/`, `zIdeas/`, `zWork/`, `! How-To-Guides/` | Research, historical decisions and operator guides; check each document's status and source revision. |
| [`screenshots/`](screenshots/README.md) | Preserved media with current references distinguished from retired-harness captures. |
| [`console-ux.md`](console-ux.md) | Completed UX behavior and acceptance rationale, replacing the retired implementation plan. |
| [`bakeoff/local-model-bakeoff-2026-10-10.md`](bakeoff/local-model-bakeoff-2026-10-10.md) | Two ordered local-tag passes; no winner or shipped-tag change. Measurement script is not retained. |

Keep each `##` section understandable on its own. The indexer uses overlapping
token windows, not Markdown heading boundaries, and only configured corpus
paths are indexed. Cite `config.yaml` or `pyproject.toml` for defaults, and put
dated reports in `audits/`.
