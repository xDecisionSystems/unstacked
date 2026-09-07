# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-31 06:40 UTC — Claude Code
Implemented Phase 4 ("Editor UI") of `plans/plan_multiple_featured_grids.md`,
the fourth of five sequential phases for multiple independently-curated
named featured grids on Home. Entirely a client-side/template change --
`POST /home/edit` already accepted an arbitrary `widgets` list before this
phase, so no new backend route was needed.

- `app/templates/home_editor.html`'s widget tray gained an "Add featured
  grid" form (`#add-widget-form`): an id input, client-side slugified and
  checked against existing rows' `data-id` for uniqueness, plus an
  optional title input. On success it appends a new `.widget-row` built
  the same shape as the server-rendered ones.
- Every row (server-rendered or newly added) now has an editable
  `.widget-title-input`; an `input`-event listener rewrites that row's
  `data-config` JSON in place, so the existing `serializeWidgets()` needed
  no changes at all.
- Every row also has a `.widget-remove` delete button. Its `confirm()`
  names the permanent-deletion behavior explicitly (the user's earlier
  decision: deleting a grid discards its curated list, not just hides it).
  Deletion itself is just `row.remove()` -- the actual
  `.unstacked-home.json` purge already happens automatically, server-side,
  via Phase 1's diff-and-purge logic in `update_home_page` once the row is
  simply absent from the submitted `widgets_json`.
- `app/static/style.css` gained matching styles for the new form/inputs/
  button, following the existing `.widget-*` conventions.
- Added `tests/test_web.py::test_home_edit_renders_multiple_featured_grids_with_their_titles`
  (three grids, each with independent id/title, all correctly pre-filled
  in `GET /home/edit`) and
  `::test_home_editor_widget_tray_includes_add_edit_remove_markup`
  (guards the exact ids/classes/attributes the new client-side JS depends
  on, since real browser interaction is out of scope for the FastAPI
  `TestClient`).

Full suite and ruff clean. `git fetch origin` showed no new Codex commits.
- Files: `app/templates/home_editor.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-31 06:25 UTC — Claude Code
Implemented Phase 3 ("API") of `plans/plan_multiple_featured_grids.md`, the
third of five sequential phases for multiple independently-curated named
featured grids on Home. Before this, Phase 1 (storage) and Phase 2
(rendering) had already made grids independent end to end *except* the two
routes a user actually toggles a star through were still hardcoded to the
one `"featured"` grid id -- this phase makes them genuinely grid-aware.

- `POST /home/feature` and `POST /home/remove` now read a required
  `grid_id` form field instead of hardcoding `"featured"`. A new
  `app/web.py::_require_featured_grid_id` helper reads
  `content.read_home_page()`'s `widgets` front matter through
  `app.home_widgets.parse_widget_entries` and rejects (`400 Bad Request`)
  any submitted `grid_id` that isn't the id of a currently-configured
  `featured`-type widget, before either content-layer call runs -- the same
  "reject rather than silently create an orphaned grid" posture the widget
  registry already takes with an unknown widget `type`. A rejected request
  writes nothing to `.unstacked-home.json`.
- Temporary stopgap (this task only, not phase 5's popover): added a hidden
  `<input type="hidden" name="grid_id" value="featured">` to the ★/☆ toggle
  forms in `app/templates/book.html`, `books.html`, `pages.html`, and
  `tree.html` (remove-only there), so the existing single-star interaction
  keeps working against the now-validating API, pointed at the one grid
  guaranteed to exist in every repo. Phase 4/5 replace this with real
  add/remove/rename controls and a multi-grid checkbox popover.
- Updated all ~8 existing `tests/test_web.py` call sites that posted to
  `/home/feature`/`/home/remove` to include `"grid_id": "featured"`. Added
  three new tests: an unconfigured `grid_id` is rejected with 400 on both
  routes and leaves `.unstacked-home.json` byte-for-byte unchanged; a valid
  non-default grid (`research`, added via `update_home_page` the way the
  future editor UI will) receives exactly the toggled target while
  `featured` stays empty; and the same target toggled into two different
  valid grids ends up in both independently.

Full suite and ruff clean; `git fetch origin` immediately before starting
and again immediately before committing both showed no new Codex commits.
- Files: `app/web.py`, `app/templates/book.html`, `app/templates/books.html`,
  `app/templates/pages.html`, `app/templates/tree.html`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-31 06:15 UTC — Claude Code
Implemented Phase 2 ("Rendering") of `plans/plan_multiple_featured_grids.md`,
the second of five sequential phases for multiple independently-curated
named featured grids on Home. Each `featured` widget instance now curates
from its own grid and gets its own optional heading, instead of every
instance implicitly sharing the single `"featured"` grid and a hardcoded
`"Featured"` title (Phase 1 already made the storage layer grid-keyed;
this phase makes rendering actually use a widget's own identity).

- `app/home_widgets.py::_render_featured`: reads `content.home_items(entry.id)`
  instead of the hardcoded `"featured"` id; `title` now comes from
  `entry.config.get("title")` (stripped; blank/whitespace/non-string all
  collapse to `""`, meaning no header) instead of the removed
  `_FEATURED_WIDGET_TITLE` constant.
- `app/web.py::_public_home_widgets` (the anonymous-visitor mirror added
  earlier this session) gets the identical two changes, so a public Home
  view renders multiple grids correctly too.
- `app/templates/tree.html`: reintroduced a per-widget `<h2>{{ widget.title }}</h2>`,
  but conditionally -- `{% if widget.title %}` -- so an untitled grid still
  renders with no visible heading, matching "optional title header" from
  the plan. Since `widget.title` can now legitimately be empty, the
  section's `aria-label` gained a fallback (`"<Type> widget"`) so it is
  never blank for a screen-reader user.
- Added unit coverage in `tests/test_home_widgets.py` (two independent
  grids with disjoint, ACL-filtered item sets; title derivation for
  blank/whitespace/non-string config) and browser-level coverage in
  `tests/test_web.py` (authenticated and anonymous/public `GET /tree`
  both showing two widgets with only the titled one rendering an `<h2>`).

Full suite and ruff clean. `git fetch origin` showed no new Codex commits
throughout.
- Files: `app/home_widgets.py`, `app/templates/tree.html`, `app/web.py`,
  `tests/test_home_widgets.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-31 05:50 UTC — Claude Code
