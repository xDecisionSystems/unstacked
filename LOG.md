# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-10-03 07:11 UTC — Claude Code

Added optional GitHub Pages publication of the filtered public site (new app/pages_publish.py; admin API under /api/admin/public-site/pages; UI in Settings → Public website). Own deploy key/known_hosts/config in data/, fast-forward-only push to a configurable branch (default gh-pages) with .nojekyll and optional CNAME; triggered after each successful public build via PublicSiteBuilder.on_published. Also fixed a pre-existing Docker bug: the shared public-site volume was seeded root-owned from the nginx image so the app (UID 999) could never build the public site — pinned app UID/GID 999 and made the nginx image ship an empty UID-999 html dir; README has a one-time repair command for existing volumes.

Files: app/pages_publish.py, app/admin_api.py, app/public_site.py, app/public_site_runtime.py, app/backup_config.py, app/templates/admin.html, app/static/style.css, tests/test_pages_publish.py, Dockerfile, deploy/public.Dockerfile, README.md, LOG.md

## 2026-10-03 06:53 UTC — Claude Code

Redesigned the Git backup form (user found it ugly): labelled URL field, SSH/HTTPS toggle that shows only the relevant fields (auto-switches from the URL), numbered SSH steps, public key in a copyable monospace box, key path tucked under "Use an existing key file", fingerprint in monospace, and one action row. Submit nulls the inactive mode's credentials.

Files: app/templates/admin.html, app/static/style.css, LOG.md

## 2026-10-03 06:21 UTC — Claude Code

Git backup form now supports SSH/GitHub deploy keys: URL field accepts git@ URLs, SSH key path + fingerprint check fields added (the JS existed but the form lacked them), and new GET/POST /api/admin/backup/deploy-key generates an ed25519 key in data/ and returns only the public half (replace needs explicit confirm). Test added.

Files: app/backup_config.py, app/admin_api.py, app/templates/admin.html, tests/test_backup_config.py, LOG.md

## 2026-10-03 06:02 UTC — Claude Code

Docker image now runs `python -m app.bootstrap` before uvicorn so a fresh deploy gets `admin`/`admin` (forced password change) without a manual step; README updated.

Files: Dockerfile, README.md, LOG.md

## 2026-09-23 18:10 UTC — Claude Code
Fixed every uploaded image (page images and page-card images) rendering
broken in the browser: `GET /assets/...` depended on the bearer-only
`get_rate_limited_ai_user`, but a plain `<img src>` sends only the session
cookie, so browsers always got 401. Added an `_asset_viewer` dependency that
takes a bearer token when present (keeping the AI rate limit) and otherwise
the session cookie via `require_normal_web_user`; book ACLs still decide
access and unauthenticated requests still get 401.

Tests: Ruff passes; `tests/test_assets.py` passes, including a new
browser-session test. Full suite: only the mkdocs-dependent
`test_public_site.py` failures, which need the `mkdocs` executable on PATH.
- Files: `app/ai_api.py`, `tests/test_assets.py`, `LOG.md`

## 2026-09-16 06:09 UTC — Claude Code
Fixed a real vulnerability the user spotted by asking the right question:
`clear-inactive` deleting a revoked `ApiToken` row could resurrect that
token, since `get_current_user`'s revocation check only fires when a row
still exists, and individual revoke deliberately never bumps the account's
`api_token_generation` (that's what keeps it from logging out every other
token). Added a `generation` column recorded at issuance; both
clear-inactive endpoints now only delete a row once it is provably inert on
its own -- expired, or superseded by a later generation bump -- never one
that was merely individually revoked.

Tests: Ruff and full pytest suite pass (same pre-existing mkdocs-dependent
failures as before); rewrote the clear-inactive tests to prove the fix
(a revoked-but-unexpired row survives clearing and the token it describes
stays rejected; a generation-superseded row is removed).
- Files: `app/admin_api.py`, `app/ai_api.py`, `app/models.py`,
  `app/migrations/versions/20260916_0005_api_token_generation.py`,
  `tests/test_admin_api.py`, `tests/test_ai_api.py`, `LOG.md`

## 2026-09-16 05:58 UTC — Claude Code
Removed the "Revoke every token for one account" dropdown form from the
Settings token panel: the per-token trash-can icons plus the "My tokens"
and "All tokens (every user)" heading actions already cover every case it
handled, per the user's observation that it was now redundant. The
underlying `/api/auth/tokens/revoke` endpoint is untouched -- the "My
tokens" heading action still calls it for the caller's own account.

Tests: Focused admin-console/token tests pass.
- Files: `app/templates/admin.html`, `LOG.md`

