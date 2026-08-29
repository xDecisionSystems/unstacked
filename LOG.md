# LOG.md

A running log of changes made by AI coding agents in this repo, so Claude
Code and Codex (and human reviewers) can see what the other did — even
between commits. See [AGENTS.md](AGENTS.md) for the logging rules.

Newest entry at the top. Only the most recent **15** entries are kept —
when a new entry would make 16, the oldest entry is deleted, regardless of
how long any entry is.

---

## 2026-08-29 03:41 UTC — Claude Code
User couldn't log in as `admin`/`admin` on a deployed instance ("Invalid
username or password"). Root cause wasn't a code bug: no `admin` row existed
because `python -m app.bootstrap` had never been run there (this local
checkout was in the same state — `data/app.db` didn't exist). Confirmed the
fix by running `unstacked-bootstrap` here and logging in successfully.

While tracing it, found `README.md`'s Quick Start and Coolify sections
documented a bootstrap CLI that doesn't exist — `--email`/`--display-name`
flags, a password prompt, `--password-stdin`, a printed API token. The real
`app/bootstrap.py` (unchanged, correct) takes no arguments and always creates
`admin`/`admin`, matching `plans/plan_initial.md`'s T1.4 spec; only the
README had drifted. Corrected both sections to describe the actual, argument-
free command.
- Files: `README.md`, `LOG.md`

## 2026-08-29 03:31 UTC — Claude Code
User asked for admin-configurable theming: four standard palette options plus
a custom one. Added `app/theme.py` (five-role `Palette`, four presets --
Future Green, Ocean Blue, Sunset Coral, Slate Mono -- plus `darken`/`tint`
helpers that derive `--accent-dark` and `--bg-alt` from `accent` so a custom
palette never needs to supply a hover shade by hand) and
`app/theme_config.py`, a runtime-editable JSON record under `data/`
mirroring `app/backup_config.py`'s precedent: a color palette is cosmetic
configuration, not wiki data, so it doesn't belong in a fifth DB table, and a
malformed record degrades to the default preset rather than breaking every
page render.

Wired the effective palette into every template -- including `login.html`
and `change_password.html`, which predate `_base_context` and never call
it -- via one Jinja global (`theme_style(request)` in `app/web.py`) that
injects a small inline `<style>{{ :root override }}</style>` block reading
the JSON file fresh per request; no cache to invalidate, so a saved change
is visible on the next page load with no restart. `style.css`'s own `:root`
now documents that it's just the Future Green defaults, overridden per
request.

Added `GET`/`PUT /api/admin/theme` (admin-only, CSRF-guarded for the cookie
transport, same as every other admin route) and an Appearance section in
the admin console: radio options with live color swatches for the four
presets plus "Custom", five `<input type=color>` fields, `location.reload()`
after a successful save so the new palette applies immediately everywhere,
not just in the panel that changed it.

52 new tests (`tests/test_theme.py`, `tests/test_theme_api.py`): hex
validation, every preset's internal consistency, `darken`/`tint` bounds
math, JSON load/save round-trips, six variants of "a corrupt or unknown-shape
record falls back to the default rather than raising," admin-only + CSRF
route contracts, the preset/palette mutual-exclusion check, and two
render-level assertions (`--accent:` appears correctly on both an
authenticated page and the pre-login screen). Full suite green, ruff clean.
- Files: `app/theme.py`, `app/theme_config.py`, `app/config.py`, `app/web.py`,
  `app/admin_api.py`, `app/static/style.css`, `app/templates/base.html`,
  `app/templates/login.html`, `app/templates/change_password.html`,
  `app/templates/admin.html`, `tests/conftest.py`, `tests/test_theme.py`,
  `tests/test_theme_api.py`, `LOG.md`

## 2026-08-29 03:14 UTC — Claude Code
Applied the user-supplied brand palette (Future Green #00CA8C, Bright
Pastel Orange #FFB54C, Cyber Lime #8CD47E, Digital Gray #808080, Cosmic
Blue #002E5D) to `app/static/style.css`, the web UI's one hand-written
stylesheet. Remapped the existing CSS custom properties rather than
introducing new hardcoded colors throughout: `--accent` → Future Green,
`--muted`/`--text` → Digital Gray/Cosmic Blue, `--bg-alt` → a light
Future Green tint, plus a new `--accent-secondary` (Cyber Lime) and
`--warm` (Pastel Orange) for search-highlight/draft-badge/diff-table
accents. Deliberately kept `--danger` a plain red rather than
repurposing a brand color for destructive actions — none of the five
reads as "danger", and legibility for delete/revoke controls matters
more than palette purism there. Added a button hover state (darker
green) since none existed before. Recolored the draft badge, search
snippet highlight, and diff add/sub/chg backgrounds to match. Verified
the stylesheet still serves correctly and the full web UI test suite
(21 tests) still passes — styling doesn't affect any Python-level
assertion, but confirmed nothing broke regardless.
- Files: `app/static/style.css`, `LOG.md`

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
