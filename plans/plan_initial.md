# Unstacked: file-based BookStack alternative

## Context

`unstacked` (currently just a README/LICENSE) is meant to be "a markdown version of BookStack." BookStack normally stores everything — books, chapters, pages, revisions — in MySQL. The goal here is to flip that: page **content** and its structure/history live as plain markdown files in a git repo, organized exactly the way mkdocs expects (`docs/` + `mkdocs.yml`), so that in a worst-case failure the content folder alone can be dropped into any mkdocs install and built into a working static site. A small SQL database is kept, but only for things that are inherently relational and security-sensitive: users, groups, and access-control rules. Content is backed up by pushing its git history to a GitHub remote.

Confirmed scope (from user):
- Backend: **Python/FastAPI** (lets the app reuse mkdocs' own markdown-extension pipeline and shell out to `mkdocs build`, instead of reimplementing rendering).
- Deployment shape: **single team, one wiki instance**. Users and group membership are managed in the webapp. **Groups** are granted **read/write access at the chapter and page level**.
- Search: no dedicated search index needed — grep-style filesystem search plus mkdocs' own generated static search is sufficient.
- Future requirement to plan for now: **AI search integration for Claude and ChatGPT** (so the search/read path needs to be exposed as a clean, permission-aware API/MCP surface from day one, not bolted on later).

## Architecture

### Content layout (the "mkdocs project")

A dedicated git repository, independent of the app's own source code repo, e.g. `content/`:

```
content/
  mkdocs.yml
  docs/
    <shelf-slug>/                 # optional grouping layer (a Shelf)
      .pages                      # mkdocs-awesome-pages: title + nav order for the shelf
      <book-slug>/
        .pages
        <chapter-slug>/
          .pages
          <page-slug>.md
          images/...
        <page-slug>.md            # pages directly in a book, no chapter
  <book-slug>/                    # books not in any shelf live at docs/ root
    ...
```

- Book → folder, Chapter → subfolder, Page → `.md` file. Shelves are just an optional top folder grouping several Books — this stays copy-paste-compatible with plain mkdocs.
- Use the `mkdocs-awesome-pages-plugin` (`.pages` files) for nav titles/ordering instead of hand-maintaining `nav:` in `mkdocs.yml`. This means the app never has to rewrite a giant nav tree — it just writes/renames folders and small `.pages` files, and `mkdocs build` picks it up automatically. This is still a static, human-readable file, so the "copy folder into mkdocs" fallback still works untouched (worst case without the plugin installed: mkdocs falls back to alphabetical nav, which still works — just less pretty).
- Every page file starts with YAML front matter for app-level metadata mkdocs itself ignores: `id` (uuid, stable across renames), `title`, `created_at`, `updated_at`, `author`, `tags`, `draft`. This keeps history/authorship out of the DB entirely.

### Version history — git, not a revisions table

- The content repo is a real git repo. Every save from the app = one commit, authored as the editing user (`git commit --author "name <email>"`). This *is* the page revision history: `git log -- path/to/page.md`, `git diff`, `git show`, `git checkout <sha> -- path` restore an old version. No `revisions` table needed.
- GitHub backup = this same repo has a GitHub remote (`origin`). The app pushes on save (debounced) and on a manual "Back up now" admin action, using a deploy key or PAT. A "Restore from GitHub" admin action re-clones/pulls if local content is ever lost.
- Worst-case fallback: a GitHub Action in the content repo (added as part of scaffolding) runs `mkdocs build` (optionally `mkdocs gh-deploy`) on every push, so the GitHub repo alone — with zero involvement from the FastAPI app or its database — always regenerates a working static site.

### Database — users, groups, permissions only

SQLite (via SQLModel/SQLAlchemy) with just:
- `users` (id, email, password hash, display name, is_admin)
- `groups` (id, name)
- `user_groups` (user_id, group_id)
- `permissions` (group_id, path_prefix, can_read, can_write) — `path_prefix` is a relative path under `docs/` (a chapter or a single page). Resolution: the most specific matching prefix wins (a page-level rule overrides its parent chapter's rule); `is_admin` users bypass checks entirely; default is deny.

This is the entire DB schema — no content, no revisions, no search index tables.

### App modules (FastAPI)

- **auth** — login/session, password hashing, group membership management (admin UI).
- **content** — CRUD for books/chapters/pages as folders/files; front-matter read/write via `python-frontmatter`; slugify + `git mv` on rename so history follows the file.
- **acl** — path-prefix permission resolution, enforced as a dependency on every content route (read and write separately).
- **git** — thin wrapper (GitPython) around commit/push/pull/log/diff/checkout for the content repo.
- **nav** — creates/updates `.pages` files when books/chapters/pages are created, renamed, reordered, or deleted.
- **render** — renders page HTML for the live app using the *same* `markdown` extensions declared in `mkdocs.yml`, so in-app preview matches the eventual static build.
- **search** — permission-filtered grep over markdown bodies (subprocess `rg`/`grep` or a plain Python file walk); no index to keep in sync.
- **export** — admin action to run `mkdocs build` (and optionally `gh-deploy`) on demand.
- **ai** — the module that matters for the stated future need: a small MCP server (tools: `search_wiki`, `get_page`, `list_pages`) and a REST+OpenAPI surface (for a ChatGPT custom GPT/Action), both thin wrappers over `content`+`search`+`acl` so AI queries are filtered by the same group permissions as a logged-in user. Building this as a real module now (not a special case) means adding Claude/ChatGPT later is just adding a transport, not new logic.
- **web** — Jinja2 templates + a markdown editor (e.g. EasyMDE) for browsing/editing; kept deliberately simple (no SPA framework) unless that's revisited later.

### Repo layout (this codebase)

```
unstacked/
  app/
    main.py
    models.py        # SQLModel: users/groups/permissions
    auth.py
    content.py
    acl.py
    git_backend.py
    nav.py
    render.py
    search.py
    export.py
    ai_mcp.py
    ai_api.py
    templates/
  content/            # the nested mkdocs git repo (gitignored from the app repo, managed via GitPython)
  data/
    app.db            # SQLite: users/groups/permissions
  tests/
```

## Implementation phases

1. **Scaffold** — FastAPI app, SQLModel schema (users/groups/user_groups/permissions), password auth + sessions.
2. **Content engine** — front-matter CRUD for books/chapters/pages as real folders/files; slugs; `.pages` nav management on every structural change.
3. **Git-backed history** — init the nested `content/` repo, auto-commit on every save with the editing user as git author, page history view (log/diff), restore-old-revision action.
4. **ACL enforcement** — path-prefix permission resolution wired as a FastAPI dependency on every read/write route; admin UI for managing groups and their chapter/page grants.
5. **Web UI** — tree browser, rendered page view (via `render`), markdown editor, admin screens.
6. **GitHub backup** — configure remote + credentials, push-on-save (debounced) and manual backup/restore admin actions.
7. **Static export & fallback** — "Publish" admin action (`mkdocs build`/`gh-deploy`) plus a GitHub Action template committed into the content repo so pushes alone rebuild the static site.
8. **Search** — permission-filtered grep search endpoint + UI.
9. **AI integration** — MCP server (Claude) and REST/OpenAPI surface (ChatGPT), reusing `content`/`search`/`acl` — no new storage.

## Verification

- Unit tests: ACL prefix-resolution logic (including page-overrides-chapter and admin-bypass cases), front-matter round-trip (write then read gives back the same fields).
- Integration test: create a book → chapter → page through the API, confirm the resulting folder/file layout matches the structure above, then run real `mkdocs build` against `content/` and confirm it succeeds with no errors.
- **Worst-case drill**: copy only `content/` (docs/ + mkdocs.yml, no app, no DB) to a clean machine with mkdocs installed, run `mkdocs build`, confirm the site renders correctly — this is the scenario the whole design exists to satisfy.
- Manual permission test: two users in different groups, confirm each can only read/write the chapters/pages their group was granted.
- GitHub backup round-trip: push to a real (test) GitHub repo, wipe local `content/`, restore from GitHub, confirm identical history (`git log`) and files.
