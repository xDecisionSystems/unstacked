# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-30 07:33 UTC — Codex
Added reserved main-hidden, main-read, and main-write starter books with
front-page pages and suffix-based Public-group default access, while keeping
their book containers out of the dashboard.
- Files: `app/content.py`, `app/default_groups.py`, `app/web.py`,
  `app/templates/tree.html`, `tests/test_ai_api.py`,
  `tests/test_default_groups.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 06:49 UTC — Codex
Replaced the chapter hierarchy with a book-and-page model: legacy chapters
promote to books at startup, their effective grants are preserved, and the
web/settings UI now uses book-level permissions and a draggable page grid.
- Files: `app/acl.py`, `app/admin_api.py`, `app/ai_api.py`,
  `app/ai_service.py`, `app/bootstrap.py`, `app/content.py`,
  `app/default_groups.py`, `app/main.py`, `app/static/style.css`,
  `app/templates/admin.html`, `app/templates/book.html`,
  `app/templates/manage.html`, `app/templates/move_page.html`,
  `app/templates/tree.html`, `app/web.py`, `tests/test_admin_api.py`,
  `tests/test_ai_api.py`, `tests/test_assets.py`, `tests/test_authorization_coverage.py`,
  `tests/test_book_migration.py`, `tests/test_content_build.py`,
  `tests/test_content_lifecycle.py`, `tests/test_content_structure.py`,
  `tests/test_content_symlink_races.py`, `tests/test_default_groups.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-30 06:28 UTC — Codex
Stopped inaccessible book shells from appearing when every chapter is denied
by a more-specific permission rule.
- Files: `app/content.py`, `tests/test_admin_api.py`, `LOG.md`

## 2026-08-30 06:25 UTC — Codex
Added an explicit Reactivate action for inactive accounts, restoring access
through the guarded user-update flow.
- Files: `app/templates/admin.html`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 06:21 UTC — Codex
Protected the primary Admin account from deletion and styled inactive users'
disabled account actions in gray.
- Files: `app/admin_api.py`, `app/templates/admin.html`,
  `app/static/style.css`, `tests/test_admin_api.py`, `tests/test_web.py`,
  `LOG.md`

## 2026-08-30 06:17 UTC — Codex
Added chapter-level default permission icons and made new custom groups inherit
the Public template’s per-chapter read/write defaults.
- Files: `app/default_groups.py`, `app/admin_api.py`,
  `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_default_groups.py`, `tests/test_web.py`, `LOG.md`

## 2026-08-30 06:11 UTC — Codex
Added built-in Public and Admin groups: Public begins with no chapter grants,
while Admin receives read/write grants for every current and new chapter.
- Files: `app/default_groups.py`, `app/main.py`, `app/bootstrap.py`,
  `app/content.py`, `app/admin_api.py`, `tests/test_default_groups.py`,
  `LOG.md`

## 2026-08-30 06:04 UTC — Codex
Made inactive chapter-permission buttons white and outlined, with an orange
filled selected state and white icon for clear status contrast.
- Files: `app/static/style.css`, `LOG.md`

## 2026-08-30 06:03 UTC — Codex
Fixed Chapter Permissions icon contrast so every dash, eye, and pencil remains
burgundy and visible against its button background.
- Files: `app/static/style.css`, `LOG.md`

## 2026-08-30 05:59 UTC — Codex
Replaced Chapter Permissions dropdowns with accessible dash, eye, and pencil
icon controls for no access, read, and read/write assignments.
- Files: `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-08-30 05:51 UTC — Codex
Renamed the groups settings section and added a chapter-by-group permissions
matrix with read/write levels and per-group select-all controls.
- Files: `app/admin_api.py`, `app/templates/admin.html`,
  `app/static/style.css`, `tests/test_admin_api.py`, `tests/test_web.py`,
  `LOG.md`

## 2026-08-30 05:34 UTC — Codex
Redesigned Groups as a user-by-group checkbox matrix with direct membership
toggle actions and compact group deletion controls.
- Files: `app/templates/admin.html`, `app/static/style.css`, `LOG.md`

## 2026-08-30 05:21 UTC — Codex
Expanded the new-user password checklist to show length, uppercase, lowercase,
and number requirements with individual live red/green feedback.
- Files: `app/templates/admin.html`, `app/static/style.css`, `LOG.md`

## 2026-08-30 05:15 UTC — Codex
Added live password-requirement feedback to Settings: red until 12 characters
are entered, then green.
- Files: `app/templates/admin.html`, `app/static/style.css`, `LOG.md`

## 2026-08-30 05:13 UTC — Codex
Added the 12-character password requirement directly beneath the new-user
password field in Settings.
- Files: `app/templates/admin.html`, `app/static/style.css`, `LOG.md`
