---
name: dotenv-guard
description: Check that CyClaw secrets stay out of dotenv files, gitignored or not — no runtime dotenv loading, no secret names in tracked env files, .gitignore coverage, a sandboxed run of macos/setup-cyclaw-keys.sh (fake Keychain) that must write no secret into any dotenv file or shell rc hook, and line checks on scripts and docs. A baseline ratchet holds the by-design findings on main. Use before merging changes to installers, launchers, key setup, or docs that mention .env, and when asked to "check dotenv" or "check secrets at rest".
disable-model-invocation: true
---

# Dotenv Guard

**Persona:** You are a secrets-at-rest reviewer for CyClaw with one question:
*can this change put a secret into a plaintext dotenv file, or spread one into
every shell?* `.gitignore` keeps a dotenv file off GitHub. It does not keep the
plaintext on disk away from every process running as the user, from backups,
or from an AI coding agent reading the workspace. You do not review the six
invariants (invariant-guard), committed secret values (gitleaks), or config
numbers (config-guard).

A name is secret-classified by `.claude/skills/dotenv-guard/envline.py`,
case-insensitively, when it starts with a letter and ends in `_API_KEY`,
`_TOKEN`, `_SECRET`, `_PASSWORD`, `_KEY`, `_PAT`, `_DSN`, or `_CREDENTIALS`.
Gitleaks owns secret values. This guard owns these names. `_KEY` also
classifies non-secret locals such as `PRINT_KEY` when they are assigned in a
dotenv file; that cost is accepted so an access key cannot hide behind a
narrower suffix. The normative rules and the shared vector table are
`ENVLINE_SPEC.md` and `envline_vectors.tsv` beside this skill.

## Run

### Step 1 — Checker (stdlib + git + bash, ~1–2 seconds)

```bash
python3 .claude/skills/dotenv-guard/check_dotenv.py
```

| Check | What it enforces | How |
|---|---|---|
| K1 | Python outside `tests/` loads no dotenv file (`dotenv` import, `load_dotenv`/`dotenv_values`/`find_dotenv`, pydantic-settings `env_file`) | AST |
| K2 | Tracked dotenv files assign no secret name, even with an empty value. Basenames: `.env`, `*.env`, `.env.*`, `*.env.example`, `.envrc`, `*.envrc`, `.env-*` (for example `config/app.env.example`, `.env-local`) | `git ls-files` plus the envline tokenizer |
| K3 | `.gitignore` still ignores dotenv files at any depth | `git check-ignore` on probe paths |
| K4 | `macos/setup-cyclaw-keys.sh`, run with a throwaway `HOME`, a fake `security`, and a fake `--repo-path` checkout, writes no secret into any dotenv file | runs the script (POSIX only) |
| K5 | The rc file that run writes neither assigns a secret (every assignment word on the line) nor loads a dotenv: `.` / `source` of a dotenv basename or any `$` operand, including after `&&` or `;`, and `eval` of `$(cat ...)`, `` `cat ...` ``, or `$(< ...)` | same run |
| K6 | No tracked shell/PowerShell/cmd line writes a literal secret assignment to a dotenv path | line heuristic |
| K7 | No tracked Markdown line pairs a secret assignment with a dotenv file; no ```` ```dotenv ```` block assigns one | line heuristic |

Exit 0: no new finding and no stale baseline entry. Exit 2: a `FAIL`. Exit 3:
env error (git missing, not a work tree, malformed baseline, unreadable
tracked file, syntax error in a non-test Python file). `verify.sh` exits 3
when no Python interpreter is on `PATH`.

### Step 2 — Interpret

- `KNOWN` lines are baselined findings (`baseline.txt`, `RULE<TAB>KEY<TAB>REASON`).
  They exist on `main` by design and do not fail.
- `FAIL … stale baseline entry` means the violation is gone. Delete that line
  in the same PR. This ratchet is the point: a fixed violation must not be
  able to come back silently under an old entry.
- `FAIL [K4] could not run` fails closed. The probe needs the script to exit 0
  and to store at least one item in the fake Keychain; a run that stores
  nothing proves nothing. If a PR renames the script's flags, update
  `_PROBE_ARGS` in the same PR.
- Never add a baseline entry to get a new violation past CI. Fix the
  violation, or say in the PR why it is by design and get a human to agree.

### Step 3 — What the checks cannot see

- K6/K7 read lines. A secret name that reaches a writer through a variable is
  invisible to them. That is why K4 runs the macOS script instead of reading
  it (`_env_upsert "$ENV_FILE" "$env_name" …` is exactly that case on `main`).
- Windows has no K4 equivalent. The PowerShell installers are covered by K6
  alone, and nothing here runs Credential Manager.
- The loaders (`Invoke-CyClaw.ps1`, `invoke-cyclaw.sh`) are not probed. Which
  names they import from a dotenv file is outside these checks.
- A doc that warns against the practice using `NAME=` syntax next to `.env`
  is flagged by K7. Rephrase it, or baseline it with that reason.

## Verify

```bash
bash .claude/skills/dotenv-guard/verify.sh
```

The live tree must pass with the shipped baseline. Then each rule must trip on
its own planted violation in a throwaway git tree, and only that rule. Plants
cover every assignment-form bypass (a later `NAME=` / `NAME+=` on the line,
`declare` / `typeset` / `readonly` / `local`, a leading BOM, lower and mixed
case), the extra dotenv basenames, the rc load forms (`&&`, `set -a`,
`eval "$(cat ...)"`, `. "$var"`, a multi-assignment rc line), and the widened
suffixes. The clean tree carries negative controls that must stay silent (a
`tests/` fixture, `>&2` plumbing, `$GITHUB_ENV`, a non-secret setting, a
comment and an `echo` argument inside a tracked env file, a secret-free
`.envrc`, a `docs/audits/` note). The ratchet tests cover a stale entry, a
`KNOWN` entry, and a malformed baseline. Syntax errors, unreadable files, and
a missing Python interpreter must exit 3.

```bash
python3 -m pytest tests/test_dotenv_envline.py -q
```

That test reads the same `envline_vectors.tsv` the shell verifier checks.

## Guardrails

- Read-only against the repo. The K4 probe writes only under a temp dir, and
  its `--repo-path` points at a fake checkout, never the real one.
- The fake `security` logs service names only. Secrets it is handed are
  discarded; probe stderr is redacted before printing.
- `tests/`, `docs/audits/`, `docs/memories/`, and this skill's directory are
  skipped by K6/K7 (fixtures, history, and the planted examples here).

## Gotchas

- CI runs this as the blocking `dotenv-guard` job next to `invariant-guard`.
  The verify-skills matrix also runs `verify.sh`, but that matrix is
  advisory (`continue-on-error`).
- The shell loaders and this checker share `ENVLINE_SPEC.md` and
  `envline_vectors.tsv`. The five K4/K5 baseline rows for the default
  plaintext write and the raw zshrc source were removed with that behavior.
  Do not put them back.
