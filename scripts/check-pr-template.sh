#!/usr/bin/env bash
# Local PR gate: is this PR body (and, when given, its title and head branch) a
# complete fill of .github/PULL_REQUEST_TEMPLATE.md?
#
# Who runs it: whoever is about to open a PR against this repo, human or coding
# agent (Claude Code, Codex, Grok Build, Kimi), before `gh pr create` or a
# GitHub connector create_pull_request. Git hooks cannot see PR bodies, so this
# is the local half; .github/workflows/pr-template-check.yml is the blocking
# CI half. The two apply the SAME rules and tag each failure with the SAME
# [key]; tests/test_pr_template_check_parity.py runs both on shared fixtures,
# so change them together.
#
# Usage:
#   scripts/check-pr-template.sh [options] PATH/TO/body.md
#   gh pr view N --json body -q .body | scripts/check-pr-template.sh [options] -
#   CYCLAW_PR_BODY_FILE=body.md scripts/check-pr-template.sh [options]
#
# Options (each also readable from the env var in brackets):
#   --title TITLE          PR title [CYCLAW_PR_TITLE]; title check skipped if unset
#   --branch BRANCH        head branch [CYCLAW_PR_BRANCH]; defaults to the
#                          current git branch, skipped on a detached HEAD
#   --changed-files FILE   newline list of changed paths for the core-path
#                          invariant rule; overrides --base
#   --base REF             diff REF...HEAD for that list (default origin/main
#                          when it resolves; otherwise the rule is skipped)
#
# Rules (keys match the workflow):
#   proposed-changes types benefits risks checklist further-comments
#   merge-order eli5   every body heading of the template is present
#   types-ticked checklist-ticked   at least one [x] under each
#   trial-merge        the merge-order note says trial merges were verified
#   eli5-last          `## ELI5` is the last heading
#   stamp              last non-blank line is `Last updated: YYYY-MM-DD HH:MM ET`
#   too-short          body under 40 characters
#   invariant          a core-path change must mention an invariant
#   title              `[prefix] - Short sentence` (commit-msg hook's prefixes
#                      and exemptions)
#   branch             a .githooks pre-commit/pre-push allowed branch name
# Fenced code blocks and HTML comments are ignored, so the template's own
# example section does not count. Run against the template file itself, the
# fill-in rules (stamp placeholder, ticked boxes) are skipped so the template
# can be self-checked.
#
# Exit 0 = ok; 1 = rules failed; 2 = usage error.
set -euo pipefail

usage() {
  printf '%s\n' \
    "usage: scripts/check-pr-template.sh [--title T] [--branch B] [--changed-files F | --base REF] <body.md|->" \
    "   or: CYCLAW_PR_BODY_FILE=body.md scripts/check-pr-template.sh [options]" \
    >&2
  exit 2
}

