# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-09-07 13:55 UTC — Codex
Moved the group deletion action into each group heading and replaced the
ambiguous “×” with a labelled trash-can icon. Group membership remains a
checkbox matrix, so no per-user delete control is presented.

Ruff and the focused Settings page test pass.
- Files: `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-07 13:34 UTC — Codex
Moved the destructive Home reset action from Settings into the Home editor,
where it is available only to administrators and carries its warning next to
the content it replaces. Removed the obsolete Settings navigation item.

Ruff and focused Settings/Home editor tests pass.
- Files: `app/templates/admin.html`, `app/templates/home_editor.html`, `LOG.md`

## 2026-09-07 13:33 UTC — Codex
Changed the Settings download from generated static HTML to a portable MkDocs
source ZIP. The archive contains the buildable content project and excludes
Git internals and symlinks, so it is safe to transfer or retain as a source
backup.

Ruff and focused export/settings tests pass.
- Files: `app/export.py`, `app/web.py`, `app/templates/admin.html`,
  `tests/test_export.py`, `LOG.md`

## 2026-09-07 13:17 UTC — Codex
Renamed the Settings Export panel to Import / Export and added a guarded
Import action. It restores only from the already-linked Git repository and,
when replacement is needed, first verifies a recovery copy and requires a
second confirmation before local content changes.

Ruff, focused settings, and backup-restore tests pass.
- Files: `app/templates/admin.html`, `tests/test_web.py`, `LOG.md`

## 2026-09-07 13:13 UTC — Codex
Standardized ordinary actions to a compact 36px control and stopped Settings
form submit buttons from stretching across their entire panels. This keeps
actions such as Create user proportional to their labels while retaining
larger, dedicated icon targets where interaction needs them.

Ruff and focused web tests pass.
- Files: `app/static/style.css`, `LOG.md`

## 2026-09-07 13:10 UTC — Codex
Removed the redundant Settings-page Invite user shortcut. The Users panel
already contains the complete creation form, so the compact settings layout
now leads directly to the relevant content without duplicating that action.

Ruff and focused web tests pass.
- Files: `app/templates/admin.html`, `app/static/style.css`, `LOG.md`

## 2026-09-07 06:10 UTC — Codex
Captured the live Books workspace into the connected Figma file, then refined
the shared UI rhythm from that review: controls and icon actions now have
consistent sizing, keyboard focus is visible, small screens retain a compact
header, and the Settings control uses the same stroke-based icon language as
the account menu.

Ruff and focused static-export test pass. The full suite has one unrelated
environment failure because `mkdocs` is absent from the shell PATH.
- Files: `app/templates/base.html`, `app/static/style.css`, `LOG.md`

## 2026-09-07 05:18 UTC — Codex
Versioned the shared stylesheet URL with the deployed commit so browsers fetch
the matching header/menu CSS after each release instead of rendering new menu
markup using a cached older stylesheet.

Focused navigation tests and ruff pass.
- Files: `app/templates/base.html`, `LOG.md`

## 2026-09-07 05:13 UTC — Codex
Reworked the responsive top bar so the brand, navigation, and account controls
remain aligned on one row, while search occupies a deliberate full-width row
below. This prevents the settings and user controls from breaking into the
awkward vertical layout shown at tablet widths.

Ruff and whitespace checks pass.
- Files: `app/static/style.css`, `LOG.md`

## 2026-09-07 05:03 UTC — Codex
Replaced the separate top-bar Change password and Log out controls with an
accessible user-icon menu. The menu contains both existing actions while the
administrator settings icon remains directly available.

Focused password-navigation tests and ruff pass.
- Files: `app/templates/base.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-06 03:47 UTC — Codex
Added administrator-managed SMTP delivery settings and a self-service
forgot-password flow. SMTP credentials are stored only in a private `data/`
file; reset emails go only to active accounts with a matching email address,
without disclosing account existence. Reset links are signed, expire after 30
minutes, and become invalid when a password changes. The Docker deployment
configuration now carries the public URL needed to build email links.

Focused SMTP/password-reset tests and ruff pass. Compose verification could
not run because Docker Desktop's daemon is unavailable on this machine.
- Files: `app/smtp_config.py`, `app/mailer.py`, `app/admin_api.py`,
  `app/web.py`, `app/config.py`, `app/templates/admin.html`,
  `app/templates/login.html`, `app/templates/forgot_password.html`,
  `app/templates/reset_password.html`, `docker-compose.yaml`, `.env.example`,
  `tests/conftest.py`, `tests/test_admin_api.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-06 03:18 UTC — Codex
Exposed the existing self-service password-change flow to all authenticated
users with a Change password link in the top bar. The page now distinguishes
between a mandatory change after an administrator reset and an ordinary
voluntary password update. Added coverage that a regular user can reach the
page and use the navigation link.

Focused web and full web-auth tests plus ruff pass.
- Files: `app/templates/base.html`, `app/templates/change_password.html`,
  `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-06 03:16 UTC — Codex
