# Consolidated memory — 2026-07-04_073240

_Structural merge of 1 snapshot(s); 32 unique line(s) across 5 section(s). Run the memory-consolidation skill for semantic merge._

## Market facts (verified, safe to cite)

- **Statement:** Atlanta MSA has ~4,050 law-office establishments (NAICS 541110, Census CBP 2023), ~3,968 (98%) under 50 employees → ~3,900–4,000 solo-to-20-attorney employer firms; no-payroll solos uncounted. Honest year-1 funnel from 10 discovery conversations: 0–2 paid concierge engagements (~$0–10K).
  **Evidence:** docs/analysis/2026-07-03_atl_small_law_market_memo.md (parsed from raw census.gov CBP file).
  **Confidence:** high
- **Statement:** Verified stat set for buyer-facing use: 69% individual legal-professional genAI use vs 34% firm-level legal-specific adoption, data security #1 barrier at 46% (8am 2026); legal-specific AI tool usage fell 58%→40% 2024→2025 as firms drift to generic ChatGPT (Clio 2025); 66%/89% shadow-AI (Wakefield/PagerDuty 2026); 88%/82% agent incidents/false confidence (Gravitee 2026); >95% memory-injection success (MINJA, arXiv 2503.03704); EU AI Act Art. 99 €35M/7% enforceable 2026-08-02; $670K shadow-AI breach premium is real IBM CODB 2025 data (previously over-excluded — reinstatable with citation).
  **Evidence:** Tri-analysis claim table + ATL memo, each stat independently web-verified with primary URLs.