Hid the "History" link on a page view for unauthenticated visitors, per
the user's request. `/pages/{path}/history` requires a real session
(`require_normal_web_user`); on a public page (see the earlier
Publish-Home-publicly work) the link was a dead end for anyone without an
account -- clicking it just hit a raw 401. Wrapped the link in
`{% if current_user %}` in `app/templates/page.html`. Added
`tests/test_web.py::test_public_page_hides_the_history_link_for_an_anonymous_visitor`
confirming the link is present for a signed-in viewer and absent for an
anonymous one on the same public page. Full suite and ruff clean.
- Files: `app/templates/page.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-31 05:42 UTC — Claude Code
Implemented Phase 1 ("Content layer") of `plans/plan_multiple_featured_grids.md`
-- the user-approved design for multiple independently-curated named
featured grids on Home, of which this is the first of five sequential
phases. Purely an internal storage-shape change in `app/content.py`; zero
user-visible behavior change (still exactly one grid, `"featured"`).

- `.unstacked-home.json` moves from flat `{"items": [...]}` to grid-keyed
  `{"grids": {"<grid_id>": [...], ...}}`. A new `_load_home_layout()`
  reads both shapes -- the old flat shape (no `"grids"` key) is treated as
  exactly one implicit `"featured"` grid -- with no migration script and
  no forced rewrite-on-read; the file naturally moves to the new shape the
  next time any grid is written.
- `home_items(grid_id: str | None = None)`: a specific grid's ordered
  targets (`[]` if that grid has no list yet, not an error) when given, or
  the de-duplicated union of every grid's targets in first-seen,
  file-key order when omitted -- the shape the admin "Featured page
  overrides" permission matrix (`app/admin_api.py`, left unchanged, still
  calls with no `grid_id`) needs.
- `feature_on_home`/`remove_from_home` gained a required `grid_id`
  parameter; each reads/writes only that one grid's list inside the
  shared `{"grids": {...}}` file, leaving every other grid's list
  untouched under the same write lock.
- `update_home_page` now diffs the current (pre-write) page's
  `featured`-type widget ids against the incoming ones; any id dropped
  from the tray has that grid's curated list deleted (not merely emptied)
  from `.unstacked-home.json` in the same locked operation -- recreating a
  widget with the same id later starts empty. Both files land in one
  `git.commit_paths` call when a grid was purged; only `index.md` is
  committed otherwise (unchanged from before). Mirrors
  `set_container_public`'s try/except rollback pattern so a failure after
  the page write restores both files atomically.
- Updated every existing call site (`app/web.py`, `app/home_widgets.py`,
  and the pre-existing tests in `tests/test_home_widgets.py`/
  `tests/test_admin_api.py`) to pass `grid_id="featured"` explicitly, so
  today's single-grid behavior is identical end to end -- no template, API
  parameter, or UI change in this phase.
- Added unit test coverage in `tests/test_home_page.py`: legacy flat-shape
  reads, unknown-grid-id returns `[]`, per-grid write isolation, the
  cross-grid de-duplicated union, the purge-on-widget-delete behavior
  (confirmed via both `home_items()` and the raw committed JSON, plus the
  actual commit's changed-file set), and the no-purge case still
  committing only `index.md`.

`git fetch origin` before starting showed Codex's Milkdown-revert and
Home-publishing work already merged into local `main`; re-read those
diffs and confirmed none touch `home_items`/`feature_on_home`/
`remove_from_home`/`update_home_page`, so this work applied cleanly on
top with no rebase needed. Full suite and ruff clean immediately before
committing.
- Files: `app/content.py`, `app/home_widgets.py`, `app/web.py`,
  `tests/test_home_page.py`, `tests/test_home_widgets.py`,
  `tests/test_admin_api.py`, `plans/plan_multiple_featured_grids.md`,
  `LOG.md`
