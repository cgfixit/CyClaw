# macOS setup and credential lifecycle

Reviewed 2026-10-23 against main at 246e406. This replaces the contradictory
August/September implementation table. See the
[original plan and ACL/trap rationale](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/plans/MACOS_BASH_SETUP_AND_KEY_LIFECYCLE.md)
for history, and [the platform guide](../../macos/README.md) for commands.

## Shipped

| Capability | Source of truth |
|---|---|
| Explicit replacement of an existing checkout | install-cyclaw.sh --replace-repo |
| Key generation, prompt/store and secret validation | setup-cyclaw-keys.sh; the store and clipboard temporary-file paths have EXIT cleanup traps |
| Keychain-first setup; plaintext persistence is explicit opt-in | setup-cyclaw-keys.sh, setup-from-clone.sh and the current secret-persistence instructions |
| Credential loading for launchers and unattended jobs | invoke-cyclaw.sh and cyclaw-keychain-env.sh |
| Optional uninstall credential deletion | uninstall-cyclaw.sh --remove-keychain; targets come from maintained secret policy plus legacy cleanup, not a fixed five-name list |
| Scheduled rotation artifact generation | setup-cyclaw-keys.sh --schedule-rotate; generation does not itself load the LaunchAgent |

The old proposed uninstall switch and dotenv-loading tasks are not missing
features. Check current setup flags rather than copying the old triple-plaintext
persistence diagram.

## Remaining work

The scheduled rotation job invokes --rotate --skip-prompts without a gateway
liveness preflight or coordinated restart. A running gateway can still hold the
old key. Existing warnings and the separate restart option do not complete that
unattended lifecycle. This remains deferred under
[#1745](https://github.com/cgfixit/CyClaw/issues/1745); no key is rotated and no
service is stopped by the documentation cleanup.

If pursued, define refusal/restart ownership and operator recovery before
changing the job. Verify with a disposable credential store and controlled
listener. Shell/static tests are not proof of native Keychain behavior.

## Credential-store boundary

Using /usr/bin/security as a trusted reader does not restrict access to CyClaw
alone: other processes with equivalent user/keychain access can invoke it.
A signed helper or a new keychain policy is a separate design, not required
cleanup. Keep secrets out of argv, logs and LaunchAgent XML. Do not wildcard
credential deletion or silently change persistence defaults.

The [Windows plan](WINDOWS_POWERSHELL_SETUP_AND_KEY_LIFECYCLE.md) records the
corresponding Credential Manager behavior.
