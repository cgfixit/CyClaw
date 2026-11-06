# Dependency security refresh — 2026-11-06

Issue [#1780](https://github.com/cgfixit/CyClaw/issues/1780), starting from
`main@ad8075e64bed0ef799fca44a44a80f9efebdcbcd`. This change fixes two actionable
dependency paths. It does not close the entire ongoing dependency/reachability
worklist or dismiss any alert.

## OAuthLib

The current main pip-audit job fails on `oauthlib==4.0.0`,
[CVE-2026-49272](https://github.com/oauthlib/oauthlib/security/advisories/GHSA-3jp2-3mrg-2vxc).
[Upstream 4.0.1](https://github.com/oauthlib/oauthlib/releases/tag/v4.0.1) validates
device codes before issuing tokens. The new validation hook changes custom
device-flow server integrations; no such CyClaw caller was found. The installed
chain is Chroma → kubernetes 37.0.1 → requests-oauthlib 2.0.0 → OAuthLib.
The parent's `oauthlib>=3.0.0` constraint permits 4.0.1, which supports Python
3.9+ and has no mandatory new dependency. PyPI's version-specific metadata
reports neither yanked artifacts nor advisories for 4.0.1 on this review date.
Package presence alone does not establish an exploitable CyClaw token endpoint.

Pin 4.0.1 in package metadata, legacy requirements, constraints and Conda's pip
tail so an existing old installation cannot satisfy the selected version.
Regenerate both lock families with their maintained arm64 macOS scripts.
Only OAuthLib changes resolved version in the three runtime closures; the
other generated changes are provenance/fingerprint records. The env-drift
checker records this deliberate transitive pin without relaxing its orphan rule.

## Official Python base

Both Docker stages move together from the October 3 manifest to the official
Python 3.12.16 bookworm image published November 5:

- Multi-architecture manifest: `sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df`.
- Linux/amd64 child: `sha256:0f086103b026048cc50cb5da25ec435c023c5241a83fc44daea593377abc61c4`.
- Manifest bytes and all four amd64 layer downloads were verified against their
  SHA-256 digests. The following versions come from the overlaid dpkg status.

| Package | Previous image finding | Candidate base |
| --- | --- | --- |
| apt / libapt-pkg6.0 | 2.6.1 | 2.6.2 |
| tzdata | 2026c-0+deb12u1 | 2026f-0+deb12u1 |
| ca-certificates | Explicitly installed 20250419~deb12u2 | Already 20250419~deb12u2; retain explicit install |

[Debian identifies 2.6.2 as the bookworm fix for CVE-2026-109518](https://security-tracker.debian.org/tracker/CVE-2026-109518).
This APT issue matters during the root-owned build's package downloads, even
though the final gateway runs as a non-root user. The timezone version matches
the scanner's DLA-4867-1 fixed version. No blanket `apt-get upgrade` is added.
The CA/bootstrap, non-root, offline verification and confinement settings stay
unchanged. Python remains on the supported 3.12 minor line.

GnuTLS `3.7.9-2+deb12u7`, all four Kerberos libraries `1.20.1-2+deb12u5`, and
libtirpc3/libtirpc-common `1.3.3+ds-1` are unchanged. Existing exact-package
exceptions retain their December 1 expiry; no exception is extended or renewed.
The October 23 native reachability assessment remains dated evidence.

## Remaining ledger

The November 6 open-alert snapshot contains 33 records: 27 Trivy, three OSV and
three Bandit. The six OSV/Bandit records refer to `ad8075e6`; Trivy's most recent
instances refer to `583f2920`. These are alert records, not 33 distinct reachable
vulnerabilities. The prior main image SARIF contains 300 results including
dismissed findings. Neither count proves exploitability or a clean image.

| Alert IDs / work | Disposition in this change | Remaining acceptance / owner |
| --- | --- | --- |
| 2196–2199, OAuthLib | Patch selected and locked | Exact-head pip-audit, OSV and built-image Trivy evidence; #1780 |
| 2193–2194 APT; 2167 timezone data | Fixed versions measured in candidate base | Application-image build/scan; #1780 |
| 2112, msgpack 1.1.2 | Research; absent from runtime locks (`ormsgpack` is distinct) | Locate actual distribution/layer from new image scan before choosing a pin; #1780 |
| 2173, 2175–2183, SQLite | Unchanged `libsqlite3-0 3.40.1-2+deb12u2`; not fixed here | Match advisory prerequisites to compiled extensions and SQL/database input ownership; #1780 |
| 2168–2169, glibc | Unchanged `2.36-9+deb12u14`; not fixed here | Validate advisory and LANGUAGE/environment/native consumer path; #1780 |
| 2184–2192, GCC/libstdc++ | Unchanged `12.2.0-14+deb12u1`; not fixed here | Identify affected template/native consumers and Debian fix availability; #1780 |
| 2195, scanner metadata | Rule describes webpack-dev-middleware while the message names Debian zlib1g | Reconcile rule/package/upstream identity before any suppression or upgrade; #1780 |
| 2170–2172, Bandit | Import-level findings; no change | Keep subprocess argv/environment checks; XML `escape` is output generation, not XML parsing. Record scoped review before any dismissal; #1780/#1779 |
| libtirpc family, including historical alert 1881 and CVE-2026-85231 | Existing libtirpc3 acceptance is not a sibling-package blanket exemption | Revisit with native package evidence before December 1, earlier if assumptions change; #1780 |
| Pillow / FastEmbed and NLTK | Already upgraded; old acceptances retired | No repeat implementation |
| Chroma | Existing embedded-only acceptance, next review February 1 or next release | #1657; no backend switch in this security patch |
| Ordinary version currency | Deferred, not a security fix by age alone | LangGraph remains #1776; qualify other families separately |

## Verification boundary

Local verification passed in a disposable Python 3.12.14 macOS environment:

- Actual hashed Torch-first runtime install, then `python -m pip check`.
- OAuthLib 4.0.1 device-grant validation with synthetic validator state: missing
  and unknown codes refused; authorized code accepted. Requests-OAuthLib OAuth1
  signing and OAuth2 Bearer delivery through an in-memory adapter, plus
  Kubernetes namespace serialization, passed without network calls.
- Both lock refresh scripts (Python 3.12.13, uv 0.12.23), lock contract, strict
  dep-guard, pin extraction and environment-drift checks passed. The maintained
  verify-deps mutation checks still reject orphan pins and broken install inputs.
- Wheel and sdist build with Hatchling 1.32.4; wheel lock/metadata contract passed
  and `Requires-Dist` contains `oauthlib==4.0.1`.
- Doc-sync found zero drift; changed Python passed Ruff F/B/S.

Container evidence comes from the draft
PR's existing build, installation-smoke and Trivy jobs; this Mac has no Docker
daemon. The PR records exact-head results separately from this base inspection.
No live OAuth provider, custom device server, Windows native runtime or Conda
solve is implied by the local checks.