title="${CYCLAW_PR_TITLE:-}"
branch="${CYCLAW_PR_BRANCH:-}"
changed_files=""
base=""
input=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --title) [[ $# -ge 2 ]] || usage; title="$2"; shift 2 ;;
    --branch) [[ $# -ge 2 ]] || usage; branch="$2"; shift 2 ;;
    --changed-files) [[ $# -ge 2 ]] || usage; changed_files="$2"; shift 2 ;;
    --base) [[ $# -ge 2 ]] || usage; base="$2"; shift 2 ;;
    -h|--help) usage ;;
    -) input="-"; shift ;;
    -*) printf 'check-pr-template: unknown option: %s\n' "$1" >&2; usage ;;
    *) input="$1"; shift ;;
  esac
done
input="${input:-${CYCLAW_PR_BODY_FILE:-}}"
[[ -n "$input" ]] || usage

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [[ "$input" == "-" ]]; then
  cat >"$tmp/body.md"
  is_template=0
elif [[ -f "$input" ]]; then
  cp "$input" "$tmp/body.md"
  input_abs="$(cd "$(dirname "$input")" && pwd)/$(basename "$input")"
  is_template=0
  [[ "$input_abs" == "$repo_root/.github/PULL_REQUEST_TEMPLATE.md" ]] && is_template=1
else
  printf 'check-pr-template: file not found: %s\n' "$input" >&2
  exit 2
fi

notes=()
if [[ -z "$branch" ]]; then
  branch="$(git -C "$repo_root" symbolic-ref --short -q HEAD 2>/dev/null || true)"
  [[ -n "$branch" ]] || notes+=("branch not checked (detached HEAD; pass --branch)")
fi
[[ -n "$title" ]] || notes+=("title not checked (pass --title)")

check_core=1
if [[ -n "$changed_files" ]]; then
  [[ -r "$changed_files" ]] || { printf 'check-pr-template: file not found: %s\n' "$changed_files" >&2; exit 2; }
  cat "$changed_files" >"$tmp/files.txt"
else
  base="${base:-origin/main}"
  if git -C "$repo_root" rev-parse --verify -q "$base^{commit}" >/dev/null 2>&1; then
    git -C "$repo_root" diff --name-only "$base...HEAD" >"$tmp/files.txt"
  else
    check_core=0
    notes+=("core-path invariant rule not checked ($base does not resolve; pass --base or --changed-files)")
  fi
fi
[[ -f "$tmp/files.txt" ]] || : >"$tmp/files.txt"

set +e
PR_TITLE="$title" PR_BRANCH="$branch" IS_TEMPLATE="$is_template" CHECK_CORE="$check_core" \
  perl -e '
use strict;
use warnings;
my ($body_path, $files_path) = @ARGV;
local $/;
open(my $bh, "<:encoding(UTF-8)", $body_path) or die "read body: $!";
my $body = <$bh>;
close $bh;
open(my $fh, "<", $files_path) or die "read files: $!";
my @files = grep { length } split /\r?\n/, (<$fh> // "");
close $fh;
$body =~ s/\r\n/\n/g;

my $is_template = $ENV{IS_TEMPLATE} eq "1";
my $title = $ENV{PR_TITLE} // "";
my $branch = $ENV{PR_BRANCH} // "";
my @missing;
sub fail { push @missing, "[$_[0]] $_[1]"; }

(my $prose = $body) =~ s/```.*?```//gs;
$prose =~ s/<!--.*?-->//gs;

my @sections = (
  ["proposed-changes", "## Proposed changes", qr/^#{1,4}\s*proposed changes\b/im],
  ["types", "## Types of changes", qr/^#{1,4}\s*types of changes\b/im],
  ["benefits", "## Benefits / why", qr/^#{1,4}\s*benefits\b/im],
  ["risks", "## Risks to monitor", qr/^#{1,4}\s*risks to monitor\b/im],
  ["checklist", "## Checklist", qr/^#{1,4}\s*checklist\b/im],
  ["further-comments", "## Further comments", qr/^#{1,4}\s*further comments\b/im],
  ["merge-order", "## Suggested merge order of open PRs", qr/^#{1,4}\s*suggested merge order\b/im],
  ["eli5", "## ELI5", qr/^#{1,4}\s*eli5\b/im],
);
for my $s (@sections) {
  fail($s->[0], "Missing section `$s->[1]`") unless $prose =~ $s->[2];
}
fail("trial-merge", "Merge-order section must say trial merges were verified (the words `trial merge`)")
  unless $prose =~ /trial[- ]merge/i;

# Text between a heading and the next heading of any level.
sub section_text {
  my ($re) = @_;
  my @lines = split /\n/, $prose, -1;
  for my $i (0 .. $#lines) {
    next unless $lines[$i] =~ $re;
    my @out;
    for my $j ($i + 1 .. $#lines) {
      last if $lines[$j] =~ /^#{1,6}\s/;
      push @out, $lines[$j];
    }
    return join "\n", @out;
  }
  return undef;
}
my $ticked = qr/^\s*[-*]\s*\[[xX]\]/m;
unless ($is_template) {
  my $types = section_text($sections[1][2]);
  fail("types-ticked", "Tick at least one box under `## Types of changes`")
    if defined $types && $types !~ $ticked;
  my $check = section_text($sections[4][2]);
  fail("checklist-ticked", "Tick at least one box under `## Checklist`")
    if defined $check && $check !~ $ticked;
}

my @headings = ($prose =~ /^(#{1,6}\s+.*)$/gm);
if ($prose =~ $sections[7][2] && @headings && $headings[-1] !~ /^#{1,6}\s*eli5\b/i) {
  fail("eli5-last", "`## ELI5` must be the last heading (the last one is `$headings[-1]`)");
}

my @nonblank = grep { /\S/ } map { (my $l = $_) =~ s/\s+$//; $l } split /\n/, $prose;
my $last = @nonblank ? $nonblank[-1] : "";
my $stamp_ok = $last =~ /^Last updated: \d{4}-\d{2}-\d{2} \d{2}:\d{2} ET$/
  || ($is_template && $last eq "Last updated: YYYY-MM-DD HH:MM ET");
fail("stamp", "Last non-blank line must be `Last updated: YYYY-MM-DD HH:MM ET`") unless $stamp_ok;

(my $trimmed = $body) =~ s/^\s+|\s+$//g;
fail("too-short", "Body is under 40 characters") if length($trimmed) < 40;

if ($ENV{CHECK_CORE} eq "1") {
  my $core = qr/^(gate\.py|gate_ops\.py|gate_auth\.py|gate_memory\.py|graph\.py|mcp_hybrid_server\.py|utils\/personality\.py|config\.yaml)$/;
  if ((grep { $_ =~ $core } @files) && $prose !~ /invariant/i) {
    fail("invariant", "Touches a core-path file (gate*.py, graph.py, mcp_hybrid_server.py, "
      . "utils/personality.py, config.yaml) but never mentions an invariant");
  }
}

if (length $title) {
  my $exempt = $title =~ /^(Merge |Revert |fixup! |squash! |Amend! )/ || $title =~ /^(chore|build|ci)\(deps\)/;
  my $prefixes = "invariant|governance|fsconnect|agentic|rag|harness|security|docs|infra|fix|feat";
  fail("title", "Title must read `[prefix] - Short sentence` with prefix one of $prefixes")
    unless $exempt || $title =~ /^\[($prefixes)\] - \S/;
}

if (length $branch) {
  my $ok = $branch =~ /^(main|master|develop)$/
    || $branch =~ m{^(grok|claude|codex|kimi|agent|CyClaw|cyclaw|dependabot|renovate|release|hotfix)/.+};
  fail("branch", "Head branch `$branch` needs a vendor prefix (claude/, codex/, grok/, kimi/, agent/, CyClaw/, cyclaw/)")
    unless $ok;
}

binmode STDOUT, ":encoding(UTF-8)";
print "$_\n" for @missing;
exit(@missing ? 1 : 0);
' "$tmp/body.md" "$tmp/files.txt" >"$tmp/missing.txt"
rc=$?
set -e

for n in "${notes[@]+"${notes[@]}"}"; do
  printf 'check-pr-template: note: %s\n' "$n" >&2
done

if [[ "$rc" -eq 1 ]]; then
  {
    printf '%s\n' "check-pr-template: not a complete fill of .github/PULL_REQUEST_TEMPLATE.md" "" "Missing:"
    sed 's/^/  - /' "$tmp/missing.txt"
    printf '%s\n' "" "Fill the full template before: gh pr create / GitHub connector create_pull_request"
  } >&2
  exit 1
elif [[ "$rc" -ne 0 ]]; then
  printf 'check-pr-template: internal error (perl exit %s)\n' "$rc" >&2
  exit 2
fi

printf 'check-pr-template: OK — complete template fill\n'
exit 0
