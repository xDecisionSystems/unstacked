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
- **History and backup = git, not a revisions table.** Every save is a
  commit; a GitHub remote on the content repo serves as backup, and a
  GitHub Action rebuilds the static site on every push.
- **Database = users/groups/permissions only.** Groups are granted
  read/write access to specific chapters/pages via path-based rules.
- **AI-ready search.** Search and page-read are exposed through a shared
  module reused by the web app, an MCP server (Claude), and a REST/OpenAPI
  surface (ChatGPT) — all filtered by the same permissions.
- **Static recovery is not authenticated.** A mkdocs export contains every
  non-draft page, so content remotes and build artifacts stay private and
  public deployment is outside the MVP.

## Status

The first API slice is implemented. Authenticated AI clients can list and
download permitted Markdown, download an ACL-filtered ZIP, and create books,
chapters, and pages. Books and chapters require an admin token; page creation
requires write access to its parent book/chapter. Each mutation is committed
to the nested content Git repository as the authenticated user.

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
uv run unstacked-bootstrap --email admin@example.com --display-name "Admin"
uv run uvicorn --factory app.main:create_app
```

The bootstrap command prompts for a password and prints the initial expiring
API token once. Clients can subsequently exchange the local password at
`POST /api/auth/token`. Automation can pass `--password-stdin` to read the
initial password from standard input; passwords are never accepted as command
line arguments. Re-running bootstrap leaves existing users unchanged.

## Local Docker deployment

Docker Compose runs the API with two named volumes: `data` holds the SQLite
database and lock, while `content` holds the independent Git/MkDocs content
repository. Generate a production signing secret, then start it with:

```bash
export UNSTACKED_API_TOKEN_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose -f docker-compose.yaml up --build -d
curl http://127.0.0.1:8001/healthz
docker compose -f docker-compose.yaml exec app python -m app.bootstrap \
  --email admin@example.com --display-name "Admin"
```

The bootstrap command prompts for the initial password inside the container.
The Compose configuration uses production mode, so it refuses to start without
the signing secret. Do not use `docker compose -f docker-compose.yaml down -v`
unless you intend to delete both the database and wiki content volumes.

The same `Dockerfile` is suitable for a Coolify Dockerfile deployment. Mount
persistent storage at `/app/data` and `/app/content`, expose the container
port `8000`, set
the production variables above, and configure one application replica. The
current app does not yet push the nested content repository to GitHub, so back
up both Coolify volumes independently.

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

Interactive request/response schemas are available at `/docs` while the app
is running.

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
python -m app.bootstrap --email you@example.com --display-name "Admin"
```

This prints an initial API token once. Re-running it on a later deploy is
safe — it leaves existing users untouched.

### Backing up the wiki

Right now the content Git repository's only copy is inside the `content`
volume — the automated push-to-GitHub backup described in
[plans/plan_initial.md](plans/plan_initial.md) (Phase 6) isn't built yet.
Until then, back up that volume the same way you'd back up any other
Coolify persistent volume, or periodically shell in and `git push` the
`content/` repo to a remote yourself.

### What's actually live right now

Only the REST/AI content API (`/api/ai/*`, `/healthz`, `/llm.md`, `/docs`)
is implemented — there is no browsable web UI yet (that's Phase 5 of the
plan). Deploying today gets you a working, permission-checked API server,
not a point-and-click wiki.

## License

GPLv3 — see [LICENSE](LICENSE).
