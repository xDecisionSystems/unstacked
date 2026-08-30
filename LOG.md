# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-30 02:52 UTC — Codex
Allowed public GitHub content repositories only when no group has restricted
read access; public links now block creation of no-read groups and denied
permission grants.
- Files: `app/admin_api.py`, `app/git_backend.py`, `app/templates/admin.html`,
  `tests/test_backup_config.py`, `tests/test_git_backend.py`, `LOG.md`

## 2026-08-30 01:16 UTC — Codex
Reframed the Settings backup control as a dedicated GitHub repository link,
with private-repository safeguards and clear automatic synchronization to the
content repository's `main` branch.
- Files: `app/templates/admin.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 01:14 UTC — Codex
Made administrator-created user passwords permanent by default, while keeping
the bootstrap account's first-login password-change safeguard unchanged.
- Files: `app/admin_api.py`, `app/templates/admin.html`,
  `tests/test_admin_api.py`, `LOG.md`

## 2026-08-30 01:13 UTC — Codex
Renamed the administration surface to Settings, replaced the top-bar Admin
label with an accessible gear link, and separated Users from the combined
Groups & permissions panel.
- Files: `app/web.py`, `app/templates/base.html`, `app/templates/admin.html`,
  `app/static/style.css`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 00:59 UTC — Codex
Changed the Administration sidebar into section navigation: each link now
shows only its related settings panel, updates the heading, and preserves a
direct URL fragment for the selected panel.
- Files: `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-30 00:35 UTC — Codex
Added portable front-matter tags to book and chapter containers, with
admin-only editing in their respective headers; tags remain valid MkDocs
metadata rather than database content.
- Files: `app/nav.py`, `app/content.py`, `app/ai_service.py`, `app/web.py`,
  `app/templates/book.html`, `app/static/style.css`, `LOG.md`

## 2026-08-29 23:02 UTC — Codex
Rebuilt the administration view around the Figma sidebar, access metrics, and
structured management panels; replaced tiny chapter/page plus controls with
clear labeled actions.
- Files: `app/templates/admin.html`, `app/templates/book.html`,
  `app/static/style.css`, `LOG.md`

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
