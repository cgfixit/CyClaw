# `deploy/` — container hardening profiles

Linux-host containment and detection scaffolding for the Docker deployment.
AppArmor and Falco are opt-in; the base Compose configuration already
selects Docker's builtin seccomp policy. Nothing here is imported by a Python
module — these are host/daemon configurations. Each hardening subdirectory
(`apparmor/`, `seccomp/`, `falco/`) carries its own README with status, scope, and apply/rollback steps; this file
is the index.

| Subdirectory | What it is | Status |
|---|---|---|
| `apparmor/` | AppArmor profile (`cyclaw-gate`) + compose overlay for a single-container deployment | Opt-in candidate; not runtime-validated under Docker Desktop's Linux VM |
| `seccomp/` | seccomp policy notes; `docker-compose.yml` pins `seccomp:builtin` explicitly | Docker builtin enforced; custom profile not yet generated |
| `falco/` | Falco eBPF detection rules — a tripwire that logs anomalous syscalls, **not** a containment boundary | Detection-only, disabled by default |
| `planning/` | Working notes (`todo.txt`) for this tree | Scratch |

## Related

- Container build/run: [`docs/DOCKER.md`](../docs/DOCKER.md)
- Hardening rationale and staging: [`docs/SECCOMP_EBPF_HARDENING.md`](../docs/SECCOMP_EBPF_HARDENING.md)
- What CyClaw does and does not defend against: [`docs/THREAT_MODEL.md`](../docs/THREAT_MODEL.md)
