# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-09-11 03:38 UTC — Codex
Made Home widgets explicitly palette-aware. Featured and data-card widgets
now derive their card colors, controls, links, and shadows from the active
palette rather than retaining fixed original-theme colors.

Tests: Ruff plus focused palette and Home-widget tests pass.
- Files: `app/static/style.css`, `LOG.md`

## 2026-09-11 03:36 UTC — Codex
Made generic data-card widgets Markdown-driven and added ADC Lab-style
switchable category filters. The source page now supplies the widget title,
introductory text, filter labels, card memberships, and all card details.

Tests: Ruff and focused Home-widget/editor tests pass.
- Files: `app/home_widgets.py`, `app/static/style.css`,
  `app/templates/home_editor.html`, `app/templates/tree.html`,
  `tests/test_home_widgets.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 03:31 UTC — Codex
Expanded generic Home data-card widgets with optional introductory text. The
widget title now occupies a left-hand heading column, while its introduction
appears above the card grid; the layout stacks cleanly on narrow screens.

Tests: Ruff and focused Home-widget tests pass.
- Files: `app/home_widgets.py`, `app/static/style.css`,
  `app/templates/home_editor.html`, `app/templates/tree.html`,
  `tests/test_home_widgets.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 03:27 UTC — Codex
Simplified the generic data-card schema: each card requires a title and can
optionally include text, a label, and a date. Authorized internal title links
remain available through the optional target field.

Tests: Ruff and focused data-card tests pass.
- Files: `app/home_widgets.py`, `app/templates/tree.html`,
  `tests/test_home_widgets.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 03:25 UTC — Codex
Added optional internal targets to generic data cards. A card title can now
link to an authorized book (`research`) or page (`research/project.md`),
while an external URL remains the fallback link when no internal target is
configured.

Tests: Ruff and focused data-card tests pass.
- Files: `app/home_widgets.py`, `app/static/style.css`,
  `app/templates/tree.html`, `tests/test_home_widgets.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-11 03:21 UTC — Codex
Added the generic Markdown-backed `data-cards` Home widget. Any authorized
book page can supply one front-matter `cards` list; Home editors choose its
source and label, and the widget renders responsive linked cards without a
new database table or grants-specific code.

Tests: Ruff, focused widget/browser tests, strict content-build tests, and
nav tests pass.
- Files: `app/home_widgets.py`, `app/static/style.css`,
  `app/templates/home_editor.html`, `app/templates/tree.html`,
  `tests/test_home_widgets.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 03:13 UTC — Codex
Stabilized the compact filter control's layout: its closed button and open
search state now reserve the same row height, so cards do not jump when the
search field is toggled.

Tests: Ruff passes.
- Files: `app/static/style.css`, `LOG.md`

## 2026-09-11 03:10 UTC — Codex
Replaced always-visible library search fields with compact funnel controls.
Books, Pages, and book page grids now reveal their existing search input only
when requested, preserving live filtering and keyboard focus behavior.

Tests: Ruff and focused Books/Pages/browser tests pass.
- Files: `app/static/filter_toggle.js`, `app/static/style.css`,
  `app/templates/book.html`, `app/templates/books.html`,
  `app/templates/pages.html`, `LOG.md`

## 2026-09-11 03:01 UTC — Codex
Improved password-manager compatibility on the login form with stable
username/password IDs, explicit label bindings, and standard autocomplete
hints so Bitwarden can reliably fill both credentials.

Tests: Ruff and focused login browser tests pass.
- Files: `app/templates/login.html`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 02:56 UTC — Codex
Added an editable Markdown introduction to every book. The section is stored
portably in each book's `.pages` file, rendered above its page grid, and can
be edited with the Toast UI book editor by users with book write access.

Tests: Ruff, focused book-editor browser tests, content-build tests, and nav
tests pass.
- Files: `app/ai_service.py`, `app/content.py`, `app/nav.py`,
  `app/templates/book.html`, `app/templates/book_editor.html`, `app/web.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-11 02:45 UTC — Codex
Completed the public/management separation at the browser-route boundary.
Anonymous management visits to Home, Books, Pages, individual books, and
individual pages now redirect to login; public content is served only by the
filtered public static service.

Tests: Ruff, focused management-route browser tests, and public-site tests
pass.
- Files: `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 02:36 UTC — Codex
Made the management site explicitly login-first: anonymous visits to its
root or Settings page now redirect to the existing login screen even when
the separately served public Home is enabled.

Tests: Ruff and focused management-login browser tests pass.
- Files: `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-09 05:57 UTC — Codex
Implemented the split public/management deployment: a filtered, atomic
public MkDocs build now runs independently of the authenticated FastAPI site,
with safe Settings controls, a loopback-only Nginx service, and proxy setup
guidance. Public builds include only explicitly public content and preserve
the last good site on failure; archive-backup and public-build triggers now
coexist.

Tests: Ruff; public-site, admin, backup-listener, and Git backend tests pass.
Local Compose verification: management healthy on 18094 and filtered public
site healthy on 18095.
- Files: `.env.example`, `Dockerfile`, `README.md`, `app/admin_api.py`,
  `app/backup_runtime.py`, `app/config.py`, `app/export.py`,
  `app/git_backend.py`, `app/main.py`, `app/public_site.py`,
  `app/public_site_runtime.py`, `app/templates/admin.html`,
  `deploy/public-nginx.conf`, `docker-compose.yaml`, `plans/plan_initial.md`,
  `tests/conftest.py`, `tests/test_admin_api.py`, `tests/test_public_site.py`,
  `LOG.md`

## 2026-09-09 05:22 UTC — Codex
Added a plan for a separate public static site and management site while
explicitly preserving the current Unstacked login process and permissions.

- Files: `plan/split_site_plan.md`, `LOG.md`

## 2026-09-09 03:24 UTC — Codex
Made top-bar content navigation explicitly session-only and added regression
coverage proving anonymous public book and page views do not expose Books or
Pages links, while authenticated users still receive them.

Tests: focused public-view browser tests pass.
- Files: `app/templates/base.html`, `tests/test_web.py`, `LOG.md`
