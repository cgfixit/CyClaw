# locks/

Hashed, closed dependency locks. The Docker build, the setup guide and CI's
locked jobs install with `pip install --require-hashes -r locks/<file>`, so a
replaced wheel fails the install instead of being accepted. The generated
requirements files and input/output fingerprint records are not edited by hand;
the contract check below detects edits that disagree with those records.

## What each family is for

| Files | Installs | Owned by |
|---|---|---|
| `requirements-lock-{linux,macos,windows}.txt` | the runtime closure (`requirements.txt` under `constraints.txt`) | `scripts/refresh-runtime-lock.sh` |
| `requirements-torch-lock-{linux,macos,windows}.txt` | torch alone, installed first | `scripts/refresh-runtime-lock.sh` |
| `requirements-test-lock-{linux,macos,windows}.txt` | the test tools (`requirements-test.txt`) | `scripts/refresh-ci-locks.sh` |
| `requirements-ci-*-lock-*.txt` | one lock per CI job's tool set (smoke, yaml, ruff, cel, numbat, numbat-contract, postgres, bandit) | `scripts/refresh-ci-locks.sh` |
| `requirements-extra-lock-*.txt` | optional extras (postgres, pgvector, dev) | `scripts/refresh-ci-locks.sh` |
| `runtime-inputs.json`, `ci-inputs.json` | SHA-256 of every input and output of the two refresh scripts | written by the refresh scripts |

The CI job inputs live in `scripts/ci-lock-inputs/*.txt`.

## Install order

Torch goes first and on its own (`--no-deps`), then the runtime lock, then the
test lock. Linux and Windows take the CPU build from the PyTorch CPU index
(`torch==X+cpu`); macOS takes plain `torch` with no `--index-url`, because
there is no `+cpu` wheel for it. Use the macOS block of the setup guide on
macOS and do not "fix" the pin. The exact commands are in `CLAUDE.md` §8 and
`setup-guide.md`.

## Changing a pin

1. Edit the input (`constraints.txt`, `pyproject.toml`, `requirements*.txt`,
   or a file under `scripts/ci-lock-inputs/`). The torch pin also lives in
   `environment.yml`; change it in the same commit.
2. Run every affected refresh script. A `constraints.txt` change affects both
   groups, even if one group's resolved versions stay the same. Both refuse
   to run anywhere except an arm64
   macOS host (`lock generation requires the supported arm64 macOS host`), so
   lock regeneration cannot be done from a Linux container. Regenerate; never
   hand-merge a lock.
3. Run the checks below before pushing.

The refresh scripts seed their staging directory with the tracked locks, so
existing transitive pins are kept as preferences. Only the pins you changed
(and what they force) should move.

To deliberately refresh selected transitives, pass a repeated
`--upgrade-package NAME` to either script; put exact version bounds in
`constraints.txt`. For example:

```bash
scripts/refresh-runtime-lock.sh --upgrade-package certifi --upgrade-package opentelemetry-api --upgrade-package aiohttp
scripts/refresh-ci-locks.sh --upgrade-package certifi --upgrade-package opentelemetry-api --upgrade-package aiohttp
```

Targets reach each non-Torch compile; dedicated Torch locks keep their existing
pins and install contract. Companion packages move only when resolution requires
it or they are explicitly targeted. Without arguments, existing pins remain
preferred. Global upgrades and arbitrary compiler options are not accepted.
Both groups fingerprint `constraints.txt`, so a constraint edit requires both
refresh scripts even when the CI package versions remain unchanged.

`constraints.txt`, `requirements*.txt` and the `scripts/ci-lock-inputs/`
files are hashed after CRLF-to-LF normalization into the input records, so
even a comment edit in one of them requires a refresh. The recorded refresh
script and contract-checker source are fingerprinted too. For `pyproject.toml`,
only `requires-python` and the dependency tables are hashed, so a coverage,
ruff or project-version edit there does not invalidate the locks.

Run from the repository root with Python 3.12 and `uv` available:

```bash
bash scripts/refresh-runtime-lock.sh
bash scripts/refresh-ci-locks.sh
```

`PYTHON_BIN`, `UV_BIN`, and `UV_CACHE_DIR` select the interpreter, compiler,
and cache. Linux/Windows locks target x86_64; macOS locks target the native
arm64 host. Successful cross-platform resolution is not proof of installation
on every platform; the hosted install matrix supplies that separate evidence.

## Dependabot

`.github/dependabot.yml` lets Dependabot edit only the manifests (monthly for
pip, with `locks/**` excluded) and never a hashed lock, because it cannot run
the refresh scripts. A Dependabot pip PR is therefore a shopping list, not a
merge candidate: it stays red on the lock contract until the operator checks
it out on the Mac, runs the owning refresh script, and pushes the regenerated
locks onto the same branch. Major updates form a separate group from
minor/patch updates. Torch and the Pydantic pair are excluded from automatic
updates; inspect the current Dependabot configuration for the remaining
compatibility limits.

## Checks

```bash
python3 scripts/check_lock_contract.py           # offline: inputs, pins, hashes, output set
python3 .claude/skills/dep-guard/check_deps.py   # pins agree across pyproject, constraints, environment.yml
python3 .claude/skills/verify-deps/check_env_drift.py
```

`scripts/check_lock_contract.py` detects changed inputs, pins, hashes and
output sets against the two JSON records. It does not claim that a fresh
resolver run against today's index would choose the same versions. CI runs it
in `.github/workflows/ci.yml`, including a pass over the built wheel.
