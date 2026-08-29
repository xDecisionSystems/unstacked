# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-29 19:45 UTC — Codex
Reworked inline editing tags into a right-side one-at-a-time entry panel with
removable current-tag bubbles and ACL-filtered previously-used tag bubbles.
- Files: `app/web.py`, `app/templates/page.html`, `app/static/style.css`,
  `LOG.md`

## 2026-08-29 08:05 UTC — Codex
Added visible text/symbol fallbacks for every EasyMDE toolbar action, so Safari
can show and use Markdown controls even when Font Awesome glyphs fail to load.
- Files: `app/static/style.css`, `LOG.md`

## 2026-08-29 08:02 UTC — Codex
Aligned floating Save/Cancel with the Markdown editor, made viewed draft status
an italic “(Draft)” beside the title, and show its checkbox there only while
editing.
- Files: `app/templates/page.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-29 07:58 UTC — Codex
Moved Save/Cancel to the left of the editor box and replaced the draft notice
with a compact Draft badge immediately beside the title for draft pages.
- Files: `app/templates/page.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

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
