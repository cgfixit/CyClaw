# CyClaw AppArmor profile

**Status: opt-in single-container candidate; not enabled by default.** AppArmor
is a Linux-host control. It is not available as a native macOS policy, and this
profile has not been runtime-validated inside Docker Desktop's managed Linux VM.

The profile permits persistent filesystem writes only under the same six paths
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

Run on the target Linux host; do not skip complain-mode workload replay:

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

This directory used to ship a second, host-level profile, `cyclaw-bwrap`, that
let `/usr/bin/bwrap` create user namespaces on stock Ubuntu 24.04 for the
agentic verification sandbox. The sandbox, its executor and
`scripts/verify_agentic_sandbox.py` were removed in October 2026
(`docs/THREAT_MODEL.md`, nineteenth amendment), so the profile went with them.
`cyclaw-gate` above is now the only AppArmor profile CyClaw ships.

A host that loaded `cyclaw-bwrap` keeps it until it is removed by hand:

```bash
sudo apparmor_parser -R /etc/apparmor.d/cyclaw-bwrap
sudo rm /etc/apparmor.d/cyclaw-bwrap
```
