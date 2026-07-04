# CyClaw × Atlanta Legal Personas: Cold-Outreach Positioning & Checklists

**Date:** 2026-07-04
**Extends:** `docs/analysis/2026-07-03_atl_small_law_market_memo.md` (outside-counsel market sizing, GA
regulatory hooks, MSP channel) and `docs/analysis/2026-07-03_tri_analysis_monetization_calibration.md`
(the calibration standard this doc is held to).

---

## Provenance & method — read this before the tables below

This doc was produced via a `deep-research` workflow (5 search angles → fetch top sources → verify →
synthesize) spun off to research two Atlanta-anchored buyer personas evaluating CyClaw: **Track A**
(new) in-house/corporate counsel and legal ops/compliance leads, and **Track B** (refresh) outside
counsel at solo-to-20-attorney firms, the persona the 2026-07-03 memo already covers in depth.

**Material limitation, disclosed rather than worked around:** this session's outbound egress proxy
rejected every fetch attempt to every source URL with `403` at the CONNECT layer — a policy-level
denial (confirmed via `/root/.ccr/__agentproxy/status`: `"kind":"connect_rejected","detail":"gateway
answered 403 to CONNECT (policy denial or upstream failure)"` for all 8 sampled hosts, including
`acc.com`, `gabar.org`, `fticonsulting.com`). Per this environment's own operating instructions, a
403/407 from the proxy is an organizational egress policy denial to be **reported, not retried or
routed around**. WebSearch itself succeeded and returned real, dated (2025–2026) titles/URLs/snippets;
only full-page fetch failed. **Consequence: nothing below could be read at its primary source this
session.** Every claim is tagged one tier down from the 2026-07-03 memo's standard:

- **[REPORTED-snippet]** — search-engine snippet only, primary page not independently fetched this
  session. Treat as a *lead to verify*, not a settled fact, before using it in an actual sales
  conversation or a more permanent doc.
- **[INFERENCE]** — derived from REPORTED-snippet claims, arithmetic/reasoning shown.
- **[SPECULATION]** — explicitly unverifiable this session.

**No willingness-to-pay evidence was found for either persona** — no signed contract, RFP win, or paid
pilot. Every stat below is demand-side/adoption-side (usage %, sentiment, event coverage). This is the
exact category error the tri-analysis doc flagged in the prior research round (treating adoption stats
as PMF/capture-side evidence); §5 below states plainly, for both tracks, that this gap is unresolved.

---

## Track A — In-house / corporate counsel (new persona)

### Positioning statement