## 2026-09-16 05:52 UTC — Claude Code
Added a "clear" action (distinct X-in-circle icon, next to the existing
revoke trash-can) beside "My tokens" and "All tokens (every user)" that
permanently deletes already-revoked or expired `api_token` rows -- pure
housekeeping, never touches an active token. New endpoints
`POST /api/auth/tokens/clear-inactive` (self, in `ai_api.py`) and
`POST /api/admin/tokens/clear-inactive` (every user, admin-only, in
`admin_api.py`), each returning how many rows were removed.

Tests: Ruff and full pytest suite pass (same pre-existing mkdocs-dependent
failures as before).
- Files: `app/admin_api.py`, `app/ai_api.py`, `app/templates/admin.html`,
  `tests/test_admin_api.py`, `tests/test_ai_api.py`, `LOG.md`

## 2026-09-16 04:58 UTC — Claude Code
Replaced the token tables' text "Revoke" buttons with a trash-can icon
(reusing the existing group-delete SVG, generalized into a shared
`.icon-delete` class), and added the same icon next to the "My tokens" and
"All tokens (every user)" headings to revoke everything in that scope at
once. The latter needed a new admin-only `POST /api/admin/tokens/revoke-all`
endpoint -- there was previously no way to revoke literally every token for
every user in one action, only one account at a time.

Tests: Ruff and full pytest suite pass (same pre-existing mkdocs-dependent
failures as before).
- Files: `app/admin_api.py`, `app/static/style.css`,
  `app/templates/admin.html`, `tests/test_admin_api.py`, `LOG.md`

## 2026-09-16 04:45 UTC — Claude Code
Widened the Settings token panel: `#tokens-section` was missing the
`admin-panel-wide` class every other full-width admin section has, so it
stayed pinned to one column of the 2-column grid and the new token tables
were clipped at the card edge instead of using the available width or
falling back to their own scrollbar.

Tests: Focused admin-console/token tests pass.
- Files: `app/templates/admin.html`, `LOG.md`

## 2026-09-16 04:35 UTC — Claude Code
Converted the Settings token panels ("My tokens" and "All tokens (every
user)") from flat `<article>` rows to real `<table>` markup with column
headers (User where applicable, Description, Issued, Expires, Status,
Action), per the user's request. Added a small reusable `.data-table`
style rather than repurposing the centered-text permission-matrix table.

Tests: Focused admin-console/token tests pass; full pytest suite green
(one unrelated pre-existing flaky test reproduced failing once, passed on
rerun in isolation and as part of the full file).
- Files: `app/templates/admin.html`, `app/static/style.css`, `LOG.md`

## 2026-09-16 04:23 UTC — Claude Code
Replaced the "Revoke all tokens" form's free-typed numeric User ID field
with a dropdown of actual accounts (display name + username), populated
from the same users list the page already fetches. The user pointed out
that typing a raw ID was awkward now that the new all-users token list
already shows names.

Tests: Ruff and focused admin-console/token tests pass.
- Files: `app/templates/admin.html`, `LOG.md`

## 2026-09-16 04:05 UTC — Claude Code
Added `GET /api/admin/tokens`, listing every issued API token across all
accounts with the owning user's username/display name attached, plus an "All
tokens (every user)" panel in Settings. Revoking reuses the existing
per-token revoke endpoint, which already allowed an admin to revoke any
user's token -- this was the missing way to find it.

Tests: Ruff and focused admin-API/token tests pass; full pytest suite green
(same pre-existing mkdocs-dependent failures as before).
- Files: `app/admin_api.py`, `app/templates/admin.html`,
  `tests/test_admin_api.py`, `LOG.md`

## 2026-09-16 03:08 UTC — Codex
Recorded the user's approval for non-secret API-token metadata in SQLite,
updating the database-boundary guidance while retaining the ban on content and
raw token storage.

- Files: `AGENTS.md`, `plans/plan_initial.md`, `LOG.md`

## 2026-09-16 03:04 UTC — Claude Code
Issuing a token now records a description and a chosen lifetime (1h/1d/7d/
30d/90d/never) in a new `api_token` table, and shows the issue date and
expiry alongside the token. A token can be revoked individually without
logging out every other integration on the account; the existing "revoke
all" action now also marks the affected rows so the list stays accurate.
Every existing bare-minted token (the whole test suite, bootstrap, etc.)
keeps working unchanged -- the account-generation counter remains the actual
security boundary, and the new per-row check only applies when a row exists.

Tests: Ruff and full pytest suite pass (same pre-existing mkdocs-dependent
failures as before).
- Files: `app/admin_api.py`, `app/ai_api.py`, `app/auth.py`,
  `app/migrations/versions/20260915_0004_api_tokens.py`, `app/models.py`,
  `app/templates/admin.html`, `app/web.py`, `app/web_auth.py`,
  `tests/test_ai_api.py`, `tests/test_models.py`, `LOG.md`
