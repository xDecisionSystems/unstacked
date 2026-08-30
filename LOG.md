# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-30 05:11 UTC — Codex
Made Settings form validation errors readable so failed user creation explains
the invalid field instead of displaying `object Object`.
- Files: `app/templates/admin.html`, `LOG.md`

## 2026-08-30 04:56 UTC — Codex
Fixed mixed book visibility so chapter settings take precedence for nested
pages and the glasses state reflects both book and chapter visibility.
- Files: `app/web.py`, `LOG.md`

## 2026-08-30 04:46 UTC — Codex
Replaced book-card eye controls with clear, mixed, and filled glasses states
that reflect private, mixed-descendant, and fully public visibility.
- Files: `app/web.py`, `app/templates/tree.html`, `app/static/style.css`, `LOG.md`

## 2026-08-30 04:43 UTC — Codex
Applied the accessible open/closed eye visibility toggle to book cards, matching
the chapter-card visibility interaction.
- Files: `app/templates/tree.html`, `app/static/style.css`, `LOG.md`

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
