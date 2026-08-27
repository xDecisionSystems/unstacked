# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

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

## 2026-08-26 23:51 UTC — Claude Code
Reviewed and expanded `plans/plan_initial.md` into a full subagent task
breakdown: 39 tasks across 11 phases, each with a recommended model tier,
context size, effort level, dependencies, and done-when criteria. Filled
gaps found in review — path-traversal safety, write locking / optimistic
concurrency, asset uploads, API tokens for AI clients, CSRF, mkdocs.yml
ownership, and operator docs. Added dispatch guidance and open questions.
- Files: `plans/plan_initial.md`

## 2026-08-26 23:46 UTC — Claude Code
Created LOG.md and added the logging requirement to AGENTS.md so every
future change (by either agent) gets recorded here, not just at commit
time.
- Files: `LOG.md`, `AGENTS.md`
