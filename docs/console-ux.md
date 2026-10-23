# Console UX behavior and historical acceptance

This note preserves useful results from the completed console UX plan, retired
during [#1745](https://github.com/cgfixit/CyClaw/issues/1745). Current behavior is
implemented in [terminal.js](../static/terminal.js) and
[terminal.html](../static/terminal.html); use [the static guide](../static/README.md)
for the maintained surface inventory.

## Completed work

- First-run and health display share the index-status state. Plain-language
  confirmation explains that no confident document match was found.
- Advanced mode controls technical detail separately from role-based visibility.
  Role gates still apply; a display preference is not authorization.
- Native health disclosure shows the payload as text. Ollama-down help gives the
  local startup command.
- Index-build elapsed time is shown only when finite/non-negative and resets
  between builds; absent data is not invented.
- Default answer metadata names the answer route/model. Raw metadata remains
  available in advanced mode; blocked/error paths do not claim a model answered.
- Error copy retains the underlying code beside the plain-language explanation.

The Agentic and SQL console buttons/routes were removed on 2026-10-18.
Descriptions of seven operator surfaces in the old plan are historical.

## Evidence and rationale

The original implementation found that a toolbar CSS display rule overrode the
browser's default hidden handling. The explicit hidden rule was verified through
computed style; source inspection alone had missed the visibility problem.
Preserve that accessibility/role-visibility rationale when changing CSS.

The [complete implementation plan and status log](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/CONSOLE_NORMIE_UX_PLAN.md)
preserve PR #1078, #1080, #1342 and #1331 provenance. Dated browser captures
remain under [screenshots](screenshots/README.md). This note records prior work;
it does not claim a new browser run or a complete Edge/Firefox/Brave matrix.
