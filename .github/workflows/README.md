# GitHub Actions workflow guide

The tables describe the tracked workflow files. Open a file for its exact path
filters, runner matrix, pins, and permissions. The `name:` inside the file is
the label shown in Actions; job names become PR check contexts. A failing job
turns its workflow red unless marked advisory. Whether that check prevents a
merge is controlled separately by the [repository rulesets](https://github.com/cgfixit/CyClaw/settings/rules).
Keep required job names stable when changing workflow labels or filenames.

## CI and contracts

| File | What it checks | When it runs |
| --- | --- | --- |
| [ci.yml](ci.yml) | Main Python 3.12 test/coverage matrix: two Ubuntu runners, Windows, Apple Silicon macOS. Also checks workflow security, invariants, dotenv, docs/locks, wheels, Docker, retrieval, mock-model HTTP, and Postgres. Skill smoke matrix is advisory. | Main pushes and PRs; dependency review is PR-only. |
| [conda-ci.yml](conda-ci.yml) | Distinct Conda install surface from root [`environment.yml`](../../environment.yml), dependency consistency, pytest coverage. Final sandbox smoke is advisory. | Main pushes and PRs. |
| [lint.yml](lint.yml) | Ruff F/B/S blocks; broader Ruff and changed-file flake8/WPS report advisory findings. | Main/vendor branch pushes and PRs to `main` or `cc`. |
| [script-lint.yml](script-lint.yml) | ShellCheck for `macos/*.sh`; Windows PowerShell PSScriptAnalyzer for `powershell/*.ps1`. Findings fail the jobs. | Main/vendor branch pushes and PRs to `main` or `cc`. |
| [codex-skills.yml](codex-skills.yml) | Repository skill metadata, inventory, references, and Python/shell syntax. It does not invoke a coding assistant. | Relevant main pushes/PRs, or manual dispatch. |
| [nemo-guardrails.yml](nemo-guardrails.yml) | Real pinned NeMo actions and Numbat/CEL gateway acceptance; generation-call inventory is advisory. | Main pushes and PRs, excluding changes only to `docs/` or `.claude/`. |
| [numbat-rules.yml](numbat-rules.yml) | Known-bad/clean fixtures, emitted stream schema, pre-action rules, and CEL evaluation. | Main pushes/PRs, excluding changes only to `docs/` or `.claude/`. |
| [lora-finetune.yml](lora-finetune.yml) | The separate fine-tune kit's mocked tests and dry-run control flow; no GPU or training. | Kit/workflow changes on main/vendor branches and PRs to `main` or `cc`. |
| [pr-template-check.yml](pr-template-check.yml) | PR title/branch/body structure, including merge-order note and final ELI5 timestamp. | PR lifecycle/body edits targeting `main` or `cc`; Dependabot is exempt. |

## Security scans

Scan execution and findings are different signals. A successful SARIF upload
means results reached the Security tab; it does not mean zero vulnerabilities.
Accepted dependency risks belong in root [`SECURITY.md`](../../SECURITY.md).

| File | What it checks | When it runs / findings policy |
| --- | --- | --- |
| [codeql.yml](codeql.yml) | Python and GitHub Actions analysis. | Main pushes, PRs to main, weekly, or manual. Findings go to code scanning. |
| [defender-for-devops.yml](defender-for-devops.yml) | **Bandit Python SAST**, on Linux/macOS, with hashed scanner dependencies. No Microsoft Defender service runs. | Main pushes/PRs, weekly, or manual. Findings are advisory; install/scan/SARIF failures fail. |
| [devskim.yml](devskim.yml) | Microsoft DevSkim source-pattern scan. | Main pushes/PRs, weekly, or manual. Findings are uploaded and retained as SARIF artifacts. |
| [gitleaks.yml](gitleaks.yml) | Secrets in Git history/PR changes. | Main pushes/PRs, weekly, or manual. Detected secrets fail. |
| [osv-scanner.yml](osv-scanner.yml) | Resolved dependency locks via Google's reusable OSV workflows. | Main pushes/PRs, weekly, or manual. PR-introduced vulnerabilities block; full scans report. |
| [pip-audit.yml](pip-audit.yml) | Six OS/install-profile checks, then base/test and optional-extra CVE audits. | Dependency/config/workflow changes, daily, or manual. Install failures and unaccepted findings fail. |
| [semgrep.yml](semgrep.yml) | Python/OWASP source-rule scans. | Main pushes, PRs to main, weekly, or manual. Findings go to code scanning. |
| [trivy.yml](trivy.yml) | Filesystem dependencies and a built Docker image. | Main pushes, PRs to main, weekly, or manual. Findings go to code scanning; image builds are conditional on changed paths for PRs. |

## Coding assistants

| File | What it does | Authorization |
| --- | --- | --- |
| [pr-review.yml](pr-review.yml) | Automatic Codex advisory review and comment, using the trusted base and candidate as data. | Owner-authored, same-repository PRs and owner-triggered events; opens can review drafts, later updates require a non-draft PR. |
| [codex.yml](codex.yml) | Answers an owner's `@codex` PR comment without editing the PR. | Owner-only, open same-repository PR; read-only sandbox. |
| [codex-apply-fixes.yml](codex-apply-fixes.yml) | Produces a candidate patch on one runner, then validates and publishes it on a separate runner. | Owner-approved bot-comment fix on an owner-authored same-repository PR. Approval binds to the exact head SHA. Protected paths remain refused. |
| [claude.yml](claude.yml) | Answers `@claude` PR comments; defaults to review/explanation. | Owner-only, open same-repository PR. Write mode requires `write access approved for this PR` as the comment's last line. |

These workflows use provider secrets and can incur provider charges. Green
advisory jobs or missing comments are not proof that an assistant completed a
review; inspect the run and the commit it reviewed.

## Publishing and manual tools

| File | What it does | Trigger / boundary |
| --- | --- | --- |
| [python-publish.yml](python-publish.yml) | Builds wheel/sdist, then publishes to **PyPI** with OIDC. | Published GitHub Release; `pypi` environment. Preserve this filename unless the PyPI trusted-publisher configuration is updated with it. |
| [publish-ghcr.yml](publish-ghcr.yml) | Builds the Linux amd64 runtime image and pushes to **GitHub Container Registry**. | `v*` tag pushes publish version/latest tags; manual dispatch publishes SHA/edge tags. Uses the `ghcr` environment. |
| [native-e2e-hosted.yml](native-e2e-hosted.yml) | Hosted macOS/Windows install, uninstall/reinstall, native credential-store, and gateway API checks with a mock model. | Manual only; does not prove desktop GUI or live-provider acceptance. |
| [copilot-setup-steps.yml](copilot-setup-steps.yml) | Installs dependencies and tracked hooks for Copilot's coding environment. | Its own file changes, manual dispatch, and Copilot setup. The filename/job ID are integration conventions. |
| [environment.yml](environment.yml) | Historical no-op workflow that explains the relocated Conda spec. | Manual-only placeholder; root [`environment.yml`](../../environment.yml) is the real spec. |

Environment names alone do not require deployment approval. Reviewer and
branch/tag restrictions live in [GitHub environment settings](https://github.com/cgfixit/CyClaw/settings/environments);
verify those settings before treating either publisher as human-gated.

`defender-for-devops.yml` retains its legacy filename because GitHub's current
Bandit analysis key includes it. Renaming it would create a new scanning
configuration and require checking the old configuration for stale results.
The Conda workflow was renamed from `python-package-conda.yml` to `conda-ci.yml`;
its job IDs, coverage gate, install surface, and permissions are unchanged.

Filename-sensitive integrations: [PyPI trusted publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/),
[Copilot setup steps](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/customize-the-agent-environment),
and [code-scanning configuration identity](https://docs.github.com/en/code-security/reference/code-scanning/workflow-configuration-options).
