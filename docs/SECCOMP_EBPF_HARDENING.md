# CyClaw eBPF + Seccomp Implementation

## What is it?
seccomp: Linux kernel feature filtering syscalls (e.g. block mount, ptrace, raw sockets). Default Docker/Podman blocks ~50 dangerous ones.
eBPF: Programmable kernel observability - used here to *trace* your app's actual syscalls and generate tight *whitelists* (via Podman OCI hook or bpftrace). Result: Minimal attack surface.

## Why (DeepState lens)
Counters persistent threats: Limits blast radius if rclone or LLM subprocess compromised (common IC vector). 

## Deploy
1. `podman run --annotation io.containers.trace-syscall=of:trace.json ...` to generate.
2. Use in compose: security_opt or --security-opt seccomp=...

Update docker-compose.yml & sync/runner.py accordingly.

Next: Integrate Landlock + AppArmor.