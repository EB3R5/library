# Carryovers from the old learning-library plan

Resolves [Carryovers from the old learning-library plan](https://github.com/EB3R5/library/issues/2).
Source: `~/Documents/GitHub/learning-library/plan.md` (locked 2026-07-22, archived).
Each old decision judged against the new baseline (`docs/DESIGN-SKETCH.md` + Claude-in-the-loop editing).

## Adopt

| Old decision | Carries over as |
|---|---|
| **Serve by ID, never by request path** — `/doc/{id}` resolves via the index; no path from a request | Adopt verbatim. Complements the sketch's containment rule (an item may only read files inside its own dir). |
| **Bind 127.0.0.1 only; network layer is the access control** | Adopt verbatim. Port number decided in [Run and deploy story](https://github.com/EB3R5/library/issues/6). |
| **Bundle signature detection** — `MISSION.md` + `lessons/` marks a teach workspace; files typed by location | Adopt into the import scanner (the sketch already uses the same signature for bundles). |
| **Text extraction** — markdown indexed as-is; HTML stripped to text for FTS, never modified for serving | Adopt verbatim (already in the sketch's FTS note). |
| **Serve HTML byte-for-byte untouched** (no injected chrome, no serve-time rewriting) | Adopt *at serve time*. Claude edits modify files **at rest** through the diff→Accept loop, so this doesn't conflict. |
| **Opportunistic mtime-sweep reindex on page load** | Adopt **adapted**: sweep `~/library/items/` (not sources) so out-of-band file edits never leave FTS stale. Source folders are only scanned on demand in the import review panel, per the sketch. Detail lands in the spec. |
| **Exclude repo-embedded research notes** | Adopt: registered sources only; a repo note can become a one-off import later. |
| **Job framing: re-entry first, search second** | Adopt in spirit. The Workbench serves re-entry via `last_opened` recents; how prominently is a UI-ticket question, noted as input to [Claude features in the Workbench UI](https://github.com/EB3R5/library/issues/5). |
| **DB-as-content-store rejection** — files are content, DB is index/gatekeeper | Adopt; identical to the sketch's rebuildable-cache rule. |

## Reject

| Old decision | Why it dies |
|---|---|
| **Strictly read-only; only write is the index DB** | Reversed by design: app-owned `~/library/` exists precisely to make writes safe. |
| **Index DB at `~/.local/share/learning-library/`** | DB is `~/library/library.db` per the sketch (rebuildable from files). |
| **Three-page UI (home / search / doc)** | Superseded by the single-screen Workbench (research-library variant B verdict). |
| **No iframe for lessons; browser back is the way home** | Superseded by the newer prototype verdict: iframe center pane. Byte-untouched serving survives inside the iframe. |
| **Tags cut as YAGNI** | Sketch's baseline includes flat tags + areas; the cut is obsolete. |
| **Index sources in place (`~/research`, `~/teach`) as permanent roots** | Replaced by import-by-copy into `~/library/`; sources are scan targets, not the served corpus. |

## Folds into an existing ticket (no new tickets needed)

For [Run and deploy story](https://github.com/EB3R5/library/issues/6):

- **TCC**: the old plan moved `~/Documents/painting` → `~/teach` because launchd
  processes can't read `~/Documents`. Import-by-copy makes this *mostly* moot —
  the served corpus lives in `~/library/` — but the **import scanner** still reads
  source folders, so if the app runs under a LaunchAgent, scanning
  `~/Documents/painting` will hit TCC. Options for that ticket: (a) run the app
  manually from a terminal (inherits its FDA, simplest), (b) move the workspace to
  `~/teach` anyway, (c) LaunchAgent + compiled Mach-O launcher (see the
  mealie-planner `scripts/macos-app/` reference impl; zsh-script .app launchers
  get TCC EPERM).
- **Deploy machinery**: `uv tool install` copy + LaunchAgent (`KeepAlive`,
  `RunAtLoad`) + `make deploy` (`--reinstall` + `launchctl kickstart`) is a proven
  recipe if always-on wins; `./run.sh` dev-style (supplement-tracker,
  ontology-studio) if manual wins. Old plan's "runtime state never in the repo"
  holds either way (`~/library/` is outside the repo already).
