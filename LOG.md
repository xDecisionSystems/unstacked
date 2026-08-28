# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-27 05:26 UTC — Codex
Integrated a second parallel implementation batch: generation-wide API-token
revocation with adversarial token tests, a safe last-good MkDocs export runner,
and repository-wide write locking with optimistic blob conflicts and rollback
coverage. All three agents ran isolated Compose deployments on ports
18011–18013, verified `/healthz`, and preserved volumes on teardown; integrated
lint and tests then passed.
- Files: `app/ai_api.py`, `app/auth.py`, `app/config.py`, `app/content.py`,
  `app/export.py`, `app/git_backend.py`, `tests/test_ai_api.py`,
  `tests/test_export.py`, `tests/test_content_lifecycle.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 05:09 UTC — Codex
Integrated three parallel plan streams: first-admin `admin:admin` credentials
with server-enforced forced password change, portable content-repository
validation CI, and descriptor-confined page reads/creation. Verified lint and
the full suite, then deployed Compose locally on port 18001: health passed,
the restricted first login was denied normal access, password change succeeded,
and the renewed session was accepted. The stack was stopped without volume
deletion.
- Files: `app/models.py`, `app/auth.py`, `app/web_auth.py`, `app/bootstrap.py`,
  `app/ai_api.py`, `app/content.py`, `app/paths.py`, `app/migrations/versions/20260827_0003_first_admin_credentials.py`,
  `tests/test_models.py`, `tests/test_web_auth.py`, `tests/test_bootstrap.py`,
  `tests/test_ai_api.py`, `tests/test_content_bootstrap.py`, `tests/test_paths.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 05:02 UTC — Codex
Added a mandatory local Docker Compose deployment check for application and
deployment changes, including a generated non-committed secret, an unused host
port, health verification, behavior checks where practical, and safe teardown
that preserves the persistent volumes.
- Files: `AGENTS.md`, `LOG.md`

## 2026-08-27 04:54 UTC — Codex
Updated the authentication and bootstrap plan for the required first account:
`admin:admin` is a one-time administrator with a server-enforced mandatory
password change. Reopened the affected completed tasks to cover username and
flag migrations, restricted first-login sessions, token/content blocking, and
the idempotent fixed-credential bootstrap.
- Files: `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 04:42 UTC — Claude Code
User-directed architecture change: GitHub backup is no longer required or
special-cased — everything must run purely on local disk, with off-site
backup as optional and pluggable (git remote, rsync, S3, all equally
valid). Rewrote the plan's context/scope, the "Version history" backup
description, and the settled-decisions table accordingly; renamed Phase 6
"GitHub backup" → "Backup & disaster recovery (optional)" and reframed
T6.1 (already-built) as one interchangeable target implementation rather
than a requirement, T6.2/T6.3 as generic "sync to whichever target is
configured" with "no target configured" as an explicitly done-when-tested
state. No code changed — T6.1's existing implementation already works
against any git host despite GitHub-flavored settings names; noted that
as a future optional rename, not required now.

Also fixed AGENTS.md, which stated a GitHub remote as a non-negotiable
design rule — that's now factually wrong and would have misled the next
agent (Codex included) reading it as a hard rule; corrected it to match.

Mid-turn, the user added a further requirement: an admin UI page to set
up the backup target, rather than env-var-only configuration requiring a
redeploy. Added a new task, T6.4, for runtime-editable backup
configuration (persisted to a `data/` file, not the DB, keeping the
settled four-table scope intact; save immediately re-validates via
`configure_remote`; a saved credential is never rendered back, matching
the API-token screen's precedent) and referenced it from T5.5's admin UI
card. Plan is now 40 tasks (was 39).
- Files: `plans/plan_initial.md`, `AGENTS.md`, `LOG.md`

## 2026-08-27 04:33 UTC — Claude Code
T6.1 (GitHub remote credential handling) landed — the last of the three
parallel subagents, and the most security-sensitive: HTTPS PAT via a
generated repo-local credential helper (never the URL, `.git/config`, or
a process argument), SSH via a pinned repo-local `core.sshCommand`, error
scrubbing, force-push made structurally impossible. Branched before the
T1.2/T2.3 merges, so real conflicts this time (config.py: both added
fields at the same insertion point; content.py: an import line) —
resolved on a scratch branch, verified `git_backend.py`'s three-way
auto-merge actually combined T2.3's commit_paths fix with this task's
push/fetch/configure_remote rewrite correctly (it did) before finalizing.

Didn't stop at reading the code and running its tests: configured a real
local repo with a fake token file and checked by hand — `.git/config` and
`git remote -v` never contain the token value, the helper file is
owner-only (0600), and `git credential fill` retrieves the token
correctly through git's real credential protocol. That's the strongest
verification of the three merges today, matching the stakes.

Marked T6.1 `[x]` with one honest caveat carried into the plan: "verified
private" is an operator affirmation, not a live GitHub API check — nothing
in this codebase makes real network calls, so that's a documented
interpretation, not a gap I found. Real coverage gaps needing an actual
GitHub account (SSH host-key enforcement, a live authenticated push) are
also recorded rather than papered over. Full suite 200 passing, ruff
clean. All three subagents from this dispatch are now merged; cleaned up
the last worktree.
- Files: `app/config.py`, `app/content.py`, `app/git_backend.py`,
  `docker-compose.yaml`, `.env.example`, `tests/test_config.py`,
  `tests/test_git_backend.py` (merged from subagent, conflicts resolved
  by me); `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 04:19 UTC — Claude Code
