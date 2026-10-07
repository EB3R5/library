# library-shelve reference

## Document names

| Document | Name | Source |
|---|---|---|
| one per research ticket | `<slug of the ticket title>.md` — lowercase, words joined by `-`, punctuation dropped, at most 60 characters, e.g. `which-dance-styles-are-there.md` | `tasks:<child id>` |
| the brief | `Brief.md` | `tasks:<map id>` |

Two tickets with the same slug: suffix the second `-2` yourself (do not leave it to the
Library's ` (2)` rule, which is for accidents).

## Body of a research document

```markdown
---
source: tasks:<child id>
task: <child title>
map: <map title>
kind: research
completed: <child completed_at, YYYY-MM-DD>
---
# <child title>

<the question: the child's Description after its first `mode:`/`type:` line>

<the body of Research.md, verbatim>

## Outcome

<the body of Outcome.md, verbatim — omit the section when the child has no Outcome.md>
```

When the child has no `Research.md`, its newest text document stands in for it and the
`## Outcome` section is omitted (that document *is* the outcome).

## Body of `Brief.md`

```markdown
---
source: tasks:<map id>
map: <map title>
category: <map category>
shelved: <today, YYYY-MM-DD>
---
# <map title>

<Destination: … and Notes: … from the map's Description, as two short paragraphs>

## Decisions so far

- **<Done child title>** — <its Outcome body, first paragraph>
- …

## Documents

- [<child title>](<slug>.md) — research
- …

<the body of any other text note on the map, e.g. an assembled brief, verbatim, under its own
heading; and the `## Not yet specified` / `## Out of scope` sections of Map.md if it exists>
```

## Confirmation block (step 5)

```
Shelve "<map title>" in the Library as one item?
  area:  research            (or: painting · teach · misc · …)
  tags:  Health, Home        (the map's Category and Group)
  documents:
    - which-dance-styles-are-there.md            ← Which dance styles are there…
    - where-and-how-do-adults-learn.md           ← Where and how do adults…
    - Brief.md  (entry document)
  skipped: "Assemble the landscape brief" (kind task), "…" (no text document)
```

## Re-run (step 2)

```
"<map title>" is already shelved as "<item title>" (library: … action item, ticked <date>).
Missing there: <names not in get_item(item)["documents"]>  — add them?  [add missing / stop]
```
Adding missing documents never re-creates `Brief.md` unless it is missing too, and never
re-pins. The map's `library:` action item is left as it is.
