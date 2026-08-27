# Unstacked: file-based BookStack alternative

## Context

`unstacked` is "a markdown version of BookStack." BookStack stores everything — books, chapters, pages, revisions — in MySQL. This project flips that: page **content** and its structure/history live as plain markdown files in a git repo, organized exactly the way mkdocs expects (`docs/` + `mkdocs.yml`), so that in a worst-case failure the content repo alone carries everything needed to create a clean mkdocs environment and build a working static site. A small SQL database is kept, but only for things that are inherently relational and security-sensitive: users, groups, and access-control rules. Content is backed up by pushing its git history to a GitHub remote.

Confirmed scope (from user):
- Backend: **Python/FastAPI** (lets the app reuse MkDocs/Python-Markdown configuration and invoke `mkdocs build`, instead of adopting an unrelated rendering stack).
- Deployment shape: **single team, one wiki instance**. Users and group membership are managed in the webapp. **Groups** are granted **read/write access at the chapter and page level**.
- Search: no dedicated search index — grep-style filesystem search plus mkdocs' own generated static search.
- Planned from day one: **AI read and write integration for Claude, ChatGPT, and other agents**, so search/download and create-book/chapter/page operations use clean, permission-aware service and API/MCP surfaces rather than transport-specific logic.
- Auth: **local passwords only** — no SSO/LDAP. Keep the auth layer behind a small `authenticate(email, password) -> user` seam anyway, so adding an external provider later is a new backend rather than a rewrite of every route.
- Static output: the built mkdocs site has **no runtime ACL**. It is a recovery/export artifact containing every non-draft page, not a permission-preserving replacement for the app. The content remote and build artifacts are private; public deployment is outside MVP scope.

### Implementation checkpoint (2026-08-27)

The first vertical slice is implemented: project/config scaffolding, the four-table SQLite schema with an initial Alembic migration, Argon2 password verification and signed bearer tokens, deterministic ACL resolution, path-safe content creation, an inter-process Git mutation lock, portable content-repo bootstrap, a shared AI service, and REST/OpenAPI endpoints for ACL-filtered tree/page/ZIP downloads plus create-book/chapter/page. Integration tests verify authentication, revocation, rate limiting, ACL conflicts, traversal/symlink rejection, Git authorship, and a real `mkdocs build --strict` with draft exclusion. Search, MCP transport, web UI, history, uploads/assets, backup/push, and later lifecycle operations remain planned work.

## Architecture

### Content layout (the "mkdocs project")

A dedicated git repository, independent of the app's own source code repo, at `content/`:

```
content/
  mkdocs.yml
  requirements.txt             # exact mkdocs/nav build dependency versions
  hooks/drafts.py               # excludes draft:true pages from the build
  .github/workflows/build.yml   # rebuilds the static site on push, app-independent
  docs/
    index.md
    llm.md                    # maintained llm-md workflow; copied to static /llm.md
    <book-slug>/                # books live at the docs/ root — no shelves
      .pages                    # awesome-nav v3: title + nav order
      <chapter-slug>/
        .pages
        <page-slug>.md
      <page-slug>.md            # pages directly in a book, no chapter
    assets/<book-slug>/...      # uploaded images/attachments
```

