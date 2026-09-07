# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-09-07 14:42 UTC — Codex
Added Navigation chrome to custom palette controls, presets, API responses,
and persisted theme records. Older custom palettes keep their prior derived
navigation colour when loaded.

Ruff and the complete theme API test suite pass.
- Files: `app/theme.py`, `app/theme_config.py`, `app/admin_api.py`,
  `app/templates/admin.html`, `tests/test_theme_api.py`, `LOG.md`

## 2026-09-07 14:38 UTC — Codex
Extended palette application to the navigation chrome: the top bar, Settings
sidebar, and active Settings control now receive visible palette-derived
backgrounds as well as the content controls.

Ruff and the complete theme API test suite pass.
- Files: `app/theme.py`, `app/static/style.css`, `tests/test_theme_api.py`,
  `LOG.md`

## 2026-09-07 14:25 UTC — Codex
Fixed saved color palettes so they override the established UI variables used
by buttons, headings, links, tags, backgrounds, and status accents instead of
only writing unused palette aliases.

Ruff and the complete theme API test suite pass.
- Files: `app/theme.py`, `tests/test_theme_api.py`, `LOG.md`

## 2026-09-07 14:20 UTC — Codex
Changed successful Book creation to return to the Books library rather than
sending the administrator directly into Page creation.

Ruff and the focused browser content-management test pass.
- Files: `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-07 14:12 UTC — Codex
Merged Branding into Appearance so color and header identity are managed in
one Settings page. MkDocs ZIP downloads now use the space-free branded format
`keybadger_<name><DDMMYYYY>-<HHMM>.zip`.

Ruff and focused export/Settings tests pass.
- Files: `app/templates/admin.html`, `app/web.py`, `tests/test_export.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-07 14:09 UTC — Codex
Removed the Back to workspace link and arrow from the Settings sidebar, along
with its obsolete styling, so the sidebar contains only Settings navigation.

Ruff and the focused Settings page test pass.
- Files: `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-07 14:06 UTC — Codex
Added a guarded MkDocs ZIP import to Import / Export. Archives are screened
for unsafe paths and links, staged as a fresh content Git repository, and can
replace the workspace only after a verified recovery copy and confirmation.

Ruff, focused Settings markup, and MkDocs export/import tests pass.
- Files: `app/mkdocs_import.py`, `app/upload_limit.py`, `app/web.py`,
  `app/templates/admin.html`, `tests/test_export.py`, `tests/test_web.py`,
  `LOG.md`

## 2026-09-07 14:01 UTC — Codex
Shortened the Settings sidebar label from SMTP server to SMTP. The SMTP form
now has more space below its guidance and between field labels and inputs.

Ruff and the focused Settings page test pass.
- Files: `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-07 13:59 UTC — Codex
Constrained the Group name and Description fields to a compact, readable
creation row. On phones, the fields stack so they continue to fit the screen.

Ruff and the focused Settings page test pass.
- Files: `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-07 13:55 UTC — Codex
Moved the group deletion action into each group heading and replaced the
ambiguous “×” with a labelled trash-can icon. Group membership remains a
checkbox matrix, so no per-user delete control is presented.

Ruff and the focused Settings page test pass.
- Files: `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-07 13:34 UTC — Codex
Moved the destructive Home reset action from Settings into the Home editor,
where it is available only to administrators and carries its warning next to
the content it replaces. Removed the obsolete Settings navigation item.

Ruff and focused Settings/Home editor tests pass.
- Files: `app/templates/admin.html`, `app/templates/home_editor.html`, `LOG.md`

## 2026-09-07 13:33 UTC — Codex
Changed the Settings download from generated static HTML to a portable MkDocs
source ZIP. The archive contains the buildable content project and excludes
Git internals and symlinks, so it is safe to transfer or retain as a source
backup.

Ruff and focused export/settings tests pass.
- Files: `app/export.py`, `app/web.py`, `app/templates/admin.html`,
  `tests/test_export.py`, `LOG.md`

## 2026-09-07 13:17 UTC — Codex
Renamed the Settings Export panel to Import / Export and added a guarded
Import action. It restores only from the already-linked Git repository and,
when replacement is needed, first verifies a recovery copy and requires a
second confirmation before local content changes.

Ruff, focused settings, and backup-restore tests pass.
- Files: `app/templates/admin.html`, `tests/test_web.py`, `LOG.md`

## 2026-09-07 13:13 UTC — Codex
Standardized ordinary actions to a compact 36px control and stopped Settings
form submit buttons from stretching across their entire panels. This keeps
actions such as Create user proportional to their labels while retaining
larger, dedicated icon targets where interaction needs them.

Ruff and focused web tests pass.
- Files: `app/static/style.css`, `LOG.md`

## 2026-09-07 13:10 UTC — Codex
Removed the redundant Settings-page Invite user shortcut. The Users panel
already contains the complete creation form, so the compact settings layout
now leads directly to the relevant content without duplicating that action.

Ruff and focused web tests pass.
- Files: `app/templates/admin.html`, `app/static/style.css`, `LOG.md`
