# Env-line specification

This file is the normative description of one env/shell assignment line.
It is language-neutral. The Python reference is `envline.py`. The shared
table is `envline_vectors.tsv`. A later shell loader (macOS keychain / public
env scripts) should implement these rules and check itself against that table,
rather than inventing a second dialect.

Nothing here expands parameters, command substitutions, or globs. Values are
returned with shell quotes removed and left otherwise literal.

## Line preparation

A line is one record with the trailing newline already removed. A single
leading U+FEFF (UTF-8 BOM) is discarded. A trailing CR is discarded. Further
BOM characters are ordinary text.

## Simple commands

The line is split into simple commands on separators that are not inside
single quotes, double quotes, a backtick command substitution, or `$(...)`.

The separators are `;`, `&`, `|`, `&&`, and `||`. `&&` and `||` are one
separator each, not two. An unquoted `#` starts a comment that runs to the
end of the line: separators after that `#` are not splits, and the comment
text is not a command.

## Words

Each simple command is split into words on unquoted spaces and tabs.

- An unquoted `#` at the start of a word starts a comment. That word and the
  rest of the command are discarded.
- Single quotes copy characters literally until the next single quote. The
  quotes themselves are removed.
- Double quotes copy characters until the next unescaped double quote. Inside
  them, a backslash escapes only `$`, `` ` ``, `"`, `\`, and newline. The
  quotes themselves are removed.
- An unquoted backslash escapes the next character. The backslash is removed.
- `$(...)` is one opaque span, including nested parentheses and quotes inside
  it. The characters are copied, not executed. The same is true of a backtick
  span. Spaces inside the span do not end the word.
- The decoded word is what remains after that quote removal. The raw word is
  the original slice, quotes included.

## Assignments

A simple command yields zero or more assignments, in order. An assignment is
a name, an operator (`=` or `+=`), and a decoded value.

The optional first word may be one of these keywords, matched case-sensitively:
`export`, `declare`, `typeset`, `readonly`, `local`. After a keyword, flag
words are skipped. A flag word is `--` (and it ends the flags) or a word
matching `[-+][A-Za-z]+`, such as `-x`, `-xr`, or `+x`.

From there, consecutive assignment words are taken. The first word that is
not an assignment stops the command. Later words are arguments of that
command, not assignments. So `echo GROK_API_KEY=x` has no assignment, and
`CYCLAW_GATE_PORT=8788 GROK_API_KEY=x` has two.

An assignment word is recognized in either of these shapes:

1. A decoded word matching `NAME`, then `=` or `+=`, then the rest of that
   same word as the value. `NAME` is `[A-Za-z_][A-Za-z0-9_]*`. The value may
   be empty (`GROK_API_KEY=`). Quotes around the whole `NAME=value` are
   already removed, so `export "GROK_API_KEY=x"` is one assignment.
2. A bare `NAME` word, then a following word that is the operator, with
   optional whitespace that the shell itself would reject. `NAME = value`,
   `NAME =value`, `NAME += value`, and `NAME + = value` are assignments. The
   value is the word after a bare operator, or the suffix of `=value` /
   `+=value`.

`+=` is an assignment operator, not a `+` plus a comparison. Every assignment
word on the command is reported, not only the first.

## Source loads

Separately from assignments, a simple command is a source load when:

- The first word is `.` (kind `dot`) or `source` (kind `source`), and there
  is a second word. The operand is that second word, quote-removed.
- The first word is `eval` and the second word is `$(cat ...)`, `` `cat ...` ``,
  or `$(< ...)`. The kind is `eval_cat`. The operand is the text inside, with
  one matching pair of wrapping quotes removed if present.

`[ -f f ] && . f` is two commands; the second is a dot-load. `set -a; . f` is
the same. `. "$var"` is a dot-load whose operand is `$var`. A comment hides
whatever follows it on that line. `if [ -f f ]; then` is not a load: `if` is
the command. A function call such as `cyclaw_source_public_env f` is not a load.

## Secret names

A name is secret-classified when all of the following hold:

- It starts with an ASCII letter.
- Every character is an ASCII letter, digit, or `_`.
- The uppercased name ends with `_` plus one of these suffixes, and at least
  one character precedes that tail: `API_KEY`, `CREDENTIALS`, `PASSWORD`,
  `SECRET`, `TOKEN`, `PAT`, `DSN`, `KEY`.

The test is case-insensitive, so `grok_api_key` and `Grok_Api_Key` classify
the same way `GROK_API_KEY` does. Windows environment names are case-insensitive;
a mixed-case spelling is still the secret.

`KEY` is deliberately broad. It catches `AWS_ACCESS_KEY` and `PRIVATE_KEY`.
It also classifies non-secret locals such as `PRINT_KEY`, `COPY_KEY`, and
`ROTATE_KEY`. Those three are shell flags in the macOS key helper; they are
not dotenv assignments there. A dotenv line that does assign `PRINT_KEY` is
reported. That cost is accepted so a bare `_KEY` suffix cannot hide an access
key. Gitleaks still owns secret values. This guard owns these names.

`CYCLAW_GATE_PORT` is not secret. A leading underscore (`_GROK_API_KEY`) is
not secret: the historical rule required a letter first, and this spec keeps
that boundary.

## Dotenv filenames

The basename (not the directory) is a dotenv file when any of these hold:

- It is `.env` or `.envrc`.
- It ends with `.env`, `.env.example`, or `.envrc` (`app.env`,
  `config/app.env.example`, `foo.envrc`).
- It starts with `.env.` or `.env-` (`.env.local`, `.env.example`,
  `.env-local`, `.env-production`).

`.environment` and `.envbackup` are not dotenv filenames. The directory does
not matter: `config/app.env.example` is judged on `app.env.example`.

## Vector file

`envline_vectors.tsv` is UTF-8, LF, tab-separated, with a header row:

`id`, `line`, `seq`, `name`, `op`, `value`, `classified`, `source_kind`,
`source_operand`.

Blank lines and lines whose first non-whitespace character is `#` are
comments. One case is every row with the same `id`. Those rows must repeat
the same `line`. Assignment rows have a non-empty `name` and `seq` `0`, `1`,
... in order. `classified` is `1` or `0`. Source rows have a non-empty
`source_kind` (`dot`, `source`, or `eval_cat`) and `source_operand`. A line
with neither still has one row with those fields empty.

Inside `line`, `name`, `value`, and `source_operand`, these escapes stand for
characters that cannot sit raw in a TSV column: `\\` backslash, `\t` tab,
`\n` newline, `\r` CR, `\uFEFF` BOM. No other escapes are defined.

## Literal name scan

`envline.py` also exposes a literal scan used only by the dotenv-guard
writer and doc checks. It is not part of the loader contract above. It finds
`NAME=` and `NAME+=`, with optional whitespace around the operator, anywhere
in a string, including inside quotes. Names are then filtered with the secret
rule. A shell loader must not use this scan to decide what to export.
