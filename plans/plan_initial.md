# Unstacked: file-based BookStack alternative

## Context

`unstacked` is "a markdown version of BookStack." BookStack stores everything — books, chapters, pages, revisions — in MySQL. This project flips that: page **content** and its structure/history live as plain markdown files in a git repo, organized exactly the way mkdocs expects (`docs/` + `mkdocs.yml`), so that in a worst-case failure the content folder alone can be dropped into any mkdocs install and built into a working static site. A small SQL database is kept, but only for things that are inherently relational and security-sensitive: users, groups, and access-control rules. Content is backed up by pushing its git history to a GitHub remote.

Confirmed scope (from user):
- Backend: **Python/FastAPI** (lets the app reuse mkdocs' own markdown-extension pipeline and shell out to `mkdocs build`, instead of reimplementing rendering).
- Deployment shape: **single team, one wiki instance**. Users and group membership are managed in the webapp. **Groups** are granted **read/write access at the chapter and page level**.
- Search: no dedicated search index — grep-style filesystem search plus mkdocs' own generated static search.
- Planned from day one: **AI search integration for Claude and ChatGPT**, so the search/read path is a clean, permission-aware API/MCP surface, not a later bolt-on.

## Architecture

### Content layout (the "mkdocs project")

A dedicated git repository, independent of the app's own source code repo, at `content/`:

```
content/
  mkdocs.yml
  .github/workflows/build.yml   # rebuilds the static site on push, app-independent
  docs/
    <shelf-slug>/               # optional grouping layer (a Shelf)
      .pages                    # mkdocs-awesome-pages: title + nav order
      <book-slug>/
        .pages
        <chapter-slug>/
          .pages
          <page-slug>.md
        <page-slug>.md          # pages directly in a book, no chapter
    <book-slug>/                # books not in any shelf live at docs/ root
    assets/<book-slug>/...      # uploaded images/attachments
```

- Book → folder, Chapter → subfolder, Page → `.md` file. Shelves are an optional top folder grouping several Books — this stays copy-paste-compatible with plain mkdocs.
- Use `mkdocs-awesome-pages-plugin` (`.pages` files) for nav titles/ordering instead of a hand-maintained `nav:` in `mkdocs.yml`. The app never rewrites a giant nav tree — it writes/renames folders and small `.pages` files. Without the plugin installed, mkdocs falls back to alphabetical nav, which still builds.
- Every page file starts with YAML front matter for app metadata mkdocs ignores: `id` (uuid, stable across renames), `title`, `created_at`, `updated_at`, `author`, `tags`, `draft`.
- **`mkdocs.yml` is app-owned but hand-editable.** The app only ever rewrites a delimited managed block; anything a human adds outside that block is preserved.

### Version history — git, not a revisions table

- The content repo is a real git repo. Every save from the app = one commit authored as the editing user. This *is* the page revision history: `git log -- path`, `git diff`, `git show`, `git checkout <sha> -- path`. No `revisions` table.
- Deletes are plain `git rm` + commit — recovery is `git checkout`, which replaces BookStack's recycle bin.
- GitHub backup = this repo has a GitHub remote. The app pushes on save (debounced) and via a manual "Back up now" admin action, using a deploy key or PAT. "Restore from GitHub" re-clones if local content is lost.
- Worst-case fallback: a GitHub Action in the content repo runs `mkdocs build` on every push, so the GitHub repo alone — no app, no database — always regenerates a working static site.

### Concurrency

Single-instance app, so a single process-wide write lock around every (write file → stage → commit) sequence is sufficient and avoids git index races. Editing uses optimistic concurrency: the editor carries the blob SHA it loaded, and a save whose base SHA no longer matches is rejected with a conflict view rather than silently overwriting.

### Database — users, groups, permissions only

SQLite (SQLModel/SQLAlchemy):
- `users` (id, email, password hash, display name, is_admin, is_active)
- `groups` (id, name, description)
- `user_groups` (user_id, group_id)
- `permissions` (group_id, path_prefix, can_read, can_write) — `path_prefix` is a relative path under `docs/`. Most specific matching prefix wins (a page rule overrides its parent chapter's rule); `is_admin` bypasses; default deny.
- `api_tokens` (id, user_id, name, token hash, created_at, last_used_at, revoked) — for ChatGPT Actions / MCP clients, which act *as* a user and inherit that user's permissions.

No content, no revisions, no search index in the database.

### App modules (FastAPI)

| Module | Responsibility |
|---|---|
| `config` | Settings (paths, secrets, GitHub creds) via pydantic-settings |
| `models` | SQLModel schema: users/groups/permissions/api_tokens |
| `auth` | Password hashing, sessions, CSRF, API-token auth |
| `paths` | Slugs + path safety (traversal prevention) — every filesystem path goes through here |
| `frontmatter_io` | Front-matter read/write round-trip |
| `content` | CRUD/move/rename for books, chapters, pages, assets |
| `nav` | `.pages` file management on every structural change |
| `acl` | Path-prefix permission resolution + FastAPI dependencies |
| `git_backend` | GitPython wrapper: commit-as-user, log, diff, show, restore, push, pull |
| `render` | Page HTML using the same markdown extensions declared in `mkdocs.yml` |
| `search` | Permission-filtered grep over markdown bodies |
| `export` | `mkdocs build` / `gh-deploy` runner |
| `ai_service` | Shared `search_wiki` / `get_page` / `list_pages` used by both AI transports |
| `ai_mcp` | MCP server (Claude) over `ai_service` |
| `ai_api` | REST + OpenAPI surface (ChatGPT Actions) over `ai_service` |
| `web` | Jinja2 templates, tree browser, EasyMDE editor, admin screens |

### Repo layout

```
unstacked/
  app/                  # modules above
    templates/
    static/
  content/              # nested mkdocs git repo — gitignored here, managed via GitPython
  data/app.db           # SQLite: users/groups/permissions/api_tokens only
  tests/
  plans/
```

---

## Subagent task breakdown

**Model tiers.** Recommendations use Claude names; if you are dispatching to the other agent's tier names, the mapping is by capability tier — small/fast = `haiku` ≈ `terra`, mid = `sonnet` ≈ `luna`, frontier = `opus` ≈ `sol`. *(Confirm this mapping — `terra`/`luna`/`sol` are not names I can verify.)*

- **`opus`** — security-critical or subtle logic where a wrong answer is silent and dangerous (ACL, path safety, credential handling, concurrency, git correctness).
- **`sonnet`** — normal feature work with clear specs and testable outcomes. The default.
- **`haiku`** — mechanical scaffolding, config files, boilerplate, templates.

**Context** = how much of the codebase the agent needs loaded: **S** (its own files, ~30k), **M** (its module + neighbors, ~80k), **L** (cross-cutting, ~150k+).
**Effort** = reasoning effort: low / medium / high / max.

Tasks marked **[P]** in the same phase are parallelizable — no shared files, no dependency between them.

---

### Phase 0 — Scaffolding

#### T0.1 — Project scaffolding **[P]**
`haiku` · **S** · **low** · depends: —
`pyproject.toml` (FastAPI, uvicorn, SQLModel, GitPython, python-frontmatter, python-slugify, passlib[bcrypt], itsdangerous, Jinja2, mkdocs, mkdocs-material, mkdocs-awesome-pages-plugin, pytest, ruff), `.gitignore` (must ignore `content/`, `data/`, `site/`, `.venv`), `ruff.toml`, empty `app/` and `tests/` packages, `README` dev-setup section.
**Done when:** `pip install -e .` succeeds and `ruff check` passes on an empty tree.

#### T0.2 — Config module **[P]**
`haiku` · **S** · **low** · depends: —
`app/config.py` using pydantic-settings: `content_repo_path`, `db_path`, `session_secret`, `github_remote`, `github_token`, `site_output_path`, `debug`. Load from env + `.env`. Include `.env.example`.
**Done when:** settings import cleanly with defaults and every secret reads only from env, never a committed file.

---

### Phase 1 — Data layer & auth

#### T1.1 — Database schema
`sonnet` · **S** · **medium** · depends: T0.1, T0.2
`app/models.py`: SQLModel definitions for the five tables above; engine/session factory; `create_all()` on startup. No migration framework yet — schema is small and pre-release.
**Done when:** tables create from scratch on a fresh DB and unit tests can insert a user, group, membership, and permission.

#### T1.2 — Password auth & sessions
`opus` · **M** · **high** · depends: T1.1
`app/auth.py`: bcrypt hashing, login/logout routes, signed session cookies (itsdangerous, HttpOnly + SameSite + Secure-in-prod), `current_user` dependency, CSRF tokens for all state-changing form posts, generic login failures that don't leak whether an account exists.
**Done when:** login/logout work end to end, a tampered session cookie is rejected, and a form POST without a valid CSRF token is rejected.

#### T1.3 — API token auth
`opus` · **M** · **high** · depends: T1.1, T1.2
Token issue/revoke (hash at rest, plaintext shown once), `Authorization: Bearer` dependency resolving to a user so machine clients inherit that user's group permissions. Used later by `ai_api`/`ai_mcp`.
**Done when:** a token authenticates as its user, a revoked token fails, and the raw token is never stored or logged.

#### T1.4 — First-run bootstrap CLI **[P]**
`haiku` · **S** · **low** · depends: T1.1
`python -m app.bootstrap` — create the first admin user, initialize the DB, and (via T3.2) the content repo.
**Done when:** a clean checkout reaches a usable logged-in admin in one command.

---

### Phase 2 — Content engine

#### T2.1 — Path safety & slugs
`opus` · **S** · **high** · depends: T0.2
`app/paths.py`: slugify titles; a `safe_join(content_root, *parts)` that resolves symlinks and **rejects anything escaping `docs/`**; reserved-name handling; collision suffixes. Every other module must route filesystem access through this.
**Done when:** an adversarial test suite (`../`, absolute paths, URL-encoded traversal, symlink escape, null bytes, Windows-reserved names, unicode lookalikes) is fully rejected.
> Security-critical: this is the single control preventing arbitrary filesystem read/write in a file-backed app.

#### T2.2 — Front-matter I/O **[P]**
`sonnet` · **S** · **medium** · depends: T0.1
`app/frontmatter_io.py`: read/write page files via `python-frontmatter`; schema for `id`/`title`/`created_at`/`updated_at`/`author`/`tags`/`draft`; tolerate missing/malformed front matter (hand-written or pasted-in files must not crash the app); preserve unknown keys on round-trip.
**Done when:** round-trip tests preserve every field including unknown keys, and a file with no front matter still loads with sane defaults.

#### T2.3 — Content repository
`opus` · **L** · **high** · depends: T2.1, T2.2
`app/content.py`: the core tree API — list/get/create/update/delete/move/rename for shelves, books, chapters, pages; tree walker producing the nav model; slug-rename via `git mv` so history follows the file; title change updates front matter *and* `.pages` without moving the file (URLs stay stable).
**Done when:** every operation leaves a tree that `mkdocs build` accepts, and rename preserves `git log --follow` history.

#### T2.4 — Nav (`.pages`) management
`sonnet` · **M** · **medium** · depends: T2.3
`app/nav.py`: create/update `.pages` on every structural change; explicit ordering; `title:` for display names; remove stale entries on delete.
**Done when:** reordering in the app changes only `.pages`, and a plain `mkdocs build` reflects the new order.

#### T2.5 — Assets & uploads
`sonnet` · **M** · **medium** · depends: T2.1, T2.3
Image/attachment upload into `docs/assets/<book>/`, content-type allowlist, size cap, filename sanitizing via `app/paths.py`, markdown-relative link generation that still resolves in a static mkdocs build.
**Done when:** an uploaded image renders both in-app and in `mkdocs build` output, and a hostile filename cannot escape the assets folder.

---

### Phase 3 — Git backend

#### T3.1 — Git wrapper
`opus` · **M** · **high** · depends: T0.2
`app/git_backend.py`: GitPython wrapper — `commit_as(user, paths, message)`, `log(path)`, `diff(sha_a, sha_b, path)`, `show(sha, path)`, `restore(sha, path)`, `push()`, `pull()`. Never invoke a shell with interpolated user input. Surface git failures as typed exceptions, not raw stderr.
**Done when:** committing as two different users produces two distinct git authors, and history operations work on a renamed file.

#### T3.2 — Content repo bootstrap
`sonnet` · **M** · **medium** · depends: T3.1
Initialize `content/` if absent: `git init`, `mkdocs.yml` with the managed-block convention and the awesome-pages plugin, a starter `docs/index.md`, `.gitignore` (ignore `site/`), and the `.github/workflows/build.yml` that runs `mkdocs build` on push.
**Done when:** a fresh bootstrap produces a directory that `mkdocs build` compiles with zero app involvement.

#### T3.3 — Write lock & optimistic concurrency
`opus` · **M** · **high** · depends: T3.1, T2.3
Process-wide lock around write→stage→commit; save requests carry the base blob SHA and are rejected with a conflict response when stale; leave the git index clean on any failure path.
**Done when:** concurrent saves to one page produce one commit plus one conflict (never a lost update or a wedged index), verified by a concurrency test.

#### T3.4 — Page history API
`sonnet` · **M** · **medium** · depends: T3.1, T2.3
Routes for per-page history list, diff between revisions, and restore-to-revision (restore = a new commit, never a rewrite).
**Done when:** a restored page's content matches the chosen revision and history shows the restore as a new commit.

---

### Phase 4 — Access control

#### T4.1 — ACL resolution engine
`opus` · **M** · **max** · depends: T1.1, T2.1
`app/acl.py`: given a user and a `docs/`-relative path, resolve read/write. Union across the user's groups; **most-specific prefix wins**; explicit deny at a more specific prefix beats an inherited allow; admins bypass; default deny. Pure function, no I/O, exhaustively table-tested.
**Done when:** a truth-table test suite covers inherited allow, page-overrides-chapter, conflicting grants across two groups, no-matching-rule, and admin bypass.
> Security-critical: every other module trusts this answer.

#### T4.2 — ACL enforcement dependencies
`opus` · **L** · **high** · depends: T4.1, T2.3
FastAPI dependencies `require_read(path)` / `require_write(path)` wired into **every** content, search, history, asset, and AI route. Tree listings filter unreadable nodes rather than 403-ing the whole page. Unreadable paths return 404, not 403, so the tree doesn't leak names.
**Done when:** a route-coverage test enumerates all registered content routes and fails if any lacks an ACL dependency.

#### T4.3 — Admin API & permission management
`sonnet` · **M** · **medium** · depends: T4.1, T1.2
CRUD for users, groups, memberships, and per-path grants; guard against removing the last admin.
**Done when:** grants created in the UI immediately change what a second user can see, and the last admin cannot be deleted or demoted.

---

### Phase 5 — Rendering & web UI

#### T5.1 — Markdown renderer
`sonnet` · **M** · **medium** · depends: T3.2
`app/render.py`: read `markdown_extensions` from `mkdocs.yml` and render with the same `markdown` config, so in-app preview matches the static build. Sanitize output (or disable raw HTML) since page content is user-supplied.
**Done when:** a page containing admonitions, fenced code, and tables renders identically in-app and in `mkdocs build`, and an injected `<script>` in page content does not execute.

#### T5.2 — Base layout & tree browser
`sonnet` · **L** · **medium** · depends: T4.2, T5.1
Jinja2 base template, sidebar tree (ACL-filtered), breadcrumbs, page view. No SPA framework.
**Done when:** two users with different grants see different trees on the same instance.

#### T5.3 — Editor & save flow **[P]**
`sonnet` · **M** · **medium** · depends: T5.2, T3.3
EasyMDE editor, live preview via `render`, save posting the base SHA for conflict detection, create/rename/move/delete UI.
**Done when:** an edit saves, commits, and re-renders; a stale save shows a conflict screen instead of overwriting.

#### T5.4 — History UI **[P]**
`sonnet` · **M** · **medium** · depends: T3.4, T5.2
Revision list, side-by-side diff, restore button with confirmation.

#### T5.5 — Admin UI **[P]**
`sonnet` · **M** · **medium** · depends: T4.3, T5.2
Screens for users, groups, memberships, permission grants, API tokens, and backup/export actions.

---

### Phase 6 — GitHub backup

#### T6.1 — Remote & credential handling
`opus` · **M** · **high** · depends: T3.1, T0.2
Configure `origin`, deploy-key or PAT auth, credentials from env only. Never log, echo, or render a token; scrub tokens from any surfaced git error text.
**Done when:** a forced push failure surfaces a useful message with no credential material in logs or the UI.

#### T6.2 — Debounced push worker
`sonnet` · **M** · **high** · depends: T6.1, T3.3
Background task coalescing rapid saves into a periodic push; retry with backoff; never block a user's save on network I/O; surface last-push status and failures in the admin UI.
**Done when:** ten rapid saves produce ten commits but far fewer pushes, and an offline period recovers automatically on reconnect.

#### T6.3 — Manual backup & restore **[P]**
`sonnet` · **M** · **medium** · depends: T6.1
"Back up now" (push) and "Restore from GitHub" (clone/pull into an empty or divergent `content/`) admin actions, with an explicit confirmation on restore since it can replace local state.

---

### Phase 7 — Static export

#### T7.1 — Build/publish runner
`sonnet` · **S** · **medium** · depends: T3.2
`app/export.py`: run `mkdocs build` (and optionally `gh-deploy`) as a subprocess; stream status; surface build errors in the admin UI.
**Done when:** "Publish" produces a `site/` directory and a failing build reports the real mkdocs error.

#### T7.2 — Content-repo GitHub Action **[P]**
`haiku` · **S** · **low** · depends: T3.2
The workflow committed *into the content repo* that installs mkdocs + plugins and builds (optionally deploying to Pages) on every push.
**Done when:** a push to the content repo builds the site in CI with no reference to the app.

---

### Phase 8 — Search

#### T8.1 — Search core
`sonnet` · **M** · **medium** · depends: T2.3, T4.1
`app/search.py`: walk/grep markdown bodies and front-matter titles/tags; ripgrep when available with a pure-Python fallback; snippet extraction with match highlighting; **filter results through ACL before returning** — never after pagination.
**Done when:** a term appearing only in a page the user cannot read returns zero results for that user, and result counts are correct after filtering.

#### T8.2 — Search API & UI **[P]**
`sonnet` · **M** · **low** · depends: T8.1, T5.2
Search box, results page with snippets and breadcrumbs.

---

### Phase 9 — AI integration

#### T9.1 — Shared AI service layer
`opus` · **M** · **high** · depends: T8.1, T4.2, T2.3
`app/ai_service.py`: one permission-aware implementation of `search_wiki(query, user)`, `get_page(path, user)`, `list_pages(user)`, returning clean structured results with token-budget-aware truncation. Both transports call only this — no duplicated logic, no permission bypass.
**Done when:** the same query through MCP and REST returns identical, identically-filtered results.

#### T9.2 — MCP server (Claude) **[P]**
`sonnet` · **M** · **high** · depends: T9.1, T1.3
MCP server exposing the three tools, authenticated by API token so tool calls run as a real user with that user's permissions. Clear tool descriptions and schemas.
**Done when:** Claude Code/Desktop connects, lists the tools, and retrieves only pages the token's user may read.

#### T9.3 — REST + OpenAPI surface (ChatGPT) **[P]**
`sonnet` · **M** · **high** · depends: T9.1, T1.3
`/api/ai/*` endpoints with a clean OpenAPI schema suitable for a ChatGPT custom GPT Action; bearer-token auth; rate limiting.
**Done when:** the generated OpenAPI validates as a GPT Action schema and unauthenticated calls are rejected.

---

### Phase 10 — Testing, CI, docs

#### T10.1 — ACL & path-safety test suites
`opus` · **M** · **high** · depends: T4.1, T2.1
Exhaustive truth-table tests for ACL resolution and adversarial tests for path traversal. These two suites are the security regression net.

#### T10.2 — Content round-trip integration test **[P]**
`sonnet` · **M** · **medium** · depends: T2.3, T3.2
Create book → chapter → page via the API, assert the on-disk layout, then run a real `mkdocs build` and assert success.

#### T10.3 — Worst-case drill script **[P]**
`sonnet` · **S** · **medium** · depends: T3.2
`scripts/worstcase_drill.sh`: copy only `content/` to a temp dir, `pip install mkdocs` + plugins in a clean venv, `mkdocs build`, assert success. **This is the project's defining guarantee — it runs in CI.**

#### T10.4 — Backup round-trip test **[P]**
`sonnet` · **M** · **medium** · depends: T6.3
Push to a scratch remote, wipe local `content/`, restore, assert identical `git log` and file tree.

#### T10.5 — App CI workflow **[P]**
`haiku` · **S** · **low** · depends: T0.1
GitHub Action for the app repo: ruff, pytest, and the worst-case drill.

#### T10.6 — Operator documentation **[P]**
`sonnet` · **M** · **low** · depends: most of the above
Install/deploy guide, backup/restore runbook, permission model explainer, and the "my app died, how do I get my wiki back" recovery procedure.

---

## Dispatch guidance

- **Critical path:** T0 → T1.1 → T2.1 → T2.3 → T3.1 → T3.3 → T4.1 → T4.2 → T5.2. Everything else hangs off these.
- **Do not parallelize** T2.1, T2.3, T4.1, T4.2, or T3.3 with each other — they define the contracts every other task builds on, and racing them produces incompatible interfaces.
- **Good parallel batches:** (T0.1, T0.2) · (T2.2, T1.4) · (T5.3, T5.4, T5.5) · (T10.2, T10.3, T10.4, T10.5, T10.6).
- Frontier-model (`opus`) tasks are concentrated in ACL, path safety, concurrency, git, and credentials — five areas where a plausible-looking wrong implementation fails silently and insecurely. Don't downgrade those to save budget.
- Every subagent must read [AGENTS.md](../AGENTS.md) first: content never in the database, the content tree stays mkdocs-buildable at all times, git is the revision history, and every change gets a `LOG.md` entry plus a commit and push.

## Verification

- **Unit:** ACL truth table (inherited allow, page-overrides-chapter, cross-group conflict, admin bypass, default deny); path-traversal rejection; front-matter round-trip including unknown keys.
- **Integration:** book → chapter → page through the API produces the documented layout and a passing real `mkdocs build`.
- **Worst-case drill (the defining test):** copy only `content/` — no app, no database — to a clean environment with mkdocs installed, build, and confirm the site renders. Runs in CI on every push.
- **Permissions:** two users in different groups each see and edit only their granted chapters/pages; unreadable paths 404 rather than 403.
- **Backup round-trip:** push to a test GitHub repo, wipe local `content/`, restore, confirm identical history and files.
- **Concurrency:** simultaneous saves to one page yield one commit and one conflict, never a lost update.

## Open questions

1. Confirm the `terra`/`luna`/`sol` → tier mapping used in the task table.
2. Shelves — build now or defer? Books-at-root works without them and they can be added later without a migration (it's just a folder move).
3. Should draft pages (`draft: true`) be excluded from `mkdocs build` output, or published like any other page?
4. Is SSO/LDAP needed eventually, or is local password auth sufficient for the foreseeable future?
