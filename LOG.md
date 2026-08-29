# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-29 07:16 UTC — Codex
Made page editing inline: Edit opens an in-place EasyMDE editor backed by the
existing CSRF/blob-conflict-protected save path. Added an up-arrow back-to-book
control before Edit.
- Files: `app/web.py`, `app/templates/page.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 07:08 UTC — Codex
Removed the page-view Move/Rename control and made the displayed page title a
clear link to the existing ACL-checked editor, where users can change it.
- Files: `app/templates/page.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 06:59 UTC — Codex
Replaced the subtle hollow collapse glyphs with large solid down/right
triangles, keeping the control's expanded/collapsed semantics unchanged.
- Files: `app/templates/book.html`, `app/static/style.css`, `LOG.md`

## 2026-08-29 06:58 UTC — Codex
Made collapse hide the whole chapter page scroller (including arrows), hid
native horizontal scrollbars, and raised open add-page forms above scroller
controls.
- Files: `app/templates/book.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 06:48 UTC — Codex
Added accessible left/right controls to each horizontal chapter page row and
reserved vertical space so a hovered card's lift and shadow are not clipped.
- Files: `app/templates/book.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 06:40 UTC — Codex
Fixed chapter collapse behavior: explicit hidden styling now overrides the
page-card grid, the diamond chapter-drag handle is gone, and the triangle has
a larger 2.2rem hit target.
- Files: `app/templates/book.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 06:32 UTC — Codex
Placed each chapter's collapse control immediately before its title and sized
the down/right triangle to match the compact add-page icon.
- Files: `app/templates/book.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 06:15 UTC — Claude Code
Three requests: drag-reorder for chapters/pages, a collapse toggle per row,
and dropping the slug field from creation popovers. Confirmed reorder scope
with the user first (shared/persisted-to-content vs personal/browser-local)
since it changes the implementation entirely -- they chose personal, the
same choice already made for the dashboard's book cards, so no backend work
was needed here at all.

Extracted the book-card drag logic (previously inline in `tree.html`) into
`app/static/reorder.js`, a small generic `initDragReorder(container, opts)`
now shared by three call sites: book cards (dashboard), chapter rows and
each chapter's page-card row (book page). Added a `handleSelector` option
for chapter rows specifically -- a row contains other interactive elements
(the per-chapter "+" popover, page-card links), so dragging is restricted
to a small grip icon by cancelling `dragstart` (via `preventDefault`)
unless it originated inside the handle, rather than making the whole row a
drag source. Page cards reuse the book-card trick of a plain
`draggable="true"` item with an inner `draggable="false"` link, since a
native `<a>` is draggable by default and would otherwise hijack the drag.
Order keys are the chapter slug or full page path; storage keys are scoped
per-book (`unstacked.chapter_order.<book>`) and per-parent
(`unstacked.page_order.<book>[/<chapter>]`) so different books/chapters
don't collide. `base.html` gained a `{% block scripts %}` so only the pages
that need `reorder.js` load it.

Added a collapse toggle (▾/▸) to every row header -- the loose "Pages" row
and each chapter row -- that hides/shows its page-card list via the
`hidden` attribute; ephemeral, not persisted (not asked for, and
`book.html` already has enough localStorage keys per page).

Removed `<label>Slug (optional)<input name="slug">` from all three
creation popovers (new book, new chapter, new page) -- title alone was
already sufficient, since every create route already treats a missing
`slug` field as `None` and derives one from the title via `make_slug`. No
backend change needed.

7 new/updated tests in `tests/test_web.py` (drag-reorder markup present
with correct keys/parents, every row's collapse toggle points at an
existing target, no `name="slug"` field anywhere). Full suite green, ruff
clean.
- Files: `app/static/reorder.js` (new), `app/templates/base.html`,
  `app/templates/tree.html`, `app/templates/book.html`,
  `app/static/style.css`, `tests/test_web.py`, `LOG.md`

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