- Book → folder, Chapter → subfolder, Page → `.md` file. **Exactly two levels of nesting under a book**, so the tree stays predictable. **No shelves** — books sit at the `docs/` root. (If grouping is ever wanted, it's a folder move plus a `.pages` file, with no schema or data migration.)
- Use the current `mkdocs-awesome-nav` plugin, explicitly configured with `filename: .pages`, for nav titles/ordering instead of a hand-maintained `nav:` in `mkdocs.yml`. The app never rewrites a giant nav tree — it writes/renames folders and small `.pages` files using the plugin's v3 syntax. A missing configured plugin makes mkdocs fail rather than fall back, so `requirements.txt`, CI, and the recovery runbook are part of the portable content repo.
- Every page file starts with YAML front matter for app metadata mkdocs ignores: `id` (uuid, stable across renames), `title`, `created_at`, `updated_at`, `author`, `tags`, `draft`.
- `docs/llm.md` is a managed, provider-neutral [llm-md](https://llm.md/) workflow that tells authenticated agents how to use the AI API safely. It contains no secrets and no content listing, so publishing the raw file at `/llm.md` cannot disclose ACL-protected paths. The portable MkDocs hook copies it unchanged to the root of a static build as `/llm.md`; the project does not require the alpha llm-md CLI at runtime.
- **`mkdocs.yml` is bootstrap-generated and then operator-owned.** Normal content operations never rewrite it. The app reads and validates it, reports unsupported settings clearly, and preserves it byte-for-byte; deliberate configuration changes are made by an operator and committed in the content repo.

### Drafts

Pages with `draft: true` in front matter are **excluded from the built site**. They stay fully visible and editable inside the app (subject to normal ACL) with a draft badge, and searchable there — they simply never reach `mkdocs build` output.

Implementation: a native mkdocs `hooks:` entry (mkdocs ≥ 1.4) pointing at `hooks/drafts.py` **committed inside the content repo**, whose `on_files` drops any file whose front matter has `draft: true`. The hook uses only the Python standard library plus dependencies already required by mkdocs. A page with no front matter is non-draft; malformed front matter is a build error so ambiguous metadata cannot accidentally publish a draft.

> Caveat to document for operators: copying only `docs/` while leaving `mkdocs.yml`/`hooks/` behind would publish drafts. The recovery runbook (T10.6) must say "copy the whole `content/` directory," and the drill (T10.3) asserts drafts are absent from the output.

### Version history — git, not a revisions table

- The content repo is a real git repo. Every save from the app = one commit authored as the editing user. This *is* the page revision history: `git log -- path`, `git diff`, `git show`, `git checkout <sha> -- path`. No `revisions` table.
- Deletes are plain `git rm` + commit — recovery is `git checkout`, which replaces BookStack's recycle bin.
- GitHub backup = this repo has a **private-by-default** GitHub remote. The app pushes after saves (debounced) and via a manual "Back up now" admin action, using a deploy key or PAT. Pushes are never forced and the app never auto-merges remote divergence.
- "Restore from GitHub" clones only into an absent/empty destination or fast-forwards a clean checkout. Divergent or dirty local state is first preserved to a timestamped recovery directory and requires an explicit admin choice; restore never silently replaces unpushed commits.
- Worst-case fallback: a GitHub Action in the content repo installs `requirements.txt` and runs `mkdocs build --strict` on every push, so the content repo alone — no app or database — regenerates the full non-draft static site. It does not recreate users, ACLs, or a private per-user view.

### Concurrency

The app is a single wiki instance but may have multiple server processes. Use a repository-scoped **inter-process file lock** around each complete mutation (validate → atomic file changes → stage exact paths → commit); all web, worker, bootstrap, restore, and admin git operations take the same lock. A failed mutation restores the original files and leaves the index clean. Editing uses optimistic concurrency: the editor carries the blob SHA it loaded, and a save whose path or base SHA no longer matches is rejected with a conflict view rather than silently overwriting.

### Database — users, groups, permissions only

SQLite (SQLModel/SQLAlchemy):
- `users` (id, email, password hash, display name, is_admin, is_active, session_generation, api_token_generation)
- `groups` (id, name, description)
- `user_groups` (user_id, group_id)
- `permissions` (group_id, path_prefix, can_read, can_write) — `path_prefix` is a normalized, segment-aware relative path under `docs/`; raw string prefix matching is forbidden. Resolution semantics are defined under T4.1.

No content, revisions, API-token records, or search index live in the database. AI clients use expiring signed bearer tokens containing user ID, token generation, issued-at, expiry, audience, and a unique token ID. Incrementing `users.api_token_generation` revokes all outstanding API tokens for that user; deactivating the user rejects them immediately. This deliberately trades per-token naming/revocation for the repo's strict four-table database boundary.

### App modules (FastAPI)

| Module | Responsibility |
|---|---|
| `config` | Settings (paths, secrets, GitHub creds) via pydantic-settings |
| `models` | SQLModel schema: users/groups/memberships/permissions + migrations |
| `auth` | Password hashing, sessions, CSRF, API-token auth |
| `paths` | Slugs + path safety (traversal prevention) — every filesystem path goes through here |
| `frontmatter_io` | Front-matter read/write round-trip |
| `content` | Transactional CRUD/move/rename for books, chapters, pages, assets |
| `nav` | `.pages` file management on every structural change |
| `acl` | Path-prefix permission resolution + FastAPI dependencies |
| `git_backend` | GitPython wrapper: commit-as-user, log, diff, show, restore, push, guarded fetch/fast-forward |
| `render` | Page HTML using the same markdown extensions declared in `mkdocs.yml` |
| `search` | Permission-filtered grep over markdown bodies |
| `export` | Private full-wiki `mkdocs build` runner |
| `ai_service` | Shared permission-aware read/export and create-book/chapter/page operations used by AI transports |
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
  data/app.db           # SQLite: users/groups/memberships/permissions only
  tests/
  plans/
```

---

## Subagent task breakdown

**Model tiers.** Each task lists both naming sets as `claude-name` / `other-name`:

| Tier | Names | Use for |
|---|---|---|
| Frontier | `opus` / `sol` | Security-critical or subtle logic where a wrong answer is silent and dangerous — ACL, path safety, credential handling, concurrency, git correctness. |
| Mid | `sonnet` / `terra` | Normal feature work with clear specs and testable outcomes. The default. |
| Small | `haiku` / `luna` | Mechanical scaffolding, config files, boilerplate, templates. |

**Context** = how much of the codebase the agent needs loaded: **S** (its own files, ~30k), **M** (its module + neighbors, ~80k), **L** (cross-cutting, ~150k+).
**Effort** = reasoning effort: low / medium / high / max.

Assignments below are risk-based rather than a measure of task size. A task is
frontier-tier when a plausible implementation can silently weaken security,
lose content, or corrupt Git history; test and documentation tasks inherit
that tier only when they must exercise those failure modes. Revisit an
assignment only if the implementation is deliberately narrowed or a proven,
reviewed primitive removes the risky part.

Tasks marked **[P]** in the same phase are parallelizable — no shared files, no dependency between them.

---

### Phase 0 — Scaffolding

#### T0.1 — Project scaffolding **[P]**
`sonnet` / `terra` · **S** · **medium** · depends: —
`pyproject.toml` with a supported Python floor and bounded direct dependencies (FastAPI, uvicorn, SQLModel/SQLAlchemy, Alembic, GitPython, python-frontmatter, python-slugify, `pwdlib[argon2]`, itsdangerous, Jinja2, filelock, mkdocs, mkdocs-material, mkdocs-awesome-nav, HTML sanitizer, pytest, ruff); a reproducible lock file; `.gitignore` (must ignore `content/`, `data/`, `site/`, `.venv`); lint config; empty `app/` and `tests/` packages; README dev setup.
**Done when:** a clean locked install succeeds, `ruff check` passes, and dependency versions used by app CI and the generated content-repo `requirements.txt` are intentionally compatible.

#### T0.2 — Config module **[P]**
`sonnet` / `terra` · **S** · **medium** · depends: —
`app/config.py` using pydantic-settings: `content_repo_path`, `db_path`, `session_secret`, API-token signing secret/audience/TTL, git remote/auth settings, `site_output_path`, upload/search limits, and `debug`. Load from env + ignored `.env`; include a redacted `.env.example`. Paths are resolved and validated once at startup. Production secrets have no insecure defaults and must be distinct where separation matters.
**Done when:** development settings import with explicit safe dev values, production startup rejects missing/placeholder secrets, and no secret is committed, logged, placed in a command line, or rendered.

---

### Phase 1 — Data layer & auth

#### T1.1 — Database schema
`sonnet` / `terra` · **M** · **high** · depends: T0.1, T0.2
`app/models.py`: SQLModel definitions for the four tables above; engine/session factory; SQLite foreign-key enforcement and appropriate unique/index/check constraints. Add Alembic from the first schema rather than relying on `create_all()` after bootstrap.
**Done when:** migrations upgrade a fresh DB to head, foreign-key cascades and uniqueness constraints behave as specified, and tests can insert a user, group, membership, and normalized permission.

#### T1.2 — Password auth & sessions
`opus` / `sol` · **M** · **high** · depends: T1.1
`app/auth.py`: Argon2 password hashing via `pwdlib`, login/logout routes, signed session cookies containing only minimal identifiers and the current `session_generation` (HttpOnly + SameSite + Secure-in-prod), `current_user` dependency, CSRF tokens for every cookie-authenticated state change, generic/timing-resistant login failures, and bounded login rate limiting. Rotate the session on login/logout; increment the generation on password/admin security reset; and reject inactive users on every request. **Local passwords only** — no SSO/LDAP — but keep credential checking behind `authenticate(email, password) -> User | None`.
**Done when:** login/logout work end to end; fixation and tampered/expired cookies are rejected; unsafe form requests without valid CSRF are rejected; inactive users lose access; and no route reads the password hash outside `authenticate()`.

#### T1.3 — API token auth
`opus` / `sol` · **M** · **high** · depends: T1.1, T1.2
Issue short-lived signed bearer tokens with `sub`, `iat`, `exp`, `aud`, `jti`, and the user's current `api_token_generation`; verify an explicit algorithm and audience, then resolve the active user so machine clients inherit current group permissions. Admin/user revocation increments the generation and revokes all of that user's issued tokens. Keep tokens out of storage and logs, and document the lack of per-token revocation.
**Done when:** a valid token authenticates as its active user; expired, wrong-audience, wrong-generation, tampered, and deactivated-user tokens fail; revocation invalidates all prior tokens; and raw tokens are never persisted or logged.

#### T1.4 — First-run bootstrap CLI
`sonnet` / `terra` · **M** · **medium** · depends: T1.1, T3.2
`python -m app.bootstrap` — create the first admin user, initialize the DB, and (via T3.2) the content repo.
Make it idempotent and non-interactive-capable without accepting passwords in process arguments.
**Done when:** a clean checkout reaches a usable admin and buildable content repo in one command, and rerunning cannot create a second accidental bootstrap admin.

---

### Phase 2 — Content engine

#### T2.1 — Path safety & slugs
`opus` / `sol` · **S** · **high** · depends: T0.1, T0.2
`app/paths.py`: slugify titles; canonicalize URL paths exactly once; reject double encoding; and provide a `safe_join(docs_root, *parts)` that resolves the existing nearest parent and **rejects anything escaping `docs/`**, including symlink escapes and case-fold collisions on case-insensitive filesystems. Handle reserved/internal names (`assets`, `.pages`, dotfiles), bounded lengths, collisions, null bytes, separators, Windows-reserved names, and Unicode normalization. Every filesystem module uses typed validated relative paths from here, never raw request strings.
**Done when:** an adversarial cross-platform suite covers traversal, encoding, symlink races/escapes, reserved names, collisions, and Unicode normalization without rejecting ordinary international titles.
> Security-critical: this is the single control preventing arbitrary filesystem read/write in a file-backed app.

#### T2.2 — Front-matter I/O **[P]**
`sonnet` / `terra` · **S** · **medium** · depends: T0.1
`app/frontmatter_io.py`: read/write page files via `python-frontmatter`; schema for `id`/`title`/`created_at`/`updated_at`/`author`/`tags`/`draft`; tolerate missing/malformed front matter (hand-written or pasted-in files must not crash the app); preserve unknown keys on round-trip.
**Done when:** round-trip tests preserve every field including unknown keys, and a file with no front matter still loads with sane defaults.

#### T2.3 — Content repository
`opus` / `sol` · **L** · **high** · depends: T2.1, T2.2, T2.4, T3.1
`app/content.py`: the core tree API — list/get/create/update/delete/move/rename for books, chapters, and pages (no shelves; books live at the `docs/` root); tree walker producing the nav model; slug rename via the git wrapper so history follows the file; title change updates front matter *and* `.pages` without moving the file (URLs stay stable); enforce the two-level depth limit. All page writes use same-directory temporary files plus atomic replace. Each logical operation declares every affected content/nav/asset path and is committed once through the locked git mutation API; direct ad-hoc filesystem writes are forbidden.
**Done when:** every successful operation leaves a clean index and a tree that `mkdocs build --strict` accepts; injected failures restore the pre-operation bytes; and rename preserves `git log --follow` history.

#### T2.4 — Nav (`.pages`) management
`sonnet` / `terra` · **M** · **medium** · depends: T0.1, T2.1
`app/nav.py`: parse and write awesome-nav v3 `.pages` files; explicit ordering and display titles; preserve unknown supported keys; reject malformed files without clobbering them; remove stale entries on delete. Writes are atomic and are orchestrated by T2.3 rather than committed independently.
**Done when:** reorder changes only `.pages`; operator-added supported keys survive round trips; malformed YAML remains untouched with an actionable error; and `mkdocs build --strict` reflects the order.

#### T2.5 — Assets & uploads
`opus` / `sol` · **M** · **high** · depends: T2.1, T2.3
Image/attachment upload into `docs/assets/<book>/`, request and decompressed-size caps, signature-based type detection, a conservative allowlist, filename sanitizing via `app/paths.py`, and markdown-relative links that resolve in a static build. Disallow active content such as HTML/SVG by default; serve downloads with `nosniff` and safe disposition headers.
**Done when:** an uploaded image renders in-app and in the static build; hostile names and polyglot/spoofed files fail safely; oversized uploads are rejected before exhausting memory/disk; and upload/asset routes obey ACL.

---

### Phase 3 — Git backend

#### T3.1 — Git wrapper
`opus` / `sol` · **M** · **high** · depends: T0.1, T0.2
`app/git_backend.py`: GitPython wrapper — exact-path staging and `commit_as(user, paths, message)`, `log(path)`, `diff(sha_a, sha_b, path)`, `show(sha, path)`, restore-as-a-new-commit, `push()`, and guarded fetch/fast-forward. Validate SHAs/ref names and paths; never invoke a shell with interpolated input; never stage unrelated working-tree changes; scrub credentials and local sensitive paths from typed errors.
**Done when:** two users produce distinct authors; history follows a rename; restore adds a commit; unrelated dirty files remain untouched; and adversarial refs/paths cannot become command options or escape the repo.

#### T3.2 — Content repo bootstrap
`sonnet` / `terra` · **M** · **medium** · depends: T3.1
Initialize `content/` if absent: `git init` with an explicit initial branch; operator-owned `mkdocs.yml` enabling `search` and `awesome-nav` configured with `filename: .pages`; `requirements.txt` with exact build dependency versions; `hooks/drafts.py`; starter `docs/index.md`; a managed provider-neutral `docs/llm.md` workflow; root `docs/.pages`; and `.gitignore` (ignore `site/`). Bootstrap refuses to adopt a non-empty unknown directory and commits the initial tree. Existing content repos receive the workflow only when it is absent; the app never overwrites a locally maintained version. T7.2 adds CI without changing build semantics.
**Done when:** bootstrap is idempotent; the generated repo builds via only `python -m venv`, `pip install -r requirements.txt`, and `mkdocs build --strict`; the workflow is available both as the rendered page and raw static `/llm.md`; draft output and draft search records are absent; malformed draft metadata fails clearly; and no app/database import is reachable from the hook.

#### T3.3 — Write lock & optimistic concurrency
`opus` / `sol` · **L** · **max** · depends: T3.1, T2.3
Repository-scoped inter-process lock around validation → mutation → exact staging → commit, with a bounded acquisition timeout. Save requests carry both path and base blob SHA; re-check both after acquiring the lock. Snapshot affected paths/index state and roll back on any pre-commit failure. Committed history is never reset to conceal an error.
**Done when:** concurrent saves from separate processes produce one commit plus one conflict; unrelated dirty state is preserved; injected write/stage/commit failures restore affected files and index; and no request can wait forever.

#### T3.4 — Page history API
`sonnet` / `terra` · **M** · **high** · depends: T3.1, T2.3
Routes for per-page history list, diff between revisions, and restore-to-revision (restore = a new commit, never a rewrite).
**Done when:** a restored page's content matches the chosen revision and history shows the restore as a new commit.

---

### Phase 4 — Access control

#### T4.1 — ACL resolution engine
`opus` / `sol` · **M** · **max** · depends: T1.1, T2.1
`app/acl.py`: given a user and validated `docs/`-relative path, resolve read/write. A prefix matches whole path segments only. Across all memberships, select only rules at the greatest matching segment depth; at that depth, explicit deny wins over allow for each capability. `can_write=true` requires `can_read=true` at validation time. Admins bypass; inactive users never do; default deny. Ancestor containers are visible only when needed to reach a readable descendant, without granting access to their page bodies. Keep the resolver pure and return an explanation object for admin diagnostics without exposing it to unauthorized callers.
**Done when:** a truth table covers inherited allow, more-specific allow/deny, equal-specificity cross-group conflict, sibling-prefix confusion (`chapter` vs `chapter-old`), write/read invariants, ancestor visibility, inactive users, default deny, and admin bypass.
> Security-critical: every other module trusts this answer.

#### T4.2 — ACL enforcement dependencies
`opus` / `sol` · **L** · **max** · depends: T4.1, T2.3
Central authorization service plus FastAPI dependencies `require_read(path)` / `require_write(path)` wired into **every** content, search, history, asset, render, export, and AI path. Service-layer methods require an authorization context too, so internal transports cannot bypass route dependencies. Tree listings filter unreadable nodes; unreadable paths return the same 404 shape/timing class as missing paths. Create checks the destination parent and refuses a path carrying an orphaned exact rule; delete checks the target; move/slug-rename checks source and destination and is admin-only in the MVP because it changes path-based access. Delete/move/slug-rename is blocked while any exact or descendant permission rule targets the affected subtree; an admin must deliberately remove/recreate those grants first, and destination rules then determine access. This avoids pretending SQLite and git can form one atomic transaction.
**Done when:** route/service coverage tests fail for unguarded reads or writes; missing/unreadable responses are indistinguishable at the contract level; and structural authorization cases cannot move content into or out of unauthorized trees, strand reusable stale grants, or partially coordinate database and git state.

#### T4.3 — Admin API & permission management
`opus` / `sol` · **L** · **high** · depends: T4.1, T1.2
CRUD for users, groups, memberships, per-path grants, and admin-set password resets (which increment `session_generation`); normalize and validate prefixes through `app/paths.py`; reject grants to missing/unsupported targets; report orphaned rules caused by out-of-band filesystem edits and let admins remove them; guard against removing/deactivating/demoting the last active admin; emit an audit log to normal application logs without secrets, password-reset values, or content bodies (not a new database table).
**Done when:** grants immediately change a second user's view; malformed/stale prefixes are rejected or safely repaired; equal-specificity conflicts are explained; password resets invalidate existing sessions as designed; and concurrent requests cannot remove the last active admin.

---

### Phase 5 — Rendering & web UI

#### T5.1 — Markdown renderer
`opus` / `sol` · **M** · **high** · depends: T3.2
`app/render.py`: use MkDocs/Python-Markdown configuration loading rather than hand-parsing only `markdown_extensions`; render the supported Markdown semantics, rewrite links/assets in context, then sanitize with an explicit allowlist because content is user-supplied. Document that the app preview is semantically aligned but not theme/HTML-byte-identical to the final site.
**Done when:** admonitions, fenced code, tables, relative links, and assets behave consistently in preview and build; unsupported plugins fail clearly; and active HTML/unsafe URLs cannot execute.

#### T5.2 — Base layout & tree browser
`sonnet` / `terra` · **L** · **high** · depends: T4.2, T5.1
Jinja2 base template, sidebar tree (ACL-filtered), breadcrumbs, page view. No SPA framework.
**Done when:** two users with different grants see different trees on the same instance.

#### T5.3 — Editor & save flow **[P]**
`sonnet` / `terra` · **L** · **high** · depends: T5.2, T3.3
EasyMDE editor, live preview via `render`, save posting the base SHA for conflict detection, create/rename/move/delete UI, and a **draft toggle** that sets `draft: true` in front matter, with a visible draft badge on the page and in the tree so nobody mistakes an unpublished page for a live one.
**Done when:** an edit saves, commits, and re-renders; a stale save shows a conflict screen instead of overwriting; toggling draft is reflected in the badge and keeps the page out of the next build.

#### T5.4 — History UI **[P]**
`sonnet` / `terra` · **M** · **medium** · depends: T3.4, T5.2
Revision list, side-by-side diff, restore button with confirmation.

#### T5.5 — Admin UI
`sonnet` / `terra` · **L** · **high** · depends: T4.3, T5.2, T1.3, T6.3, T7.1
Screens for users, groups, memberships, permission grants, issue/revoke-all API tokens, and backup/export actions. Token UI states plainly that tokens are short-lived, shown once, and revocation affects all tokens for that user.

---

### Phase 6 — GitHub backup

#### T6.1 — Remote & credential handling
`opus` / `sol` · **M** · **high** · depends: T3.1, T0.2
Configure and validate `origin`; support a least-privilege deploy key or PAT from environment/secret files without embedding credentials in the remote URL or process arguments. Pin/verify SSH host keys where SSH is used. Never log, echo, render, or persist a credential; scrub surfaced git errors.
**Done when:** auth and non-fast-forward failures are distinguishable and useful without credential material; the configured remote is verified private for MVP; and no code path can force-push.

#### T6.2 — Debounced push worker
`opus` / `sol` · **L** · **high** · depends: T6.1, T3.3
Background task coalescing rapid saves into a periodic push; retry transient failures with bounded exponential backoff and jitter; never block a save on network I/O. Derive durable pending state from local-vs-upstream refs, so startup resumes an unpushed branch without a queue table. Serialize with the repository lock and stop retrying non-fast-forward/auth/configuration errors until admin action. Surface ahead count, last success, and sanitized failure in the admin UI.
**Done when:** ten rapid saves produce ten commits but fewer pushes; restart/offline periods recover automatically; divergence never triggers merge/force; and worker/admin git operations cannot race content commits.

#### T6.3 — Manual backup & restore **[P]**
`opus` / `sol` · **L** · **high** · depends: T6.1
"Back up now" (push) and guarded restore. Clone only into a validated absent/empty destination; permit fast-forward only from a clean checkout. For dirty/divergent state, first copy the entire local repo (including `.git`) to a timestamped recovery directory outside the target, verify that copy, show the divergence, and require a second explicit confirmation before any replacement. Never use force-push or destructive reset.
**Done when:** empty and fast-forward restores work; dirty/divergent restores cannot proceed without a verified recovery copy and confirmation; invalid remotes cannot escape the configured destination; and interrupted replacement leaves either the old or restored repo recoverable.

---

### Phase 7 — Static export

Static export is a full non-draft recovery copy and has no per-user ACL. The app must display this warning before download actions. Public deployment is out of MVP scope.

#### T7.1 — Build/export runner
`sonnet` / `terra` · **M** · **high** · depends: T3.2
`app/export.py`: run the exact configured mkdocs executable with `build --strict` using argument arrays, a fixed working directory, a clean/minimal environment, timeout, and output cap; never shell-interpolate input. Build into a fresh temporary directory and atomically replace the last successful export. Do not include `gh-deploy` in MVP.
**Done when:** export produces the full non-draft `site/`; a failed/timed-out build preserves the previous successful export and reports a sanitized useful error; drafts are absent from HTML and the search index; and only admins can trigger/download it after acknowledging the no-ACL warning.

#### T7.2 — Content-repo GitHub Action **[P]**
`sonnet` / `terra` · **S** · **medium** · depends: T3.2
The workflow committed *inside the content repo* that installs `requirements.txt` and runs `mkdocs build --strict` on every push. It validates only and does not publish to Pages by default; artifacts use short retention and remain private.
**Done when:** a push builds with no app/database reference, a draft is absent from output/search, and the workflow cannot accidentally make the artifact public.

---

### Phase 8 — Search

#### T8.1 — Search core
`opus` / `sol` · **L** · **high** · depends: T2.3, T4.1
`app/search.py`: fixed-string search by default over Markdown bodies and front-matter titles/tags; bound query length, result count, file size, runtime, and snippet size. Use ripgrep through argument arrays when available with a behaviorally equivalent pure-Python fallback. Discover candidate paths, authorize each path **before reading content or producing snippets/counts**, and paginate only the filtered set. Escape highlights at the final HTML boundary.
**Done when:** a term appearing only in an unreadable page yields no result, count, timing-dependent snippet, or error leak; fallback and ripgrep return the same ordered contract; pathological input/files respect limits; and no query is interpreted as a regex or command option.

#### T8.2 — Search API & UI **[P]**
`sonnet` / `terra` · **M** · **low** · depends: T8.1, T5.2
Search box, results page with snippets and breadcrumbs.

---

### Phase 9 — AI integration

#### T9.1 — Shared AI service layer
`opus` / `sol` · **L** · **high** · depends: T8.1, T4.2, T2.3
`app/ai_service.py`: one permission-aware implementation of search, tree/list, get/download page, filtered export, create book, create chapter, and create page. Return structured results with deterministic item/character limits (do not depend on a model tokenizer). Treat wiki text as untrusted data, not tool instructions. Book/chapter creation is admin-only; page creation requires write access on the parent. Both transports call only this service and its ACL-aware content/search modules.
**Done when:** direct service contract tests prove read/export and create operations apply the same ACL and limits expected by both transports, including missing/unreadable equivalence and Git author attribution.

#### T9.2 — MCP server (Claude) **[P]**
`opus` / `sol` · **L** · **high** · depends: T9.1, T1.3
MCP server exposing search/list/get/download and create-book/chapter/page tools over a documented transport, authenticated by the signed bearer token from T1.3 so calls run as an active user with current permissions. Validate origin/transport security as applicable; expose bounded schemas and neutral tool descriptions.
**Done when:** a supported MCP client reads and creates only authorized content; expired/revoked tokens fail; oversized/malformed calls are bounded; and wiki content cannot alter tool authorization or response envelopes.

#### T9.3 — REST + OpenAPI surface (ChatGPT) **[P]**
`sonnet` / `terra` · **M** · **high** · depends: T9.1, T1.3
`/api/ai/*` endpoints with a provider-neutral OpenAPI schema for ACL-filtered tree/page/ZIP downloads and create-book/chapter/page operations; signed bearer-token auth, request/response limits, and rate limiting. Keep the REST contract provider-neutral even if a ChatGPT Action is the first client.
**Done when:** the generated OpenAPI validates against the target action client; unauthenticated/expired/revoked calls fail; response limits are enforced; create operations produce one correctly authored Git commit; and REST/MCP authorization results match.

---

### Phase 10 — Testing, CI, docs

#### T10.1 — ACL & path-safety test suites
`opus` / `sol` · **L** · **high** · depends: T4.2, T2.1
Consolidate the task-level ACL/path tests into exhaustive security regression suites, including segment-aware matching, conflicting equal-depth rules, inactive users, ancestor visibility, Unicode/case behavior, URL decoding, symlinks, and route/service authorization coverage. Add property-based tests where they improve boundary coverage.

#### T10.2 — Content round-trip integration test **[P]**
`sonnet` / `terra` · **L** · **high** · depends: T2.3, T3.2, T4.2
Create book → chapter → page via the API, assert exact on-disk/front-matter/nav/git layout, then run `mkdocs build --strict`. Include title edit, reorder, move, delete, failed-operation rollback, and an unrelated dirty file.

#### T10.3 — Worst-case drill script **[P]**
`sonnet` / `terra` · **M** · **high** · depends: T3.2
`scripts/worstcase_drill.sh`: copy only `content/` (including its dependency manifest and hooks, excluding any existing build output) to a temporary directory, create a clean venv, install only `content/requirements.txt`, run `mkdocs build --strict`, and assert a seeded draft is absent from both generated HTML and the search index. The script must not import the app or access its database. **This is the project's defining guarantee and runs in CI.**

#### T10.4 — Backup round-trip test **[P]**
`opus` / `sol` · **L** · **high** · depends: T6.3
Push to a local bare scratch remote, remove the disposable local checkout, restore, and assert identical refs/history/tree. Separately exercise dirty/divergent refusal, verified recovery-copy behavior, interrupted replacement, and credential redaction without depending on a real GitHub account.

#### T10.5 — App CI workflow **[P]**
`sonnet` / `terra` · **M** · **medium** · depends: T0.1, T10.3
GitHub Action for the app repo: locked dependency install, ruff, tests with coverage, migration check, package build, and the worst-case drill. Pin third-party actions to immutable commit SHAs and grant minimum token permissions.

#### T10.6 — Operator documentation **[P]**
`sonnet` / `terra` · **M** · **low** · depends: most of the above
Install/deploy/upgrade guide; secret rotation; private backup and guarded restore runbook; precise permission semantics; static export's lack of ACL; token revocation tradeoff; and the "my app died, how do I get my wiki back" recovery procedure. State that recovery restores non-draft content/history, not users or permissions unless `data/app.db` is separately backed up securely.

---

## Dispatch guidance

- **Critical path:** T0 → T1.1/T2.1/T2.2/T2.4/T3.1 → T2.3 → T3.3 → T4.1 → T4.2 → T5.1 → T5.2. T1.4 waits for T3.2.
- **Do not parallelize** T2.1, T2.3, T4.1, T4.2, or T3.3 with each other — they define the contracts every other task builds on, and racing them produces incompatible interfaces.
- **Good parallel batches:** (T0.1, T0.2) · (T2.1, T2.2, T2.4, T3.1) · (T5.3, T5.4) · (T10.2, T10.3, T10.4, T10.5, T10.6). Only dispatch a batch after shared interfaces from its dependencies are committed.
- Frontier-model (`opus`) tasks are concentrated in ACL, path safety, untrusted uploads/rendering, concurrency, Git/backup correctness, search isolation, and AI transports — areas where a plausible-looking wrong implementation can silently leak content, lose data, or weaken security. Don't downgrade those to save budget.
- Every subagent must read [AGENTS.md](../AGENTS.md) first: content never in the database, the content tree stays mkdocs-buildable at all times, git is the revision history, and every change gets a `LOG.md` entry plus a commit and push.

## Verification

- **Unit:** precise ACL truth table; path/encoding/symlink rejection; front-matter and `.pages` round trips including unknown keys; token expiry/revocation; search limits and filtering.
- **Integration:** content lifecycle through the API produces the documented filesystem/nav/git layout, preserves unrelated dirty files, rolls back injected failures, and passes `mkdocs build --strict`.
- **Worst-case drill (the defining test):** copy only `content/` — no app or database — to a clean environment, install its own requirements, build strictly, and confirm the full non-draft site renders with no draft search records. Runs in CI on every push.
- **Permissions:** two users in different groups each see and edit only their granted chapters/pages; unreadable paths 404 rather than 403.
- **Static-boundary:** export/build artifacts contain every non-draft page regardless of ACL, are private by default, and cannot be mistaken for an authenticated per-user site.
- **Backup round-trip:** push to a bare test remote, restore a disposable checkout, confirm identical refs/history/files, and prove dirty/divergent state is preserved rather than overwritten.
- **Concurrency:** simultaneous cross-process saves yield one commit and one conflict, never a lost update, deadlock, unrelated staging, or wedged index.

## Settled decisions

No open questions remain. Decisions made during planning, recorded so they
aren't relitigated mid-implementation:

| Decision | Choice | Rationale |
|---|---|---|
| Backend | Python / FastAPI | Reuses MkDocs/Python-Markdown configuration and invokes `mkdocs build` instead of adopting an unrelated renderer. |
| Content storage | Markdown files in a git repo | The whole point: a working static site must be recoverable from the content folder alone. |
| Revision history | Git commits | No revisions table; `git log`/`diff`/`checkout` replace it, and deletes are recoverable in place of a recycle bin. |
| Database scope | Four tables: users, groups, memberships, permissions | No content, revision, token, or search rows. Signed API tokens use a generation field on the user for revoke-all. |
| Permissions | Group → segment-aware path rules; greatest specificity, deny wins ties | Deterministic across multiple groups; default deny; write implies read. Path moves are admin-only in MVP because location defines access. |
| Auth | Local passwords only | No SSO/LDAP, but kept behind an `authenticate()` seam. |
| Shelves | Not built — books at `docs/` root | Adds a level nobody asked for; addable later as a folder move with no migration. |
| Drafts | `draft: true` excluded from the build | Via a `hooks/drafts.py` inside the content repo, so exclusion survives the worst-case drill. |
| Static output | Private full-wiki recovery/export artifact | MkDocs cannot reproduce database ACLs; every non-draft page is included. Public deployment is not implemented in MVP. |
| Nav tooling | `mkdocs-awesome-nav` v3 with `filename: .pages` | Uses the maintained successor while retaining the repo's small `.pages` convention. |
| Search | Grep, no app index | Nothing to keep in sync or rebuild; mkdocs supplies a separate search index inside static exports. |
| AI access | Read/export and create operations through one `ai_service` behind MCP and REST | Both transports inherit the same ACL and Git mutation path; book/chapter creation is admin-only and page creation requires parent write access. |
