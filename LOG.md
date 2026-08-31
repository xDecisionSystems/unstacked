# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-30 21:37 UTC — Claude Code
Added `GET /version`, at the user's request, so a deployed container's
actual commit can be confirmed directly (`curl https://.../version`)
instead of guessing whether a redeploy picked up a given push -- came up
while chasing the Toast UI toolbar bug, since the user's live site
auto-deploys on push and there was no way to confirm what commit it was
actually running.

`.dockerignore` excludes `.git` from the runtime image entirely, so the
commit is resolved once at Docker *build* time instead: a new step at the
very end of the builder stage (after the cacheable dependency-install
layers, since this one changes on every single commit) copies in `.git`,
runs `git rev-parse HEAD > /app/GIT_COMMIT`, then deletes `.git` again --
only the one resolved SHA string crosses into the runtime image, never the
repository history. `app/main.py` reads that file once at startup
(`app.state.commit`); outside Docker (local dev, where the baked file never
exists) it falls back to asking the actual checkout via `git rev-parse
HEAD` directly, and reports `"unknown"` if neither source is available.

Verified with a real `docker compose up --build`: correctly reported
`93894b1` (the last real commit; uncommitted working-tree changes don't
move `.git`'s HEAD, as expected). New `tests/test_main.py` covers the
endpoint plus all three `_resolve_commit()` branches (baked file present,
blank baked file falling back rather than reporting empty, and the
git-unavailable "unknown" case). Full suite green, ruff clean.
- Files: `app/main.py`, `Dockerfile`, `.dockerignore`, `tests/test_main.py`,
  `LOG.md`

## 2026-08-30 21:18 UTC — Claude Code
Fixed the Toast UI markdown editor's "H" toolbar button getting stuck
"active" regardless of actual cursor position (reported by the user with a
screenshot on the new Edit Home page, confirmed by Safari console errors to
also affect the regular page editor). Not a CSS or app-code bug -- two real
problems with the CDN plugin scripts loaded in `page.html`/`editor.html`/
`home_editor.html`:

- The chart plugin depends on a separate library, `toastui-chart`, that was
  never loaded. Without it, the plugin throws (`t().barChart` on undefined)
  *inside* Toast UI Editor's own constructor call, on every page load before
  any user interaction -- which aborts the rest of the editor's internal
  setup partway through, including the toolbar's cursor-position tracking.
  Whatever button was "active" at the moment of the crash just never gets
  updated again.
- The color-syntax plugin's script URL 404s outright: unlike the other
  plugins, it ships no `-all` bundle variant, and the URL used that suffix
  anyway.

Added the missing `toastui-chart` JS+CSS (loaded before the chart plugin)
and corrected the color-syntax filename, in all three templates that load
this script set. Added regression assertions to `tests/test_web.py`: the
chart library now loads before the plugin that needs it, and the corrected
color-syntax filename is present while the broken one is not. Full suite
green, ruff clean.
- Files: `app/templates/page.html`, `app/templates/editor.html`,
  `app/templates/home_editor.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 20:25 UTC — Claude Code
Implemented the remaining phases (3, 4, 5) of `plan_editable_widget_home.md`
on top of the backend foundation from the prior entry, using two parallel
subagents in isolated git worktrees (to avoid a shared-tree collision),
then merged, verified, and pushed both.

**Phase 3 (Home rendering + editing UI):** `GET`/`POST /home/edit` --
mirrors the existing page-editor route shape, gated on
`AuthorizationContext.require_write("index.md")` (a real write grant, not
`is_admin`), reuses the same markdown editor as page editing. `GET /tree`
now renders `index.md`'s real body through `MarkdownRenderer` plus its
widgets in one fixed slot below. New `home_editor.html` widget tray: an
ordered list with move-up/move-down buttons as the primary,
keyboard-accessible reorder mechanism (plus an optional pointer-drag
layer) -- deliberately not `reorder.js`'s `localStorage` mechanism, since
this order is real, git-committed content; the tray's order is serialized
into the save request and checked against the page's blob SHA even on a
reorder-only save.

**Phase 4+5 (Settings separation + featured-star verification):** Trimmed
`Branding` to name + logo only, deleting `home_eyebrow`/`home_title`/
`home_description`/`featured_label` end to end (dataclass, load/save,
admin API models, admin.html form) now that `index.md` itself is the live
source of that copy. Added a Settings "Home page" section: a pointer to
Home's own Edit button, plus a "reset to starter content" admin action
that goes through `update_home_page`'s ordinary blob-SHA commit path
(`ContentRepository.reset_home_page_to_starter`), not a raw overwrite.
Verified (read-only) that the existing `/home/feature`/`/home/remove`
star toggles still work unchanged against the new model.

**Integration:** both worktree branches merged into `main` cleanly --
only `tests/test_web.py` was touched by both, and git's own merge
resolved it with no manual conflict. Full suite (100% pass, all dots) and
ruff clean on the merged tree. Verified through a real Docker Compose
deployment per `AGENTS.md`: container healthy, `/healthz` 200, and --
more telling than an HTTP smoke test -- directly inspected the actual
`index.md` written into the real content volume by genuine container
bootstrap, confirming the widget front matter is correct outside of test
fixtures. Could not exercise the new routes over HTTP in that container
since its persisted `data` volume already holds an admin account from an
earlier verification run with a since-changed password (expected --
`AGENTS.md` forbids wiping these volumes between runs).

Deferred, per the implementing agents' own judgment, not required by the
plan: inline widget-placeholder tokens (v1 uses one fixed slot, as the
plan already specifies) and additional widget types beyond `featured`.

Merge commits `f26c10e` and `75af1c5` on `main`; worktrees and their
branches removed after merging.
- Files: `app/web.py`, `app/templates/tree.html`,
  `app/templates/home_editor.html`, `app/static/style.css`,
  `app/branding.py`, `app/admin_api.py`, `app/content.py`,
  `app/templates/admin.html`, `tests/test_web.py`,
  `tests/test_admin_api.py`, `LOG.md`

