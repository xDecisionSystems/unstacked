# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-28 20:18 UTC — Codex
T6.4 backend completed from the pushed WIP snapshot and merged with `--no-ff`.
Preserved its typed JSON persistence, owner-only managed-token storage, admin
routes, tombstone precedence, and runtime worker/manual-service wiring, then
finished and independently reviewed the security/transaction contracts.

Review found two material gaps: the claimed immediate validation never
contacted the target, and failure rollback re-called `configure_remote`, whose
intentional no-op for "no target" left the refused URL/auth wiring in
`.git/config`. Saving now performs `git ls-remote` and a non-mutating dry-run
push, catching reachability, auth/write permission, and incompatible history
before persistence. Git config, credential-helper bytes/mode, managed-token
files, and token environment state are restored byte-exactly on update/clear
failure, including preservation of an operator-owned origin. Status exposes
credential kind but never credential values or key/token paths; rejected URLs
and validation bodies cannot echo embedded credentials. A broken persisted
credential is reported to admins but cannot block app startup.

Added 12 runtime-config tests plus a Git probe test. Full suite 370 passing,
focused backup/Git suite 58 passing, ruff clean. Production Compose rebuilt,
became healthy, returned `{"status":"ok"}` on port 18053, and confirmed the
record path `/app/data/backup_config.json`; stopped without `-v`.
- Files: `.env.example`, `README.md`, `app/admin_api.py`, `app/backup_api.py`,
  `app/backup_config.py`, `app/backup_runtime.py`, `app/config.py`,
  `app/content.py`, `app/git_backend.py`, `app/main.py`, `docker-compose.yaml`,
  `tests/conftest.py`, `tests/test_backup_config.py`,
  `tests/test_git_backend.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 19:58 UTC — Codex
T2.5 independently reviewed, repaired, and merged with `--no-ff`. Read the
complete pending branch diff and empirically checked the security-sensitive
claims: spoofed labels derive their stored type/name from bytes, appended
payloads and active formats are refused, dimension bombs fail while still
small on disk, a declared oversize body never reaches the app, an understated
stream is cut off at the ASGI receive boundary, denied users cannot upload or
read, served assets carry `nosniff`, and a strict standalone MkDocs build
copies and resolves the same relative image link.

Review found two real gaps beyond the report. Structurally empty containers
(for example, PNG with no IDAT) could be accepted as images; parsers now
require actual image data. Book delete/rename ignored `docs/assets/<book>`,
leaving deleted assets published and renamed assets under the stale ACL
namespace; those lifecycle operations now delete or move assets in the same
recoverable Git commit and rewrite the renamed book's relative asset links.
Focused asset coverage is 52 passing; full suite is 357 passing and ruff is
clean. Production Compose rebuilt successfully, became healthy, and returned
`{"status":"ok"}` from `/healthz` on port 18052; stopped without `-v`.
- Files: T2.5 branch files plus `app/assets.py`, `app/content.py`,
  `tests/test_assets.py`, `app/main.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 19:46 UTC — Claude Code
Session had to stop mid-wave (user hit their session limit) with T2.5 and
T6.4 subagents outstanding. T2.5 had actually finished (reported complete,
342 passing, ruff clean) but was sitting on a local-only worktree branch,
never reviewed or merged. T6.4 was still mid-flight with real but
incomplete, uncommitted changes in its worktree. Neither state is safe to
just walk away from: a local-only branch is invisible to anyone who isn't
this exact session (including Codex, which works from `origin`), and
uncommitted changes in a worktree can simply vanish.

Committed T6.4's in-progress state as an explicit WIP snapshot (not a
finished task — labeled as such) so it survives regardless of what happens
to this session or its worktrees. Pushed both branches to `origin` under
`pending/t2.5-assets-review` and `pending/t6.4-backup-config-wip` rather
than leaving them local, since local branches in this clone may not be
visible to Codex depending on how it's actually invoked, and pushing costs
nothing to be safe. Added a prominent "Pending handoff" section at the top
of the plan (before the implementation checkpoint, so it's the first thing
anyone reads) naming both branches, their real status (T2.5: done,
unreviewed; T6.4: genuinely incomplete), and what to do with each —
explicitly to stop a future session (mine or Codex) from silently
re-dispatching work that already exists.

Did not mark T2.5 or T6.4 `[x]` or `[~]` — that would overclaim before an
independent review actually happens, which is the standard every other
merged task in this plan was held to.
- Files: `plans/plan_initial.md`, `LOG.md` (plus the two pushed branches,
  not part of `main`)

