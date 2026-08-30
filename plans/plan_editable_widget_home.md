# Plan: Editable, widget-based home page

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
   ```

3. Keep the existing `.unstacked-home.json` as the Git-versioned curation
   list that powers the `featured` widget. It continues to store the featured
   book/page targets and their order.
4. Treat `index.md` as a reserved, first-class content path. It is not a book
   page, but it receives explicit path-prefix ACL checks such as `index.md`.
   The bootstrap/default policy grants administrators write access.

## Implementation phases

### 1. Content and permission foundation

- Add safe `read_home_page` and `update_home_page` operations to the content
  repository, using the existing optimistic blob-SHA and locked Git commit
  workflow.
- Create a default `docs/index.md` during content initialization only when it
  does not already exist. Its starter content matches the current Home design
  and includes one `featured` widget.
- Extend ACL/path handling so `index.md` can be read and written without
  weakening the book/page permission model.
- Ensure `mkdocs build --strict` renders the Markdown page normally.

### 2. Widget schema and rendering

- Define a small validated widget registry rather than executing arbitrary
  front-matter instructions.
- First supported widget: `featured`, which renders the curated featured
  books/pages list and filters each item for the viewing user.
- Ignore unknown widgets safely in the live app with an editor-visible error;
  preserve unknown front matter during round trips.
- Render Markdown body and widgets in the exact authored order. Widgets can
  appear before, between, or after Markdown sections through explicit widget
  placeholders/tokens in the editor model.

### 3. Home editing experience

- Replace the current fixed Home heading with rendered `index.md` content.
- Show an Edit button only when the current user has write permission for
  `index.md`.
- Use the existing Markdown editor for the text body.
- Add a widget tray in the editor. Users can add the `featured` widget and
  drag widgets to reorder them; keyboard-accessible move controls accompany
  drag-and-drop.
- Save both Markdown and widget order in one home-page commit.

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
- Add tests for ACL visibility, editor/write authorization, widget ordering,
  malformed front matter, unknown widgets, static MkDocs builds, and Git
  commit/rollback behavior.
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
  widget reordering.
