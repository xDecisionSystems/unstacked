# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-29 05:59 UTC — Claude Code
User asked to remove the "Manage content" topbar link and make every "+"
button follow actual write permission rather than admin status. Confirmed
with the user first that this meant loosening chapter creation's backend
authorization too (not just hiding/showing a button), since
`AIContentService.create_chapter` was `require_admin()`-gated, unlike page
creation which was already write-gated -- the codebase's own stated reason
("container changes are administrator-only because they can affect
path-based permissions") was a deliberate choice, not an oversight, so this
needed confirming rather than assuming.

Changed `create_chapter` to `require_write(book_slug)`, mirroring
`create_page`'s existing shape exactly. Its API route
(`POST /api/ai/books/{book}/chapters`) previously returned a bespoke 403
"Administrator access required" on denial; now folds `AccessDenied` into
the same indistinguishable-from-missing 404 `create_page`'s route already
uses, since the denial is now path-specific (a caller with read-only access
to a real book must not be able to use a different status code to confirm
it exists) rather than a global admin fact. Book creation is unchanged and
still admin-only -- there is no existing path to hold a grant on when the
book doesn't exist yet, so "write permission" has nothing to check there.

Discovered and fixed a real bug this surfaced: `ContentRepository.tree()`
built a non-admin's book/chapter list *only* from pages they can already
read, so a book or chapter they'd just been granted write (or even read) on
-- but which has no pages yet -- was invisible to them, everywhere,
permanently. `AccessPolicy.can_view_container()` already existed and was
fully unit-tested for exactly this (three test files), but was never
actually called from application code. Wired it into `tree()`'s directory
walk, which also let the admin-only branch collapse into the same walk
(the predicate already returns `True` unconditionally for an admin).

`_tree_view_model` now computes `can_write` per book too (not just per
chapter), and both the dashboard's per-chapter "+" and the book page's
"add chapter" + "add page" buttons key off it instead of `is_admin`.

9 new/updated tests across `test_web.py` (topbar link gone; a non-admin
editor with a write grant can both see and actually use the chapter button)
and `test_authorization_coverage.py` (403 -> 404 for the now-write-gated
route). Full suite green, ruff clean (one pre-existing, unrelated
formatting deviation in `test_authorization_coverage.py` left alone).
- Files: `app/ai_service.py`, `app/ai_api.py`, `app/content.py`,
  `app/web.py`, `app/templates/base.html`, `app/templates/book.html`,
  `tests/test_web.py`, `tests/test_authorization_coverage.py`, `LOG.md`

## 2026-08-29 05:44 UTC — Claude Code
Two user requests handled together (the second arrived mid-turn on the
first): a lightweight page-creation popover matching the book/chapter
pattern, and removing the sidebar from every page.

**Sidebar removal.** Dropped `<nav class="sidebar">`/`{% include "_tree.html"
%}` from `base.html`; deleted the now-unused `_tree.html` partial (confirmed
nothing else referenced it) and the `.layout`/`.sidebar*` CSS rules,
replacing them with `.content` centered at the same 900px max-width it
already had, `min-height` moved onto it directly. `_base_context`'s `tree`
context key is untouched -- `/tree` and `/books/{slug}` still need it for
their card grids, only the sidebar rendering of it is gone. One test
(`test_editor_saves_through_the_acl_service_and_marks_drafts`) asserted a
draft badge on `/tree`, which only ever came from the sidebar's per-page
listing; repointed it at `/books/{slug}`, where drafts are still visible.

**Quick page creation.** The chapter-row "+" was a plain link straight into
the full markdown editor (`/pages/new`) -- inconsistent with book/chapter
creation's small title+slug popover, and skipped past "see the new card,
then click into it." Added `POST /manage/page`, a new route deliberately
separate from `/pages/new` (which stays exactly as-is for the "write real
content" flow reached via a full editor, still used by book creation and
the rename redirects) -- creates a page with blank markdown and redirects to
`/books/{slug}`, same shape as chapter creation's own popover. Clicking the
resulting card opens the ordinary page view, which already had an Edit
button; nothing there needed to change.

5 new/updated tests. Full suite green, ruff clean.
- Files: `app/web.py`, `app/templates/base.html`, `app/templates/book.html`,
  `app/static/style.css`, `tests/test_web.py`, `LOG.md`
- Deleted: `app/templates/_tree.html`

## 2026-08-29 05:32 UTC — Claude Code
Two follow-ups to the book overview page. Chapter creation
(`create_chapter_submit` in `app/web.py`) now redirects to `/books/{slug}`
on success instead of straight into `/pages/new` -- book creation still
redirects into the editor since starting the first page is the point there,
but a new chapter has nothing to write yet, so landing back on the book page
(where the new chapter's row, with its own "+", is now visible) is more
useful.

Added a "+" inside each chapter row to add a page to it
(`/pages/new?parent=<book>/<chapter>`), gated on `chapter.can_write` rather
than `is_admin` -- unlike book/chapter creation, `AIContentService.create_page`
only requires a write grant, not admin, so an admin-only gate would have
hidden the button from a legitimate non-admin editor. Computed via
`authorization.policy.decide(path).can_write`, the same non-throwing
pattern `can_restore` already uses for the history view -- extended
`_tree_view_model` to take `authorization` and added `slug`/`can_write` to
each chapter's view-model dict.

3 new tests (`tests/test_web.py`): the redirect target, and the write-gated
button visibility across an admin, a read-only user, and a user with an
actual write grant on just that one chapter (not the whole book) -- the
case an `is_admin` gate would have gotten wrong. `_grant` test helper gained
a `can_write` kwarg. Full suite green, ruff clean.
- Files: `app/web.py`, `app/templates/book.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 05:23 UTC — Claude Code
User asked for a book overview page: clicking a book card now opens
`/books/{slug}` instead of jumping straight to its first page, showing one
horizontally-scrollable row of page cards per chapter (plus a "Pages" row
for pages directly in the book), and an admin-only "+" that creates a
chapter instead of a book.

New `book_view` route in `app/web.py` reuses the same ACL-filtered `tree`
context every page already builds -- looks up the requested slug in it
rather than a second query, so a nonexistent book and one this user can't
read collapse to the same 404, matching every other route in this module.
New `book.html` template; `+` posts to the existing `/manage/chapter` route
unchanged, just like the dashboard's book "+" already reuses
`/manage/book`. Removed `_tree_view_model`'s now-unused `first_page` field
and `_first_book_page` helper -- the dashboard card no longer needs a
first-page target now that it links to the book page instead.

Page cards reuse the same shadow/radius/hover language as the dashboard's
book cards but as a `flex` row with `overflow-x: auto` rather than a
wrapping subgrid, since a chapter row has no cross-card alignment need --
just scroll.

Updated the two dashboard tests that asserted the old first-page-link
behavior, added 7 new tests for the book page (chapter rows, loose pages,
draft badges, empty chapter/book states, 404 on unknown/inaccessible book,
admin-only "+"). Full suite green, ruff clean.
- Files: `app/web.py`, `app/templates/tree.html`, `app/templates/book.html`,
  `app/static/style.css`, `tests/test_web.py`, `LOG.md`

## 2026-08-29 05:16 UTC — Claude Code
User shared a screenshot of a CSS-subgrid card demo and asked for similar
style/spacing/drop-shadow on the book dashboard cards added earlier this
session. Restyled `.book-card` in `app/static/style.css`: resting drop
shadow (not just on hover), larger radius/padding/gap, and -- the actual
technique in the screenshot -- `grid-template-rows: subgrid` so every card's
footer row aligns to the same baseline across a row of cards even when one
title wraps to more lines than its neighbors (parent `.book-cards` defines
the two row tracks; degrades harmlessly to independent per-card auto-height
in browsers without subgrid support).

Restructured the card markup to make that subgrid usable without nesting it
two levels deep: the clickable link is now a separate absolutely-positioned
overlay (`.book-card-link`, full-card click target via `aria-label`) rather
than wrapping the title/footer, so title and footer stay direct grid
children of the card and slot straight into its two subgrid row tracks.
Footer split into two stats (page count, chapter count), the first
accent-colored to echo the reference image's colored/muted footer pair.
Existing `tests/test_web.py` assertions (href/data-slug substrings) needed
no changes since those attributes' values didn't move. Full suite green.
- Files: `app/templates/tree.html`, `app/static/style.css`, `LOG.md`

## 2026-08-29 05:07 UTC — Claude Code
User asked for a book dashboard: cards on the post-login main page (`/tree`),
default alphabetical order, drag-to-reorder, and a "+" to add a book.
Clarified two design forks before building: reorder is per-user/browser-local
(not a shared wiki-wide order — user chose this over persisting to
`docs/.pages` and touching every user's view), and a card click opens the
book's first page.

Extended `_tree_view_model` (already the sole source for the sidebar) with
`slug`, `first_page` (own first page, else first chapter's first page, else
`None`), and `page_count`, reusing the same `tree` context already built for
every page rather than adding a second query. Rewrote `tree.html`: a card
grid from that same data, native HTML5 drag-and-drop (vanilla JS, no
library) persisting the dragged order to `localStorage` and reapplying it on
load -- books outside the saved order (new ones) sort after it. `<a
draggable="false">` inside a `draggable="true"` `<li>`, since links are
natively draggable and would otherwise hijack the drag before it reaches the
card. A book with no pages yet links to `/pages/new?parent=<slug>` instead
of a dead card. The "+" is a `<details>`-based popover (CSS/HTML only, no JS
state) posting to the existing `/manage/book` route unchanged -- admin-gated
in the template the same way the topbar's Manage/Admin links already are,
matching that route's own admin-only enforcement.

4 new tests in `tests/test_web.py` (card slugs/hrefs, empty-book fallback
link, admin-only "+", empty-tree state). Full suite green, ruff clean.
- Files: `app/web.py`, `app/templates/tree.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 03:41 UTC — Claude Code
User couldn't log in as `admin`/`admin` on a deployed instance ("Invalid
username or password"). Root cause wasn't a code bug: no `admin` row existed
because `python -m app.bootstrap` had never been run there (this local
checkout was in the same state — `data/app.db` didn't exist). Confirmed the
fix by running `unstacked-bootstrap` here and logging in successfully.

While tracing it, found `README.md`'s Quick Start and Coolify sections
documented a bootstrap CLI that doesn't exist — `--email`/`--display-name`
flags, a password prompt, `--password-stdin`, a printed API token. The real
`app/bootstrap.py` (unchanged, correct) takes no arguments and always creates
`admin`/`admin`, matching `plans/plan_initial.md`'s T1.4 spec; only the
README had drifted. Corrected both sections to describe the actual, argument-
free command.
- Files: `README.md`, `LOG.md`

## 2026-08-29 03:31 UTC — Claude Code
User asked for admin-configurable theming: four standard palette options plus
a custom one. Added `app/theme.py` (five-role `Palette`, four presets --
Future Green, Ocean Blue, Sunset Coral, Slate Mono -- plus `darken`/`tint`
helpers that derive `--accent-dark` and `--bg-alt` from `accent` so a custom
palette never needs to supply a hover shade by hand) and
`app/theme_config.py`, a runtime-editable JSON record under `data/`
mirroring `app/backup_config.py`'s precedent: a color palette is cosmetic
configuration, not wiki data, so it doesn't belong in a fifth DB table, and a
malformed record degrades to the default preset rather than breaking every
page render.

Wired the effective palette into every template -- including `login.html`
and `change_password.html`, which predate `_base_context` and never call
it -- via one Jinja global (`theme_style(request)` in `app/web.py`) that
injects a small inline `<style>{{ :root override }}</style>` block reading
the JSON file fresh per request; no cache to invalidate, so a saved change
is visible on the next page load with no restart. `style.css`'s own `:root`
now documents that it's just the Future Green defaults, overridden per
request.

Added `GET`/`PUT /api/admin/theme` (admin-only, CSRF-guarded for the cookie
transport, same as every other admin route) and an Appearance section in
the admin console: radio options with live color swatches for the four
presets plus "Custom", five `<input type=color>` fields, `location.reload()`
after a successful save so the new palette applies immediately everywhere,
not just in the panel that changed it.

52 new tests (`tests/test_theme.py`, `tests/test_theme_api.py`): hex
validation, every preset's internal consistency, `darken`/`tint` bounds
math, JSON load/save round-trips, six variants of "a corrupt or unknown-shape
record falls back to the default rather than raising," admin-only + CSRF
route contracts, the preset/palette mutual-exclusion check, and two
render-level assertions (`--accent:` appears correctly on both an
authenticated page and the pre-login screen). Full suite green, ruff clean.
- Files: `app/theme.py`, `app/theme_config.py`, `app/config.py`, `app/web.py`,
  `app/admin_api.py`, `app/static/style.css`, `app/templates/base.html`,
  `app/templates/login.html`, `app/templates/change_password.html`,
  `app/templates/admin.html`, `tests/conftest.py`, `tests/test_theme.py`,
  `tests/test_theme_api.py`, `LOG.md`

## 2026-08-29 03:14 UTC — Claude Code
Applied the user-supplied brand palette (Future Green #00CA8C, Bright
Pastel Orange #FFB54C, Cyber Lime #8CD47E, Digital Gray #808080, Cosmic
Blue #002E5D) to `app/static/style.css`, the web UI's one hand-written
stylesheet. Remapped the existing CSS custom properties rather than
introducing new hardcoded colors throughout: `--accent` → Future Green,
`--muted`/`--text` → Digital Gray/Cosmic Blue, `--bg-alt` → a light
Future Green tint, plus a new `--accent-secondary` (Cyber Lime) and
`--warm` (Pastel Orange) for search-highlight/draft-badge/diff-table
accents. Deliberately kept `--danger` a plain red rather than
repurposing a brand color for destructive actions — none of the five
reads as "danger", and legibility for delete/revoke controls matters
more than palette purism there. Added a button hover state (darker
green) since none existed before. Recolored the draft badge, search
snippet highlight, and diff add/sub/chg backgrounds to match. Verified
the stylesheet still serves correctly and the full web UI test suite
(21 tests) still passes — styling doesn't affect any Python-level
assertion, but confirmed nothing broke regardless.
- Files: `app/static/style.css`, `LOG.md`

## 2026-08-29 03:08 UTC — Claude Code
Completed T9.3 (the plan's last open task) — every task is now `[x]` or
`[not planned]`. Discovered a real gap while investigating "OpenAPI
validation against a real action client" from scratch: fetched the whole
app's actual `/openapi.json` and found 40 operations across 32 paths —
the AI surface mixed in with the admin console, backup, and browser-
cookie routes. That's both over ChatGPT Actions' 30-operation import
limit and the wrong thing to expose as AI "tools" regardless of the
limit; nothing before this pointed it out because nobody had actually
fetched and inspected the schema rather than just building routes.

Added `GET /api/ai/openapi.json` (`build_ai_openapi_schema` in
app/ai_api.py), built directly from the router's own route objects
filtered to `/api/ai/*` so it can't drift from what those routes actually
accept — 13 paths, 14 operations. Deliberately excludes
`/api/auth/token`/`tokens/revoke`: an Action gets one bearer token
configured out of band, not by calling a credential-issuing endpoint as
one of its own operations. Added `Settings.public_base_url` (validated
absolute http(s) URL) so the schema can declare the `servers` entry an
Action needs — omitted, not guessed, when unset.

Validated with the real `openapi-spec-validator` library against the
actual OpenAPI 3.1 spec, not a shape this app's own tests invented, plus
Action-specific checks a generic validator wouldn't catch (operationId
uniqueness, the 30-op ceiling, universal bearer security). Mutation-
tested the security check specifically: stripped one operation's
`security` array and confirmed my assertion catches it while the generic
validator still accepts the now-unauthenticated shape as structurally
valid OpenAPI — proving the extra check earns its place. Full suite 602
passing (was 583 at the start of this session's work on T2.1/T9.3), ruff
clean.
- Files: `app/ai_api.py`, `app/config.py`, `.env.example`, `pyproject.toml`,
  `uv.lock`, `tests/test_ai_openapi.py`, `tests/test_config.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-29 02:55 UTC — Claude Code
User asked to complete the remaining two tasks; did T2.1 directly rather
than dispatching a subagent (narrow finishing work on a codebase I already
had full context on). Closed the last gap — recursive container
delete/rename still used `shutil.rmtree`/`os.replace`/`safe_join` while
every other content operation had already migrated to `ConfinedTree`.

Added `ConfinedTree.walk_files` (recursive, descriptor-confined) and
rewrote `_delete_container`/`_rename_container` to use it exclusively —
confirmed by grep that zero raw Path-mutation calls remain in either.
Rename's rollback doesn't need delete's byte-snapshot approach (a
directory rename is one atomic op); it unwinds via a small ordered stack
of closures instead. Removed the now-dead Path-based `_changed_nav` and
`_container_path` rather than leaving unused code behind.

Hit one real bug of my own making mid-implementation: naming a new method
`walk_files -> list[str]` after the class already defines a method
literally called `list` shadows the builtin for every annotation
evaluated later in the same class body — `TypeError: 'function' object is
not subscriptable` at import time. Fixed by reordering, not renaming, so
future methods aren't left as a trap.

Verified rather than assumed: added two adversarial tests swapping the
parent book for a symlink between the confined walk and the delete/rename
that follows it. A mutation test (temporarily reverting to raw
`shutil.rmtree`) still passed them — an earlier confined step (the
nav-parent check) independently catches the same race first — so also
added a call-spy proving `ConfinedTree.delete_tree`/`.rename()` are
genuinely invoked, not merely that the pipeline is safe via a different
layer. Full suite 585 passing (was 583), ruff clean. T2.1 marked `[x]`.
Starting T9.3 next.
- Files: `app/content.py`, `app/paths.py`,
  `tests/test_content_symlink_races.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:36 UTC — Claude Code
User asked to remove the MCP server (T9.2) — too token-costly per call
versus a plain API for the same operations, REST-only going forward.
Found Codex had already made this exact change (`b0bf3dc`, "Keep AI
integration REST-only") before I got to it — T9.2 marked `[not planned]`
with reasoning recorded, checkpoint already says REST is the sole AI
transport. Nothing left to do there.

Fixed one thing Codex's change missed: `AGENTS.md` still described "Claude
MCP" as a live AI transport and listed `ai_mcp` in the module layout
diagram, contradicting the plan. Corrected both, and tidied two more
stale MCP mentions in the plan itself (the top-of-file scope bullet and
the settled-decisions table row) that still framed it as planned/dual-
transport rather than explicitly dropped.
- Files: `AGENTS.md`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:33 UTC — Codex
Extended T2.1 confinement through page delete and move transactions, including
navigation edits and rollback. Ancestor-symlink adversarial tests confirm that
the operations do not delete or publish an outside sentinel.
- Files: `app/content.py`, `tests/test_content_symlink_races.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:31 UTC — Codex
Removed MCP from the MVP at the user's request. The existing signed-bearer
REST/OpenAPI surface is now the sole AI transport, avoiding a second protocol
and its client-context overhead.
- Files: `README.md`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:10 UTC — Codex
Added a bounded, lock-protected per-user throttle for authenticated AI content
requests and exhaustive finite-domain ACL regression coverage. Token rotation
shares a user budget while users behind one proxy remain isolated.
- Files: `app/ai_api.py`, `app/config.py`, `tests/test_ai_api.py`,
  `tests/test_acl_properties.py`, `plans/plan_initial.md`, `LOG.md`
