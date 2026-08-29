# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-29 07:53 UTC — Codex
Moved the Draft toggle into the hidden inline editor, so it appears only while
editing rather than in the normal page title row.
- Files: `app/templates/page.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-29 07:53 UTC — Codex
Restored floating editor actions without a panel, border, or shadow. On wide
screens they sit immediately right of the editor; narrow screens keep them
inline below it.
- Files: `app/static/style.css`, `LOG.md`

## 2026-08-29 07:50 UTC — Codex
Moved the concise Draft toggle next to the page title and returned Save/Cancel
to the inline editor flow without the fixed floating card.
- Files: `app/templates/page.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 07:45 UTC — Codex
Moved inline-editor Save and Cancel into a fixed floating group on the left,
with a bottom horizontal layout on narrow screens.
- Files: `app/templates/page.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 07:41 UTC — Codex
Loaded Font Awesome explicitly for EasyMDE so its toolbar icons render in
Safari, and removed the page-path breadcrumb row from page views.
- Files: `app/templates/page.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-29 07:35 UTC — Codex
Replaced the title popup with direct in-place editing: click the displayed
title, type, then press Enter or blur to save; Escape restores its old value.
- Files: `app/templates/page.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 07:26 UTC — Codex
Made page-title editing genuinely inline: clicking the title opens a local
title field saved through the shared ACL-aware service, rather than following
the legacy full-page editor link.
- Files: `app/ai_service.py`, `app/web.py`, `app/templates/page.html`,
  `app/static/style.css`, `tests/test_web.py`, `LOG.md`

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