T2.3 (content repository update/delete/move/rename) landed from the second
parallel subagent. This was the highest-risk of the three — content
mutation contracts everything else builds on — so reviewed harder than
usual: read the full diff, and independently reproduced the subagent's
central bug-fix claim before trusting it (GitPython's `index.add` does
*not* stage a missing path as a deletion, contrary to a comment I myself
wrote in an earlier commit — verified with a throwaway repo, confirmed
`FileNotFoundError`). That bug had been latent since my own T1.1 fix and
would have blocked every delete/rename `commit_paths` call; `git_backend.py`
now partitions declared paths into present/absent and stages absent ones
via `index.remove(..., ignore_unmatch=True)`.

Also independently mutation-tested the rollback claim rather than taking
"7 injected-failure tests pass" at face value: neutered `_Rollback.undo()`
to a no-op and reran — all 7 parametrized cases failed as expected,
confirming the tests actually exercise rollback rather than passing
vacuously. Restored the file, reran clean. New methods
(`update_page`/`set_page_title`/`set_container_title`/`delete_page`/
`delete_chapter`/`delete_book`/`move_page`/`rename_book`/`rename_chapter`)
correctly declare both halves of a rename per-file (not just the directory)
so `git log --follow` survives renaming a whole chapter's contents, not
only top-level moves — a subtlety a naive implementation would miss.
Merged cleanly (different files than T1.2's merge, no conflicts); full
suite 173 passing, ruff clean. Marked T2.3 `[x]` and added a post-hoc note
to T3.1 documenting the git_backend.py fix.
- Files: `app/content.py`, `app/git_backend.py`,
  `tests/test_content_lifecycle.py` (merged from subagent);
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 04:13 UTC — Claude Code
Dispatched three parallel subagents (isolated git worktrees, opus tier) to
coordinate plan implementation: T2.3 finish (update/delete/move/rename),
T1.2 (web session auth), T6.1 (GitHub remote credentials) — run alongside
Codex, which is independently committing to main. T2.3 was run solo
(the plan forbids racing it against T2.1/T4.1/T4.2/T3.3); T1.2/T6.1 are
independent modules so ran in parallel with it.

T1.2 landed first. Reviewed its actual diff (not just its report):
`app/web_auth.py`, cookie sessions cleanly separated from bearer-token
auth, session_generation-based invalidation, synchronizer-pattern CSRF,
fixation defense via a freshly rotated session id per login, shared rate
limiter with the bearer login path. Independently re-ran the full suite
and ruff myself before merging — both clean, 16 new tests. Found and
fixed one real gap the subagent flagged itself: it added `itsdangerous`
to pyproject.toml but had no uv binary to update uv.lock, which would
have broken CI's `uv sync --locked`. Installed uv, regenerated the lock,
reverified. Merged to main, marked T1.2 `[x]`.
- Files: `.gitignore`, `uv.lock` (from me); `app/web_auth.py`,
  `tests/test_web_auth.py`, `app/config.py`, `app/main.py`,
  `.env.example`, `pyproject.toml` (merged from subagent);
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 03:52 UTC — Codex
Completed the Git-wrapper plan task with guarded `origin` push and
fetch/fast-forward operations. Synchronization now refuses dirty or divergent
content histories and returns generic typed failures, preventing remote or
credential details from reaching callers. Added bare-repository integration
tests for push, fast-forward, and refusal behavior.
- Files: `app/git_backend.py`, `tests/test_git_backend.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 03:49 UTC — Codex
Completed three unblocked plan foundations: database-level authorization
constraints with migration coverage, atomic awesome-nav `.pages` management,
and deterministic ACL container visibility/diagnostics. Updated the plan to
mark T1.1, T2.4, and T4.1 complete; the full validation suite follows.
- Files: `app/models.py`, `app/migrations/versions/20260827_0002_database_constraints.py`,
  `tests/test_models.py`, `app/nav.py`, `app/content.py`, `tests/test_nav.py`,
  `app/acl.py`, `tests/test_acl.py`, `plans/plan_initial.md`, `LOG.md`


