# Claude features live in a third-pane tab; diff takes over the center pane

The three Claude edit features (integrate addition · capability retrofit ·
free-form edit) surface as a **✨ Claude tab in the Workbench's third pane**,
alongside an Info tab; when a run finishes, the **diff takes over the center
pane** with an Accept/Revert bar until resolved. Decided 2026-08-10 via the
`workbench-claude-ui` prototype (three placements compared live), resolving
[Claude features in the Workbench UI](https://github.com/EB3R5/library/issues/5).

## Considered Options

- **A — third-pane tab + center-pane diff takeover** — chosen: forms get a
  permanent, discoverable home; the diff gets full width; no floating chrome.
- **B — doc toolbar + popover forms + overlay diff** — rejected: keeps the
  third pane metadata-only, but hides the features behind a click and layers
  the diff over the doc.
- **C — IDE-style bottom drawer console** — rejected for now: doc stays
  visible during diff review (its real advantage) but costs vertical space
  and needs collapse/reopen management just to get out of the way.

## Consequences

- The diff replaces the document while pending — you review the diff, not a
  side-by-side with the rendered page. If side-by-side review turns out to
  matter, C's drawer is the fallback shape.
- The third pane is tabbed from v1 (Info · ✨ Claude), so item metadata and
  edit forms never fight for the same space.
- Pending state stays as prototyped: run bar over the center pane, "pending ✎"
  badge on the tree item, one-in-flight refusal message inline.