## 2026-08-28 19:42 UTC — Claude Code
T5.2 (base web UI: login, ACL-filtered tree, page view) landed — first
dispatch of a new wave (T2.5 assets, T6.4 backup config also running in
parallel), checked `git log` for new Codex activity before starting this
time per last session's lesson. Clean diff, no file overlap except the
expected line in `app/main.py`. Reviewed and independently verified rather
than trusting the report: constructed a book/page with a hostile title
(`<script>…`) and confirmed Jinja2 autoescaping renders it inert in both
the sidebar and breadcrumb — the only `|safe` use is the pre-sanitized
page body from `MarkdownRenderer`, everything else relies on default
escaping; separately confirmed a logout POST without a CSRF token is
genuinely rejected (403) and the session survives, not just accepted
silently. Login/logout/change-password bridge the JSON-oriented
`app/web_auth.py` routes by calling them as plain Python with a
`RedirectResponse` in place of the `Response` they set the cookie on —
reuses 100% of credential/CSRF/cookie logic, works with JS disabled.
Full suite 305 passing, ruff clean. Merged cleanly, no conflicts.
- Files: `app/web.py`, `app/templates/*.html`, `app/static/style.css`,
  `app/main.py`, `tests/test_web.py` (merged from subagent);
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 18:48 UTC — Claude Code
Dispatched three parallel subagents (T3.3, T4.3, T7.1) before Codex's most
recent burst of work landed; all three got cut off mid-task by a session
API limit, uncommitted. Resuming them turned up a real coordination
collision: while they ran, Codex independently pushed 19 commits
implementing its own T3.3, T4.2, T6.2, T7.1, and T8.1 directly on main —
same tasks, different code, neither side aware of the other. Verified my
subagents' actual work first rather than assuming: independently confirmed
T3.3's `blob_sha()` matches real `git hash-object` byte-for-byte, and that
its cross-process concurrency tests use genuine `subprocess.Popen`
children with a shared wall-clock start (not threads, which would only
prove the GIL) — solid work, but redundant: Codex's own concurrency tests
are equally rigorous (real `multiprocessing`, spawn context). Discarded
the T3.3 and T7.1 branches rather than force a merge of two correct,
independently-built solutions to the same problem.

T4.3 (admin API) was genuinely still open — merged after reconciling
against the schema/API drift Codex's other work introduced in the
meantime: added the new `username` field (now the login identifier,
separate from email) to the create-user flow and fixed every affected
test; set `must_change_password=True` on admin-created/reset users to
match bootstrap's own admin account; fixed a real test-harness bug (a
`threading.Barrier(2)` that assumed one `_require_user` call per request,
but `update_user` legitimately calls it twice) rather than loosening the
underlying guard, which is already race-safe by construction — one
`UPDATE ... WHERE <no other active admin exists>` statement under
SQLite's write lock, verified correct independently. Full suite 295
passing, ruff clean. Rewrote the plan's stale implementation checkpoint
and added a coordination-lesson note: check `git log origin/main` for
recent activity before dispatching a task believed unclaimed.
- Files: `app/admin_api.py`, `tests/test_admin_api.py` (merged, with
  fixes); `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 05:54 UTC — Codex
Integrated three more plan tasks: sanitized MkDocs-aligned preview rendering,
guarded optional manual backup/restore, and the shared ACL-aware bounded AI
search service. Each agent passed focused tests and an isolated Compose health
check on ports 18041–18043; integrated lint and tests passed before completion
was recorded.
- Files: `app/render.py`, `app/manual_backup.py`, `app/backup_api.py`,
  `app/ai_service.py`, `app/main.py`, `tests/test_render.py`,
  `tests/test_manual_backup.py`, `tests/test_ai_service.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 05:44 UTC — Codex
Specified the web-home routing contract: unauthenticated visitors to `/` go to
the login page, authenticated users land on their ACL-filtered tree, and a
first-password-change session is limited to its password-change flow.
- Files: `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 05:41 UTC — Codex
Updated Docker/Coolify configuration for the implemented write-lock, session,
static-export, and optional backup-sync settings. The static export path is
explicitly persisted under `/app/data`; corrected the local deployment guide
to use the fixed `admin:admin` bootstrap and mandatory first password change.
- Files: `Dockerfile`, `docker-compose.yaml`, `README.md`, `LOG.md`

## 2026-08-27 05:37 UTC — Codex
Integrated ACL enforcement, bounded ACL-first search, and the optional backup
sync worker. The agents each passed focused security tests and a separate
Docker Compose deployment (`/healthz` on ports 18021–18023); the combined lint
and test suite passed before marking T4.2, T6.2, and T8.1 complete.
- Files: `app/acl.py`, `app/ai_api.py`, `app/ai_service.py`, `app/backup.py`,
  `app/config.py`, `app/git_backend.py`, `app/main.py`, `app/search.py`,
  `tests/test_acl.py`, `tests/test_ai_api.py`, `tests/test_backup.py`,
  `tests/test_search.py`, `plans/plan_initial.md`, `LOG.md`
