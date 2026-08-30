# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-30 19:23 UTC — Claude Code
Reviewed Codex's `plan_editable_widget_home.md` at the user's request and
folded in five concrete revisions before any implementation starts:

- A `config: {}` bag on every widget entry from day one, so a later
  widget needing a parameter (count, tag filter) doesn't force a schema
  migration across every existing `index.md`.
- `index.md`'s read access made explicit (open to every authenticated
  user by default -- Home is the shared landing screen) and its write
  access reframed from a hardcoded admin check to the ordinary ACL grant
  model (Admin's existing blanket grant already covers it; any group can
  get an explicit grant, same as a book).
- Widgets render in one fixed slot below the body for v1 rather than
  interleaved inline via placeholder tokens -- real `mkdocs build
  --strict` has no concept of such a token and would render it as literal
  text in the static export; inline placement would need a
  `hooks/drafts.py`-style build-time handler, deferred as unnecessary for
  a single-widget v1.
- A concrete candidate-widget list beyond `featured` (recently updated,
  by tag, pinned/announcement, your-drafts-or-writable), ordered by how
  little new plumbing each needs, plus an explicit call to avoid any
  widget needing a new counter store (e.g. "most viewed") since that's
  either a new DB table -- outside the users/groups/ACL guardrail -- or a
  JSON file taking a write on every page view.
- A concurrency note: a widget-only reorder must still carry the page's
  current blob SHA, since front matter and body share one file and one
  conflict domain.

Added a matching acceptance criterion (static build shows only the body,
no widget content or placeholder text) and a verification-phase mention
of testing the new default-read grant and the `config` round trip. No
code changes -- planning only, per the user's request to fold improvements
in before implementation begins.
- Files: `plans/plan_editable_widget_home.md`, `LOG.md`

## 2026-08-30 19:08 UTC — Codex
Documented the phased implementation plan for a Git-versioned, editable
Markdown homepage with ACL-aware, reorderable widgets.
- Files: `plans/plan_editable_widget_home.md`, `LOG.md`

## 2026-08-30 18:39 UTC — Codex
Added a generated badger-at-a-typewriter header logo and administrator-managed
branding controls for a custom workspace name and validated raster logo.
- Files: `app/admin_api.py`, `app/branding.py`, `app/config.py`,
  `app/static/branding/badger-typewriter.png`, `app/static/style.css`,
  `app/templates/admin.html`, `app/templates/base.html`, `app/web.py`, `LOG.md`

## 2026-08-30 18:34 UTC — Codex
Separated the workspace landing page from content libraries: Home now shows
only featured items, while new Books and permission-filtered Pages views are
available from the top navigation.
- Files: `app/static/style.css`, `app/templates/base.html`,
  `app/templates/books.html`, `app/templates/pages.html`,
  `app/templates/tree.html`, `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 18:27 UTC — Codex
Replaced text-based home-feature actions with visible star toggles that retain
their selected state and return the user to the current book or library view.
- Files: `app/static/style.css`, `app/templates/book.html`,
  `app/templates/tree.html`, `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 17:18 UTC — Codex
Added optional, safe page-card images. Images are Git-tracked book assets,
validated against the page's book, available through the page editor and API,
and displayed on book and featured-home page cards.
- Files: `app/ai_api.py`, `app/ai_service.py`, `app/content.py`,
  `app/static/style.css`, `app/templates/book.html`,
  `app/templates/editor.html`, `app/templates/page.html`,
  `app/templates/tree.html`, `app/web.py`, `tests/test_assets.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-30 17:07 UTC — Codex
Replaced fake home books with a Git-versioned curated home layout that can
feature real books or pages, and allowed exact permissions only for featured
pages so normal pages retain inherited book access.
- Files: `app/acl.py`, `app/admin_api.py`, `app/content.py`,
  `app/default_groups.py`, `app/static/style.css`, `app/templates/admin.html`,
  `app/templates/book.html`, `app/templates/tree.html`, `app/web.py`,
  `plans/plan_initial.md`, `tests/test_acl.py`, `tests/test_admin_api.py`,
  `tests/test_ai_api.py`, `tests/test_book_migration.py`,
  `tests/test_default_groups.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 07:33 UTC — Codex
Added reserved main-hidden, main-read, and main-write starter books with
front-page pages and suffix-based Public-group default access, while keeping
their book containers out of the dashboard.
- Files: `app/content.py`, `app/default_groups.py`, `app/web.py`,
  `app/templates/tree.html`, `tests/test_ai_api.py`,
  `tests/test_default_groups.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 06:49 UTC — Codex
Replaced the chapter hierarchy with a book-and-page model: legacy chapters
promote to books at startup, their effective grants are preserved, and the
web/settings UI now uses book-level permissions and a draggable page grid.
- Files: `app/acl.py`, `app/admin_api.py`, `app/ai_api.py`,
  `app/ai_service.py`, `app/bootstrap.py`, `app/content.py`,
  `app/default_groups.py`, `app/main.py`, `app/static/style.css`,
  `app/templates/admin.html`, `app/templates/book.html`,
  `app/templates/manage.html`, `app/templates/move_page.html`,
  `app/templates/tree.html`, `app/web.py`, `tests/test_admin_api.py`,
  `tests/test_ai_api.py`, `tests/test_assets.py`, `tests/test_authorization_coverage.py`,
  `tests/test_book_migration.py`, `tests/test_content_build.py`,
  `tests/test_content_lifecycle.py`, `tests/test_content_structure.py`,
  `tests/test_content_symlink_races.py`, `tests/test_default_groups.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-30 06:28 UTC — Codex
Stopped inaccessible book shells from appearing when every chapter is denied
by a more-specific permission rule.
- Files: `app/content.py`, `tests/test_admin_api.py`, `LOG.md`

## 2026-08-30 06:25 UTC — Codex
Added an explicit Reactivate action for inactive accounts, restoring access
through the guarded user-update flow.
- Files: `app/templates/admin.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 06:21 UTC — Codex
Protected the primary Admin account from deletion and styled inactive users'
disabled account actions in gray.
- Files: `app/admin_api.py`, `app/templates/admin.html`,
  `app/static/style.css`, `tests/test_admin_api.py`, `tests/test_web.py`,
  `LOG.md`

## 2026-08-30 06:17 UTC — Codex
Added chapter-level default permission icons and made new custom groups inherit
the Public template’s per-chapter read/write defaults.
- Files: `app/default_groups.py`, `app/admin_api.py`,
  `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_default_groups.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 06:11 UTC — Codex
Added built-in Public and Admin groups: Public begins with no chapter grants,
while Admin receives read/write grants for every current and new chapter.
- Files: `app/default_groups.py`, `app/main.py`, `app/bootstrap.py`,
  `app/content.py`, `app/admin_api.py`, `tests/test_default_groups.py`,
  `LOG.md`

## 2026-08-30 06:04 UTC — Codex
Made inactive chapter-permission buttons white and outlined, with an orange
filled selected state and white icon for clear status contrast.
- Files: `app/static/style.css`, `LOG.md`
