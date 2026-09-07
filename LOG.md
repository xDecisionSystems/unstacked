# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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
