# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-27 00:38 UTC — Codex
Added ACL-enforced AI page-history endpoints for Git commit lists, unified
revision diffs, and restore-as-a-new-commit. Validated revision input and
path containment, and covered the complete restore history flow in tests.
- Files: `app/git_backend.py`, `app/content.py`, `app/ai_service.py`,
  `app/ai_api.py`, `tests/test_ai_api.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 00:38 UTC — Codex
Added the app CI workflow and the portable worst-case recovery drill. The
drill copies only the content repository into a temporary directory, builds
with a clean supported-Python environment and its own manifest, and proves a
seeded draft is absent from HTML and static search. CI runs locked setup,
linting, tests with coverage, migration upgrade, packaging, and that drill.
- Files: `.github/workflows/ci.yml`, `scripts/worstcase_drill.sh`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 00:38 UTC — Codex
Added a tolerant front-matter I/O module so hand-authored pages without valid
metadata remain readable, while atomic writes retain operator-defined metadata
keys. Wired page creation and reads through the module and added focused
round-trip/default tests; marked the completed plan task.
- Files: `app/frontmatter_io.py`, `app/content.py`,
  `tests/test_frontmatter_io.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 00:33 UTC — Codex
Audited every planned task’s model tier, context level, and reasoning effort.
Raised scaffolding/configuration, bootstrap, migrations, history, export, CI,
and recovery verification where their contracts exceed mechanical work; moved
uploads, rendering, admin permission changes, push/restore, search isolation,
and MCP transport to the frontier tier because failures can silently leak,
corrupt, or destroy data. Added the risk-based assignment rule to the plan.
- Files: `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 00:32 UTC — Codex
Added a managed provider-neutral `llm.md` workflow to the portable content
repository. It explains authenticated AI API use without secrets or content
discovery data, is served by the app and copied verbatim to static `/llm.md`,
and is provisioned for existing repositories only when absent so local edits
are preserved. Documented the contract and added endpoint/build verification.
- Files: `app/content.py`, `app/main.py`, `tests/test_content_build.py`,
  `tests/test_ai_api.py`, `README.md`, `plans/plan_initial.md`, `LOG.md`
