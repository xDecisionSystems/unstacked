# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-29 03:08 UTC — Claude Code
Completed T9.3 (the plan's last open task) — every task is now `[x]` or
`[not planned]`. Discovered a real gap while investigating "OpenAPI
validation against a real action client" from scratch: fetched the whole
app's actual `/openapi.json` and found 40 operations across 32 paths —
the AI surface mixed in with the admin console, backup, and browser-
cookie routes. That's both over ChatGPT Actions' 30-operation import
limit and the wrong thing to expose as AI "tools" regardless of the
limit; nothing before this pointed it out because nobody had actually
fetched and inspected the schema rather than just building routes.

Added `GET /api/ai/openapi.json` (`build_ai_openapi_schema` in
app/ai_api.py), built directly from the router's own route objects
filtered to `/api/ai/*` so it can't drift from what those routes actually
accept — 13 paths, 14 operations. Deliberately excludes
`/api/auth/token`/`tokens/revoke`: an Action gets one bearer token
configured out of band, not by calling a credential-issuing endpoint as
one of its own operations. Added `Settings.public_base_url` (validated
absolute http(s) URL) so the schema can declare the `servers` entry an
Action needs — omitted, not guessed, when unset.

Validated with the real `openapi-spec-validator` library against the
actual OpenAPI 3.1 spec, not a shape this app's own tests invented, plus
Action-specific checks a generic validator wouldn't catch (operationId
uniqueness, the 30-op ceiling, universal bearer security). Mutation-
tested the security check specifically: stripped one operation's
`security` array and confirmed my assertion catches it while the generic
validator still accepts the now-unauthenticated shape as structurally
valid OpenAPI — proving the extra check earns its place. Full suite 602
passing (was 583 at the start of this session's work on T2.1/T9.3), ruff
clean.
- Files: `app/ai_api.py`, `app/config.py`, `.env.example`, `pyproject.toml`,
  `uv.lock`, `tests/test_ai_openapi.py`, `tests/test_config.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-29 02:55 UTC — Claude Code
User asked to complete the remaining two tasks; did T2.1 directly rather
than dispatching a subagent (narrow finishing work on a codebase I already
had full context on). Closed the last gap — recursive container
delete/rename still used `shutil.rmtree`/`os.replace`/`safe_join` while
every other content operation had already migrated to `ConfinedTree`.

Added `ConfinedTree.walk_files` (recursive, descriptor-confined) and
rewrote `_delete_container`/`_rename_container` to use it exclusively —
confirmed by grep that zero raw Path-mutation calls remain in either.
Rename's rollback doesn't need delete's byte-snapshot approach (a
directory rename is one atomic op); it unwinds via a small ordered stack
of closures instead. Removed the now-dead Path-based `_changed_nav` and
`_container_path` rather than leaving unused code behind.

Hit one real bug of my own making mid-implementation: naming a new method
`walk_files -> list[str]` after the class already defines a method
literally called `list` shadows the builtin for every annotation
evaluated later in the same class body — `TypeError: 'function' object is
not subscriptable` at import time. Fixed by reordering, not renaming, so
future methods aren't left as a trap.

Verified rather than assumed: added two adversarial tests swapping the
parent book for a symlink between the confined walk and the delete/rename
that follows it. A mutation test (temporarily reverting to raw
`shutil.rmtree`) still passed them — an earlier confined step (the
nav-parent check) independently catches the same race first — so also
added a call-spy proving `ConfinedTree.delete_tree`/`.rename()` are
genuinely invoked, not merely that the pipeline is safe via a different
layer. Full suite 585 passing (was 583), ruff clean. T2.1 marked `[x]`.
Starting T9.3 next.
- Files: `app/content.py`, `app/paths.py`,
  `tests/test_content_symlink_races.py`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:36 UTC — Claude Code
User asked to remove the MCP server (T9.2) — too token-costly per call
versus a plain API for the same operations, REST-only going forward.
Found Codex had already made this exact change (`b0bf3dc`, "Keep AI
integration REST-only") before I got to it — T9.2 marked `[not planned]`
with reasoning recorded, checkpoint already says REST is the sole AI
transport. Nothing left to do there.

Fixed one thing Codex's change missed: `AGENTS.md` still described "Claude
MCP" as a live AI transport and listed `ai_mcp` in the module layout
diagram, contradicting the plan. Corrected both, and tidied two more
stale MCP mentions in the plan itself (the top-of-file scope bullet and
the settled-decisions table row) that still framed it as planned/dual-
transport rather than explicitly dropped.
- Files: `AGENTS.md`, `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:33 UTC — Codex
Extended T2.1 confinement through page delete and move transactions, including
navigation edits and rollback. Ancestor-symlink adversarial tests confirm that
the operations do not delete or publish an outside sentinel.
- Files: `app/content.py`, `tests/test_content_symlink_races.py`,
  `plans/plan_initial.md`, `LOG.md`

## 2026-08-28 23:31 UTC — Codex
Removed MCP from the MVP at the user's request. The existing signed-bearer
REST/OpenAPI surface is now the sole AI transport, avoiding a second protocol
and its client-context overhead.
- Files: `README.md`, `plans/plan_initial.md`, `LOG.md`

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



