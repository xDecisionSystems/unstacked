# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-09-16 02:31 UTC — Claude Code
The issued API token was a raw `<pre>` that overflowed its column instead of
wrapping, with no way to copy it besides manual text selection. It now sits
in a bordered box that wraps long text and has a Copy button.

- Files: `app/templates/admin.html`, `app/static/style.css`, `LOG.md`

## 2026-09-16 02:26 UTC — Claude Code
Fixed an undefined `issuedToken` reference in the Settings API-token form:
the `#issued-token` `<pre>` was never queried into a variable, so displaying
a freshly issued token threw `ReferenceError: issuedToken is not defined`
instead of showing it.

- Files: `app/templates/admin.html`, `LOG.md`

## 2026-09-15 00:59 UTC — Claude Code
Added email invitations for user account creation: administrators can invite
a user by email and display name from Settings, and the recipient follows a
signed 7-day link to choose their own username and password. New accounts
start in no groups, so every active administrator gets an email nudge to
assign group memberships once the invite is accepted.

Tests: Ruff and full pytest suite pass (same pre-existing mkdocs-dependent
failures as before).
- Files: `app/admin_api.py`, `app/invitations.py`, `app/mailer.py`,
  `app/templates/accept_invite.html`, `app/templates/admin.html`,
  `app/web.py`, `tests/test_admin_api.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-14 04:39 UTC — Codex
Moved SMTP test-email feedback beside its Test button, with inline success and
error states instead of using the page-level settings message.

Tests: Ruff and focused admin-console test pass.

- Files: `app/static/style.css`, `app/templates/admin.html`, `tests/test_web.py`,
  `LOG.md`

## 2026-09-14 03:28 UTC — Codex
Made page-editor Save and Cancel controls persist while scrolling: sticky in
the desktop action rail and floating at the lower right on narrow screens.

Tests: Ruff and focused page-editor tests pass.

- Files: `app/static/style.css`, `LOG.md`

## 2026-09-13 02:22 UTC — Codex
Grouped SSH archive actions into one vertical control stack so their spacing
stays consistent, including the immediate archive action.

Tests: Ruff and focused admin-console test pass.

- Files: `app/static/style.css`, `app/templates/admin.html`, `LOG.md`

## 2026-09-13 02:06 UTC — Codex
Added an admin-only SMTP test-email action with a recipient field so saved
mail settings can be verified without starting a password-reset flow.

Tests: Ruff and focused SMTP API/console tests pass. Compose build and
health check pass on local port 8001.

- Files: `app/admin_api.py`, `app/mailer.py`, `app/templates/admin.html`,
  `tests/test_admin_api.py`, `LOG.md`

## 2026-09-13 02:02 UTC — Codex
Aligned the book-permissions matrix so book names stay left-aligned and the
per-book default-access icon group is pinned to the right edge of its column.

- Files: `app/static/style.css`, `LOG.md`

## 2026-09-11 19:33 UTC — Codex
Restored the required App CI coverage threshold with targeted tests instead
of weakening the 85% gate. Added coverage for widget-source validation,
widget ACL behavior, malformed card-link data, and public-site staging,
publication, and worker fail-closed paths. This protects the recently added
widget and split public-site behavior while making CI actionable again.

Tests: Ruff and the complete pytest suite pass at 85.02% coverage.
- Files: `tests/test_home_widgets.py`, `tests/test_public_site.py`, `LOG.md`

