# PsyClaw — Feature Ideas for Regulated SMBs

CyClaw began as **PsyClaw**, an offline-first RAG assistant aimed at small and
mid-sized businesses that operate under real confidentiality pressure: law
firms, psychology/therapy practices, medical/dental offices, and accounting
shops. These organizations are plausible users for local AI governance because
client data, privilege, and approved-tool boundaries matter. That is an ICP
hypothesis, not validated demand.

The product's whole value proposition is its security topology: RAG-first,
topology-as-policy, triple-gated external calls, audit convergence, and soul
governance (see `CLAUDE.md` → *Security Invariants*). Every feature idea below is
evaluated against that posture — **a feature that erodes the invariants is not
worth shipping**, no matter how marketable.

Evidence labels used below:

- **Repo-backed fact:** implemented in current CyClaw code.
- **Market signal:** supported by external reporting or professional guidance,
  but not proof that buyers will pay.
- **Inference:** plausible from the product and market facts.
- **Hypothesis:** needs discovery calls or a paid pilot before being treated as
  business evidence.

The proposals are ordered by leverage-to-risk ratio. The first is implemented in
current CyClaw; the rest are roadmap hypotheses.

---

## 1. Audit / compliance summary endpoint

**What:** `GET /audit/summary` — an API-key-gated, read-only endpoint that returns
aggregate metrics over the audit log: total events, event breakdown, RAG-query
count, score distribution (avg/min/max), retrieval-mode mix, model-usage
breakdown, and external-LLM escalation count.

**Evidence level:** Repo-backed fact for the endpoint and aggregate audit
metrics. Market signal for the regulated-SMB need to demonstrate AI usage.

**Why it matters for the market:** Regulated SMBs may be asked by auditors,
malpractice insurers, bar associations, or HIPAA risk assessments to explain how
AI tools are used. "How many queries went to an outside model last quarter?" is
a concrete governance question this endpoint can help answer. It is operational
evidence, not a substitute for legal advice, SOC 2, or a formal compliance
program.

**Why it's safe:** It exposes **aggregates only**. The audit log already persists
SHA-256 query hashes rather than plaintext (see `utils/logger.py`), and the
summary deliberately drops even those — no `query` field, no hashes, no
per-record rows. There is therefore **no new data egress**: it surfaces counts
that already exist on disk, behind the same API key that gates soul mutations.
It is built directly on the existing `metrics.py` aggregation
(`compute_metrics`), so the CLI and the API report identical numbers from one
code path.

**Roadmap extension:** a signed PDF/CSV "evidence pack" (hash-chained,
timestamped). Treat this as a design hypothesis until the threat model defines
where the chain head is anchored, how crash recovery works, and what the export
can prove.

---

## 2. Retention & right-to-erasure tooling

**What:** A config-driven purge of audit and interaction records older than a
configurable `retention.ttl_days`, exposed as a CLI (`cyclaw-retention`) and an
optional scheduled task. Reuses the TTL concept already present in the
personality/interaction store.

**Evidence level:** Inference. Retention discipline is a credible regulated-data
need, but this specific CyClaw feature has not been validated with buyers.

**Why it matters:** Regulated organizations often need a defined retention period
and a defensible deletion process. "We keep audit logs forever" can be a
liability, not a feature: it expands the blast radius of a future breach and can
conflict with data-minimization expectations.

**Security considerations:** Deletion must be append-only-log-aware (rewrite to a
new file + `os.replace`, never in-place truncation that could corrupt a
concurrent write), must itself emit an audit event recording *that* a purge ran
(count + cutoff, never the deleted content), and must be gated so it cannot run
autonomously without an explicit operator action — mirroring the soul-governance
invariant (no autonomous destructive mutation).

---

## 3. Matter / client tagging + conflict wall (law-firm specific)

**What:** An optional per-query `matter_id` / `client_tag` that flows into the
audit trail as a *tag dimension*, plus a lightweight "conflict wall" check that
can flag when the same engagement is being queried across walled-off teams.

**Evidence level:** Hypothesis. This may fit law-firm workflows, but it needs
discovery with actual firm operators before it is treated as a sales advantage.

**Why it matters:** Law firms manage conflict-of-interest checks and ethical
walls. Being able to attribute AI usage to a matter — "show me all assistant
activity on the Acme acquisition" — could make CyClaw fit a matter-centric
workflow. Whether that changes willingness to pay is unvalidated.

**Security trade-offs (the hard part):** Tags are *metadata about* sensitive
matters and must be treated with the same care as the queries themselves. The
safe design keeps tags **out of any raw-text persistence path** — store a
salted hash of the tag in the audit log (consistent with the existing query-hash
discipline) so aggregation and filtering still work without writing client names
to disk. The conflict-wall check should be a *local* set-membership test, never
an external lookup. This one is explicitly **roadmap, not near-term**: it touches
the audit schema and deserves its own design review against the five invariants
before any code lands.

---

## Guiding principle

For regulated SMBs, trust claims need evidence. Each idea above is shaped so the
security invariants stay intact: nothing here should introduce a new external
call, a new plaintext persistence path, or an autonomous destructive action.
Features that cannot clear that bar belong in a different product. Features that
cannot clear discovery belong in a backlog, not a build plan.
