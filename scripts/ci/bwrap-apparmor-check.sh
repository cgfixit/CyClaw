#!/usr/bin/env bash
# Version-aware bubblewrap AppArmor proof for the Linux CI legs.
#
# VERSION_ID from /etc/os-release selects the proof. The runner label does not.
#   22.04: jammy pin and stock confinement (no cyclaw-bwrap load).
#   24.04: noble pin, stock userns refusal, load deploy/apparmor/cyclaw-bwrap,
#          then confinement. Same commands the ubuntu-latest leg ran before
#          the 26.04 split.
#   26.04 and newer: do not load cyclaw-bwrap and do not install the noble pin.
#          Require the userns sysctl to read 1, Ubuntu's bwrap profile in
#          enforce mode, a non-/usr/bin copy to be refused, then the same
#          confinement command on /usr/bin/bwrap.
#   Anything else fails.
#
# Reads kernel.apparmor_restrict_unprivileged_userns. Never writes it.
# The version table from `apt-cache policy` is the package source of truth.
# `apt-cache show bubblewrap=<version>` can exit 0 for a version that is
# not in that table (measured on Ubuntu 26.04 for the noble pin).

read_os_release() {
  local key="$1"
  awk -F= -v key="${key}" '
    $1 == key {
      val = substr($0, length(key) + 2)
      gsub(/^"|"$/, "", val)
      print val
      exit
    }
  ' /etc/os-release
}

