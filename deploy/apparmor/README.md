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
ops/executor processes are split into separately confined services.

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

## `cyclaw-bwrap`: user namespaces for the agentic sandbox (Ubuntu 24.04+)

**Status: opt-in host profile, separate from `cyclaw-gate`.** Stock Ubuntu
24.04 and newer set `kernel.apparmor_restrict_unprivileged_userns=1`, so
bubblewrap cannot create its namespaces and
`scripts/verify_agentic_sandbox.py` refuses (fails closed). The
`deploy/apparmor/cyclaw-bwrap` profile lifts that block for one binary only.
Never set the global sysctl to `0` instead: that removes the restriction for
every program on the host.

What the profile grants:

- It attaches to exactly `/usr/bin/bwrap`, the path apt's `bubblewrap`
  package installs. There are no globs, no other binaries, and no
  `local/` include.
- Its only rule is `userns,`.
- It uses `flags=(unconfined)`, so **bwrap itself runs without AppArmor
  confinement**. The profile does not sandbox bwrap. CyClaw's sandbox comes
  from bwrap's own flags (`--unshare-all --cap-drop ALL --die-with-parent
  --new-session` in `agentic/executor/hard_sandbox.py`).
- It needs AppArmor 4 (`abi <abi/4.0>`), so Ubuntu 24.04 or newer.

Load, verify, and remove:

```bash
sudo apparmor_parser -r deploy/apparmor/cyclaw-bwrap
python scripts/verify_agentic_sandbox.py
sudo apparmor_parser -R deploy/apparmor/cyclaw-bwrap
```

To load it at boot, install it to `/etc/apparmor.d/cyclaw-bwrap` first; the
[setup guide](../../setup-guide.md) has those commands.

**Why not Ubuntu's `bwrap-userns-restrict`.** AppArmor's extra-profiles ship a
stricter option. Its `bwrap` profile is confined rather than unconfined, and
it stacks every bwrap child under `unpriv_bwrap`, which denies capabilities
inside the namespace. CyClaw uses the one-rule profile by default because:

- `bwrap-userns-restrict` is not userns-only. Its `bwrap` profile also allows
  `capability`, `mount`, `ptrace`, `dbus`, `network`, and `rwlkm` on `/**`.
  That is a much larger policy to review, and it must match the host's
  AppArmor ABI (the upstream copy declares `abi <abi/5.0>`).
- Its main gain, children without capabilities, is what CyClaw's own sandbox
  already gets from `--cap-drop ALL`. What it adds is protection against
  *other* bwrap callers on the same host.
- CI proves the one-rule profile on `ubuntu-latest` (stock refuses, the
  profile loads, the verifier passes). CI does not exercise the stricter
  profile.

**Residual risk.** With `cyclaw-bwrap` loaded, any local user can run
`/usr/bin/bwrap` to get a user namespace, so bwrap becomes an exemption from
the host's userns restriction. That's acceptable on a single-user CyClaw
workstation. On shared or multi-user hosts, load `bwrap-userns-restrict`
instead and rerun the verifier. Don't load both, because both attach to
`/usr/bin/bwrap`.
