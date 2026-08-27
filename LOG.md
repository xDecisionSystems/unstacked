# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-27 03:20 UTC — Codex
Kept the Docker application listener and health checks on internal port 8000,
while making the external Compose host port configurable through
`UNSTACKED_HOST_PORT` (default 8001) to avoid the occupied Coolify host port.
Updated the deployment instructions with the host-to-container port mapping.
- Files: `Dockerfile`, `docker-compose.yaml`, `README.md`, `LOG.md`

## 2026-08-27 03:06 UTC — Codex
Validated the committed production Docker Compose deployment locally. Built
the multi-stage image, started it with a generated non-committed signing
secret, confirmed `/healthz` and Docker health, and verified the initialized
SQLite database and nested Git content repository on persistent volumes.
Added the exact local test/bootstrap commands and recorded the Docker/Coolify
state-persistence decision in the plan.
- Files: `README.md`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 02:57 UTC — Claude Code
User installed Docker Desktop, so I could finally test-build instead of
reasoning from logs alone. Confirmed the README.md fix resolved the build
failure, but found a second, more serious bug the build alone wouldn't
have caught: the runtime image (python:3.12-slim) has no `git` binary, so
GitPython raised ImportError at process startup and the container
crash-looped on every run — Coolify would have deployed a Dockerfile that
built cleanly and then never actually served traffic. Added `git` via
apt-get to the runtime stage. Verified end-to-end this time: built the
image, ran the container, confirmed Docker's own HEALTHCHECK reports
healthy, hit /healthz, /llm.md and /docs successfully, and inspected
/app/content and /app/data inside the container — running as non-root
uid 999, content repo initialized with real git history, generated
api_token_secret correctly mode 0600.
- Files: `Dockerfile`, `LOG.md`

## 2026-08-27 02:46 UTC — Claude Code
Fixed a Coolify Docker Compose build failure: `RUN uv sync --locked
--no-dev` (the step that installs the project itself, not just
dependencies) exited 1 at Dockerfile:25. pyproject.toml declares
`readme = "README.md"`, but the builder stage never copied README.md into
the image, so hatchling had nothing to build the project's metadata from.
Added README.md to the initial COPY alongside pyproject.toml/uv.lock.
Diagnosed from the log (exact line match plus a well-known uv+hatchling
Docker gotcha) rather than a local repro — this sandbox still has no
Docker/uv, so the user needs to confirm the redeploy succeeds.
- Files: `Dockerfile`, `LOG.md`

## 2026-08-27 02:28 UTC — Claude Code
Renamed docker-compose.yml to docker-compose.yaml. Coolify's Docker
Compose resource type looks for /docker-compose.yaml at the repo root by
default and the user hit that lookup failure; renaming avoids needing to
touch Coolify's "Docker Compose Location" setting. No content changed —
Compose doesn't care which spelling is used, and nothing in the file
referenced its own filename.
- Files: `docker-compose.yaml` (renamed from `docker-compose.yml`),
  `README.md`, `LOG.md`

## 2026-08-27 02:22 UTC — Claude Code
Added Coolify/Docker deployment support at the user's request. A
multi-stage Dockerfile (uv-based, pinned to the same uv version as CI,
non-root runtime user, HEALTHCHECK against /healthz, single worker to
match the project's one-file-lock concurrency model) and a
docker-compose.yml, since the user hadn't yet decided which Coolify
resource type to use. Both declare /app/content and /app/data as the
only persistent state — losing them loses the wiki. Documented both
Coolify setup paths in README, including that UNSTACKED_TRUSTED_PROXY_HOPS
must be set to 1 behind Coolify's Traefik proxy, that first-admin
bootstrap is a manual one-time step (deliberately not automatic on
deploy), and that automated GitHub backup of content/ isn't built yet
(Phase 6) so the volume is the only copy for now. Also noted plainly that
only the REST/AI API is live — no web UI exists yet.
Caveat: this sandbox has neither Docker nor a local uv binary, so the
Dockerfile could not be test-built here; syntax was checked by hand
against uv's documented Docker pattern and uvicorn's --factory flag.
- Files: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `README.md`,
  `LOG.md`

## 2026-08-27 01:05 UTC — Claude Code
Reviewed Codex's implementation and fixed everything found, most-severe
first. High: the JWT signing secret defaulted to a shared constant and was
only validated in production, so a default-environment run let anyone
forge an admin token — now no default; dev/test generate and persist a
private secret, production refuses to start without one, known
placeholders are rejected everywhere. `commit_paths` committed the whole
index (an operator's staged work could be swept into another user's commit
and misattributed) — the index is now reset to HEAD before staging.
Medium: `log()` used rev-list, which can't follow renames — switched to
`git log --follow`; history/diff/restore required the file to exist,
making deleted pages unrecoverable — they now work from history alone,
which is what stands in for the recycle bin; the draft hook treated CRLF
files as having no front matter and published them — now normalizes line
endings first; pages could be created below the two-level depth limit,
buildable but invisible in the tree — now rejected; the login rate limiter
trusted the raw socket peer (one shared bucket behind any proxy) and grew
unbounded — added a configurable trusted-proxy-hops lookup and a capped,
evicting table. Lower: normalized `Permission.path_prefix` at the model
boundary so a trailing slash can't silently grant nothing; batched ACL
loading (`load_policy`) so a tree listing queries permissions once instead
of per page; quoted `Content-Disposition` filenames against header
injection; added Windows-reserved-name rejection to path safety; expanded
`test_acl.py` to the plan's full nine-case truth table and `test_paths.py`
to the full adversarial set (both found additional gaps in normalization,
now fixed too); added a coverage floor (85%) to CI. Updated the plan with
`[x]`/`[~]` status markers and Remaining notes on every partial task, and
recorded the review in an Implementation checkpoint addendum. Full suite:
100 tests passing, 88.65% coverage, ruff clean, worst-case drill still
passes against a fresh bootstrap.
- Files: `app/config.py`, `app/git_backend.py`, `app/paths.py`,
  `app/acl.py`, `app/models.py`, `app/auth.py`, `app/content.py`,
  `app/ai_api.py`, `app/main.py`, `.env.example`, `.github/workflows/ci.yml`,
  `tests/test_acl.py`, `tests/test_paths.py`, `tests/test_config.py`,
  `tests/test_git_backend.py`, `tests/test_rate_limit.py`,
  `tests/test_content_structure.py`, `tests/test_content_build.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 00:43 UTC — Codex
Ignored the generated coverage data file so the CI-equivalent verification
command leaves no local test artifact in the application worktree.
- Files: `.gitignore`, `LOG.md`

## 2026-08-27 00:42 UTC — Codex
Completed the remaining initial scaffolding and bootstrap acceptance criteria.
Added the planned template, sanitization, and MkDocs theme dependencies plus
coverage tooling to the locked project; made first-run bootstrap safe for
automation through standard input and idempotent on rerun; and documented the
behavior. Marked T0.1 and T1.4 complete after verification.
- Files: `pyproject.toml`, `uv.lock`, `app/bootstrap.py`,
  `tests/test_bootstrap.py`, `README.md`, `plans/plan_initial.md`, `LOG.md`