In-house legal teams don't buy AI tools to "save time" — they buy them because a General Counsel can no
longer delegate AI-tool selection to IT or legal ops and then disclaim responsibility when it goes wrong;
courts are holding counsel personally accountable for AI-generated errors regardless of who picked the
vendor **[REPORTED-snippet: corporatecomplianceinsights.com, "AI Risk in 2026: 3 Critical Changes for the
General Counsel"]**. That reframes the sale from "here's a faster research tool" to "here's a tool whose
architecture you can defend to your own board, your customers' vendor-risk questionnaires, and — if it
ever comes to it — a regulator," which is a claim a contractual privacy promise (OpenAI/Microsoft's "we
don't train on your data") cannot make as cleanly, because it still requires the GC to trust and audit a
third party's data-handling *promise* rather than verify an architecture that never transmits data at
all. 2026 procurement-standards commentary specifically calls out that legal-tech vendors without SOC 2,
signed DPAs, and answered security questionnaires ready on day one **"are not ready for enterprise
procurement"** **[REPORTED-snippet: brightflag.com, "2026 Legal Ops & Legal Technology Predictions"]** —
so the pitch has to lead with the audit trail and data-boundary story, not features.

### Evidence base

| Claim | Tier | Source |
|---|---|---|
| GCs are increasingly held personally responsible for AI-tool errors regardless of who selected the vendor, pushing tool-selection authority up to the GC | REPORTED-snippet | corporatecomplianceinsights.com/ai-risk-2026-critical-changes-general-counsel |
| 2026 enterprise legal-tech procurement expects SOC 2 / DPAs / security questionnaires answered before a pilot, plus transparent per-seat pricing and real free trials | REPORTED-snippet | brightflag.com/resources/2026-legal-ops-legal-technology-predictions |
| GC legal-department budgets in 2025 are built in partnership with legal ops, aligned to broader business/finance goals — no hard sign-off dollar threshold found | REPORTED-snippet | axiomlaw.com/blog/2025-gc-trends-legal-budgeting-cost-savings |
| Corporate law departments' active GenAI use jumped to ~52% in 2025 vs ~23% the prior year (ACC survey) | REPORTED-snippet | acc.com/resource-library/generative-ais-growing-strategic-value-corporate-law-departments-survey-results |
| A *separate* 2026 report states 47% of corporate legal departments use GenAI in 2026, up from 23% in 2025 | REPORTED-snippet | wolterskluwer.com — "Legal Operations Trends 2026" |
| Majority of GCs report openness to AI across major legal use cases (contract review, investigations, compliance) — measures sentiment/openness, not spend | REPORTED-snippet | fticonsulting.com, "General Counsel Report" press release |
| Legal-ops job postings grew 23% YoY in 2025 (projected >50% in 2026) — legal ops is a formalizing function with its own tooling budget, a possible second buyer besides the GC | REPORTED-snippet | hirelegalops.com/resources/legal-ops-tools-2026 |
| 2026 legal-tech RFPs increasingly demand proof of data boundaries/governance/audit trails before signing | REPORTED-snippet | uslegalsupport.com/blog/2026-legal-tech-ai-trends |
| Legal-AI price bands referenced in vendor buyer's guides: ~$150–400/mo typical, up to ~$2,000/mo enterprise | REPORTED-snippet (vendor marketing — weakest tier) | gc.ai/blog/best-legal-ai-tools-for-in-house-counsel; spellbook.com/learn/legal-ai-tools |

**⚠️ Flag — reconcile before reuse:** the ACC (52%/23%) and Wolters Kluwer (47%/23%) figures share an
identical 23% prior-year baseline via two differently-cited sources. That's either the same underlying
survey cited two ways, or a coincidence — do not present them as two independent corroborating data
points until the primary reports are actually read.

### Georgia/Atlanta hook

- **ACC Georgia chapter**: an active, dues-paying chapter with **1,100+ in-house counsel members**
  **[REPORTED-snippet: acc.com/chapters-networks/chapters/georgia]** — a directly addressable local
  community, distinct from the outside-counsel State Bar hooks the existing memo already uses.
- Named 2025–2026 ACC Georgia local programming specifically on AI adoption/governance for in-house
  teams: *"Beyond the Hype: Practical AI Adoption for In House Legal Teams"* (2026 panel),
  *"U.S. AI Law Considerations for In-House Counsel"* (2025 webinar), *"AI and the Legal Profession: A
  Responsible Approach to Adoption"* (2025 panel), and the *Legal Innovation Forum Atlanta 2025*
  **[all REPORTED-snippet, acc.com/education-events/...]** — evidence Atlanta in-house legal is actively,
  currently wrestling with AI governance, a concrete "why now" hook and a set of named events for warm
  introductions or attendee lists.

### Cold-outreach checklist (initial email / LinkedIn / first 5–10 min call)

1. *"When's the last time someone on your team pasted a contract, complaint, or investigation notes into
   ChatGPT or Copilot — do you actually know, or would you have to guess?"* — tests whether shadow-AI use
   inside the department is a *known, felt* problem or a hypothetical.
2. *"If your board, a customer's vendor-risk questionnaire, or a regulator asked you to produce evidence
   of who on your team used AI on what matter and when — could you produce that today?"* — tests the
   audit-trail pain directly; CyClaw's hashed audit log is a literal answer.
3. *"What's the last piece of software your legal team bought that had to clear a security/DPA review
   before anyone could touch it — and how long did that actually take?"* — tests real procurement
   friction (not survey sentiment) and surfaces who the actual approver is.
4. *"Has a customer's security questionnaire, your cyber insurer, or IT/InfoSec ever flagged an AI tool
   your legal team already uses?"* — tests whether the governance concern has already produced a
   concrete external trigger event, not just internal worry.
5. *"If I could show you a private research/drafting assistant that never sends a byte outside your
   network and produces a tamper-evident log of every query for your board or a regulator — what's your
   first objection?"* — direct pitch + willingness-to-pay probe; the objection itself is the data.

**Disqualifying answer patterns (any one is a strong signal to deprioritize):**

- **D1:** "We already have Copilot/ChatGPT Enterprise and legal/InfoSec signed off on it" *and* no
  incident, audit request, or customer questionnaire has ever actually been raised — the pain is
  espoused, not felt.
- **D2:** No one can name who in the department currently owns an AI-tool decision (no GC personal
  ownership, no legal-ops budget authority identified) — the buying process is too diffuse to sell into.
- **D3:** The security/DPA vendor-review process for the year is already closed with an approved AI
  vendor list — a timing/process dead end, not evidence against the product.

---

## Track B — Outside counsel refresh (condensed cold-outreach version)

The 2026-07-03 memo already has a rigorous 10-conversation, 5-question **deep-discovery** kit with
disqualifying criteria (D1–D3) and falsification criteria — that stands as-is for the actual discovery
conversations. What follows is new: material found since 2026-07-03 that sharpens the pitch, plus a
**shorter, cold-outreach-only** checklist (email/LinkedIn/first call) distinct from the deep-discovery
script, which is too long for a first touch.

### What's new since 2026-07-03

| Claim | Tier | Source |
|---|---|---|
| As of 2026, Georgia's State Bar still has no formal AI ethics opinion — firms rely on ABA Formal Opinion 512 + the existing competence rule (GRPC 1.1), consistent with the existing memo | REPORTED-snippet | legalaigovernance.com/tracker/states/georgia |
| A State Bar of Georgia Special Committee on AI and Technology (active since Oct 2024) and a Judicial Council Ad Hoc Committee report (submitted July 2025) signal formal guidance may be imminent — new since the memo's Nov 2025 snapshot | REPORTED-snippet | aivortex.io/legal/ai-regulation/georgia |
| Additional 2025–2026 hallucinated-citation sanctions nationally beyond *Shahid v. Esaam*, corroborating the memo's flagship GA sanction hook | REPORTED-snippet | spellbook.com/learn/lawyer-fined-using-ai-legal-fake-citations |
| Jan 2026 bar-association commentary (NC, an analogous small/mid-firm audience) argues firms need a *realistic, written* AI-use policy rather than an outright ban | REPORTED-snippet | ncbar.org/2026/01/13/beyond-the-ban |

### Condensed cold-outreach checklist (first touch only — not the full discovery script)

1. *"Have you or anyone at your firm had a citation challenged, or had to explain your AI use to a judge
   or your malpractice carrier, in the last 12 months?"*
2. *"Do you have a written AI-use policy — one your malpractice carrier has actually seen?"*
3. *"What's stopping you from just using the ChatGPT or Copilot subscription you (or your firm) already
   pay for?"* — surfaces the real objection instead of assuming one.
4. *"Georgia's State Bar has a special committee actively working on formal AI guidance — are you
   tracking that, or would a heads-up be useful?"* — tests whether the regulatory-change hook lands.
5. *"For a fixed few thousand dollars, would a written AI policy your carrier would accept, plus a
   private research tool that always shows its sources, be worth a 15-minute call?"* — direct
   willingness-to-pay probe for the first-touch stage.

**Disqualifying answer patterns:** reuse the existing memo's D1–D3 (confidentiality pain is espoused not
felt; MSPs won't white-label at any margin; no technology purchase >$2K in 18 months) — nothing found
this session changes those.

---

## Weakest evidence / explicit gaps (read before using this doc in a real pitch)

1. **Zero willingness-to-pay evidence for Track A.** Every in-house stat is adoption/sentiment
   (usage %, openness %, job-posting growth). No RFP win, signed pilot, or paid engagement was found for
   an unfunded, single-operator vendor selling into an in-house legal department. Track A is *weaker*
   evidence than Track B, which at least inherits the existing memo's disqualifying-criteria discipline
   and its acknowledgment that the concierge price band is "payable but only for a deliverable framed as
   governance + pilot, not GitHub project."
2. **Nothing in this doc was read at primary source this session** — every claim is one tier below the
   existing memo's [VERIFIED]/[REPORTED] standard specifically because of the proxy denial described
   above. Before using any specific number (52%, 23%, 47%, price bands) in an actual outreach message,
   fetch and read the primary page in a session where egress isn't blocked, or ask the user for a manual
   fetch.
3. **The 52%/23% (ACC) and 47%/23% (Wolters Kluwer) adoption figures likely share a source or lineage** —
   flagged above, unresolved.
4. **Price-band figures ($150–2,000/mo) are vendor-marketing content**, the weakest evidentiary tier used
   in this doc — useful only as a rough anchor, not a defensible number in a pitch.
5. Per the tri-analysis doc's standing conclusion, none of the above changes the core finding: **the
   product is not the constraint — customer conversations are.** This doc adds two cold-outreach
   checklists; it does not manufacture evidence that either persona will pay.

---

## Recommended actions

1. Treat this doc as a **lead list to verify**, not a finished pitch deck — re-fetch the primary sources
   above in an unrestricted session before quoting any specific percentage to a prospect.
2. Reconcile the ACC vs. Wolters Kluwer adoption-stat overlap before using either number externally.
3. If pursuing Track A, the first two outreach targets should be the named ACC Georgia 2025–2026
   panels/webinars (attendee lists, speaker introductions) rather than cold LinkedIn — a warm path
   already exists and is cheaper to test than the generic bear-memo distribution problem.
4. Fold the Track B "what's new" items (GA Special Committee, additional sanctions) into the existing
   memo's discovery kit as supporting color; they don't materially change its disqualifying criteria.
