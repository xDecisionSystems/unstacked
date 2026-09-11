# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-09-11 06:06 UTC — Claude Code
Fixed three data-loss risks from the widget-feature commits (see
`plans/plan_widget_regression_fixes.md`, Phase 2): a page/Home save that
failed validation or hit a conflict redisplayed the widget editor with an
empty tray regardless of what was submitted, so an unnoticed resubmission
would wipe every widget (now recovers the submitted list for redisplay via
a new `_redisplay_widgets` helper); removing a widget never deleted its
generated Markdown source, so reusing the same id later silently
resurrected the old file's stale content instead of a fresh starter
template (`ensure_widget_sources` now prunes sources its location no
longer references, scoped to that location's own filename prefix so a
book's and its pages' sources sharing one directory can't cross-delete
each other); and a failure in `ensure_widget_sources` *after* the main
content commit already succeeded routed the response through the error
path (claiming nothing was saved) or, for a bare `OSError`, crashed as an
unhandled 500 -- now caught, logged, and the save still redirects as the
success it is.

Tests: Ruff and full pytest pass (same two pre-existing, unrelated
failures as before).
- Files: `app/content.py`, `app/web.py`, `plans/plan_widget_regression_fixes.md`,
  `tests/test_home_widgets.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 05:38 UTC — Claude Code
Fixed four regressions from the recent widget-feature commits (see
`plans/plan_widget_regression_fixes.md`, Phase 1): non-admin readers saw
empty data-cards/text widgets on Home because their generated source path
had no ACL rows of its own (now decided against `index.md`, matching the
write path); the shared widget macro had silently dropped the admin
"remove from Home" control (restored); `switching-cards` widgets never
rendered their Markdown text (the check only matched the literal
`"data-cards"` type); and a book could be created named `widget-sources`,
colliding with the reserved generated-widget-source directory and vanishing
from listings once any Home widget existed (now a reserved root name, and
excluded from the Admin group's book-permission mirroring).

Tests: Ruff and full pytest pass (only the two pre-existing, unrelated
failures remain: `test_existing_content_repo_receives_missing_ci_once_and_preserves_custom_workflow`,
`test_settings_nav_has_a_dedicated_home_page_entry_pointing_to_home`).
- Files: `app/default_groups.py`, `app/home_widgets.py`, `app/paths.py`,
  `app/templates/_content_widgets.html`, `app/templates/book.html`,
  `app/templates/page.html`, `app/templates/tree.html`, `app/web.py`,
  `plans/plan_widget_regression_fixes.md`, `tests/test_paths.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-11 04:54 UTC — Codex
Added immediate red duplicate-ID feedback beneath the Book/Page Widget ID
input. IDs are also validated server-side, including names that would create
the same generated Markdown filename.

Tests: Ruff and focused duplicate-ID test pass.
- Files: `app/content.py`, `app/static/widget_editor.js`,
  `app/templates/_widget_editor.html`, `tests/test_home_widgets.py`, `LOG.md`

## 2026-09-11 04:52 UTC — Codex
Made Book and Page widget IDs user-entered, visible, and unique per host so
multiple widgets of the same kind are distinguishable. The ID continues to
determine the generated Markdown source filename.

Tests: Ruff and focused Book-editor test pass.
- Files: `app/static/widget_editor.js`, `app/templates/_widget_editor.html`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-11 04:46 UTC — Codex
Kept the compact filter button at a fixed 42px width when its search field is
opened, preventing flexbox resizing during the interaction.

Tests: Ruff and whitespace checks pass.
- Files: `app/static/style.css`, `LOG.md`

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


