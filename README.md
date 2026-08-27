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

## License

GPLv3 — see [LICENSE](LICENSE).
