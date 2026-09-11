# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-09-11 04:42 UTC — Codex
Made source-backed widgets create their own deterministic Markdown files on
save. Source paths derive from the host and widget ID; each new file contains
a commented example, and widget rows now link directly to its editor.

Tests: Ruff and focused widget/editor tests pass.
- Files: `app/content.py`, `app/home_widgets.py`, `app/search.py`, `app/static/widget_editor.js`,
  `app/templates/_widget_editor.html`, `app/templates/home_editor.html`,
  `app/web.py`, `tests/test_home_widgets.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 04:30 UTC — Codex
Added a Horizontal separator widget to the Home, Book, and Page pickers. It
renders a palette-aware divider and requires no Markdown source file.

Tests: Ruff and focused separator/widget-picker tests pass.
- Files: `app/home_widgets.py`, `app/static/style.css`,
  `app/static/widget_editor.js`, `app/templates/_content_widgets.html`,
  `app/templates/_widget_editor.html`, `app/templates/home_editor.html`,
  `tests/test_home_widgets.py`, `LOG.md`

## 2026-09-11 04:27 UTC — Codex
Added the missing Text choice to Home's widget picker. Selecting it now
reveals the same required Markdown source-page field available in Book and
Page widget editors.

Tests: Ruff and the focused Home widget-picker test pass.
- Files: `app/templates/home_editor.html`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 04:22 UTC — Codex
Added an explicit Switching cards widget choice for the ADC Lab Hiring-style
filter controls. It uses the existing Markdown source format for title,
intro, filter labels, card memberships, and card content.

Tests: Ruff and focused text/data-card/switching-card tests pass.
- Files: `app/home_widgets.py`, `app/templates/_content_widgets.html`,
  `app/templates/_widget_editor.html`, `app/templates/home_editor.html`,
  `tests/test_home_widgets.py`, `LOG.md`

## 2026-09-11 03:49 UTC — Codex
Enabled safe Markdown formatting for data-card widget introductions and card
text. These fields now render through the same Markdown pipeline as Text
widgets, while titles, labels, dates, and filter controls remain plain text.

Tests: Ruff and focused text/data-card widget tests pass.
- Files: `app/static/style.css`, `app/templates/_content_widgets.html`,
  `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 03:46 UTC — Codex
Extended portable widgets from Home to book and page views. Authors can now
add Markdown-backed text or data-card widgets in Book and Page editors; text
widgets render an authorized source Markdown page below the host content.

Tests: Ruff and focused widget renderer, Book, and Page-view tests pass.
- Files: `app/ai_service.py`, `app/content.py`, `app/home_widgets.py`,
  `app/static/widget_editor.js`, `app/static/widget_filters.js`,
  `app/templates/_content_widgets.html`, `app/templates/_widget_editor.html`,
  `app/templates/base.html`, `app/templates/book.html`,
  `app/templates/book_editor.html`, `app/templates/editor.html`,
  `app/templates/page.html`, `app/templates/tree.html`, `app/web.py`,
  `tests/test_home_widgets.py`, `tests/test_web.py`, `LOG.md`

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
