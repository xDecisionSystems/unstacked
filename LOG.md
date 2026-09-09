# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-09-09 03:24 UTC — Codex
Made top-bar content navigation explicitly session-only and added regression
coverage proving anonymous public book and page views do not expose Books or
Pages links, while authenticated users still receive them.

Tests: focused public-view browser tests pass.
- Files: `app/templates/base.html`, `tests/test_web.py`, `LOG.md`

## 2026-09-09 03:07 UTC — Codex
Separated SSH workspace archives from Git synchronization. Administrators can
now pin an SSH server fingerprint, upload a portable restore-ready ZIP, and
guardedly reconstruct content, permissions, users, featured data, and
appearance settings without exporting operational secrets.

Ruff and focused workspace-archive and Settings tests pass.
- Files: `Dockerfile`, `app/config.py`, `app/main.py`, `app/ssh_archive.py`,
  `app/ssh_archive_api.py`, `app/templates/admin.html`, `README.md`,
  `plans/plan_initial.md`, `tests/conftest.py`, `tests/test_ssh_archive.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-09 02:41 UTC — Codex
Clarified Git as synchronization in Settings and enriched every content commit
message with changed paths, editor identity, and a UTC timestamp.

Ruff and focused content, Git, Home, and Settings tests pass.
- Files: `app/git_backend.py`, `app/templates/admin.html`,
  `tests/test_content_lifecycle.py`, `tests/test_home_page.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-09 02:37 UTC — Codex
Wired every successful content commit to wake the optional Git backup worker
immediately. Book and page saves now trigger a prompt remote push without
putting network work or failure on the save request.

Ruff and focused backup and Git tests pass.
- Files: `app/git_backend.py`, `app/backup_runtime.py`,
  `tests/test_git_backend.py`, `LOG.md`

## 2026-09-09 02:19 UTC — Codex
Split backup connection choices into separate Settings pages: Git repository
for HTTPS/token setup and SSH backup for deploy-key and server-fingerprint
confirmation. Each still configures the one active backup destination.

Ruff and focused backup and Settings tests pass.
- Files: `app/templates/admin.html`, `tests/test_web.py`, `LOG.md`

## 2026-09-08 13:16 UTC — Codex
Moved SSH repository backup configuration into its own Remote backup Settings
page. Import / Export now remains focused on moving MkDocs ZIP files and
restoring from the named backup repository.

Ruff and focused Settings markup tests pass.
- Files: `app/templates/admin.html`, `tests/test_web.py`, `LOG.md`

## 2026-09-07 15:40 UTC — Codex
Replaced the Settings known-hosts-path field with an SSH server fingerprint
check. Administrators review and confirm the discovered fingerprint; Unstacked
then stores and enforces the matching host key privately for future syncs.

Ruff and focused backup tests pass. Full suite: 750 passed; one pre-existing
Settings navigation assertion fails because it expects an obsolete Home entry.
- Files: `app/admin_api.py`, `app/backup_config.py`, `app/templates/admin.html`,
  `tests/test_backup_config.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-07 15:24 UTC — Codex
Corrected the palette display name to Pegasus nights, preserving the approved
UCF colors and all palette behavior.

Ruff and focused palette tests pass.
- Files: `app/theme.py`, `tests/test_theme_api.py`, `LOG.md`

## 2026-09-07 15:21 UTC — Codex
Renamed the UCF preset to Pegasus Nights. The Figma comparison now verifies
the exact UCF black, bright gold, and white treatment across Home, Books, and
Settings while retaining readable dark labels on gold actions.

Ruff and focused palette tests pass.
- Files: `app/theme.py`, `tests/test_theme_api.py`, `LOG.md`

## 2026-09-07 15:18 UTC — Codex
Added a selectable UCF Black & Gold palette based on UCF's official digital
black and bright gold. Bright action colors now receive an automatically
contrasting dark label, preserving readable controls.

Ruff and focused palette tests pass.
- Files: `app/theme.py`, `app/static/style.css`, `tests/test_theme.py`,
  `tests/test_theme_api.py`, `LOG.md`

## 2026-09-07 15:11 UTC — Codex
Implemented the four reviewed Figma palette directions as the selectable
built-in palettes. Navigation now uses palette-aware contrasting text, so the
dark Harbor Ink chrome remains readable in both the top bar and Settings.

Ruff and focused palette tests pass.
- Files: `app/theme.py`, `app/static/style.css`, `tests/test_theme.py`,
  `tests/test_theme_api.py`, `LOG.md`

## 2026-09-07 14:55 UTC — Codex
Restored the original light navigation surface for every built-in color
preset. Navigation chrome remains available for custom palette changes.

Ruff and the focused palette tests pass.
- Files: `app/theme.py`, `tests/test_theme.py`, `LOG.md`

## 2026-09-07 14:46 UTC — Codex
Expanded every preset preview to show all six editable palette colors,
including Navigation chrome, so no color disappears from the palette chooser.

Ruff and the complete theme test suite pass.
- Files: `app/templates/admin.html`, `app/theme.py`, `tests/test_theme.py`,
  `tests/test_theme_api.py`, `LOG.md`

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