- **Statement:** Do NOT use these claims — they failed verification: "91% discover AI agent activity after the fact (Forrester 2026)" (unfindable); "96% of AI safety incidents involved blackmail (Apollo)" (garbled — real source is Anthropic's June 2025 red-team scenario rate, not an incident share); "80% of AI inference local by end of 2026" (content-farm only); "fine-tuning = bar violation for law firms" (mechanically false for local fine-tunes).
  **Evidence:** Tri-analysis calibration audit, adversarially verified ratings all upheld.
- **Statement:** Georgia enforcement hooks that are real and citable: Shahid v. Esaam $2,500 sanction (June 2025), Fulton & Cherokee County AI standing orders (July 2025), State Bar of Georgia Generative AI Toolkit (Nov 2025), no formal GA ethics opinion yet. Channel: six named Atlanta legal-vertical MSPs (Network 1, IntegriCom, Century Solutions Group, JETT, Teamspring, Vision Computers). Competitive floor: ChatGPT Business $20–25/user/mo, Copilot ~$21, Clio Duo ~$39 inside the incumbent PM system; lawyers' top concern is accuracy (75%), where local models are weakest.
  **Evidence:** ATL market memo, sources section.
- **Statement:** Naming collision confirmed: Cysic launched an identically-spelled "CyClaw" AI-agent platform in 2026 (DL News coverage). Rename/trademark check is required before any commercial artifact (invoice, landing page, LLC). USPTO status unverified from sandbox.
  **Evidence:** ATL memo naming section; owner independently noticed ("CyClaw is already an existing thing too").

## Project patterns

- **Statement:** Highest-confidence cross-artifact conclusion (bull insights, bear memo, PR #411, tri-analysis all independently agree): the code is not the problem; evidence packaging and customer conversations are. The recurring optimism failure mode is categorical — treating verified demand-side statistics as capture-side PMF evidence.
  **Evidence:** Tri-analysis §3; owner's decision comment adopts the same framing.
  **Confidence:** high
- **Statement:** The repo's calibration pipeline is itself an asset worth preserving: noisy input → verified-subset adoption → explicit exclusion of unverifiable stats → adversarial review rounds → provenance quarantine of unvetted content in docs/planning/_research/ (never docs/memories/). Unvetted external stats must not enter this memory directory.
  **Evidence:** PR #391 thread (144bad6, 67a82e7, 4352f9f); tri-analysis process assessment.
- **Statement:** PR dispositions as of 2026-07-03: #391 (Trust & Compliance Trio planning docs) — superseded by #411, to be closed once this memory save lands; its F1/F2/F3 plans remain archived reference with two known defects to fix before any implementation (F1 hash chain forks under multi-process writers — gate + cyclaw-mcp + CLIs all append audit.jsonl, needs OS-level file lock or single-writer decision; F2 packaging claim wrong — data/ and new top-level modules absent from hatch wheel include list). #411 (bear-case docs cleanup, ICP-as-hypothesis) supersedes. #412 = tri-analysis + ATL memo docs. #413 (gate hardening: auto-docs disabled, /soul/* writes rate-limited) and #414 (compose 0.0.0.0 container-internal bind fix) are hardening/polish, compatible with the feature freeze; #414 needs one manual `docker compose up` + host-side curl check before merge.
  **Evidence:** This session's PR reviews and agent reports; all findings adversarially verified.

## Strategic decisions

- **Statement:** As of 2026-07-03 the owner's standing decision is: freeze new CyClaw feature work; CyClaw's primary role is a polished, living portfolio signal for high-agency infra/AI-security roles; the commercial track (concierge/retainer for regulated SMBs) is explicitly "option B," reactivatable only after better runway or actual paid conversations. Long-form video vision is scoped to a minimal demo walkthrough at most.
  **Evidence:** Owner's decision comment on PR #412 and the Grok "Business Launch Tower" assessment on PR #391; "This isn't giving up on the mission. It's matching activity to current constraints."
  **Confidence:** high
- **Statement:** The operative test for any proposed CyClaw work: "name the mechanism by which more code moves the PMF probability distribution right without customer conversations." For the business path there is none — "the next commit should be a calendar invite, not a feature." Polish (READMEs, governance case-study framing, knowledge map, demo crispness) passes the test; new features do not.
  **Evidence:** Owner-endorsed assessment quoted on PR #411; reaffirmed in the PR #412 decision comment.
- **Statement:** Business-track probability, per the owner's own accepted math: ~25–35% chance of a repeatable $15k+/mo motion in 18–24 months even with disciplined execution; earliest realistic revenue Q4 2026–Q1 2027; W-2 path dominates probability-weighted 3-year dollars. Highest-scored dimension is solve-ability (5/5, Veeam delivery background + CyClaw depth); weakest are speed-to-cashflow (2/5) and personal sustainability of outbound sales (2–3/5, self-identified avoidance-via-feature-work failure mode).
  **Evidence:** Grok Business Launch Tower scoring table posted by owner on PR #391, consistent with the bear-case memo and tri-analysis.

## Uncategorized

Source: 2026-07-03 analysis session (tri-analysis + ATL market research + PR #391/#411 threads). Noise and low-signal extractor terms removed at owner's request; only decision-relevant, durable insights retained.

## Workflow notes

- **Statement:** Owner sequencing (bear memo §8, still standing): employment-attorney IP consult first (blocks all commercialization; Veeam IP-assignment overlap unresolved), job move second, discovery conversations third (10 conversations, 4–6 h/wk × 4 weeks, learning-not-selling, concierge framing "AI governance policy + carrier-ready audit trail + private pilot" at $3–5K fixed fee — the band survives sanity-checking only in that framing, not as software).
  **Evidence:** Bear-case memo; ATL memo willingness-to-pay section; PR #411 comments (10-conversation plan).
  **Confidence:** high
- **Statement:** Real distribution assets that generic bear framing undervalues: the owner's Veeam-era warm-intro graph (professional contacts, conference relationships, LinkedIn visibility) and Atlanta-local in-person reach. Opportunity-cost framing at $86/hr is theatrical — evening/weekend hours aren't billable; the true cost is fatigue and job-search momentum.
  **Evidence:** Owner-endorsed assessment on PR #411 ("Where it overstates").
  **Confidence:** medium
