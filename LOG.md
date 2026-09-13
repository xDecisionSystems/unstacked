# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-09-11 15:40 UTC — Claude Code
Fixed the two tests that had been failing on `main` independent of
`plans/plan_widget_regression_fixes.md` (both genuinely missed follow-ups
from other, unrelated commits, not caused by that plan's work):

- `test_content_bootstrap.py`'s CI-workflow test asserted the seeded
  commit's message with exact equality, but `a38b934` ("Clarify Git sync
  and annotate content commits") added Changed-paths/User/Timestamp
  trailers to every content commit and updated `test_content_lifecycle.py`
  for it while missing this one. Switched to the same
  startswith()/substring pattern that test already uses.
- `test_web.py`'s Settings-nav test asserted a "home" panel existed in
  Settings, but `76d3e7e` ("Move home reset into home editor") removed
  that panel entirely -- confirmed via `git show` that its one piece of
  real functionality (the reset-to-starter action) was fully and
  correctly relocated into `home_editor.html` in the same commit, not
  dropped. Replaced the stale assertion with two tests: one confirming
  Settings no longer has a home panel (plus the still-valid check that
  Home's much-older retired copy-editing fields never reappear), and a
  new one confirming the reset control now exists in the Home editor
  instead -- filling a real coverage gap that commit also left behind.

Tests: Ruff and full pytest pass -- zero failures, not just the same two
pre-existing ones as prior entries in this log.
- Files: `tests/test_content_bootstrap.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 15:27 UTC — Claude Code
Phase 5 (efficiency) of `plans/plan_widget_regression_fixes.md`, the last
phase of that plan: cached `_load_markdown_settings`'s result in
`app/render.py`, keyed by the `mkdocs.yml` path and mtime. MkDocs' config
loader does full schema validation (plus its own separate plugin-name
parse pass first), and a page with several source-backed widgets was
redoing that once per card/widget on every render. Verified a changed
config still invalidates the cache correctly (no app restart needed to
pick up an edited `mkdocs.yml`). Left two other items alone deliberately:
the `book_view` redundancy (item 15) was already bundled into Phase 3;
threading pre-validated widget state through `ContentRepository`'s public
write methods to avoid a third, cheap, in-memory re-validation (item 17)
would mean real API changes to security/data-integrity-sensitive write
paths for a gain in the microseconds -- not worth the risk.

This closes out plan_widget_regression_fixes.md: all 5 phases done.

Tests: Ruff and full pytest pass (same two pre-existing, unrelated
failures as before).
- Files: `app/render.py`, `plans/plan_widget_regression_fixes.md`,
  `tests/test_render.py`, `LOG.md`

## 2026-09-11 15:16 UTC — Claude Code
Phase 4 (cleanup, no behavior change) of `plans/plan_widget_regression_fixes.md`:
deleted six functions left fully dead in `app/web.py` since the anonymous-
access removal (`_public_page`, `_public_context`, `_home_public`,
`_unauthenticated_destination`, `_public_home_widgets`, `_public_home_context`,
plus `_container_description`, made dead by this pass' own `book_view`
consolidation) and fixed a docstring in `app/admin_api.py` that still
described the removed anonymous-redirect-to-Home behavior as current;
unified the three independent "is this a generated widget-source path"
checks (`app/content.py` x2, `app/search.py`) into one
`is_widget_source_path()`, and the book-directory-name reservation check
into the same `RESERVED_ROOT_NAMES` Phase 1 already established rather than
a separately-hardcoded set; drove `home_editor.html`'s widget-type
classification lists from one server-supplied `source_widget_types` value
(`app.content.SOURCE_WIDGET_TYPES`, renamed public) instead of six
hand-copied JS/Jinja literals; removed a byte-identical duplicate CSS rule
block in `style.css`. While verifying the widget-type-list change in a
real browser, found and fixed a real, pre-existing bug in the same code
(confirmed via `git log -p` to predate this plan): the "Add widget" form's
Title-field visibility never accounted for the `horizontal-rule` type.
Left one item (aligning client/server widget-id uniqueness checks) as
comments rather than a behavior change -- traced fully and found the
current two-layer validation already correct end-to-end; tightening the
weaker check to match the stricter one would reject currently-valid ids on
widget types that don't need to slugify cleanly.

Tests: Ruff and full pytest pass (same two pre-existing, unrelated
failures as before); the widget-type-list and horizontal-rule fixes were
also verified by driving `/home/edit` in a real headless browser, since
neither has Python-level test coverage.
- Files: `app/admin_api.py`, `app/content.py`, `app/search.py`,
  `app/static/style.css`, `app/static/widget_editor.js`, `app/web.py`,
  `app/templates/home_editor.html`, `plans/plan_widget_regression_fixes.md`,
  `tests/test_home_widgets.py`, `LOG.md`

## 2026-09-11 13:59 UTC — Claude Code
Fixed a closed-session reuse bug in `book_view` (see
`plans/plan_widget_regression_fixes.md`, Phase 3): its `with Session(...) as
session:` block only wrapped `_base_context`, and two later calls to
`_authorization(session, user)` ran against the already-closed session --
SQLAlchemy silently reopens a connection for the reuse rather than raising,
so it survived every normal request as long as the response still
rendered, and would leak a checked-out connection under sustained traffic.
Widened the `with` block to cover the whole function, and (bundled in
since it's the same lines) reused one `AuthorizationContext` and one
`read_navigation()` result instead of building/parsing each twice --
removing `_container_description`, whose only remaining caller this
consolidation replaced. Verified with a session that asserts if queried
after `close()`; had to switch it to a non-admin reader after finding an
admin's `AuthorizationContext` short-circuits before ever touching the
database, which let the bug hide from the first version of the test too.

Tests: Ruff and full pytest pass (same two pre-existing, unrelated
failures as before).
- Files: `app/web.py`, `plans/plan_widget_regression_fixes.md`,
  `tests/test_web.py`, `LOG.md`

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