is_2604_or_newer() {
  local ver="$1" major minor
  case "${ver}" in
    [0-9]*.[0-9]*) ;;
    *) return 1 ;;
  esac
  major="${ver%%.*}"
  minor="${ver#*.}"
  minor="${minor%%.*}"
  case "${major}" in
    ''|*[!0-9]*) return 1 ;;
  esac
  case "${minor}" in
    ''|*[!0-9]*) return 1 ;;
  esac
  major=$((10#$major))
  minor=$((10#$minor))
  if [ "${major}" -gt 26 ]; then
    return 0
  fi
  if [ "${major}" -eq 26 ] && [ "${minor}" -ge 4 ]; then
    return 0
  fi
  return 1
}

policy_value() {
  local key="$1"
  # Read the whole policy. An early awk exit under pipefail is SIGPIPE.
  awk -v key="${key}" '
    index($0, "  " key ": ") == 1 && val == "" {
      val = substr($0, length(key) + 5)
    }
    END { print val }
  '
}

# Rows under "Version table:" only. Pin lines ("500 http://...") are not
# versions. The installed row is marked with "***".
version_table_versions() {
  awk '
    /^  Version table:/ { in_table = 1; next }
    in_table && /^        / { next }
    in_table && /^ / {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      sub(/^\*\*\*[[:space:]]+/, "", line)
      split(line, fields, /[[:space:]]+/)
      if (fields[1] ~ /^[0-9]/ && fields[1] ~ /[.:~+-]/) print fields[1]
    }
  '
}

version_in_table() {
  local policy="$1" want="$2" line found=0
  # Consume every version row. grep -q would SIGPIPE the producer under pipefail.
  while IFS= read -r line; do
    if [ "${line}" = "${want}" ]; then
      found=1
    fi
  done < <(printf '%s\n' "${policy}" | version_table_versions)
  [ "${found}" -eq 1 ]
}

require_runner_temp() {
  if [ -z "${RUNNER_TEMP:-}" ] || [ ! -d "${RUNNER_TEMP}" ]; then
    echo "::error::RUNNER_TEMP must be an existing directory"
    exit 1
  fi
}

assert_userns_sysctl_is_one() {
  local restrict
  restrict="$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo missing)"
  echo "kernel.apparmor_restrict_unprivileged_userns=${restrict}"
  if [ "${restrict}" != "1" ]; then
    echo "::error::expected stock kernel.apparmor_restrict_unprivileged_userns=1, got '${restrict}'"
    exit 1
  fi
}

install_pinned_bubblewrap() {
  local ver="$1"
  sudo apt-get update
  sudo apt-get install --yes --no-install-recommends "bubblewrap=${ver}"
  bwrap --version
  test "$(bwrap --version)" = "bubblewrap ${ver%%-*}"
}

prove_confinement() {
  local bin="$1"
  "${bin}" --die-with-parent --new-session --unshare-all --cap-drop ALL \
    --ro-bind / / --proc /proc --dev /dev /bin/true
}

prove_ubuntu_2204() {
  install_pinned_bubblewrap '0.6.1-1ubuntu0.3'
  prove_confinement bwrap
}

prove_ubuntu_2404() {
  local probe_err
  install_pinned_bubblewrap '0.9.0-1ubuntu0.3'
  require_runner_temp
  assert_userns_sysctl_is_one
  probe_err="${RUNNER_TEMP}/bwrap-stock-probe.err"
  if bwrap --die-with-parent --new-session --unshare-all --cap-drop ALL \
    --ro-bind / / --proc /proc --dev /dev /bin/true 2>"${probe_err}"; then
    echo "::error::bwrap succeeded under stock AppArmor; expected a refusal before the cyclaw-bwrap profile loads"
    exit 1
  fi
  cat "${probe_err}" >&2
  if ! grep -E -q -i 'permission denied|operation not permitted|no permissions to create new namespace|user namespace' "${probe_err}"; then
    echo "::error::bwrap failed, but not with a userns/permission denial; refusing to count it as the stock AppArmor refusal"
    exit 1
  fi
  echo "Stock AppArmor refused bwrap with a userns/permission denial, as expected."
  sudo install -m 0644 deploy/apparmor/cyclaw-bwrap /etc/apparmor.d/cyclaw-bwrap
  sudo apparmor_parser -r /etc/apparmor.d/cyclaw-bwrap
  prove_confinement bwrap
}

install_distro_bubblewrap() {
  local policy candidate installed upstream noble='0.9.0-1ubuntu0.3'
  sudo apt-get update
  policy="$(apt-cache policy bubblewrap)"
  printf '%s\n' "${policy}"
  candidate="$(printf '%s\n' "${policy}" | policy_value Candidate)"
  if [ -z "${candidate}" ] || [ "${candidate}" = "(none)" ]; then
    echo "::error::apt-cache policy has no bubblewrap candidate"
    exit 1
  fi
  if ! printf '%s\n' "${candidate}" | grep -E -q '^[0-9][0-9A-Za-z.+:~-]*$'; then
    echo "::error::refusing bubblewrap candidate that is not a version: ${candidate}"
    exit 1
  fi
  if [ "${candidate}" = "${noble}" ]; then
    echo "::error::26.04+ candidate is the noble pin ${noble}; refusing to install it"
    exit 1
  fi
  if ! version_in_table "${policy}" "${candidate}"; then
    echo "::error::candidate ${candidate} is not in the apt-cache policy version table"
    exit 1
  fi
  sudo apt-get install --yes --no-install-recommends "bubblewrap=${candidate}"
  policy="$(apt-cache policy bubblewrap)"
  printf '%s\n' "${policy}"
  installed="$(printf '%s\n' "${policy}" | policy_value Installed)"
  if [ "${installed}" != "${candidate}" ]; then
    echo "::error::installed bubblewrap ${installed} != policy candidate ${candidate}"
    exit 1
  fi
  if ! version_in_table "${policy}" "${installed}"; then
    echo "::error::installed bubblewrap ${installed} is not in the apt-cache policy version table"
    exit 1
  fi
  # Single-quoted so bash does not expand the dpkg format under set -u.
  local dpkg_fmt got
  dpkg_fmt='${Version}'
  got="$(dpkg-query -W -f="${dpkg_fmt}" bubblewrap)"
  if [ "${got}" != "${candidate}" ]; then
    echo "::error::dpkg bubblewrap version is not ${candidate}"
    exit 1
  fi
  upstream="${candidate%%-*}"
  upstream="${upstream##*:}"
  bwrap --version
  test "$(bwrap --version)" = "bubblewrap ${upstream}"
  if [ "$(command -v bwrap)" != "/usr/bin/bwrap" ]; then
    echo "::error::bwrap resolved to $(command -v bwrap), expected /usr/bin/bwrap"
    exit 1
  fi
}

assert_ubuntu_bwrap_profile_enforced() {
  local profiles="/sys/kernel/security/apparmor/profiles"
  local profile_file="/etc/apparmor.d/bwrap-userns-restrict"
  if [ ! -f "${profile_file}" ]; then
    echo "::error::Ubuntu bwrap profile file ${profile_file} is missing"
    exit 1
  fi
  if ! grep -F -q 'profile bwrap /usr/bin/bwrap' "${profile_file}"; then
    echo "::error::${profile_file} does not attach profile bwrap to /usr/bin/bwrap"
    exit 1
  fi
  if ! sudo test -r "${profiles}"; then
    echo "::error::cannot read ${profiles}"
    exit 1
  fi
  if ! sudo grep -q -x 'bwrap (enforce)' "${profiles}"; then
    echo "::error::Ubuntu bwrap profile is not loaded in enforce mode"
    sudo cat "${profiles}" >&2 || true
    exit 1
  fi
  if sudo grep -q '^cyclaw-bwrap ' "${profiles}"; then
    echo "::error::cyclaw-bwrap is loaded; 26.04+ must not load it"
    exit 1
  fi
  echo "Ubuntu profile bwrap is loaded in enforce mode."
}

refuse_unprofiled_bwrap_copy() {
  local copy probe_err
  require_runner_temp
  copy="${RUNNER_TEMP}/bwrap-unprofiled"
  case "${copy}" in
    /usr/bin|/usr/bin/*)
      echo "::error::unprofiled copy path ${copy} is under /usr/bin"
      exit 1
      ;;
  esac
  cp -a /usr/bin/bwrap "${copy}"
  chmod 755 "${copy}"
  if [ "$(readlink -f "${copy}")" = "$(readlink -f /usr/bin/bwrap)" ]; then
    echo "::error::unprofiled copy ${copy} resolves to /usr/bin/bwrap"
    exit 1
  fi
  probe_err="${RUNNER_TEMP}/bwrap-unprofiled.err"
  if "${copy}" --die-with-parent --new-session --unshare-all --cap-drop ALL \
    --ro-bind / / --proc /proc --dev /dev /bin/true 2>"${probe_err}"; then
    echo "::error::bwrap copy at ${copy} succeeded; the userns restriction is not live"
    exit 1
  fi
  cat "${probe_err}" >&2
  if ! grep -F -q 'bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted' "${probe_err}"; then
    echo "::error::bwrap copy at ${copy} was not refused with the measured RTM_NEWADDR denial"
    exit 1
  fi
  echo "Unprofiled bwrap copy at ${copy} was refused, as expected."
}

assert_child_label() {
  local label_out label_line
  require_runner_temp
  label_out="${RUNNER_TEMP}/bwrap-child-label.out"
  /usr/bin/bwrap --die-with-parent --new-session --unshare-all --cap-drop ALL \
    --ro-bind / / --proc /proc --dev /dev \
    /bin/sh -c 'printf "child_apparmor="; tr "\0" " " < /proc/self/attr/apparmor/current; printf "\n"' \
    >"${label_out}"
  cat "${label_out}"
  label_line="$(sed -n 's/^child_apparmor=//p' "${label_out}")"
  label_line="${label_line//$'\r'/}"
  label_line="${label_line%"${label_line##*[![:space:]]}"}"
  if [ "${label_line}" != "bwrap//&unpriv_bwrap (enforce)" ]; then
    echo "::error::child AppArmor label '${label_line}' is not bwrap//&unpriv_bwrap (enforce)"
    exit 1
  fi
  echo "Child label is bwrap//&unpriv_bwrap (enforce)."
}

prove_ubuntu_2604_or_newer() {
  echo "26.04+ path: not loading cyclaw-bwrap and not installing the noble pin."
  install_distro_bubblewrap
  assert_userns_sysctl_is_one
  assert_ubuntu_bwrap_profile_enforced
  refuse_unprofiled_bwrap_copy
  prove_confinement /usr/bin/bwrap
  assert_child_label
}

main() {
  local os_id version_id pretty repo_root
  set -euo pipefail
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  cd "${repo_root}"
  if [ ! -r /etc/os-release ]; then
    echo "::error::/etc/os-release is not readable"
    exit 1
  fi
  os_id="$(read_os_release ID)"
  version_id="$(read_os_release VERSION_ID)"
  pretty="$(read_os_release PRETTY_NAME)"
  printf 'ID=%s\nVERSION_ID=%s\nPRETTY_NAME=%s\n' "${os_id}" "${version_id}" "${pretty}"
  if [ "${os_id}" != "ubuntu" ]; then
    echo "::error::expected ID=ubuntu, got '${os_id}'"
    exit 1
  fi
  case "${version_id}" in
    22.04)
      prove_ubuntu_2204
      ;;
    24.04)
      prove_ubuntu_2404
      ;;
    *)
      if is_2604_or_newer "${version_id}"; then
        prove_ubuntu_2604_or_newer
      else
        echo "::error::unsupported Ubuntu VERSION_ID='${version_id}' (expected 22.04, 24.04, or 26.04+)"
        exit 1
      fi
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
