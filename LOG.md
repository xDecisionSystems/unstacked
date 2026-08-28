# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-28 23:10 UTC — Codex
Added a bounded, lock-protected per-user throttle for authenticated AI content
requests and exhaustive finite-domain ACL regression coverage. Token rotation
shares a user budget while users behind one proxy remain isolated.
- Files: `app/ai_api.py`, `app/config.py`, `tests/test_ai_api.py`,
  `tests/test_acl_properties.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:07 UTC — Codex
Extended the T2.1 descriptor-confined migration to existing-page updates and
page/container retitles. Navigation control-file reads, writes, and rollback
now use a fixed `.pages` descriptor API; adversarial ancestor-symlink swaps
cannot rewrite outside sentinels.
- Files: `app/content.py`, `app/paths.py`, `tests/test_content_lifecycle.py`,
  `tests/test_content_symlink_races.py`, `tests/test_paths.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:00 UTC — Codex
Integrated the T2.1 foundations: descriptor-rooted confined tree operations
reject symlink traversal for lifecycle primitives, and navigation now has pure
parse/serialize helpers for confined callers.
- Files: `app/paths.py`, `app/nav.py`, `tests/test_paths.py`,
  `tests/test_nav.py`, `LOG.md`

## 2026-08-28 22:50 UTC — Codex
Integrated T9.3 REST bounds: reject obviously oversized page JSON before any
content write and cap Git diff responses by UTF-8 bytes, including historical
oversized/non-ASCII content.
- Files: `app/ai_api.py`, `tests/test_ai_api.py`, `LOG.md`

## 2026-08-28 22:32 UTC — Codex
Completed T5.5's admin console: confirmed user/group/grant actions, browser
token revocation, backup controls, and a CSRF-protected acknowledged static
export download backed by the safe ZIP packager.
- Files: `app/web.py`, `app/templates/admin.html`, `app/static/style.css`,
  `tests/test_web.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 22:42 UTC — Codex
Integrated safe static-export packaging for the forthcoming admin download:
admin-only, lock-protected, synthetic archive paths, and no symlinks or server
paths in the ZIP.
- Files: `app/export.py`, `tests/test_export.py`, `LOG.md`

## 2026-08-28 22:35 UTC — Codex
Integrated exhaustive ACL boundary tests for segment matching, deepest-rule
resolution, write-implies-read, equal-depth denial, order independence, and
sibling non-leakage.
- Files: `tests/test_acl_boundaries.py`, `LOG.md`

## 2026-08-28 22:30 UTC — Codex
Made API-token revocation usable from the cookie-based admin console without
weakening bearer support: browser requests now require the existing CSRF token.
- Files: `app/ai_api.py`, `LOG.md`

## 2026-08-28 22:25 UTC — Codex
Integrated the browser search UI and operator documentation. Search reuses the
shared ACL-first service, escapes snippets before literal highlight markup, and
keeps pagination filtered. README now documents deployment, recovery, backup,
ACL, exports, secrets, and token revocation.
- Files: `app/web.py`, `app/templates/base.html`, `app/templates/search.html`,
  `app/static/style.css`, `tests/test_web.py`, `README.md`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 22:16 UTC — Codex
Integrated reviewed search API and ACL authorization coverage from the parallel
batch. Bearer callers can now search through the shared ACL-first service with
bounded pagination/errors; new tests verify no unreadable-result leak and
route/service mutation boundaries.
- Files: `app/ai_api.py`, `tests/test_ai_api.py`,
  `tests/test_authorization_coverage.py`, `app/web.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 22:13 UTC — Codex
Reviewed and integrated T10.4 backup round-trip coverage. The tests prove an
identical bare-remote restore, verified recovery before divergent replacement,
safe interruption rollback, and credential redaction on transport failure.
- Files: `tests/test_backup_roundtrip.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 22:10 UTC — Codex
Made manual backup/restore compatible with the browser admin console: these
admin endpoints now accept either bearer tokens or authenticated cookies, and
cookie requests require the existing synchronizer CSRF token.
- Files: `app/backup_api.py`, `LOG.md`

## 2026-08-28 22:01 UTC — Codex
Started T5.5 with an admin-only browser console wired to the established
cookie/CSRF-protected APIs for users, groups, memberships, grants, API token
issuance/revocation, and runtime backup configuration/manual backup. This is
an incremental checkpoint; export actions and fuller management controls
remain before T5.5 is complete.
- Files: `app/web.py`, `app/templates/base.html`, `app/templates/admin.html`,
  `app/static/style.css`, `tests/test_web.py`, `LOG.md`

## 2026-08-28 21:55 UTC — Codex
Completed T5.4's browser history UI. The ACL-filtered revision page displays
Git commits and an escaped side-by-side source diff; selecting a historical
revision and restoring it creates a new commit through the existing service.
Restore controls are not rendered to read-only users, and a deleted page can
be recovered through its still-reachable Git history.

Browser history tests: 18 passing; API/Git history tests: 47 passing; ruff
clean. Production Compose rebuilt and became healthy on port 18055, where
`/healthz` returned `{"status":"ok"}`; stopped without `-v`.
- Files: `app/content.py`, `app/ai_service.py`, `app/web.py`,
  `app/templates/page.html`, `app/templates/history.html`,
  `app/static/style.css`, `tests/test_web.py`, `plans/plan_initial.md`,
  `LOG.md`

## 2026-08-28 20:53 UTC — Codex
Completed T5.3's server-rendered editor and content-management browser flow.
The EasyMDE editor previews through the same sanitized Markdown renderer as
page display, and saves use the existing ACL-aware content service with the
loaded blob SHA, so a stale submission returns a conflict page rather than
overwriting a newer Git commit. Added browser forms for page creation, moves/
slug renames and deletion, plus admin-only book/chapter management; all
state-changing forms require the session CSRF token. Drafts now have visible
badges in both the page view and ACL-filtered tree.

Focused web tests: 32 passing; ruff clean. Production Compose rebuilt and
became healthy on port 18054; `/healthz` returned `{"status":"ok"}` and the
stack was stopped without `-v`.
- Files: `app/web.py`, `app/web_auth.py`, `app/templates/base.html`,
  `app/templates/_tree.html`, `app/templates/page.html`,
  `app/templates/editor.html`, `app/templates/move_page.html`,
  `app/templates/manage.html`, `app/static/style.css`, `tests/test_web.py`,
  `plans/plan_initial.md`, `LOG.md`
