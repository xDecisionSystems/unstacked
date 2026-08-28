# Unstacked: file-based BookStack alternative

## Context

`unstacked` is "a markdown version of BookStack." BookStack stores everything — books, chapters, pages, revisions — in MySQL. This project flips that: page **content** and its structure/history live as plain markdown files in a git repo, organized exactly the way mkdocs expects (`docs/` + `mkdocs.yml`), so that in a worst-case failure the content repo alone carries everything needed to create a clean mkdocs environment and build a working static site. A small SQL database is kept, but only for things that are inherently relational and security-sensitive: users, groups, and access-control rules. **Everything lives on local disk; the app has no required external dependency.** Off-site backup is optional and pluggable — pushing the content repo's git history to a remote (GitHub or any other git host) is one built-in way to do it, not a requirement; syncing the `content/`/`data/` directories via `rsync`, `aws s3 sync`, or any other out-of-band mechanism the operator already trusts works exactly as well and needs nothing from the app.

Confirmed scope (from user):
- Backend: **Python/FastAPI** (lets the app reuse MkDocs/Python-Markdown configuration and invoke `mkdocs build`, instead of adopting an unrelated rendering stack).
- Deployment shape: **single team, one wiki instance**. Users and group membership are managed in the webapp. **Groups** are granted **read/write access at the chapter and page level**.
- Search: no dedicated search index — grep-style filesystem search plus mkdocs' own generated static search.
- Planned from day one: **AI read and write integration for Claude, ChatGPT, and other agents**, so search/download and create-book/chapter/page operations use clean, permission-aware service and API/MCP surfaces rather than transport-specific logic.
- Auth: **local passwords only** — no SSO/LDAP. Keep the auth layer behind a small `authenticate(email, password) -> user` seam anyway, so adding an external provider later is a new backend rather than a rewrite of every route.
- Static output: the built mkdocs site has **no runtime ACL**. It is a recovery/export artifact containing every non-draft page, not a permission-preserving replacement for the app. Any configured backup destination and build artifacts are private; public deployment is outside MVP scope.
- Runtime deployment: package the FastAPI application in a Docker image for
  Coolify (or any Docker host) deployments. The single application replica
  receives persistent mounts for both `/app/data` (SQLite/lock) and
  `/app/content` (the nested Git repository); neither directory may be
  replaced on deploy. Nothing about running the app requires GitHub or any
  other external service — those volumes are the durable state, full stop.
- Backup: **optional and pluggable, never required.** The app is fully
  functional with zero backup destination configured. Phase 6 exists purely
  to reduce an operator's disaster-recovery risk, and a git-remote push
  (already built, works against GitHub or any other git host) is one
  interchangeable way to do that — `rsync` to another host or `aws s3 sync`
  to a bucket are equally valid and need no app support beyond the
  already-durable local directories to sync from.

### Implementation checkpoint (2026-08-27, updated)

The backend is substantially complete: scaffolding, schema/migrations, both auth transports (bearer tokens and cookie sessions, username-based login, forced password change on admin-issued credentials), path safety, the full content CRUD lifecycle (create/read/update/delete/move/rename, all through one locked git-mutation path), optimistic concurrency (blob-sha conflict detection), the ACL resolver plus its central enforcement (`AuthorizationContext`), the admin API (users/groups/grants/last-admin protection), pluggable/optional backup (runtime-editable git-remote target, debounced sync worker, manual backup/restore), static export, grep-based search, and the shared AI service behind the REST/OpenAPI surface. Real `mkdocs build --strict` runs are exercised in tests throughout, including after full lifecycle sequences (create → edit → move → rename → delete).

Remaining: the web UI (T5.5, including the browser form for the completed backup-config backend), search's own UI (T8.2), the MCP transport (T9.2), a few partial-completion notes (T1.3/T2.1/T9.3/T10.1), and documentation polish (T10.6).

Per-task status is tracked with `[x]`/`[~]` markers below; a `[~]` task names what already exists so nobody rebuilds it.

**Coordination note.** Two independent agents (this session and Codex) built equivalent implementations of T3.3, T4.2, T6.2, and T7.1 concurrently, on the same repository, unaware of each other — Codex's versions landed first and are what's in the tree; a subagent dispatched from this session for T3.3 and T7.1 did real, independently-verified-correct work that turned out to be entirely redundant and was discarded rather than merged. T4.3 was *not* duplicated and was merged after reconciling it against schema/API drift (a new `username` field, `AuthorizationContext`) introduced by Codex's other work in the meantime. Lesson for future dispatch: check `git log origin/main` for very recent activity before starting a task already believed unclaimed, especially after a long-running subagent wave.

