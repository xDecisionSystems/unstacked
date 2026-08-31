# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-30 19:48 UTC — Claude Code
Implemented Phase 1+2 of `plan_editable_widget_home.md`: the backend
foundation for the editable, widget-based home page, deliberately stopping
short of `app/web.py`, templates, and Branding routes so two parallel
agents can build the editing UI and settings separation on top.

- `ContentRepository` gained `read_home_page()`, `home_page_blob_sha()`, and
  `update_home_page(markdown, widgets, actor, *, base_blob_sha, title=None)`,
  mirroring `update_page`'s optimistic blob-SHA/locked-commit workflow but
  fixed to the literal depth-1 `index.md` path rather than any depth-2 page.
- Bootstrap now writes a widget-aware `index.md` starter (front matter with
  `title` and one `featured` widget entry, body copy folded in once from
  `app.branding`'s soon-to-be-retired `DEFAULT_HOME_*` constants as literal
  text, not a live import). A new `_migrate_home_page()` upgrades an
  existing repo's still-untouched bare placeholder to the same starter --
  exact-byte comparison only, mirroring `_remove_legacy_main_books` -- and
  leaves any hand-edited Home page alone.
- `app/acl.py`'s `AccessPolicy.explain()` gained a narrow, read-only bypass:
  `index.md` is readable by every active user regardless of group grants
  (a brand-new user in no group must still see Home), while write stays
  fully grant-gated like a book; scoped to that one literal path only.
- `app/default_groups.py`'s `ensure_default_groups()` now folds `index.md`
  into the same set it mirrors into the Admin group's grants, unconditionally
  (never pruned the way a book's grant is when its directory disappears).
- `app/admin_api.py`'s `_target_kind()` gained one branch classifying
  `index.md` as `"home"`, so an administrator can grant another group
  explicit write access to it from the existing permissions UI.
- New `app/home_widgets.py`: a small explicit widget-type registry (not an
  arbitrary-code executor). `parse_widget_entries`/`render_widgets`/
  `build_home_widgets` never raise on malformed front matter or an unknown
  widget `type` -- that entry renders nothing but produces a `WidgetError`
  instead, and is never dropped (round-trip preservation is `update_home_page`
  not gatekeeping on the registry). The one supported widget, `featured`,
  reads `content.home_items()`, resolves each target's title the same way
  `app/web.py`'s `_container_title`/`_page_view` do (without importing from
  the web layer), and filters to what the given `AuthorizationContext` can
  read, preserving stored order.
- Added `tests/test_home_page.py`, `tests/test_home_widgets.py`, and ACL/
  admin-API cases in `tests/test_acl.py`/`tests/test_admin_api.py` covering
  the round trip, blob-SHA conflicts, bootstrap/migrate/leave-alone, the
  registry's malformed/unknown-type handling, featured-widget ACL filtering,
  and a real `mkdocs build --strict` against the new starter content.
- Ruff and the full test suite (`uv run ruff check .`, `uv run pytest`) are
  clean. `git fetch origin` showed no new commits since this work started.
- Files: `app/acl.py`, `app/admin_api.py`, `app/content.py`,
  `app/default_groups.py`, `app/home_widgets.py`, `tests/test_acl.py`,
  `tests/test_admin_api.py`, `tests/test_home_page.py`,
  `tests/test_home_widgets.py`, `LOG.md`

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
