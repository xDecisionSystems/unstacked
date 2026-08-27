# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-27 00:27 UTC — Codex
Implemented the first secure application slice for AI-authored wiki content.
Added the FastAPI app, locked Python project, initial Alembic schema, Argon2
login and signed bearer tokens, login throttling, deterministic path ACLs,
safe filesystem/Git content services, portable MkDocs bootstrap, and shared
AI service plus REST endpoints for filtered tree/page/ZIP downloads and
book/chapter/page creation. Added integration and security tests, including
a real strict MkDocs build proving drafts stay out of output/search, and
updated the plan and contributor/operator documentation for AI writes.
- Files: `.env.example`, `.gitignore`, `pyproject.toml`, `uv.lock`, `app/*.py`,
  `app/migrations/**`, `tests/*.py`, `README.md`, `AGENTS.md`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-27 00:10 UTC — Codex
Reviewed the planning-only repo and hardened the initial architecture plan.
Clarified that static builds contain all non-draft content and have no ACL;
kept API authentication inside the four-table database boundary with signed,
generation-revocable tokens; specified deterministic ACL conflict behavior,
safe cross-process content mutations, guarded non-destructive restore, strict
recovery builds, and bounded search/upload/render behavior; corrected task
dependencies and verification criteria; and updated current dependencies to
Argon2 via `pwdlib` and `mkdocs-awesome-nav` v3 while retaining `.pages`.
- Files: `plans/plan_initial.md`, `AGENTS.md`, `README.md`, `LOG.md`

## 2026-08-27 00:01 UTC — Claude Code
Settled the last two open questions: no shelves (books live at the `docs/`
root, two levels max under a book) and `draft: true` pages are excluded
from the built site. Drafts are excluded via a `hooks/drafts.py` committed
inside the content repo rather than a third-party plugin, so the exclusion
travels with the content and survives the worst-case drill. Updated the
content layout, T2.3, T3.2, T5.3 (draft toggle + badge) and T10.3 (drill
now asserts drafts produce no output), and replaced "Open questions" with
a settled-decisions table.
- Files: `plans/plan_initial.md`, `LOG.md`

## 2026-08-26 23:58 UTC — Claude Code
Resolved the auth open question: local passwords only, no SSO/LDAP. Added
it to confirmed scope and tightened task T1.2 to require an
`authenticate()` seam plus login rate limiting, so an external provider
could be added later without touching every route.
- Files: `plans/plan_initial.md`, `LOG.md`

## 2026-08-26 23:55 UTC — Claude Code
Corrected the model-tier mapping in the plan per user: `luna` is the small
tier and `terra` the mid tier (I had them reversed). Every task card now
lists both naming sets (`opus`/`sol`, `sonnet`/`terra`, `haiku`/`luna`) so
either agent can read its own tier directly. Replaced the mapping prose
with a table, dropped the now-resolved open question, and fixed the task
count in the previous entry (39, not 34).
- Files: `plans/plan_initial.md`, `LOG.md`

