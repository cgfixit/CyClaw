# Review a trust boundary

Establish threat model, deployment and candidate scope. Read `INVARIANTS.md`,
`SECURITY.md`, `docs/THREAT_MODEL.md` and actual config/execution paths.
Trace input to sensitive sinks, alternate routes, admission/execution checks,
audit, credential handling and egress. Use relevant maintained guards as
structural evidence; distinguish tested behavior from hardening ideas.
Use available Codex Security skills when the requested scan type fits them.
Return source-backed findings and minimal mitigations; do not implement a policy
change or expand a scoped review into a whole-repository scan without a request.
