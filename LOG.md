# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-09-11 02:56 UTC — Codex
Added an editable Markdown introduction to every book. The section is stored
portably in each book's `.pages` file, rendered above its page grid, and can
be edited with the Toast UI book editor by users with book write access.

Tests: Ruff, focused book-editor browser tests, content-build tests, and nav
tests pass.
- Files: `app/ai_service.py`, `app/content.py`, `app/nav.py`,
  `app/templates/book.html`, `app/templates/book_editor.html`, `app/web.py`,
  `tests/test_web.py`, `LOG.md`

## 2026-09-11 02:45 UTC — Codex
Completed the public/management separation at the browser-route boundary.
Anonymous management visits to Home, Books, Pages, individual books, and
individual pages now redirect to login; public content is served only by the
filtered public static service.

Tests: Ruff, focused management-route browser tests, and public-site tests
pass.
- Files: `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-11 02:36 UTC — Codex
Made the management site explicitly login-first: anonymous visits to its
root or Settings page now redirect to the existing login screen even when
the separately served public Home is enabled.

Tests: Ruff and focused management-login browser tests pass.
- Files: `app/web.py`, `tests/test_web.py`, `LOG.md`

## 2026-09-09 05:57 UTC — Codex
Implemented the split public/management deployment: a filtered, atomic
public MkDocs build now runs independently of the authenticated FastAPI site,
with safe Settings controls, a loopback-only Nginx service, and proxy setup
guidance. Public builds include only explicitly public content and preserve
the last good site on failure; archive-backup and public-build triggers now
coexist.

Tests: Ruff; public-site, admin, backup-listener, and Git backend tests pass.
Local Compose verification: management healthy on 18094 and filtered public
site healthy on 18095.
- Files: `.env.example`, `Dockerfile`, `README.md`, `app/admin_api.py`,
  `app/backup_runtime.py`, `app/config.py`, `app/export.py`,
  `app/git_backend.py`, `app/main.py`, `app/public_site.py`,
  `app/public_site_runtime.py`, `app/templates/admin.html`,
  `deploy/public-nginx.conf`, `docker-compose.yaml`, `plans/plan_initial.md`,
  `tests/conftest.py`, `tests/test_admin_api.py`, `tests/test_public_site.py`,
  `LOG.md`

## 2026-09-09 05:22 UTC — Codex
Added a plan for a separate public static site and management site while
explicitly preserving the current Unstacked login process and permissions.

- Files: `plan/split_site_plan.md`, `LOG.md`

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
