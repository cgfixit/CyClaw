# CyClaw AppArmor profile

**Opt-in single-container candidate.** Linux-host control; unavailable
natively on macOS and unvalidated in Docker Desktop's managed VM.

The profile permits filesystem writes only under the same six paths
already writable under the read-only Compose root filesystem (plus required
`/dev/null`, `/dev/zero`, and `/dev/full` device I/O):

```text
/app/data  /app/index  /app/logs  /app/checkpoints  /app/.emb_cache  /tmp
```

It intentionally omits shells, `git`, `gh`, and `rclone`. Python-only `/ops`
children can still start through the allowed interpreter and inherit this same
profile; `/ops` actions that need an external executable fail closed. Treat it
as one gate-runtime policy, not process-role isolation, until optional
`/ops` processes are split into separately confined services.

IPv4/IPv6 raw sockets, packet sockets, and AF_ALG are denied. Unprivileged
netlink raw sockets remain allowed because glibc uses them for address-family
discovery; Linux capabilities are still fully dropped.

## Fail-closed enablement

Run from the repository root on the target Linux host, after preparing the
base Compose mounts in [`docs/DOCKER.md`](../../docs/DOCKER.md). Do not skip
complain-mode workload replay:

```bash
sudo apparmor_parser -Q -W deploy/apparmor/cyclaw-gate
sudo apparmor_parser -r -W deploy/apparmor/cyclaw-gate
sudo aa-complain cyclaw-gate
sudo aa-status

docker compose \
  -f docker-compose.yml \
  -f deploy/apparmor/docker-compose.apparmor.yml \
  config
docker compose \
  -f docker-compose.yml \
  -f deploy/apparmor/docker-compose.apparmor.yml \
  up --build
```

Inspect the rendered configuration before starting: the app service must keep
the base `no-new-privileges:true` and `seccomp:builtin` entries alongside
`apparmor:cyclaw-gate`. The overlay only chooses the AppArmor profile; it does
not load that profile into the host kernel. Complain mode is for collecting
evidence before enforcement, not proof that all of these restrictions block.

Exercise the full gate workload in
[`docs/SECCOMP_EBPF_HARDENING.md`](../../docs/SECCOMP_EBPF_HARDENING.md), then
inspect denials and promote only reviewed rules:

```bash
sudo aa-logprof
sudo aa-enforce cyclaw-gate
docker inspect cyclaw-prod --format '{{.AppArmorProfile}}'
```

Expected negative tests after enforcement:

```bash
docker exec cyclaw-prod python -c "open('/app/blocked', 'w')"
docker exec cyclaw-prod python -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)"
docker exec cyclaw-prod python -c "import socket; socket.socket(socket.AF_PACKET, socket.SOCK_RAW)"
docker exec cyclaw-prod sh -c true
```

All four must fail. A write under `/app/data` and `/tmp` must still succeed;
`/health`, cold/warm `/query`, audit writes, Chroma persistence, graceful
shutdown, and restart recovery must still pass.

Rollback is explicit and returns to Docker's generated `docker-default`
profile:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/apparmor/docker-compose.apparmor.yml \
  down
sudo apparmor_parser -R deploy/apparmor/cyclaw-gate
docker compose up
```

## Former `cyclaw-bwrap` profile (removed 2026-10-18)

`cyclaw-bwrap` enabled Ubuntu 24.04 user namespaces
for the agentic sandbox. It was removed with that executor in October 2026
(`docs/THREAT_MODEL.md`, nineteenth amendment). Only `cyclaw-gate` remains.

A host that loaded `cyclaw-bwrap` keeps it until it is removed by hand:

```bash
sudo apparmor_parser -R /etc/apparmor.d/cyclaw-bwrap
sudo rm /etc/apparmor.d/cyclaw-bwrap
```
