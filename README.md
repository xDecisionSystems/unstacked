# unstacked

A file-based alternative to [BookStack](https://www.bookstackapp.com/).

Instead of storing books/chapters/pages in a database, `unstacked` keeps
them as plain markdown files in a git repo, laid out exactly the way
[mkdocs](https://www.mkdocs.org/) expects. Worst case, if the app and its
database disappear entirely, the content repo carries its build dependency
manifest and can be built into a working static site on its own.

A small database is still used, but only for users, groups, and
permissions — never for content.

## Key ideas

- **Content = files, not rows.** Books → folders, chapters → subfolders,
  pages → `.md` files under `content/docs/`, with a real `mkdocs.yml` next
  to them.
- **History = git, not a revisions table.** Every save is a commit in the
  local content repository. Off-site backup is optional: a private git remote
  is built in, while volume snapshots, rsync, or S3 sync work independently.
- **Database = users/groups/permissions only.** Groups are granted
  read/write access to specific chapters/pages via path-based rules.
- **AI-ready API.** Search and page-read are exposed through a shared module
  reused by the web app and a bearer-authenticated REST/OpenAPI surface — all
  filtered by the same permissions.
- **Static recovery is not authenticated.** A mkdocs export contains every
  non-draft page, so content remotes and build artifacts stay private and
  public deployment is outside the MVP.

## Status

The application has a browser wiki for reading, editing, history/restore, and
basic administration, alongside the authenticated REST API. Every content
mutation is committed to the nested content Git repository as the acting user.
The browser administration screen is still being expanded; the API/OpenAPI
surface remains the complete operator interface for administration and backup
operations.

See [plans/plan_initial.md](plans/plan_initial.md) for the full architecture
and phased build plan, and [AGENTS.md](AGENTS.md) for contributor rules.

## Development setup

Python 3.10 or newer is required (the maintained navigation plugin requires
it). With `uv` installed:

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
```

Copy `.env.example` to `.env`, replace the API signing secret, then create the
initial admin and content repository:

```bash
uv run unstacked-bootstrap
uv run uvicorn --factory app.main:create_app
```

Bootstrap takes no arguments: it always creates exactly one initial
administrator, `admin` / `admin`, and forces a password change on first
login before that account can access content or issue an API token. Clients
subsequently exchange the (changed) password at `POST /api/auth/token`.
Re-running bootstrap is safe — if any user already exists, it leaves them
unchanged and does nothing.

## Local Docker deployment

Docker Compose runs the API with two named volumes: `data` holds the SQLite
database and lock, while `content` holds the independent Git/MkDocs content
repository. Generate a production signing secret, then start it with:

```bash
export UNSTACKED_API_TOKEN_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose -f docker-compose.yaml up --build -d
curl http://127.0.0.1:8001/healthz
docker compose -f docker-compose.yaml exec app python -m app.bootstrap
```

Bootstrap creates the one initial administrator as `admin:admin`. Its first
login is restricted to changing that default password; it cannot access content
or issue API tokens until the change succeeds.
The Compose configuration uses production mode, so it refuses to start without
the signing secret. Do not use `docker compose -f docker-compose.yaml down -v`
unless you intend to delete both the database and wiki content volumes.

The same `Dockerfile` is suitable for a Coolify Dockerfile deployment. Mount
persistent storage at `/app/data` and `/app/content`, expose container port
`8000`, set the production variables above, and configure one application
replica. Local disk remains complete application state. Optionally configure a
private git remote through the admin backup API, and independently snapshot
both volumes so the SQLite users/permissions database is protected too.

## Operating the service

### Upgrade and deploy

Keep both persistent directories before changing versions: `content/` is the
independent Git/MkDocs repository, and `data/` contains `app.db`, the content
lock, runtime backup configuration, and local secrets. For a source checkout,
fetch the intended revision, run `uv sync --extra dev`, then run `uv run ruff
check .` and `uv run pytest` before restarting the service. For Compose, pull
the intended source revision and use `docker compose -f docker-compose.yaml up
--build -d`; the application initializes its schema and content repository on
startup. Confirm `GET /healthz` before retiring the previous deployment.

Do not replace or discard persistent `content/` or `data/` as part of an
upgrade. Take a filesystem/platform snapshot first, and retain it until the
new instance is healthy. A Git remote is useful for content history, but it
does not contain the user and permission database.

### Rotate the signing secret

`UNSTACKED_API_TOKEN_SECRET` signs both API bearer tokens and browser sessions.
Generate a new random value of at least 32 bytes, update the production secret
in the deployment environment, and restart all application processes together.
For example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Rotation immediately invalidates existing browser sessions and bearer tokens;
users must sign in again and automation must obtain new tokens. Keep the old
secret only long enough to roll back a failed deployment, and never place it in
Git, a content remote, or an exported site. In development, when the variable
is unset, the application persists its generated secret at
`data/api_token_secret`; replacing or deleting that file has the same
invalidate-every-session-and-token effect.

### Permission model

Content permissions belong to groups and are path-prefix rules under `docs/`.
They are segment-aware: a rule for `handbook` matches `handbook/intro`, not
`handbook-old`. Access is default-deny. Among matching rules, the deepest path
wins; if several rules are equally specific, an explicit deny wins. Write is
never granted without read. Administrators bypass content ACLs, while inactive
accounts have no access.

Unreadable content is intentionally presented as missing rather than forbidden.
Navigation may show an ancestor only to reach a readable descendant; that does
not grant access to the ancestor's page. Create requires write access to its
parent; moving, renaming, and deleting content is additionally protected from
stranding exact or descendant permission rules, so an administrator must review
those grants first.

### API tokens and revocation

Bearer tokens are short-lived signed credentials; they are shown only when
issued and are not stored as token rows. A user can revoke all of their own
tokens, and an administrator can revoke all tokens for any user, through
`POST /api/auth/tokens/revoke`. This is intentionally account-wide revocation:
there is no per-token name, listing, or selective revocation. Password resets,
forced password changes, account deactivation, and signing-secret rotation also
invalidate affected credentials.

### Backup and guarded restore

Backup is optional. The built-in target is any **private** Git remote and
backs up the complete `content/` Git repository, including drafts and without
per-user ACL filtering. Configure it as an administrator with
`GET`/`PUT`/`DELETE /api/admin/backup/config`; saving validates remote access
with a remote listing and a dry-run push before persisting the setting. A
supplied inline token is stored in an owner-only file under `data/` and is not
returned by the API. A saved runtime setting takes precedence over environment
settings; clearing it writes a tombstone, so an old environment value does not
silently reactivate backup after restart.

Use `POST /api/admin/backup/now` for an immediate non-force push. To restore,
use `POST /api/admin/backup/restore`. An empty destination is cloned and a
clean checkout that is behind is fast-forwarded. If local content is dirty,
ahead, or divergent, the first call creates and verifies a complete recovery
copy outside the target and returns a one-time confirmation ID. Submit that ID
in a second restore request to replace the checkout. Restore never silently
overwrites local work and never force-pushes. Keep the recovery copy until the
restored instance has been checked.

### Exports and disaster recovery

`GET /api/ai/export` is an ACL-filtered ZIP for the authenticated caller.
This is different from a static MkDocs export: a static build contains every
non-draft page and has **no runtime ACL**. Treat static sites, build artifacts,
and content Git remotes as private; they are recovery artifacts, not a
permission-preserving web deployment.

If the application or database is lost, recover the wiki by restoring the
**entire** `content/` directory (not only `content/docs/`) and running its own
MkDocs build instructions. That restores non-draft content and Git history
without any application code. To restore users, groups, permissions, runtime
backup settings, and locally managed secrets, securely restore `data/` as well,
including `data/app.db`. If `data/` was not backed up, bootstrap a new admin
and recreate access control; do not assume the content Git remote contains it.

## AI content API

All `/api/ai/*` routes require `Authorization: Bearer <token>`.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/ai/tree` | List the ACL-filtered book/chapter/page tree. |
| `GET` | `/api/ai/content/{path}` | Return page metadata and Markdown; add `?download=true` for the raw `.md` file. |
| `GET` | `/api/ai/export` | Download an ACL-filtered ZIP of readable Markdown pages. |
| `POST` | `/api/ai/books` | Create a book (admin only). |
| `POST` | `/api/ai/books/{book}/chapters` | Create a chapter (admin only). |
| `POST` | `/api/ai/books/{book}/pages` | Create a page directly in a book. |
| `POST` | `/api/ai/books/{book}/chapters/{chapter}/pages` | Create a page in a chapter. |
| `POST` | `/api/ai/books/{book}/assets` | Upload one image (multipart `file`); requires write access to the book. |
| `GET` | `/api/ai/books/{book}/assets` | List the book's assets. |
| `DELETE` | `/api/ai/books/{book}/assets/{filename}` | Delete one asset. |
| `GET` | `/assets/{path}` | Serve one asset for the live app, `nosniff` and `inline`. |

Interactive request/response schemas are available at `/docs` while the app
is running.

### Assets

Uploads land in `content/docs/assets/<book>/` and are committed like any other
content change. What a file *is* comes from its own signature, never from its
name or declared `Content-Type`: only PNG, JPEG, GIF and WebP are accepted, and
each is parsed end to end, so a file with a second payload appended to it is
rejected rather than stored. SVG and every other scriptable or executable
format is refused by design. The submitted filename is slugified the same way a
page slug is, and the stored extension is rewritten to match the real format.

Reference an asset from Markdown with a **relative** link so the same page works
in the running app and in a standalone `mkdocs build`:

```markdown
![Logo](../assets/my-book/logo.png)          <!-- from a page in the book -->
![Logo](../../assets/my-book/logo.png)       <!-- from a page in a chapter -->
```

A static build serves the file straight from the built site; `/assets/{path}`
exists only for the live, permission-checked app, where an asset inherits the
ACL of the book that owns it.

## LLM workflow

The website serves a maintained [llm-md](https://llm.md/) workflow at
`/llm.md`. It documents the authenticated AI content API and safe operating
rules without embedding secrets or an ACL-bypassing content index. The same
file is committed as `content/docs/llm.md`, rendered by MkDocs, and copied to
the root of static builds so it remains available when the site is recovered
from the content repository alone.

## Deploying with Coolify

A `Dockerfile` and `docker-compose.yaml` are both provided; Coolify can use
either depending on which resource type you create.

**State that must be persisted.** The app's entire state is two directories
— `content/` (the Git-backed wiki) and `data/` (SQLite database, the
inter-process lock file, and a generated API token secret). Both must be
mounted as persistent volumes, never left on the container's writable layer,
or a redeploy wipes the wiki.

### Option A — Dockerfile resource

1. In Coolify, create a new **Application** from this GitHub repo, branch
   `main`, build pack **Dockerfile**.
2. Under **Storage**, add two persistent volumes:
   - container path `/app/content`
   - container path `/app/data`
3. Under **Environment Variables**, set at minimum:
   - `UNSTACKED_ENVIRONMENT=production`
   - `UNSTACKED_API_TOKEN_SECRET` — generate one with
     `python -c "import secrets; print(secrets.token_urlsafe(48))"`;
     production refuses to start without this set explicitly (see
     [app/config.py](app/config.py)).
   - `UNSTACKED_TRUSTED_PROXY_HOPS=1` — Coolify puts its own Traefik proxy in
     front of the app, so the login rate limiter needs to know to trust one
     hop of `X-Forwarded-For`, or every client will share one bucket.
   - Any other tuning from [.env.example](.env.example) you want to override.
4. Set the exposed port to `8000` and the health check path to `/healthz`.
   The Compose file maps host port `UNSTACKED_HOST_PORT` (default `8001`) to
   that internal port, so set `UNSTACKED_HOST_PORT` to an unused server port
   in Coolify when you need direct host-port access.
   (the `Dockerfile` already declares a `HEALTHCHECK` against it).
5. Deploy. `create_app()` runs the database migration and content-repo
   bootstrap automatically on startup — no separate init step is needed.

### Option B — Docker Compose resource

Point Coolify at `docker-compose.yaml` directly. It declares the same two
named volumes and reads its environment from Coolify's **Environment
Variables** UI (Coolify substitutes `${VAR}` at deploy time), so the same
variables from Option A step 3 apply — `UNSTACKED_API_TOKEN_SECRET` is
required and the compose file will refuse to deploy without it.

### First admin user (either option)

Bootstrap only creates users; it never runs automatically, since a fresh
deploy shouldn't silently create an admin account. After the first
successful deploy, use Coolify's container terminal to run it once:

```bash
python -m app.bootstrap
```

It takes no arguments and always creates exactly one administrator,
`admin` / `admin`, forced to change that password on first login. Re-running
it on a later deploy is safe — if any user already exists, it leaves them
untouched and does nothing.

### Backing up the wiki

Local `content/` and `data/` storage is sufficient to run the app; backup is
optional. The built-in target pushes the content repository to any private git
host. An administrator can configure, inspect, replace, or clear it at runtime
through `GET`/`PUT`/`DELETE /api/admin/backup/config`. Saving performs a
read-only remote listing and dry-run push before persistence, so unreachable
hosts, rejected credentials, and incompatible history fail immediately. A
supplied token is written to an owner-only file under `data/` and is never
returned by later reads. Once configured, `POST /api/admin/backup/now` triggers
a manual push and the debounced worker handles later content commits.

The browser administration screen can configure, test, clear, and manually
push the target. The authenticated admin API/OpenAPI page remains available
for automation and guarded restore. A saved runtime record wins over the
initial environment variables; clearing writes a tombstone so a stale variable
cannot silently turn backup back on after restart.

A git target protects content history, not `data/app.db`. Snapshot both
persistent volumes through Coolify—or use rsync/S3 or another trusted external
backup mechanism—when users, groups, and permissions also need off-site
recovery.

### What's actually live right now

The application provides a permission-checked browser wiki (`/`), login,
editor, page history/restore, and an administrator console (`/admin`), in
addition to `/api/ai/*`, `/healthz`, `/llm.md`, and `/docs`. Some management
and export controls continue to be completed in the web interface; use the
documented authenticated API when a browser control is not yet present.

## License

GPLv3 — see [LICENSE](LICENSE).
