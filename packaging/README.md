# Packaging targets

Everything that launches the app lives here; the app modules never change for a new target
(the one exception was adding `/healthz`, which every target probes). `packaging/` has no
`__init__.py` and is never imported — it would shadow the PyPI `packaging` library. Scripts run
the launcher by path.

**Operating model.** Docker owns the app's port (8900) in normal operation. The Linux desktop
entry and the macOS `.app` attach a window to whatever answers `/healthz` there; only when
nothing does, they start their own uvicorn on a free port and stop it when the window closes.
The dev server (`./run.sh`) is for development: run it with the container stopped, or it fails
to bind. Never have two servers on the same `~/learning-library` at once — it holds a SQLite
file and the git undo store.

**Data.** `~/learning-library/` (items, `library.db`, the git repo). `LIBRARY_HOME` overrides
the path; the image sets it to `/data`, and the homelab compose bind-mounts
`~/learning-library` there.

**Claude edits.** The image has no `claude` CLI or subscription, so a Claude run started
against the container answers "claude CLI not found". With the container owning 8900 the
desktop window attaches to it and inherits that limit. To use the ✨ Claude tab, stop the
container (`docker compose stop library` in the homelab repo) and open the window or
`./run.sh` — the launcher then starts a local server that finds `claude` on your PATH.

## server (dev)

```bash
./run.sh              # uv run app.py → http://127.0.0.1:8900
./run.sh rebuild      # regenerate library.db from ~/learning-library/items
```

## docker

Build context is the repo root. There is no build backend (flat modules), so the image installs
the locked dependencies with uv and runs the modules from `/app`. `git` is installed for gitops;
a fixed git identity is baked in because the container runs as the host uid with no passwd entry.

```bash
docker build -f packaging/docker/Dockerfile -t library .
docker run --rm -p 127.0.0.1:8900:8000 -v ~/learning-library:/data library
```

The `homelab` repo's `compose.yml` builds this Dockerfile, mounts `~/learning-library:/data`,
and publishes `127.0.0.1:8900:8000`; `compose.linux.yml` runs it as uid 1000 so the files stay
yours.

## desktop/launcher.py

Shared pywebview launcher; the CONFIG block at the top is the only per-repo difference.

```bash
uv run --extra desktop packaging/desktop/launcher.py
```

## desktop/linux

Arch/Omarchy or Debian/Ubuntu, pywebview's GTK/WebKit2 backend. `install.sh` (re-runnable):

1. checks the distro packages (`python-gobject gtk3 webkit2gtk-4.1` on Arch,
   `python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1` on Debian);
2. **pins the project to the distro Python** (`uv python pin --resolved $(command -v python3)`,
   written to the gitignored `.python-version`) and runs `uv sync --extra desktop`. The distro
   `gi` is a C extension built for the distro interpreter; a uv-managed Python cannot import it.
   The pin is per machine, so a fresh clone runs uv's default Python until `install.sh` runs,
   which recreates `.venv` once;
3. drops `system-gi.pth` into the venv so the distro `gi` is importable (appended to `sys.path`,
   so the venv's own packages still win);
4. renders `library.desktop` with this repo's path and installs it with `library.png` under
   `~/.local/share`.

`run.sh` is what the entry executes: it exports `GI_TYPELIB_PATH`, sets
`WEBKIT_DISABLE_DMABUF_RENDERER=1` (WebKitGTK's DMA-BUF path crashes with a Wayland protocol
error on Hyprland + NVIDIA) and execs `uv run --extra desktop packaging/desktop/launcher.py`.
The window's class is `launcher.py` (GTK names it after the script), which is what the
`.desktop` entry's `StartupWMClass` matches. `uninstall.sh` reverses the install.

## desktop/macos

`build.sh` compiles `launcher.c`, assembles and ad-hoc signs `/Applications/library.app` with the
committed `library.icns`. The launcher is a compiled Mach-O, not a shell script: TCC attributes
Documents-folder access to the code signature, and a zsh launcher is attributed to `/bin/zsh`
and dies with EPERM reading the repo. It sets `LIBRARY_APP_ICON`, cds to
`~/Documents/GitHub/library` (compiled in) and execs `/opt/homebrew/bin/uv run --extra desktop
packaging/desktop/launcher.py`. Approve the Documents prompt on first launch; every rebuild
re-signs, so macOS asks again. `make_icon.py` regenerates the artwork (see the comment at the
end of `build.sh`).
