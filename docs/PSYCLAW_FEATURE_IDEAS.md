# PsyClaw — Feature Ideas for Regulated SMBs

CyClaw began as **PsyClaw**, an offline-first RAG assistant aimed at small and
mid-sized businesses that operate under real compliance pressure — law firms,
psychology/therapy practices, medical/dental offices, and accounting shops.
These are organizations that *want* AI leverage but cannot tolerate client data
leaving the building or landing in a third-party model's training set.

The product's whole value proposition is its security topology: RAG-first,
topology-as-policy, triple-gated external calls, audit convergence, and soul
governance (see `CLAUDE.md` → *Security Invariants*). Every feature idea below is
evaluated against that posture — **a feature that erodes the invariants is not
worth shipping**, no matter how marketable.

The proposals are ordered by leverage-to-risk ratio. The first is **shipping in
this PR**; the rest are roadmap.

---

## 1. Audit / compliance summary endpoint  ✅ shipping now

**What:** `GET /audit/summary` — an API-key-gated, read-only endpoint that returns
aggregate metrics over the audit log: total events, event breakdown, RAG-query
count, score distribution (avg/min/max), retrieval-mode mix, model-usage
breakdown, and external-LLM escalation count.

**Why it matters for the market:** Regulated SMBs are periodically asked — by
auditors, malpractice insurers, bar associations, or HIPAA risk assessments — to
*demonstrate* how an AI tool is used. "How many queries went to an outside model
last quarter?" is a question a managing partner needs to answer with evidence,
not a shrug. This endpoint produces that evidence on demand.

**Why it's safe:** It exposes **aggregates only**. The audit log already persists
SHA-256 query hashes rather than plaintext (see `utils/logger.py`), and the
summary deliberately drops even those — no `query` field, no hashes, no
per-record rows. There is therefore **no new data egress**: it surfaces counts
that already exist on disk, behind the same API key that gates soul mutations.
It is built directly on the existing `metrics.py` aggregation
(`compute_metrics`), so the CLI and the API report identical numbers from one
code path.

**Roadmap extension:** a signed PDF/CSV "evidence pack" (hash-chained, timestamped)
for HIPAA / SOC 2 audit binders. Same aggregates, durable export format.

---

## 2. Retention & right-to-erasure tooling

**What:** A config-driven purge of audit and interaction records older than a
configurable `retention.ttl_days`, exposed as a CLI (`cyclaw-retention`) and an
optional scheduled task. Reuses the TTL concept already present in the
personality/interaction store.

**Why it matters:** HIPAA, GDPR (for any EU-adjacent clients), and most state bar
record-retention rules require both a *defined retention period* and a
*defensible deletion process*. "We keep audit logs forever" is a liability, not a
feature — it expands the blast radius of any future breach and conflicts with
data-minimization mandates.

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

**Why it matters:** Law firms live and die by conflict-of-interest checks and
ethical walls (ABA Model Rule 1.10). Being able to attribute AI usage to a matter
— "show me all assistant activity on the Acme acquisition" — turns CyClaw from a
generic tool into something that fits a firm's existing matter-centric workflow,
which is a strong differentiator at the point of sale.

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

For this market, **trust is the product**. Each idea above is shaped so that the
security invariants stay intact: nothing here introduces a new external call, a
new plaintext persistence path, or an autonomous destructive action. Features that
can't clear that bar belong in a different product.
