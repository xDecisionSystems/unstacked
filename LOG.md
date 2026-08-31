# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-31 02:05 UTC — Claude Code
Per the user's request, removed the dashboard's redundant "Home" and
"Featured" heading text: dropped `tree.html`'s `<h1>{{ home_title }}</h1>`
and the `<h2>{{ widget.title }}</h2>` widget heading (kept as an
`aria-label` on the section for accessibility, and kept in the browser
tab `<title>`). Along the way, found that "Home" was also literal
Markdown body content -- `_home_page_starter_body()` wrote a `# Home`
line into every bootstrapped/reset Home page -- and removed that line
from the starter too. This only changes newly bootstrapped or explicitly
reset Home pages, not any already-existing `index.md`, including a real
deployed site's, which would need a hand edit or a reset to pick this up.

Per the user's next request: renamed "Book Permissions" to "Permissions" in
Settings (internal `data-admin-panel="book-permissions"`/section id
unchanged, only the visible text and `data-title`), and added a "Publish
the Home page publicly" toggle to that same panel. Backed by a new
`ContentRepository.set_home_public(public, actor)` -- mirrors
`set_page_title`'s minimal single-field write rather than
`set_container_public`/`set_subtree_public`, since `index.md` is a fixed
single file, never a container those two require -- exposed via
`GET`/`PUT /api/admin/home/visibility`. Confirmed the `public` front-matter
field survives an unrelated `update_home_page` save (it is an unknown key
to that method, so it only round-trips correctly because
`serialize_page` starts from `document.raw_metadata`).

Also implemented the user's second, related request: an unauthenticated
visitor hitting a non-public page/book, or `/`, or `/tree` itself, is now
redirected to `/tree` if Home is public (a real, working destination) or
to `/login` otherwise -- previously these were a mix of hard 401s and
404s. `/tree` now accepts an optional user and renders a genuine
read-only public view when anonymous and Home is public, with its
`featured` widget filtered by the existing `_public_page`/
`_container_public` predicates rather than an `AuthorizationContext`
(anonymous visitors have no ACL identity to evaluate). The redirect never
depends on whether the specific requested page/book exists -- only on
Home's global public status -- so it preserves the existing
existence-leak guarantee `page_view`/`book_view` already had via a
uniform 404.

