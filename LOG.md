# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-30 04:37 UTC — Codex
Replaced chapter visibility action buttons with a single accessible eye toggle
that reflects and switches the chapter’s recursive public state.
- Files: `app/templates/book.html`, `app/static/style.css`, `LOG.md`

## 2026-08-30 04:15 UTC — Codex
Moved book privacy controls into the library cards and made pages inherit both
visibility and permissions from their parent chapter or book.
- Files: `app/acl.py`, `app/admin_api.py`, `app/ai_service.py`,
  `app/content.py`, `app/web.py`, `app/templates/book.html`,
  `app/templates/page.html`, `app/templates/tree.html`,
  `app/static/style.css`, `tests/test_acl.py`, `tests/test_admin_api.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-30 03:09 UTC — Codex
Replaced visibility checkboxes with recursive Make Public and Make Private
actions, and re-anchored tag and new-page popovers beneath their controls.
- Files: `app/content.py`, `app/ai_service.py`, `app/web.py`,
  `app/templates/book.html`, `app/static/style.css`, `LOG.md`

## 2026-08-30 03:01 UTC — Codex
Added portable public visibility controls for books, chapters, and pages, and
made anonymously reachable public content render without a web session.
- Files: `app/nav.py`, `app/content.py`, `app/ai_service.py`, `app/web.py`,
  `app/templates/base.html`, `app/templates/book.html`,
  `app/templates/page.html`, `tests/test_web.py`, `LOG.md`

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
