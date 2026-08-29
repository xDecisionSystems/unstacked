# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-29 22:58 UTC — Codex
Anchored chapter page-creation popovers to their full headers and constrained
their width so they remain visible beside scrollable page-card rows.
- Files: `app/static/style.css`, `LOG.md`

## 2026-08-29 22:42 UTC — Codex
Replaced EasyMDE with TOAST UI Editor in both editing surfaces, loading its
chart, syntax-highlighting, color, merged-table, and UML plugins while keeping
the existing Markdown form submission intact.
- Files: `app/templates/page.html`, `app/templates/editor.html`,
  `app/static/style.css`, `tests/test_web.py`, `LOG.md`

## 2026-08-29 22:30 UTC — Codex
Forced EasyMDE toolbar glyphs and their text fallbacks to a high-contrast
black so they remain visible against the pale Markdown toolbar.
- Files: `app/static/style.css`, `LOG.md`

## 2026-08-29 22:22 UTC — Codex
Kept the Page View’s accessible Back-to-book title metadata while applying its
new Figma-style action treatment.
- Files: `app/templates/page.html`, `LOG.md`

## 2026-08-29 22:07 UTC — Codex
Wrapped the book-tag aggregation for the project linting standard.
- Files: `app/web.py`, `LOG.md`

## 2026-08-29 22:06 UTC — Codex
Implemented the Figma knowledge-workspace visual system across login, books,
chapters, pages, and administration, while retaining the existing Markdown,
Git, and ACL-backed behavior. Book filtering uses tags from readable pages.
- Files: `app/web.py`, `app/templates/base.html`,
  `app/templates/tree.html`, `app/templates/book.html`,
  `app/templates/page.html`, `app/templates/login.html`,
  `app/static/style.css`, `LOG.md`

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