Updated the one existing test this necessarily changed
(`test_web_routes_require_a_session`: bare unauthenticated `/tree` and
`/pages/alice-book/secret` now redirect to `/login` rather than 401/404,
since Home defaults to private) and added new coverage in
`tests/test_admin_api.py` and `tests/test_web.py` for the visibility
toggle, the public-Home render, and the public-featured-widget filtering.
Full suite and ruff clean.
- Files: `app/admin_api.py`, `app/content.py`, `app/templates/admin.html`,
  `app/templates/tree.html`, `app/web.py`, `tests/test_admin_api.py`,
  `tests/test_home_page.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-31 01:20 UTC — Claude Code
Reverted the Milkdown/Crepe editor (Codex's five commits, `06bb974`..`9a18394`)
back to Toast UI, per the user's explicit instruction after directly
comparing both: "Fix it. Or create a simple page that uses Toast and test
if same issue exists. I like toast better." Verified with Playwright
(headless Chromium) against a standalone test page that Toast UI, with the
three CDN plugin dependency fixes already committed earlier, correctly
tracks cursor position (heading button's `active` class toggles right);
Milkdown's own `TopBar` heading label, by contrast, never left "Paragraph"
and `document.activeElement` incorrectly became a `<button>` after clicking
into content -- a genuine bug in Crepe, not this app's code. Restored
`app/templates/page.html`, `editor.html`, `home_editor.html`,
`app/static/style.css`, and `tests/test_web.py` to their pre-Milkdown
(`539689b`) content; deleted `app/static/markdown-editor.js`. Did not carry
forward Codex's `6234fc1` heading-popup-dismissal workaround, since it
treated a symptom of the underlying dependency bugs that no longer exists
once those are fixed.

While re-verifying against the real app (not just the standalone test
page), found a second, previously-undiagnosed bug via Playwright bisection:
clicking anywhere in the editor content moved focus to the toolbar's
Heading button and opened its dropdown, blocking further input -- this is
almost certainly the actual root cause of the original "H stuck" report,
not (only) the missing plugin dependencies. Root cause: all three templates
wrapped the markdown `<textarea>` in `<label>Markdown<textarea>...
</textarea></label>`; Toast UI's mount point is inserted via
`source.before(mount)`, landing it *inside* that same `<label>` alongside
the now-hidden textarea. A browser's native `<label>` forwards clicks
anywhere within it to its associated control, and this silently corrupted
Toast UI's own focus/toolbar-state tracking. Fixed by splitting label and
textarea into siblings, associated only via `for`/`id`
(`app/templates/page.html` uses a `<div class="markdown-field">` wrapper to
preserve its CSS grid placement; `editor.html`/`home_editor.html` use a
plain sibling pair, no CSS depended on the old nesting there). Renamed the
corresponding `style.css` selectors from `.editor-form>label` to
`.editor-form>.markdown-field`.

Verified with a real local Docker Compose deployment (not just a static
test file): rebuilt the image, created a page with real heading+paragraph
content, and drove the actual inline editor, the full "New page" editor,
and the Home editor with Playwright -- in all three, the heading button now
toggles correctly and `document.activeElement` stays on the real
ProseMirror content region, with zero console errors. Full suite and ruff
clean. `git fetch origin` showed no new commits since this work started.
- Files: `app/templates/page.html`, `app/templates/editor.html`,
  `app/templates/home_editor.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md` (deleted `app/static/markdown-editor.js`)

## 2026-08-30 23:42 UTC — Codex
Corrected the remaining Milkdown CDN failures visible in Safari. The prior
paths pointed at package-relative stylesheet wrappers that only work after a
bundler rewrites them; they now load the pinned underlying `@milkdown/prose`
styles directly. Switched the browser editor import from esm.sh to the
pinned jsDelivr ESM bundle, whose source map resolves, and disabled Crepe's
collaboration cursor feature so it does not request unused cursor CSS.
The regular rich-text controls remain enabled; image upload remains disabled
until it can use a server-validated browser upload flow. All pinned runtime
assets return 200, and focused tests and ruff pass. Production Compose
started cleanly on port 18765; `/healthz` returned 200 and served the new
editor bundle before teardown.
- Files: `app/static/markdown-editor.js`, `app/templates/editor.html`,
  `app/templates/home_editor.html`, `app/templates/page.html`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-30 23:34 UTC — Codex
Fixed Milkdown’s CSS delivery after Safari exposed real 404s for styles that
were written for a bundler rather than direct CDN use. Replaced the broken
package-relative CSS imports with the pinned underlying ProseMirror,
gap-cursor, table, virtual-cursor, and KaTeX styles. Restored the default
CodeMirror and LaTeX features and enabled Crepe’s optional Top Bar so the
editor exposes the richer library interface. Image-block upload remains
disabled until it can call the app’s server-validated upload flow.
All replacement styles returned 200; focused tests and ruff pass. Production
Compose also started cleanly on port 18765 and `/healthz` returned 200.
- Files: `app/static/markdown-editor.js`, `app/templates/editor.html`,
  `app/templates/home_editor.html`, `app/templates/page.html`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-30 23:27 UTC — Codex
Replaced the temporary native Markdown toolbar with Milkdown Crepe, a
WYSIWYG Markdown editor. Crepe is loaded from pinned v7.21.1 browser assets
and submits `getMarkdown()` to the unchanged form routes, so content remains
plain Markdown on disk. Included the required Crepe styles and workspace
theme-token overrides. Image-block and LaTex features are intentionally off:
uploads will continue through the app's validated asset path rather than an
editor-side bypass. The native textarea remains as a usable fallback if the
editor bundle cannot load. All pinned CDN assets returned 200; focused editor
tests and ruff pass. Verified with production Compose on port 18765:
`/healthz` returned 200 and the Milkdown script was served.
- Files: `app/static/markdown-editor.js`, `app/static/style.css`,
  `app/templates/editor.html`, `app/templates/home_editor.html`,
  `app/templates/page.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 23:07 UTC — Codex
