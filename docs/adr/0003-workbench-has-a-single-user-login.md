---
status: accepted
---

# The Workbench has a single-user login

Until now the library had no authentication: `config.py` bound it to
127.0.0.1 and "the network layer is the access control". Two things changed
that on 2026-10-07. The repository is public, so the exact routes and the
absence of a login are visible to anyone; and the homelab serves port 8900 to
the tailnet over `tailscale serve`, so every device on that tailnet (and every
node shared into it) could read, write and delete the whole library. Research
written in the private, password-protected Tasks app is about to be shelved
here (ADR 0007), which makes the gap matter.

The library now asks for a username, a password and a TOTP code once per
session, exactly as tasks-webapp does. One credential row lives in a `users`
table in `library.db`; `./run.sh create-user` writes it and prints the
authenticator secret. The session cookie is signed with `SESSION_SECRET`
from `library/.env`, which is git-ignored, Docker-ignored and mounted into
the container by the homelab compose as `env_file`. The server refuses to
start without it.

## Considered Options

- **A — Session login, password + TOTP** (chosen): the same shape as
  tasks-webapp (`bcrypt`, `pyotp`, Starlette `SessionMiddleware`), so one
  mental model covers both apps and the code can be lifted almost verbatim.
- **B — Drop 8900 from `tailscale serve`** — rejected as the only measure:
  it keeps the Workbench localhost-only but gives up phone and laptop access,
  and the public code would still describe an open app for anyone who runs it
  the same way.
- **C — Tailscale ACLs / identity headers** — rejected: ties the app's
  safety to one network's configuration, and the desktop window and dev
  server would still be open.
- **D — HTTP basic auth** — rejected: no second factor, and browsers cache
  the credential for the session with no logout.

## Consequences

- Every page and `/api/*` route needs a session, except `/login`, `/logout`
  and `/healthz`. Browser misses redirect to `/login`; API misses get a
  401 JSON. The gate also admits a valid `API_TOKEN` bearer header, which is
  how the agent API (ADR 0005) will get in without a cookie.
- `library/.env` is the first secret in the repo's working tree. It holds
  `SESSION_SECRET` (and later `API_TOKEN`); it is never committed and never
  copied into compose, tests or docs.
- The desktop window (pywebview) shows the login page once per cookie
  lifetime (seven days by default). The dev server needs the same `.env`.
- Tests disable the gate with `app.state.auth_disabled = True`; a dedicated
  test module seeds a user and drives the real gate.
- What this does not cover: rate limiting, account lockout, multiple users,
  password reset. It is one person's library behind one login.