**Review pass (2026-08-27).** A review of that slice found and fixed:
- The API token signing secret defaulted to a shared constant and was only validated in `production`, so a default-environment deployment let anyone forge an admin token. There is now no default: development generates a private persisted secret, production refuses to start without one, and known placeholders are rejected everywhere.
- `commit_paths` committed the whole index, so anything an operator had staged was swept into the next user's commit under their name. The index is now reset to HEAD before staging.
- `log()` used `rev-list`, which cannot follow renames; it now uses `git log --follow`, so history survives the slug renames T2.3 will add.
- History, diff and restore required the file to exist, making deleted pages unrecoverable through the API and contradicting "git replaces the recycle bin". They now operate on the path's history.
- The draft hook treated CRLF files as having no front matter and published them.
- Pages could be created below the two-level limit, where they would build into the static site but never appear in the tree.
- Login throttling trusted the socket peer (one shared bucket behind any proxy) and grew an unbounded key table.

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
- **Local storage is the whole story by default.** `content/` and `data/` on disk are durable, complete, and sufficient on their own — nothing about running the app requires a network call or an external account. Everything below this line is optional disaster-recovery insurance, not a dependency.
- **Backup target = pluggable, not GitHub-specific.** One built-in target is a git remote: this repo has an optional **private-by-default** remote (GitHub, GitLab, a self-hosted git host — the code has no GitHub-specific dependency, only GitHub-flavored naming from when it was written). The app pushes after saves (debounced) and via a manual "Back up now" admin action, using a deploy key or PAT. Pushes are never forced and the app never auto-merges remote divergence. **This target is entirely optional** — if no remote is configured, the app runs exactly the same way, just without off-site copies.
- A git remote is not the only valid target. `rsync`-ing `content/` (and `data/`, for the user/permission database) to another host, or `aws s3 sync`-ing them to a bucket, are equally valid and arguably simpler for an operator who doesn't want a GitHub account in the loop — they need no application code at all, just a cron job or the platform's own volume-backup feature (e.g. Coolify's). The debounced-sync-worker contract in T6.2 is written generically enough that a second target implementation (S3, rsync) could sit next to the git-remote one later, but building that second implementation is not required for MVP.
- "Restore from [git remote]" clones only into an absent/empty destination or fast-forwards a clean checkout. Divergent or dirty local state is first preserved to a timestamped recovery directory and requires an explicit admin choice; restore never silently replaces unpushed commits. (An rsync/S3 restore is just as valid and is entirely outside the app — copy the files back and start the app pointed at them.)
- Worst-case fallback: a GitHub Action *template* in the content repo installs `requirements.txt` and runs `mkdocs build --strict` on every push, so if a git remote happens to be GitHub, the content repo alone — no app or database — regenerates the full non-draft static site on push. This is a convenience for that one specific target, not part of the core recovery guarantee: the worst-case drill (T10.3) only requires the `content/` directory itself to build standalone, regardless of where or whether it's backed up.

### Concurrency

The app is a single wiki instance but may have multiple server processes. Use a repository-scoped **inter-process file lock** around each complete mutation (validate → atomic file changes → stage exact paths → commit); all web, worker, bootstrap, restore, and admin git operations take the same lock. A failed mutation restores the original files and leaves the index clean. Editing uses optimistic concurrency: the editor carries the blob SHA it loaded, and a save whose path or base SHA no longer matches is rejected with a conflict view rather than silently overwriting.

### Database — users, groups, permissions only

SQLite (SQLModel/SQLAlchemy):
- `users` (id, username, email, password hash, display name, is_admin, is_active, must_change_password, session_generation, api_token_generation)
- `groups` (id, name, description)
- `user_groups` (user_id, group_id)
- `permissions` (group_id, path_prefix, can_read, can_write) — `path_prefix` is a normalized, segment-aware relative path under `docs/`; raw string prefix matching is forbidden. Resolution semantics are defined under T4.1.

No content, revisions, API-token records, or search index live in the database. AI clients use expiring signed bearer tokens containing user ID, token generation, issued-at, expiry, audience, and a unique token ID. Incrementing `users.api_token_generation` revokes all outstanding API tokens for that user; deactivating the user rejects them immediately. This deliberately trades per-token naming/revocation for the repo's strict four-table database boundary.

### First administrator credentials

The initial account is always created as **`admin` / `admin`** (username and
password). It is an administrator, has `must_change_password=true`, and is the
only account bootstrap creates. The first successful password login may create
only a password-change session: every other authenticated route, including API
token issuance and AI/content operations, rejects that session until the
password is changed. The change-password operation must validate the current
password, set a compliant replacement, clear `must_change_password`, revoke
the temporary session and any outstanding API tokens, and issue a fresh normal
session. This is enforced server-side, not merely as a UI redirect. Re-running
bootstrap never recreates or resets the account; an administrator uses the
ordinary reset process if this initial credential is lost.

### App modules (FastAPI)

| Module | Responsibility |
|---|---|
| `config` | Settings (paths, secrets, optional backup-remote creds) via pydantic-settings |
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

**Status markers.** `[x]` every acceptance criterion is met and tested. `[~]`
code exists and is used in production paths but at least one criterion is
unmet — read the task's "Remaining" note before picking it up, and check the
named module before writing anything new. No marker means nothing is built.

---

### Phase 0 — Scaffolding

#### [x] T0.1 — Project scaffolding **[P]**
`sonnet` / `terra` · **S** · **medium** · depends: —
`pyproject.toml` with a supported Python floor and bounded direct dependencies (FastAPI, uvicorn, SQLModel/SQLAlchemy, Alembic, GitPython, python-frontmatter, python-slugify, `pwdlib[argon2]`, itsdangerous, Jinja2, filelock, mkdocs, mkdocs-material, mkdocs-awesome-nav, HTML sanitizer, pytest, ruff); a reproducible lock file; `.gitignore` (must ignore `content/`, `data/`, `site/`, `.venv`); lint config; empty `app/` and `tests/` packages; README dev setup.
**Done when:** a clean locked install succeeds, `ruff check` passes, and dependency versions used by app CI and the generated content-repo `requirements.txt` are intentionally compatible.

#### [x] T0.2 — Config module **[P]**
`sonnet` / `terra` · **S** · **medium** · depends: —
`app/config.py` using pydantic-settings: `content_repo_path`, `db_path`, `session_secret`, API-token signing secret/audience/TTL, git remote/auth settings, `site_output_path`, upload/search limits, and `debug`. Load from env + ignored `.env`; include a redacted `.env.example`. Paths are resolved and validated once at startup. Production secrets have no insecure defaults and must be distinct where separation matters.
**Done when:** development settings import with explicit safe dev values, production startup rejects missing/placeholder secrets, and no secret is committed, logged, placed in a command line, or rendered.

---

### Phase 1 — Data layer & auth

#### [x] T1.1 — Database schema
`sonnet` / `terra` · **M** · **high** · depends: T0.1, T0.2
`app/models.py`: SQLModel definitions for the four tables above; engine/session factory; SQLite foreign-key enforcement and appropriate unique/index/check constraints. `users.username` is unique and suitable for the initial `admin` login; `must_change_password` is non-null and defaults false. Add Alembic from the first schema rather than relying on `create_all()` after bootstrap.
**Done when:** migrations upgrade a fresh DB to head, foreign-key cascades and uniqueness constraints behave as specified, tests can insert a user, group, membership, and normalized permission, and migration coverage proves the initial-password flag and unique username survive upgrades.

#### [x] T1.2 — Password auth & sessions
`opus` / `sol` · **M** · **high** · depends: T1.1
`app/auth.py`: Argon2 password hashing via `pwdlib`, login/logout routes, signed session cookies containing only minimal identifiers and the current `session_generation` (HttpOnly + SameSite + Secure-in-prod), `current_user` dependency, CSRF tokens for every cookie-authenticated state change, generic/timing-resistant login failures, and bounded login rate limiting. Authenticate by unique username (with email retained for account administration); rotate the session on login/logout; increment the generation on password/admin security reset; and reject inactive users on every request. **Local passwords only** — no SSO/LDAP — but keep credential checking behind `authenticate(username, password) -> User | None`.
When `must_change_password` is true, issue a restricted session that can access only logout and the CSRF-protected current-password-verified change endpoint; block bearer-token issuance and every other authenticated route/service dependency until it clears the flag. A successful forced change revokes that restricted session and outstanding API tokens, then issues a new normal session.
**Done when:** login/logout work end to end; fixation and tampered/expired cookies are rejected; unsafe form requests without valid CSRF are rejected; inactive users lose access; first use of `admin:admin` is forced through a server-enforced password change with no content/API access; and no route reads the password hash outside `authenticate()`.

#### [x] T1.3 — API token auth
`opus` / `sol` · **M** · **high** · depends: T1.1, T1.2
Issue short-lived signed bearer tokens with `sub`, `iat`, `exp`, `aud`, `jti`, and the user's current `api_token_generation`; verify an explicit algorithm and audience, then resolve the active user so machine clients inherit current group permissions. Admin/user revocation increments the generation and revokes all of that user's issued tokens. Keep tokens out of storage and logs, and document the lack of per-token revocation.
**Done when:** a valid token authenticates as its active user; expired, wrong-audience, wrong-generation, tampered, and deactivated-user tokens fail; revocation invalidates all prior tokens; and raw tokens are never persisted or logged.

#### [x] T1.4 — First-run bootstrap CLI
`sonnet` / `terra` · **M** · **medium** · depends: T1.1, T3.2
`python -m app.bootstrap` — initialize the DB and (via T3.2) the content repo, then create the first administrator as `admin:admin` with `must_change_password=true`. It must be idempotent: bootstrap never resets, recreates, or prints the default password after the initial account exists. Do not accept passwords in process arguments.
**Done when:** a clean checkout reaches a buildable content repo and the restricted `admin:admin` first-login flow in one command, rerunning cannot create a second accidental bootstrap admin, and the first login must replace the default password before accessing the application.

---

### Phase 2 — Content engine

#### [~] T2.1 — Path safety & slugs
`opus` / `sol` · **S** · **high** · depends: T0.1, T0.2
`app/paths.py`: slugify titles; canonicalize URL paths exactly once; reject double encoding; and provide a `safe_join(docs_root, *parts)` that resolves the existing nearest parent and **rejects anything escaping `docs/`**, including symlink escapes and case-fold collisions on case-insensitive filesystems. Handle reserved/internal names (`assets`, `.pages`, dotfiles), bounded lengths, collisions, null bytes, separators, Windows-reserved names, and Unicode normalization. Every filesystem module uses typed validated relative paths from here, never raw request strings.
**Done when:** an adversarial cross-platform suite covers traversal, encoding, symlink races/escapes, reserved names, collisions, and Unicode normalization without rejecting ordinary international titles.
**Remaining:** Descriptor-confined read and no-clobber create helpers now protect page reads/creation from symlink races, alongside canonical form, traversal/symlink escape, reserved/Windows device names, and NFKC normalization. Remaining: update/move/delete/nav lifecycle operations still need a transaction-wide descriptor-based I/O refactor before this task can be complete.
> Security-critical: this is the single control preventing arbitrary filesystem read/write in a file-backed app.

#### [x] T2.2 — Front-matter I/O **[P]**
`sonnet` / `terra` · **S** · **medium** · depends: T0.1
`app/frontmatter_io.py`: read/write page files via `python-frontmatter`; schema for `id`/`title`/`created_at`/`updated_at`/`author`/`tags`/`draft`; tolerate missing/malformed front matter (hand-written or pasted-in files must not crash the app); preserve unknown keys on round-trip.
**Done when:** round-trip tests preserve every field including unknown keys, and a file with no front matter still loads with sane defaults.

#### [x] T2.3 — Content repository
`opus` / `sol` · **L** · **high** · depends: T2.1, T2.2, T2.4, T3.1
`app/content.py`: the core tree API — list/get/create/update/delete/move/rename for books, chapters, and pages (no shelves; books live at the `docs/` root); tree walker producing the nav model; slug rename via the git wrapper so history follows the file; title change updates front matter *and* `.pages` without moving the file (URLs stay stable); enforce the two-level depth limit. All page writes use same-directory temporary files plus atomic replace. Each logical operation declares every affected content/nav/asset path and is committed once through the locked git mutation API; direct ad-hoc filesystem writes are forbidden.
**Done when:** every successful operation leaves a clean index and a tree that `mkdocs build --strict` accepts; injected failures restore the pre-operation bytes; and rename preserves `git log --follow` history.
**Note:** `update_page`/`set_page_title`/`set_container_title`/`delete_page`/`delete_chapter`/`delete_book`/`move_page`/`rename_book`/`rename_chapter` are implemented on `ContentRepository`, each via the shared `_Rollback` snapshot/undo helper and one `GitBackend.commit_paths` call. Fixed a real latent bug in the process: `commit_paths` assumed plain `git add` stages deletions — it doesn't (GitPython raises `FileNotFoundError`); it now partitions declared paths into present/absent and stages absent ones via `index.remove(..., ignore_unmatch=True)`. No route/service wiring yet — that's T4.2 (ACL-guarded mutation endpoints) and T9.1/T9.3 (AI transport surface); exposing these methods unguarded would violate the ACL-everywhere rule.

#### [x] T2.4 — Nav (`.pages`) management
`sonnet` / `terra` · **M** · **medium** · depends: T0.1, T2.1
`app/nav.py`: parse and write awesome-nav v3 `.pages` files; explicit ordering and display titles; preserve unknown supported keys; reject malformed files without clobbering them; remove stale entries on delete. Writes are atomic and are orchestrated by T2.3 rather than committed independently.
**Done when:** reorder changes only `.pages`; operator-added supported keys survive round trips; malformed YAML remains untouched with an actionable error; and `mkdocs build --strict` reflects the order.

#### [x] T2.5 — Assets & uploads
`opus` / `sol` · **M** · **high** · depends: T2.1, T2.3
Image/attachment upload into `docs/assets/<book>/`, request and decompressed-size caps, signature-based type detection, a conservative allowlist, filename sanitizing via `app/paths.py`, and markdown-relative links that resolve in a static build. Disallow active content such as HTML/SVG by default; serve downloads with `nosniff` and safe disposition headers.
**Done when:** an uploaded image renders in-app and in the static build; hostile names and polyglot/spoofed files fail safely; oversized uploads are rejected before exhausting memory/disk; and upload/asset routes obey ACL.
**Note:** PNG, JPEG, GIF, and WebP uploads are detected and structurally
validated from their bytes, bounded by request bytes and declared dimensions,
stored under the owning book, committed through the shared locked content
path, and served with re-detected media types, `nosniff`, safe inline
disposition, and the book's ACL. A raw ASGI guard rejects declared oversize
requests before FastAPI parses multipart data and cuts off undeclared or
understated streams as they cross the cap. Independent review added rejection
of metadata-only image containers and fixed book deletion/rename so assets do
not remain published or stranded under a stale ACL namespace; relative links
inside renamed books migrate with them. Verified with 357 passing tests,
strict standalone MkDocs coverage, and a healthy production Compose build.

---

### Phase 3 — Git backend

#### [x] T3.1 — Git wrapper
`opus` / `sol` · **M** · **high** · depends: T0.1, T0.2
`app/git_backend.py`: GitPython wrapper — exact-path staging and `commit_as(user, paths, message)`, `log(path)`, `diff(sha_a, sha_b, path)`, `show(sha, path)`, restore-as-a-new-commit, `push()`, and guarded fetch/fast-forward. Validate SHAs/ref names and paths; never invoke a shell with interpolated input; never stage unrelated working-tree changes; scrub credentials and local sensitive paths from typed errors.
**Done when:** two users produce distinct authors; history follows a rename; restore adds a commit; unrelated dirty files remain untouched; and adversarial refs/paths cannot become command options or escape the repo.
**Fixed post-hoc (2026-08-27):** `commit_paths` assumed a plain `git add` on a missing path stages its deletion — GitPython actually raises `FileNotFoundError`. Discovered while building T2.3, since every delete/rename calls `commit_paths` with an already-removed source path. Now partitions paths into present/absent and stages absent ones via `index.remove(..., ignore_unmatch=True)`.

#### [x] T3.2 — Content repo bootstrap
`sonnet` / `terra` · **M** · **medium** · depends: T3.1
Initialize `content/` if absent: `git init` with an explicit initial branch; operator-owned `mkdocs.yml` enabling `search` and `awesome-nav` configured with `filename: .pages`; `requirements.txt` with exact build dependency versions; `hooks/drafts.py`; starter `docs/index.md`; a managed provider-neutral `docs/llm.md` workflow; root `docs/.pages`; and `.gitignore` (ignore `site/`). Bootstrap refuses to adopt a non-empty unknown directory and commits the initial tree. Existing content repos receive the workflow only when it is absent; the app never overwrites a locally maintained version. T7.2 adds CI without changing build semantics.
**Done when:** bootstrap is idempotent; the generated repo builds via only `python -m venv`, `pip install -r requirements.txt`, and `mkdocs build --strict`; the workflow is available both as the rendered page and raw static `/llm.md`; draft output and draft search records are absent; malformed draft metadata fails clearly; and no app/database import is reachable from the hook.

#### [x] T3.3 — Write lock & optimistic concurrency
`opus` / `sol` · **L** · **max** · depends: T3.1, T2.3
Repository-scoped inter-process lock around validation → mutation → exact staging → commit, with a bounded acquisition timeout. Save requests carry both path and base blob SHA; re-check both after acquiring the lock. Snapshot affected paths/index state and roll back on any pre-commit failure. Committed history is never reset to conceal an error.
**Done when:** concurrent saves from separate processes produce one commit plus one conflict; unrelated dirty state is preserved; injected write/stage/commit failures restore affected files and index; and no request can wait forever.

#### [x] T3.4 — Page history API
`sonnet` / `terra` · **M** · **high** · depends: T3.1, T2.3
Routes for per-page history list, diff between revisions, and restore-to-revision (restore = a new commit, never a rewrite).
**Done when:** a restored page's content matches the chosen revision and history shows the restore as a new commit.

---

### Phase 4 — Access control

#### [x] T4.1 — ACL resolution engine
`opus` / `sol` · **M** · **max** · depends: T1.1, T2.1
`app/acl.py`: given a user and validated `docs/`-relative path, resolve read/write. A prefix matches whole path segments only. Across all memberships, select only rules at the greatest matching segment depth; at that depth, explicit deny wins over allow for each capability. `can_write=true` requires `can_read=true` at validation time. Admins bypass; inactive users never do; default deny. Ancestor containers are visible only when needed to reach a readable descendant, without granting access to their page bodies. Keep the resolver pure and return an explanation object for admin diagnostics without exposing it to unauthorized callers.
**Done when:** a truth table covers inherited allow, more-specific allow/deny, equal-specificity cross-group conflict, sibling-prefix confusion (`chapter` vs `chapter-old`), write/read invariants, ancestor visibility, inactive users, default deny, and admin bypass.
> Security-critical: every other module trusts this answer.

#### [x] T4.2 — ACL enforcement dependencies
`opus` / `sol` · **L** · **max** · depends: T4.1, T2.3
Central authorization service plus FastAPI dependencies `require_read(path)` / `require_write(path)` wired into **every** content, search, history, asset, render, export, and AI path. Service-layer methods require an authorization context too, so internal transports cannot bypass route dependencies. Tree listings filter unreadable nodes; unreadable paths return the same 404 shape/timing class as missing paths. Create checks the destination parent and refuses a path carrying an orphaned exact rule; delete checks the target; move/slug-rename checks source and destination and is admin-only in the MVP because it changes path-based access. Delete/move/slug-rename is blocked while any exact or descendant permission rule targets the affected subtree; an admin must deliberately remove/recreate those grants first, and destination rules then determine access. This avoids pretending SQLite and git can form one atomic transaction.
**Done when:** route/service coverage tests fail for unguarded reads or writes; missing/unreadable responses are indistinguishable at the contract level; and structural authorization cases cannot move content into or out of unauthorized trees, strand reusable stale grants, or partially coordinate database and git state.

#### [x] T4.3 — Admin API & permission management
`opus` / `sol` · **L** · **high** · depends: T4.1, T1.2
CRUD for users, groups, memberships, per-path grants, and admin-set password resets (which increment `session_generation`); normalize and validate prefixes through `app/paths.py`; reject grants to missing/unsupported targets; report orphaned rules caused by out-of-band filesystem edits and let admins remove them; guard against removing/deactivating/demoting the last active admin; emit an audit log to normal application logs without secrets, password-reset values, or content bodies (not a new database table).
**Done when:** grants immediately change a second user's view; malformed/stale prefixes are rejected or safely repaired; equal-specificity conflicts are explained; password resets invalidate existing sessions as designed; and concurrent requests cannot remove the last active admin.
**Note:** `app/admin_api.py` (`/api/admin/*`). Last-admin protection is a single `UPDATE/DELETE ... WHERE <no other active admin exists>` statement evaluated under SQLite's write lock — not a check-then-write pair, which was verified to actually lose the race before being replaced. Admin-created/reset passwords set `must_change_password=True`, matching bootstrap's own admin account. Both transports (bearer and cookie) are supported via one `get_admin_actor` helper, which returns 403 for a non-admin directly rather than routing through T4.2's `AuthorizationContext.require_admin()` (that raises `AccessDenied`, which content routes map to 404 — correct there, wrong here, since a non-admin hitting an admin route should see 403, not a fake-not-found). Orphaned-grant reporting cross-references `Permission` rows against the live content tree read-only; nothing is auto-deleted.

---

### Phase 5 — Rendering & web UI

#### [x] T5.1 — Markdown renderer
`opus` / `sol` · **M** · **high** · depends: T3.2
`app/render.py`: use MkDocs/Python-Markdown configuration loading rather than hand-parsing only `markdown_extensions`; render the supported Markdown semantics, rewrite links/assets in context, then sanitize with an explicit allowlist because content is user-supplied. Document that the app preview is semantically aligned but not theme/HTML-byte-identical to the final site.
**Done when:** admonitions, fenced code, tables, relative links, and assets behave consistently in preview and build; unsupported plugins fail clearly; and active HTML/unsafe URLs cannot execute.

#### [x] T5.2 — Base layout & tree browser
`sonnet` / `terra` · **L** · **high** · depends: T4.2, T5.1
Jinja2 base template, sidebar tree (ACL-filtered), breadcrumbs, page view, and
login page. No SPA framework. The root route (`/`) redirects an unauthenticated
visitor to the login page; an authenticated user lands on their ACL-filtered
tree. A user in the mandatory first-password-change state is routed only to
that change-password flow.
**Done when:** an unauthenticated `/` request redirects to login, a
first-password-change session cannot reach the tree, and two users with
different grants see different trees on the same instance.
**Note:** `app/web.py` + `app/templates/`. The `/auth/*` JSON routes in `app/web_auth.py` are reused directly (not reimplemented) — the browser-form login/logout/change-password handlers call those functions as plain Python with a `RedirectResponse` standing in for the `Response` they set the cookie on, so credential verification, CSRF, and cookie issuance stay in one place. Verified independently, not just via the report: constructed a book/page with a hostile title (`<script>…`) and confirmed Jinja2 autoescaping renders it inert in both the sidebar and the breadcrumb (only the pre-sanitized page `body` uses `|safe`); confirmed a logout POST without a CSRF token is genuinely rejected (403) and the session survives. `/pages/{path}` returns 404 identically for "doesn't exist" and "can't read it".

#### [x] T5.3 — Editor & save flow
`sonnet` / `terra` · **L** · **high** · depends: T5.2, T3.3
EasyMDE editor, live preview via `render`, save posting the base SHA for conflict detection, create/rename/move/delete UI, and a **draft toggle** that sets `draft: true` in front matter, with a visible draft badge on the page and in the tree so nobody mistakes an unpublished page for a live one.
**Done when:** an edit saves, commits, and re-renders; a stale save shows a conflict screen instead of overwriting; toggling draft is reflected in the badge and keeps the page out of the next build.
**Note:** Browser routes in `app/web.py` use the existing `AIContentService` mutation methods, preserving ACL checks, Git commits, and optimistic blob-SHA conflict detection. EasyMDE uses the server's `MarkdownRenderer` preview route; create, move/slug rename, delete, and admin-only book/chapter management are server-rendered forms with CSRF protection. Drafts visibly badge both the page and tree. Focused web tests: 32 passing; ruff clean; production Compose healthy on port 18054.

#### [x] T5.4 — History UI
`sonnet` / `terra` · **M** · **medium** · depends: T3.4, T5.2
Revision list, side-by-side diff, restore button with confirmation.
**Note:** `/pages/{path}/history` is ACL-filtered through `AIContentService`; it compares selected Git revisions using escaped `HtmlDiff` output and renders restore controls only for writers. Restoring creates a new Git commit and works even after a page was deleted. Browser history tests: 18 passing; API/Git history tests: 47 passing; clean ruff; production Compose healthy on port 18055.

#### T5.5 — Admin UI
`sonnet` / `terra` · **L** · **high** · depends: T4.3, T5.2, T1.3, T6.3, T6.4, T7.1
Screens for users, groups, memberships, permission grants, issue/revoke-all API tokens, a **backup setup page** (configure/test/clear the backup target and trigger a manual backup — see T6.4, which owns the persistence and re-configuration logic this page calls), and export actions. Token UI states plainly that tokens are short-lived, shown once, and revocation affects all tokens for that user; the backup setup page carries the same "never rendered back" guarantee for a saved credential.

---

### Phase 6 — Backup & disaster recovery (optional)

Nothing in this phase is required for the app to run. `content/` and `data/`
on local disk are the complete, durable state; everything here exists only to
give an operator who wants off-site insurance a way to get it, and a git
remote is one interchangeable way among several (rsync, S3 sync, a platform's
own volume-backup feature) — the only one with application code behind it so
far, because it's the one that also doubles as the worst-case static-site
fallback (T3.2/T10.3) when that remote happens to be a git host with CI.

#### [x] T6.1 — Git-remote backup target (one implementation, not a requirement)
`opus` / `sol` · **M** · **high** · depends: T3.1, T0.2
Configure and validate an optional `origin`; support a least-privilege deploy key or PAT from environment/secret files without embedding credentials in the remote URL or process arguments. Pin/verify SSH host keys where SSH is used. Never log, echo, render, or persist a credential; scrub surfaced git errors. Configuring no remote at all is a fully supported, fully functional state — this step is skipped entirely when `github_remote_url` is unset.
**Done when:** auth and non-fast-forward failures are distinguishable and useful without credential material; the configured remote is verified private for MVP; and no code path can force-push.
**Note:** `GitBackend.configure_remote(RemoteConfig)` wires `origin` from settings, called once from `ContentRepository.initialize()`, and is a no-op when no remote URL is configured. HTTPS uses a generated repo-local credential helper (`.git/unstacked-credential-helper`, mode 0600) so the token reaches git only through the credential protocol — never the URL, `.git/config`, or a process argument; SSH pins the host key via a repo-local `core.sshCommand` and refuses an unpinned host. Verified independently, not just via the subagent's tests: configured a real repo with a fake token file and confirmed by hand that `.git/config` and `git remote -v` never contain the value, the helper file is owner-only, and `git credential fill` retrieves the token correctly through the real git credential protocol.
"Verified private" is implemented as an explicit operator affirmation (`UNSTACKED_GITHUB_REMOTE_CONFIRMED_PRIVATE`) rather than a live GitHub API check — this repo has no way to test a real network call, and nothing else in the codebase makes one either. **Coverage gaps that need a real GitHub account to close:** SSH host-key pinning enforcement against actual github.com (the *configuration* is tested; OpenSSH's enforcement is not), an authenticated HTTPS push to a real private repo, and an actual privacy check (candidate for T6.3, which already expects network access).
Despite GitHub-flavored settings names (`github_remote_url`, `github_token`, …), the implementation works against any git host reachable over https/ssh — nothing in `configure_remote` is GitHub-specific. Renaming those settings to generic `backup_remote_*` names is a reasonable future cleanup but not required; not doing it now to avoid unrelated churn.

#### [x] T6.2 — Debounced backup-sync worker
`opus` / `sol` · **L** · **high** · depends: T6.1, T3.3
Background task coalescing rapid saves into a periodic sync to whichever backup target is configured (today: git-remote push via T6.1); retry transient failures with bounded exponential backoff and jitter; never block a save on network I/O. For the git-remote target, derive durable pending state from local-vs-upstream refs, so startup resumes an unpushed branch without a queue table. Serialize with the repository lock and stop retrying non-fast-forward/auth/configuration errors until admin action. Surface ahead count, last success, and sanitized failure in the admin UI. Do nothing at all — no background task, no admin-UI status — when no backup target is configured; this must never be on the startup-required path.
**Done when:** ten rapid saves produce ten commits but fewer pushes; restart/offline periods recover automatically; divergence never triggers merge/force; worker/admin git operations cannot race content commits; and the app starts and runs normally with no backup target configured at all.

#### [x] T6.3 — Manual backup & restore **[P]**
`opus` / `sol` · **L** · **high** · depends: T6.1
"Back up now" (sync to whichever target is configured — today, git-remote push) and guarded restore. For the git-remote target: clone only into a validated absent/empty destination; permit fast-forward only from a clean checkout. For dirty/divergent state, first copy the entire local repo (including `.git`) to a timestamped recovery directory outside the target, verify that copy, show the divergence, and require a second explicit confirmation before any replacement. Never use force-push or destructive reset. An operator relying on rsync/S3 instead needs no admin-UI support here at all — restoring is copying files back and pointing the app at them, entirely outside this task.
**Done when:** empty and fast-forward restores work; dirty/divergent restores cannot proceed without a verified recovery copy and confirmation; invalid remotes cannot escape the configured destination; interrupted replacement leaves either the old or restored repo recoverable; and none of this is reachable or required when no backup target is configured.

#### [x] T6.4 — Backup setup page & runtime-editable configuration
`opus` / `sol` · **M** · **high** · depends: T6.1, T4.3
Today the backup target is env-var-only, wired once at startup via `ContentRepository.initialize()` → `GitBackend.configure_remote`. An operator wants a page to set this up rather than editing `.env`/Coolify env vars and redeploying — so this task makes it admin-UI-configurable at runtime:
- Persist target configuration to a local file under `data/` (e.g. `data/backup_config.json`), following the same file-based-secret precedent already used for `api_token_secret_path` — **not** a new table, so the settled "four tables" database-scope decision stays intact. The stored record is target-typed (`type: "git-remote" | ...`) so a future S3/rsync implementation is another variant of the same record, not a redesign.
- Admin-only read/update routes. Reading back the config **never** re-renders a saved token or key — same "shown once" precedent as the API-token screen — it shows target type, URL, and status only. Saving a new configuration re-runs `configure_remote` immediately (so a bad credential or unreachable host is caught the moment it's saved, not at the next restart) and only persists on success.
- The admin UI page itself (folded into T5.5, not a separate screen): current status (configured / not configured, target type, last successful sync from T6.2, last sanitized error), a form to set/change the git-remote target (URL, the "confirmed private" affirmation checkbox, token *or* deploy-key-path + known-hosts-path), a "Back up now" button (T6.3), and a "Clear configuration" action that returns the app to the fully-supported "no backup target" state.
**Backend done when:** an admin configures, tests, and clears a git-remote
target through the admin API with no env edit or redeploy; a credential is
never rendered back; and a failed update leaves the exact previous working
configuration (or no configuration) in effect. The browser form remains part
of T5.5, which consumes this completed backend.
**Note:** The target-typed record and any app-managed token live owner-only
under `data/`, with a persisted `none` tombstone that outranks stale
environment settings after clear. Save validates local URL/credential shape,
then runs `git ls-remote` plus a non-mutating dry-run push to prove reachability,
authentication, write permission, and fast-forward compatibility before
persistence. Git config, helper bytes, managed-token bytes, and environment
state are transactionally restored on failure. Runtime activation/deactivation
uses the application lifespan; a broken persisted credential never prevents
the optional-backup-free app from starting. Verified with 370 passing tests,
58 focused backup/Git tests, clean ruff, and healthy production Compose.

---

### Phase 7 — Static export

Static export is a full non-draft recovery copy and has no per-user ACL. The app must display this warning before download actions. Public deployment is out of MVP scope.

#### [x] T7.1 — Build/export runner
`sonnet` / `terra` · **M** · **high** · depends: T3.2
`app/export.py`: run the exact configured mkdocs executable with `build --strict` using argument arrays, a fixed working directory, a clean/minimal environment, timeout, and output cap; never shell-interpolate input. Build into a fresh temporary directory and atomically replace the last successful export. Do not include `gh-deploy` in MVP.
**Done when:** export produces the full non-draft `site/`; a failed/timed-out build preserves the previous successful export and reports a sanitized useful error; drafts are absent from HTML and the search index; and only admins can trigger/download it after acknowledging the no-ACL warning.

#### [x] T7.2 — Content-repo GitHub Action **[P]**
`sonnet` / `terra` · **S** · **medium** · depends: T3.2
The workflow committed *inside the content repo* that installs `requirements.txt` and runs `mkdocs build --strict` on every push. It validates only and does not publish to Pages by default; artifacts use short retention and remain private.
**Done when:** a push builds with no app/database reference, a draft is absent from output/search, and the workflow cannot accidentally make the artifact public.

---

### Phase 8 — Search

#### [x] T8.1 — Search core
`opus` / `sol` · **L** · **high** · depends: T2.3, T4.1
`app/search.py`: fixed-string search by default over Markdown bodies and front-matter titles/tags; bound query length, result count, file size, runtime, and snippet size. Use ripgrep through argument arrays when available with a behaviorally equivalent pure-Python fallback. Discover candidate paths, authorize each path **before reading content or producing snippets/counts**, and paginate only the filtered set. Escape highlights at the final HTML boundary.
**Done when:** a term appearing only in an unreadable page yields no result, count, timing-dependent snippet, or error leak; fallback and ripgrep return the same ordered contract; pathological input/files respect limits; and no query is interpreted as a regex or command option.

#### T8.2 — Search API & UI **[P]**
`sonnet` / `terra` · **M** · **low** · depends: T8.1, T5.2
Search box, results page with snippets and breadcrumbs.

---

### Phase 9 — AI integration

#### [x] T9.1 — Shared AI service layer
`opus` / `sol` · **L** · **high** · depends: T8.1, T4.2, T2.3
`app/ai_service.py`: one permission-aware implementation of search, tree/list, get/download page, filtered export, create book, create chapter, and create page. Return structured results with deterministic item/character limits (do not depend on a model tokenizer). Treat wiki text as untrusted data, not tool instructions. Book/chapter creation is admin-only; page creation requires write access on the parent. Both transports call only this service and its ACL-aware content/search modules.
**Done when:** direct service contract tests prove read/export and create operations apply the same ACL and limits expected by both transports, including missing/unreadable equivalence and Git author attribution.

#### T9.2 — MCP server (Claude) **[P]**
`opus` / `sol` · **L** · **high** · depends: T9.1, T1.3
MCP server exposing search/list/get/download and create-book/chapter/page tools over a documented transport, authenticated by the signed bearer token from T1.3 so calls run as an active user with current permissions. Validate origin/transport security as applicable; expose bounded schemas and neutral tool descriptions.
**Done when:** a supported MCP client reads and creates only authorized content; expired/revoked tokens fail; oversized/malformed calls are bounded; and wiki content cannot alter tool authorization or response envelopes.

#### [~] T9.3 — REST + OpenAPI surface (ChatGPT) **[P]**
`sonnet` / `terra` · **M** · **high** · depends: T9.1, T1.3
`/api/ai/*` endpoints with a provider-neutral OpenAPI schema for ACL-filtered tree/page/ZIP downloads and create-book/chapter/page operations; signed bearer-token auth, request/response limits, and rate limiting. Keep the REST contract provider-neutral even if a ChatGPT Action is the first client.
**Done when:** the generated OpenAPI validates against the target action client; unauthenticated/expired/revoked calls fail; response limits are enforced; create operations produce one correctly authored Git commit; and REST/MCP authorization results match.
**Remaining:** `app/ai_api.py` exposes auth, tree, search, content, export, history, diff, restore and create endpoints with bearer auth. Remaining: response size limits, rate limiting beyond login, and OpenAPI validation against a real action client.

---

### Phase 10 — Testing, CI, docs

#### [~] T10.1 — ACL & path-safety test suites
`opus` / `sol` · **L** · **high** · depends: T4.2, T2.1
Consolidate the task-level ACL/path tests into exhaustive security regression suites, including segment-aware matching, conflicting equal-depth rules, inactive users, ancestor visibility, Unicode/case behavior, URL decoding, symlinks, and route/service authorization coverage. Add property-based tests where they improve boundary coverage.
**Remaining:** `tests/test_acl.py` (truth table), `tests/test_paths.py` (adversarial), and `tests/test_authorization_coverage.py` cover pure, route, and service boundaries. Remaining: property-based boundary tests.

#### [x] T10.2 — Content round-trip integration test **[P]**
`sonnet` / `terra` · **L** · **high** · depends: T2.3, T3.2, T4.2
Create book → chapter → page via the API, assert exact on-disk/front-matter/nav/git layout, then run `mkdocs build --strict`. Include title edit, reorder, move, delete, failed-operation rollback, and an unrelated dirty file.

#### [x] T10.3 — Worst-case drill script **[P]**
`sonnet` / `terra` · **M** · **high** · depends: T3.2
`scripts/worstcase_drill.sh`: copy only `content/` (including its dependency manifest and hooks, excluding any existing build output) to a temporary directory, create a clean venv, install only `content/requirements.txt`, run `mkdocs build --strict`, and assert a seeded draft is absent from both generated HTML and the search index. The script must not import the app or access its database. **This is the project's defining guarantee and runs in CI.**

#### [x] T10.4 — Backup round-trip test
`opus` / `sol` · **L** · **high** · depends: T6.3
Push to a local bare scratch remote, remove the disposable local checkout, restore, and assert identical refs/history/tree. Separately exercise dirty/divergent refusal, verified recovery-copy behavior, interrupted replacement, and credential redaction without depending on a real GitHub account.
**Note:** `tests/test_backup_roundtrip.py` covers the bare-remote round trip, guarded dirty/divergent recovery, simulated interrupted replacement rollback, and secret-redacted transport failure. Focused suite: 4 passing; backup/Git suite: 50 passing; ruff clean.

#### [x] T10.5 — App CI workflow **[P]**
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
| Backup | Optional and pluggable — not required to run the app | Local disk (`content/` + `data/`) is durable and complete on its own. A git remote (GitHub or any git host) is one built-in target; `rsync`/S3 sync are equally valid and need no app code. Zero backup targets configured is a fully supported, fully functional state. |
| Nav tooling | `mkdocs-awesome-nav` v3 with `filename: .pages` | Uses the maintained successor while retaining the repo's small `.pages` convention. |
| Search | Grep, no app index | Nothing to keep in sync or rebuild; mkdocs supplies a separate search index inside static exports. |
| AI access | Read/export and create operations through one `ai_service` behind MCP and REST | Both transports inherit the same ACL and Git mutation path; book/chapter creation is admin-only and page creation requires parent write access. |