Replaced Toast UI across page, standalone-page, and home Markdown editing
with a lightweight native textarea editor owned by the application. The new
toolbar uses direct Markdown insertions for headings, text formatting,
quotes, lists, tasks, links, images, and inline code; it has no CDN
dependencies, browser-specific popup behavior, or conversion layer, so the
stored Markdown and existing save routes remain unchanged. Added focused
template assertions and removed the now-unused Toast UI styling.
Focused editor, page-view, and home-editor tests pass; ruff passes. Verified
through production Compose on port 18765: container started and `/healthz`
returned 200; the new static toolbar script was served successfully.
- Files: `app/static/markdown-editor.js`, `app/static/style.css`,
  `app/templates/editor.html`, `app/templates/home_editor.html`,
  `app/templates/page.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 22:59 UTC — Codex
Completed the follow-up review of the Toast UI heading control. The plugin
dependency fixes already committed by Claude eliminate the editor
initialization failure; the rendered inline script was also checked with a
real page response and is valid JavaScript. Added a small inline-editor
interaction guard so the heading chooser dismisses shortly after the pointer
leaves both the toolbar and its menu, using Toast UI's own outside-click
cleanup path rather than forcing its DOM closed. This prevents the menu from
obscuring the editing surface while preserving access to its heading choices.
Focused page-view regression test passes; ruff passes.
- Files: `app/templates/page.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 22:47 UTC — Claude Code
Third round on the Toast UI toolbar bug. With the color-picker fix
confirmed live (`GET /version` showed the deployed commit, and its specific
console error was gone), a fresh console check still showed a `SyntaxError`
with no source-file attribution -- unusual enough to suspect a browser
extension, ruled out by the user reproducing it in a Private Browsing
window.

Went back and checked the one plugin never actually verified for hidden
dependencies: `code-syntax-highlight`. Despite its "-all" filename
(everywhere else in this set, "-all" meant "self-contained bundle"), it
references `window.Prism` directly and does not include Prism.js -- the
same missing-peer-dependency shape as chart and color-syntax, just from a
different, unrelated library (Prism ships from cdnjs, not uicdn.toast.com).
Added Prism.js + its theme CSS before the plugin script in all three
templates.

Also re-checked `table-merged-cell` and `uml` more thoroughly this time
(broader pattern match, not just `window.X`) before calling the set clean:
`table-merged-cell` references nothing external; `uml` does reference a
`plantuml-encoder` dependency and an external plantuml.com rendering
service, but both are inside a lazily-invoked, try/caught code path used
only when someone actually renders a UML diagram -- not at editor
construction time -- so left alone rather than adding a dependency nothing
has exercised yet.

Extended the existing regression test with the same load-order assertion
pattern. Full suite green, ruff clean.
- Files: `app/templates/page.html`, `app/templates/editor.html`,
  `app/templates/home_editor.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 22:23 UTC — Claude Code
Follow-up to the Toast UI toolbar fix: with `GET /version` confirming the
live site really was running the earlier fix, the user still saw the "H"
button stuck -- a fresh console check (after a hard refresh) showed the
color-syntax plugin now loads (no more 404) but throws its own error:
`TypeError: undefined is not an object (evaluating 't.tui.colorPicker')`.

Same root cause as the chart plugin, one plugin over: color-syntax also
depends on a separate library -- TOAST UI Color Picker -- that the "-all"
bundle variant would have included inline, but the plain variant (the only
one that actually exists for this plugin) does not. Added the missing
`tui-color-picker` JS+CSS before the color-syntax plugin script, in all
three templates. Checked the remaining two plugins (table-merged-cell, uml)
for the same pattern first -- neither has an "-all" variant and neither
references any external global, so neither has this problem. Re-verified
every TOAST UI CDN URL now used across all three templates returns 200.

Extended the existing regression test with the same load-order assertion
already used for the chart fix. Full suite green, ruff clean.
- Files: `app/templates/page.html`, `app/templates/editor.html`,
  `app/templates/home_editor.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 21:53 UTC — Claude Code
Corrected the previous `GET /version` commit (its `.git`-copying build step
worked in local `docker compose` testing but broke the user's real Coolify
deployment): Coolify "imports" a plain file snapshot of the commit, no
`.git` directory at all, so `COPY .git ./.git` failed with
`"/.git": not found` at deploy time -- caught immediately from the user's
pasted deployment log.

Replaced it with Coolify's own purpose-built mechanism: a `SOURCE_COMMIT`
build arg, which Coolify supplies automatically (off by default, to avoid
busting layer caching on every commit -- the user needs to enable "Include
Source Commit in Build" under the app's Advanced settings for it to
actually populate). Dockerfile now just declares `ARG SOURCE_COMMIT=unknown`
in the runtime stage and writes it to `/app/GIT_COMMIT`; `.dockerignore`'s
original `.git` exclusion is restored since the build context no longer
needs it at all. `app/main.py`'s `_resolve_commit()` and its tests were
already written against that same file path and needed no changes --
only the file's provenance comment.

Verified directly with `docker build`: passing `--build-arg
SOURCE_COMMIT=<sha>` reports that exact commit; omitting it falls back to
`"unknown"` rather than failing the build. Full suite green, ruff clean.
- Files: `Dockerfile`, `.dockerignore`, `app/main.py`, `LOG.md`

