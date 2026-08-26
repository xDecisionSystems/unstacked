# unstacked

A file-based alternative to [BookStack](https://www.bookstackapp.com/).

Instead of storing books/chapters/pages in a database, `unstacked` keeps
them as plain markdown files in a git repo, laid out exactly the way
[mkdocs](https://www.mkdocs.org/) expects. Worst case, if the app and its
database disappear entirely, the content folder alone can be dropped into
any mkdocs install and built into a working static site.

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

## Status

Planning stage — no application code yet. See
[plans/plan_initial.md](plans/plan_initial.md) for the full architecture
and phased build plan, and [AGENTS.md](AGENTS.md) for the working rules AI
coding agents (and contributors) should follow in this repo.

## License

GPLv3 — see [LICENSE](LICENSE).