Made the existing administrator password-reset API reachable from Settings.
Every user row now has a temporary-password field and Reset password control;
the confirmation clearly explains that all sessions and API tokens are
revoked and the affected user must replace the temporary password on login.
The API already enforced those security properties, so this exposes the
capability without duplicating auth logic. Added a console markup regression
test for the control and its API wiring.

Focused web and password-reset API tests plus ruff pass.
- Files: `app/templates/admin.html`, `tests/test_web.py`, `LOG.md`

## 2026-09-06 03:01 UTC — Codex
Fixed the Home editor's “Add featured grid” control. It was implemented as
a form nested inside the page-save form, which is invalid HTML and caused
browsers to submit the outer form and redirect to the workspace before adding
the grid. The controls now use a non-form container and a non-submitting
button; Enter in either field adds the grid as well. Updated the template
regression assertion to prevent reintroducing nested forms.

Focused web regression test and ruff pass. The full suite had 738 passing
tests; its lone export failure was caused by this shell's missing `mkdocs` on
`PATH`, and that export test passes when the virtualenv's absolute bin path is
provided.
- Files: `app/templates/home_editor.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-31 06:57 UTC — Claude Code
Implemented Phase 5 ("Card popover"), the fifth and LAST phase of
`plans/plan_multiple_featured_grids.md`. Replaces Phase 3's temporary
hardcoded `grid_id=featured` stopgap on every book/page card's ★/☆ toggle
with a real popover letting an admin choose which grid(s) (of however many
are now configured via Phase 4's editor) a target belongs to. This closes
out the whole 5-phase plan.

- `app/web.py::_base_context` now computes, once per request: a shared
  `_featured_grid_entries(content)` helper (also now used by
  `_require_featured_grid_id`, replacing its own duplicate parse) reads
  Home's configured `featured`-type widgets; each book/page dict gains a
  `featured_grid_ids` set (which configured grids it currently belongs to)
  and `featured` stays as a derived `bool(featured_grid_ids)` convenience;
  the context gains a top-level `featured_grids` list (`{"id", "title"}`
  per configured grid, in authored order) for the popover to render.
- New `app/templates/_widgets.html` partial: one Jinja macro
  `feature_popover(target, return_to, featured_grid_ids, featured_grids,
  csrf_token)`, replacing the identical inline `<form class="card-home-action">`
  block that was previously duplicated in `book.html`/`books.html`/
  `pages.html`. Renders a `<details class="feature-popover">` disclosure
  (matching the existing `new-book-popover` pattern) whose `<summary>`
  reuses the `.feature-star`/★/☆ look, and a panel listing every configured
  grid as a checkbox (checked per `featured_grid_ids`), or, with zero grids
  configured, an `empty-state` message linking to `/home/edit` instead of
  an empty list.
- New `app/static/feature-popover.js`, loaded unconditionally from
  `base.html` (so all four card-bearing pages get it with no per-template
  script block): a single delegated `change` listener on
  `.feature-grid-checkbox` fires one `fetch()` `POST` (form-encoded, via
  `URLSearchParams`, mirroring `page.html`'s existing inline-title-edit
  fetch convention) to `/home/feature` or `/home/remove` per checkbox --
  neither route gained batch support, so this is genuinely one request per
  changed checkbox, not a diff-on-submit. The checkbox disables during the
  request and reverts + `alert()`s on failure; on success the summary
  ★/☆ and `is-featured` class update in place, no page reload.
- `tree.html` keeps its own simple remove-only form (per the plan, its
  cards already belong to the grid they render, so the full checkbox
  popover would be redundant) but now sends the enclosing widget's own
  `id` as `grid_id` instead of Phase 3's hardcoded `"featured"` -- a real
  bug fix: removing an item from e.g. a `research` grid's rendered card
  previously always hit `grid_id=featured` regardless of which grid was
  actually showing it.
- `app/static/style.css`: `.feature-star` joined the base `button,.button`
  selector (it is now sometimes a `<summary>`, not always a `<button>`,
  and needs the same base sizing/cursor/transition), plus new
  `.feature-popover`/`.feature-popover-panel`/`.feature-popover-list`/
  `.feature-popover-option` rules mirroring `.new-book-popover`'s existing
  positioning convention.
- `tests/test_web.py`: the two pre-existing `feature-star`/`is-featured`
  markup assertions needed no changes (the macro renders byte-identical
  classes for those states). Added four new tests: correct per-grid
  checked/unchecked state across three configured grids; the zero-grids
  empty state (message + no checkboxes); `is_admin` gating of the popover
  across `book.html`/`books.html`/`pages.html`; and the `tree.html`
  grid_id bug fix specifically (a widget's own remove form now carries
  its own id, not the old stopgap).

Full suite (313 tests) and ruff clean immediately before committing.
`git fetch origin` before starting and again immediately before committing
both showed no new Codex commits.
- Files: `app/web.py`, `app/templates/_widgets.html` (new),
  `app/templates/book.html`, `app/templates/books.html`,
  `app/templates/pages.html`, `app/templates/tree.html`,
  `app/templates/base.html`, `app/static/feature-popover.js` (new),
  `app/static/style.css`, `tests/test_web.py`, `LOG.md`
