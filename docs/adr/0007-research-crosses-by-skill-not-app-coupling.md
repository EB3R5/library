---
status: accepted
---

# Research crosses from Tasks by a skill, not by app-to-app coupling

Research is produced in the Tasks app: a map (a top-level task) with Done
research tickets, each carrying a `Research.md` and an `Outcome.md`. It
belongs here, in the library, once the user has reviewed it. The question
was how it gets across.

It crosses by the `library-shelve` skill (`agent/skills/library-shelve/`,
symlinked into `~/.claude/skills`): an agent reads the map through the
`tasks` MCP server, writes one Item through the `library` MCP server (ADR
0006), and marks the map in Tasks with a ticked `library: <item title>`
action item. One Item per map; one document per research ticket plus a
pinned `Brief.md`; every Item and document carries `source: tasks:<id>` (ADR
0004). Explicit only: the user names the map, sees the proposal, and
confirms before anything is written. Decided 2026-10-07.

## Considered Options

- **A — A skill over the two MCP servers** (chosen): neither app knows the
  other exists; each keeps its own rules and its own token; the agent is the
  only place the mapping (ticket → document, map → item) lives, and it is
  readable prose.
- **B — Tasks pushes to the library's HTTP API** ("Send to library" button)
  — rejected: Tasks would need the library's token and URL, a client, error
  handling and a UI for the area and tags; the mapping would be code in the
  wrong app.
- **C — The library pulls from Tasks** — rejected for the same reason in
  the other direction, plus the library would have to understand maps,
  tickets, Kinds and Outcomes.
- **D — Automatic on Done** — rejected by the user: unreviewed content would
  land in the library; a research ticket being Done is not the same as its
  research being worth keeping.

## Consequences

- Granularity is one Item per map. A single research task that is not a map
  is not shelved by this skill; it would need a map or a hand upload.
- Idempotence is the skill's job: `list_items(source="tasks:<map id>")` and the
  map's `library:` action item say whether it was shelved before, and a
  re-run only adds documents whose names are missing.
- The link back is the Source; nothing is kept in sync. Edits here stay here.
- The skill lives in this repository because the library is what it writes;
  the Tasks side needs nothing beyond the Kind field and the action-item
  convention it already has.
