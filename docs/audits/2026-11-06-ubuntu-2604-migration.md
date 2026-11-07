# Ubuntu 26.04 migration qualification — 2026-11-06

Issue [#1777](https://github.com/cgfixit/CyClaw/issues/1777), baseline
`ad8075e64bed0ef799fca44a44a80f9efebdcbcd`.
[GitHub's migration window](https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/)
runs through November 19. This draft explicitly selects 26.04 for existing
lint, shell lint, runtime and install-profile jobs. It adds no duplicate suite
and preserves every check name, command, permission, timeout and failure gate.

## Already observed on main

The successful jobs below report Ubuntu **26.04.1**, image **ubuntu-26.04**,
image version **20261101.186.1** in their setup logs. A job named
`ubuntu-latest` alone was not used as image evidence.

| Current-main job | Evidence |
| --- | --- |
| Required runtime `ubuntu-latest` | [127672115406](https://github.com/cgfixit/CyClaw/actions/runs/42149677643/job/127672115406) |
| Required `invariant-guard` | [127672115247](https://github.com/cgfixit/CyClaw/actions/runs/42149677643/job/127672115247) |
| Hashed requirements installation | [127743153714](https://github.com/cgfixit/CyClaw/actions/runs/42172442714/job/127743153714) |
| Editable installation | [127743153800](https://github.com/cgfixit/CyClaw/actions/runs/42172442714/job/127743153800) |

The test matrix keeps the required context `ubuntu-latest` but selects
`ubuntu-26.04` as its actual runner. The two Linux install profiles use the
same mapping. Ubuntu 22.04, Windows and macOS entries stay unchanged.
Python lint and shell lint select 26.04 literally. Other jobs continue following
their existing runner labels; this is bounded qualification, not a blanket pin.

## Baseline consumer map

The live main ruleset requires `ubuntu-latest`, `ubuntu-22.04`, `windows-latest`,
`macos-latest`, `invariant-guard` and `dotenv-guard`. Of the consumers below,
only `ci.yml:test`'s Ubuntu context, `invariant-guard` and `dotenv-guard` are
required by that ruleset. Other jobs can still fail their workflow; they are not
new required branch checks. This inventory includes manual/publish/agent jobs
without enabling or invoking them.

| Workflow | Jobs using ubuntu-latest directly or in a matrix | Tool assumptions / scope |
| --- | --- | --- |
| ci.yml | docker-build; workflow-lint; invariant-guard; doc-sync; dotenv-guard; packaging; dependency-review; test; ollama-mock-smoke; postgres-backend; discover-skills | Python jobs use setup-python 3.12; Docker setup-buildx/build-push; shell/Git and PostgreSQL service. Required jobs identified above. |
| claude.yml | gate; review; write | Action-provided Node/agent runtime; owner/provider gating unchanged |
| codeql.yml | analyze | setup-python and CodeQL action |
| codex-apply-fixes.yml | gate; candidate; publish; report | setup-python in candidate; action runtime/Git in other jobs; protected publication gates unchanged |
| codex.yml | codex; post_feedback | Agent/action runtime and shell/Git |
| copilot-setup-steps.yml | copilot-setup-steps | setup-python; existing installer path |
| defender-for-devops.yml | bandit (Linux matrix row) | setup-python and hashed Bandit tools |
| devskim.yml | devskim | Action-provided scanner |
| environment.yml | noop | Placeholder only; actual Conda uses its separate workflow |
| gitleaks.yml | gitleaks | Scanner action |
| lint.yml | lint | setup-python 3.12; pinned Ruff/flake8/WPS; now explicit 26.04 |
| lora-finetune.yml | test | setup-python; optional existing workload |
| nemo-guardrails.yml | nemo-runtime | setup-python; hashed dependencies and native engine |
| numbat-rules.yml | numbat-rules-fixture; numbat-stream-contract; numbat-cel | setup-python and purpose-specific locks |
| pip-audit.yml | verify-install (Linux, two profiles); scan; scan-optional | setup-python 3.12; fresh venv/Torch-first install. Only install profiles explicitly mapped to 26.04 here |
| pr-review.yml | review; post_review | setup-python in review, action runtime in posting; trusted checkout split unchanged |
| pr-template-check.yml | check | Action-provided Node |
| publish-ghcr.yml | build-and-push | Docker/Buildx; release publication not triggered by this work |
| python-publish.yml | release-build; pypi-publish | setup-python for build; trusted publication action |
| script-lint.yml | shellcheck-scripts | apt xz-utils/CA/curl, SHA-verified ShellCheck; now explicit 26.04 |
| semgrep.yml | semgrep | setup-python and pinned scanner |
| trivy.yml | trivy; docker-image | Scanner action and Docker/Buildx |

Fixed-label jobs (including Conda's Ubuntu 22.04 leg and skill verification on
22.04) are outside the alias migration. No job here relies on a repository-owned
Java application or changes Java setup; action-internal runtime compatibility
must still come from the actual job result.

## Lint compatibility and verification

The latest upstream actionlint release is still **1.7.12**. Its built-in label
table predates 26.04, although GitHub supports and already runs that image.
`.github/actionlint.yaml` uses actionlint's documented additional-label setting
for the single exact label `ubuntu-26.04`. The setting is named
`self-hosted-runner` by actionlint; it does not change GitHub execution to a
self-hosted runner. No wildcard label or error-ignore rule is added. Remove the
entry when the pinned upstream release recognizes this hosted label.

Local actionlint passes the changed workflows. A stdin negative control replacing
the label with `ubuntu-26.99` still fails the runner-label check. Hosted jobs must
prove actual tool installation/runtime behavior; local YAML lint is not Linux
runtime acceptance. The draft PR records its exact final head and job results.

## Remaining observation and failure handling

Keep #1777 open through the migration observation window. Record one green week
on 26.04 after rollout, or an explicitly accepted pin disposition; draft status
alone cannot prove that future window. On a failure, record image/version and
the failing command before attributing it to the OS. Fix a demonstrated tool or
package assumption. If a real required-job blocker remains near November 19,
consider a dated 24.04 pin for only the affected job, preserving its check name.

Main's OAuthLib pip-audit failure is separately fixed by draft #1810; this draft
does not duplicate those dependency changes. Codespaces prebuild's manifest
upload failure is also distinct from the runtime/install jobs above.
