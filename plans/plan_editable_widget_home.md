# Plan: Editable, widget-based home page

## Implementation checkpoint (2026-08-30)

All six phases are implemented, merged to `main`, and verified: full test
suite and `ruff` clean, a real Docker Compose deployment healthy with
`index.md`'s widget front matter confirmed correct in the actual content
volume (not just under test fixtures). Phases 1-2 (content/ACL/widget
foundation) landed in `1871a09`; phases 3-5 (home editing UI, settings
separation, featured-star verification) landed via two parallel
worktree-isolated agents merged in `f26c10e`/`75af1c5`. Deferred, by
design rather than time pressure: inline widget-placeholder tokens (the
plan's own fixed-slot v1 decision) and every candidate widget beyond
`featured` (recently-updated, by-tag, pinned, your-drafts) -- the schema
supports adding them later without migration, but none were requested yet.

## Goal

Replace the current fixed Home screen with a Git-versioned Markdown home page.
Users with write permission for that page can edit its copy. Its layout also
contains reorderable widgets, initially including a permission-filtered
Featured books and pages widget.

## Guardrails

- The home page and widget layout are content files in the nested `content/`
  Git repository, never database rows.
- Every save is a normal content-repository commit authored by the editor.
- The database remains limited to users, groups, memberships, and ACL rules.
- Widget output must apply the same ACL filtering as Books, Pages, and search.
- A content checkout must remain a strict-buildable MkDocs project without
  the application or database.

## Proposed content model

1. Reserve `docs/index.md` as the homepage Markdown document.
2. Give it ordinary page front matter plus a `widgets` list, for example:

   ```yaml
   title: Home
   widgets:
     - id: featured
       type: featured
       config: {}
   ```

   `config` is an open, widget-defined map -- empty for `featured` today, but
   present from the start. A later widget needing a parameter (a count, a
   tag filter) should not require a schema migration across every existing
   `index.md`.

3. Keep the existing `.unstacked-home.json` as the Git-versioned curation
   list that powers the `featured` widget. It continues to store the featured
   book/page targets and their order.
4. Treat `index.md` as a reserved, first-class content path. It is not a book
   page, but it receives explicit path-prefix ACL checks such as `index.md`.
   Read defaults to every authenticated user -- Home is the shared landing
   screen, not grant-gated content. Write follows the ordinary ACL grant
   model rather than a hardcoded admin check: the Admin default group's
   existing blanket grant already covers it, and any other group can be
   given an explicit write grant on `index.md`, the same as a book.

## Implementation phases

### 1. Content and permission foundation

- Add safe `read_home_page` and `update_home_page` operations to the content
  repository, using the existing optimistic blob-SHA and locked Git commit
  workflow.
- Create a default `docs/index.md` during content initialization only when it
  does not already exist. Its starter content matches the current Home design
  and includes one `featured` widget.
- Extend ACL/path handling so `index.md` can be read and written without
  weakening the book/page permission model. Read is open to every
  authenticated user by default; write stays grant-gated exactly like a
  book (Admin's existing blanket grant already covers it).
- Ensure `mkdocs build --strict` renders the Markdown page normally.

### 2. Widget schema and rendering

- Define a small validated widget registry rather than executing arbitrary
  front-matter instructions. Each entry is `{id, type, config}` (see the
  content model above).
- First supported widget: `featured`, which renders the curated featured
  books/pages list and filters each item for the viewing user.
- Ignore unknown widgets safely in the live app with an editor-visible error;
  preserve unknown front matter during round trips.
- Render widgets in one fixed slot (below the Markdown body) in their
  authored order for v1, rather than interleaving them inline via
  placeholder tokens in the body text. A real `mkdocs build --strict` has no
  concept of a widget token and would render it as literal text in the
  static export; a fixed slot sidesteps that without a custom markdown-hook
  just to swallow it. Inline placement, if wanted later, is a separate,
  larger piece of work (a `hooks/`-style build-time handler, mirroring
  `hooks/drafts.py`) and isn't required for a single-widget v1.
- Candidate widgets beyond `featured`, roughly in order of how little new
  plumbing they need (all ACL-filtered the same way `featured` is):
  - **Recently updated** -- sort pages by front-matter `updated_at`, top N.
  - **By tag** -- book/page tags already exist; list tags with counts.
  - **Pinned/announcement** -- an admin pins one page; the widget renders
    its body inline via the existing `MarkdownRenderer`.
  - **Your drafts / pages you can write** -- the first widget that varies by
    *viewer identity*, not only viewer permission on a shared curated list;
    worth naming explicitly since it's a small framing shift from
    `featured`.
  - Avoid, for now, anything needing a new counter store (e.g. "most
    viewed") -- that's either a new DB table (outside the users/groups/ACL
    guardrail) or a JSON file with a write on every page view. Not worth it
    unless specifically requested later.

### 3. Home editing experience

- Replace the current fixed Home heading with rendered `index.md` content.
- Show an Edit button only when the current user has write permission for
  `index.md`.
- Use the existing Markdown editor for the text body.
- Add a widget tray in the editor. Users can add the `featured` widget and
  drag widgets to reorder them; keyboard-accessible move controls accompany
  drag-and-drop.
- Save both Markdown and widget order in one home-page commit, carrying the
  page's current blob SHA through a widget-only reorder exactly like a text
  edit. Front matter and body are one file, so the two share one conflict
  domain; a reorder that skipped the SHA check could silently clobber a
  concurrent text edit.

### 4. Settings separation

- Add a dedicated Settings navigation item, **Home page**, rather than mixing
  homepage settings into Branding.
- Move default home-copy controls out of Branding. The Home page itself
  becomes the source of editable copy; Settings only exposes administrator
  actions appropriate to the home page (for example reset-to-starter-layout
  with explicit confirmation, if requested).
- Keep Branding limited to application name and logo.

### 5. Featured-item controls

- Retain the in-card star toggle on Books and Pages.
- Make the star update `.unstacked-home.json` and immediately affect the
  `featured` widget; preserve the user's current view after toggling.
- Continue allowing exact page grants only for pages currently featured.

### 6. Verification and migration

- Migrate the current fixed homepage values into `docs/index.md` on first
  startup, without overwriting a hand-authored page.
- Add tests for ACL visibility (including the default-open read grant),
  editor/write authorization, widget ordering, the `config` map surviving a
  round trip, malformed front matter, unknown widgets, static MkDocs builds,
  and Git commit/rollback behavior.
- Run Ruff, the full test suite, and the Docker Compose health check.

## Acceptance criteria

- Home content is Markdown in `content/docs/index.md` and is editable only by
  users with write access to that path.
- A default Home page renders a Featured widget containing only permitted
  featured books and pages.
- A permitted editor can drag widgets into a new order and sees that order
  after reload; the save is one content-repository Git commit.
- Administrators access Home-related administrative controls from a dedicated
  Settings page; Branding no longer controls page copy.
- A standalone `mkdocs build --strict` succeeds after bootstrap, editing, and
  widget reordering, and its output shows only the Markdown body -- no
  widget content and no literal placeholder text -- consistent with the
  static export already carrying no runtime ACL.
