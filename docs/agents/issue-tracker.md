# Issue tracker

GitHub issues on `EB3R5/library` (private). `gh` CLI is authenticated as EB3R5.

## Wayfinding operations

- **Map**: issue #16 (v2 — documents in SQLite), labelled `wayfinder:map`; **complete** — spec locked in plan.md. The v1 map (#1) is also closed. A new effort starts a new map issue. Tickets are native **sub-issues**
  of the map.
- **Ticket types**: labels `wayfinder:research | grilling | prototype | task`.
- **Claim** a ticket: `gh issue edit <n> --add-assignee EB3R5` — assignee is the
  claim; unassigned+open = takeable.
- **Blocking** uses GitHub's native issue dependencies (renders in the UI):
  - add: `gh api repos/EB3R5/library/issues/<n>/dependencies/blocked_by -X POST -F issue_id=$(gh api repos/EB3R5/library/issues/<blocker> --jq .id)`
  - list: `gh api repos/EB3R5/library/issues/<n>/dependencies/blocked_by`
- **Add a sub-issue** to the map: `gh api repos/EB3R5/library/issues/16/sub_issues -X POST -F sub_issue_id=$(gh api repos/EB3R5/library/issues/<n> --jq .id)`
- **Frontier** (open, unblocked, unclaimed): `gh issue list --state open --search "no:assignee -label:wayfinder:map"`,
  then drop any with a non-empty open `blocked_by` list.
- **Resolve**: answer as a comment, `gh issue close <n>`, append a one-line
  pointer to the map's "Decisions so far".
