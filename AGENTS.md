# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, etc.) working in this repo.

## What this project is

`unstacked` is a file-based alternative to BookStack. The core idea: wiki
**content** (books/chapters/pages) lives as plain markdown files in a git
repo, laid out exactly the way [mkdocs](https://www.mkdocs.org/) expects
(`docs/` + `mkdocs.yml`). Only **users, groups, and permissions** live in a
real database (SQLite). See [plans/plan_initial.md](plans/plan_initial.md)
for the full architecture and phased implementation plan — read it before
making structural changes, and keep it up to date as decisions evolve.

## Non-negotiable design rules

These exist to preserve the project's whole reason for being (a working
static site must always be recoverable from the content folder alone) —
don't work around them without checking with the user first.

- **Content never goes in the database.** Books/chapters/pages are folders
  and `.md` files under `content/docs/`, never rows. The database only
  holds `users`, `groups`, `user_groups`, and `permissions`.
- **The content tree must stay a valid, buildable mkdocs project at all
  times.** Any change to books/chapters/pages must leave `mkdocs build`
  working from `content/` alone, with no app code or database involved.
  Use `.pages` files (`mkdocs-awesome-nav` v3 configured with
  `filename: .pages`) for nav/ordering, not a hand-maintained `nav:` in
  `mkdocs.yml`.
- **Git is the revision history — don't add a revisions table.** Every
  content save is one git commit in the `content/` repo, authored as the
  editing user. Page history = `git log`/`git diff`/`git checkout` on that
  path.
- **`content/` is its own git repository**, independent of this app's
  source repo, with its own GitHub remote used for backup. Never merge its
  history into the app repo's history.
- **Permissions are path-prefix based**, not tied to content rows (there
  are none). A `permissions` row maps `(group, path_prefix) -> read/write`;
  matching is segment-aware, greatest specificity wins, and explicit deny
  wins equal-specificity ties; `is_admin` bypasses checks. Every content
  route must enforce this — don't add a route that reads/writes files
  without going through the ACL check.
- **No dedicated search index.** Search is grep-style over the filesystem,
  filtered by the same permission check as everything else. Don't
  introduce a search database/index unless the user asks.
- **AI-facing read/write (Claude MCP, REST/OpenAPI) reuses the same
  content/search/acl modules** as the web app — it's a new transport, not
  new logic or a permission bypass. Book/chapter creation is admin-only;
  page creation requires write access on the parent path.

## Layout (see the plan for the authoritative version)

```
unstacked/
  app/            # FastAPI app: auth, content, acl, git_backend, nav,
                   #   render, search, export, ai_mcp, ai_api, templates/
  content/        # nested mkdocs git repo (docs/ + mkdocs.yml) — gitignored
                   #   from this repo, managed via GitPython
  data/           # app.db (SQLite: users/groups/permissions only)
  tests/
  plans/          # planning docs, e.g. plan_initial.md
```

## Working conventions

- Stack: Python, FastAPI, SQLModel/SQLAlchemy (SQLite), GitPython,
  `python-frontmatter`, mkdocs + `mkdocs-awesome-nav` (configured to retain
  the `.pages` filename convention).
- Front matter on every page (`id`, `title`, `created_at`, `updated_at`,
  `author`, `tags`, `draft`) is app metadata only — mkdocs ignores it.
  Don't repurpose it for anything mkdocs needs to read.
- Development setup: `uv sync --extra dev`.
- Lint: `uv run ruff check .`.
- Tests (including a real strict MkDocs build): `uv run pytest`.

## Commit and push after every change

This repo is configured for autonomous commits: after every change you make
here (docs or code), commit and push it — don't leave work uncommitted or
batch it up across turns.

- Stage only the files relevant to the change you just made (avoid broad
  `git add -A`); check `git status`/`git diff` first and never commit
  anything that looks like a secret or credential.
- Write a real commit message describing *why* the change was made, not
  just what changed.
- Commit, then `git push origin main` immediately — don't wait for
  additional changes to batch together.
- This applies to the app repo. The nested `content/` mkdocs repo (once it
  exists) is separate — its own commit/push behavior is on save, as
  described in the plan, not tied to app-repo changes.
- This standing authorization covers routine commit-and-push to `main` in
  this repo only. It does not cover force-pushes, history rewrites, or
  pushing to any other remote/branch — those still need explicit sign-off.

## Log every change in LOG.md

[LOG.md](LOG.md) exists so Claude Code and Codex can see what the *other*
agent did, even if no commit was made yet. After every change you make in
this repo (docs or code):

- Add a new entry to the **top** of `LOG.md` (newest first), with:
  - An ISO-ish timestamp — run `date -u "+%Y-%m-%d %H:%M UTC"`, don't guess
    or reuse a prior entry's time.
  - Which agent made the change: `Claude Code` or `Codex`.
  - A short description of *what* changed and *why*.
  - A `Files:` line listing the files touched.
- Keep only the most recent **15** entries. When adding a new entry would
  make 16, delete the oldest (bottom-most) entry — regardless of how long
  any entry is. Never trim by shortening entries instead of removing the
  oldest one.
- Log the change even if you are not committing it yet (e.g. mid-task,
  work in progress) — `LOG.md` is how the other agent finds out about
  uncommitted work in the working tree.
- This is separate from git commit messages: commit messages describe one
  commit; `LOG.md` is a shared, capped-length changelog both agents read
  and write to stay in sync with each other.

## Verifying changes

Run `uv run ruff check .` and `uv run pytest`. The test suite includes a real
`mkdocs build --strict` against API-created content and verifies that drafts
are absent from HTML and the static search index. For broader content-layer
changes, also run the standalone "worst case" drill described in the plan
once that script is implemented. Don't consider a content-layer change done
unless the strict build still passes.
