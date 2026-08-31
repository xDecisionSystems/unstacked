# Multiple named featured grids on Home

## Context

Today Home has exactly one featured grid. It is populated by a single,
flat, Git-versioned curated list (`content/.unstacked-home.json`'s
`items`), toggled by a ★ button that appears on every book/page card
(`book.html`, `books.html`, `pages.html`) and on the grid's own cards in
`tree.html`. Rendering is the one `featured` entry in `index.md`'s
`widgets` front matter (`app/home_widgets.py`); the widget's heading was a
hardcoded `"Featured"` constant, and its visible `<h2>` was removed from
`tree.html` earlier in this project's history at the user's request (the
`aria-label` still carries it).

The user wants several independent featured grids on Home at once (e.g.
*Research*, *IT*, *News*), each configured separately, each named (so it
is recognizable while editing), and each with an *optional* visible title
header. Confirmed with the user: curation stays star-toggle-driven, not
tag-driven, but the toggle must become **grid-aware** — a book or page can
be featured in one, several, or no grids, chosen from a small popover
rather than a single on/off star.

## Design

### Naming and the optional header

A widget's existing `id` (already required, already unique per the
Phase 1 widget model) doubles as its editor-facing name — e.g. `research`,
`it`, `news` — shown as the row label in the widget tray and in the
grid-picker popover. A new `config.title` string (the `config` bag has
existed on every widget entry since the original plan) is the optional,
independently-editable page-visible heading: rendered as `<h2>` above the
grid only when non-empty, omitted entirely otherwise. This keeps "named"
and "optional title" as two genuinely separate concerns without inventing
a third field.

### Curation storage: grid-keyed, not flat

`ContentRepository`'s home-layout file moves from

```json
{"items": ["book-a", "book-b/page.md"]}
```

to

```json
{"grids": {"featured": ["book-a", "book-b/page.md"]}}
```

`home_items()` becomes `home_items(grid_id: str | None = None) -> list[str]`:
a specific grid's ordered targets when `grid_id` is given, or the union
(de-duplicated, first-seen order) of every grid's targets when omitted —
the shape the admin "Featured page overrides" permission matrix and any
other caller that wants "is this featured *anywhere*" still need. Reading
the old flat `{"items": [...]}` shape (no `"grids"` key) is treated as one
implicit `featured` grid, so no migration script or write-on-read is
needed — old and new shapes both parse; the file naturally moves to the
new shape the next time anything under Home is edited.

`feature_on_home`/`remove_from_home` gain a required `grid_id: str`
parameter and read/write only that grid's list, leaving every other grid's
list untouched — critical, since two different widgets' curated lists now
live in the same file and must not stomp each other under the existing
single write-lock.

Deleting a widget (see below) **also deletes its grid's curated list**
from `.unstacked-home.json` — confirmed with the user: recreating a widget
with the same `id` later starts empty, not restored. `update_home_page`
diffs the incoming `widgets` list's ids against the ones already on the
page before overwriting it; any `featured`-type id present before and
absent after has its entry removed from `.unstacked-home.json` as part of
the same locked operation, so the widget-front-matter commit and the
curation-list commit land together as one atomic change (both files
touched, one Git commit) rather than leaving a window where the tray
already shows the grid gone but its old members still linger on disk.

### Rendering (`app/home_widgets.py`)

`_render_featured` already receives its own `WidgetEntry`; the only change
is reading `content.home_items(entry.id)` instead of the global
`content.home_items()`, and setting `RenderedWidget.title` from
`entry.config.get("title")` (default `""`, meaning "no header") instead of
the hardcoded constant. `render_widgets`/`build_home_widgets` need no
change — they already loop over every entry in authored order, so N
`featured` widgets already "just work" once each one's curation and title
are independent.

`app/web.py`'s `_public_home_widgets` (the anonymous-visitor path, added
this session) needs the same two changes, mirrored, since it re-implements
`_render_featured` without an `AuthorizationContext`.

### Editor UI (`app/templates/home_editor.html`)

The widget tray currently only reorders; it has no way to add, remove, or
configure a widget. This plan adds:

- **Add a featured grid**: a small form (id/name input, slugified the same
  way a page title already is; optional title input) appends a new
  `{"id": ..., "type": "featured", "config": {"title": ...}}` entry to the
  tray, client-side, exactly like the existing move-up/move-down buttons
  already mutate the tray's DOM before `widgets_json` is serialized on
  submit — no new save endpoint needed, this is still one
  `update_home_page` commit.
- **Edit a grid's title**: replace the row's static label with the id
  (read-only once created, to avoid silently orphaning its curated list —
  see above) plus an editable title text input, wired into
  `data-config`/`serializeWidgets()` the same way move already is.
- **Remove a grid**: a delete control on the row. A confirmation
  (`confirm()`, matching every other destructive action in this app) warns
  that this discards the grid's curated list permanently — recreating a
  grid with the same id afterward starts empty.

### Grid-aware feature toggle

The ★ button (duplicated today in `book.html`, `books.html`, `pages.html`,
and `tree.html`'s own cards) becomes a `<details>` popover, matching the
`new-book-popover` pattern already used for book/page creation elsewhere
in this app: opening it lists every currently-configured `featured` widget
as a checkbox (checked if this target is in that grid's list), submitting
diffs the checked set against the current one with one `/home/feature` or
`/home/remove` POST per change. With zero grids configured, the popover
shows "No featured grids yet — add one from the Home editor" instead of
an empty list, so a fresh install's cards are not silently non-functional.

Given four templates duplicate this markup today, extract it once as a
Jinja macro (e.g. `app/templates/_widgets.html`) parameterized on the
target/return-to/currently-featured-grid-ids, rather than deepening a
four-way copy-paste with popover markup on top.

### API surface

- `POST /home/feature`, `POST /home/remove`: gain a required `grid_id`
  form field; a `grid_id` that doesn't match any configured `featured`
  widget is rejected (400), the same "reject rather than silently create
  an orphaned grid" posture the widget registry already takes with unknown
  widget `type`s.
- `home_editor.html`'s existing `widgets_json` field/`update_home_page`
  call needs no new endpoint for add/remove/rename-title, since those are
  ordinary widget-tray edits already flowing through that one path.

### What does not change

- The widget registry contract (`WidgetEntry`/`RenderedWidget`/
  `WidgetError`, unknown-type-renders-nothing-but-is-preserved) is
  unchanged; this plan is entirely inside the existing `featured` widget
  type plus the tray's add/remove/edit affordances, not a new widget type
  or a registry change.
- ACL filtering per grid is unchanged — each grid still filters its own
  curated list to what the viewer (real `AuthorizationContext`, or the
  anonymous public-visibility predicates) can read, exactly as today's
  single grid does.
- The admin "Featured page overrides" permission matrix keeps using
  `home_items()` with no `grid_id` (the union), since an exact-permission
  override is about the page itself, not which grid(s) happen to surface
  it.

## Implementation phases

1. **Content layer**: grid-keyed `.unstacked-home.json` read/write
   (`home_items(grid_id=None)`, `feature_on_home`/`remove_from_home` with
   a required `grid_id`), old-shape-still-reads compatibility, and
   `update_home_page`'s removed-grid-id purge (diff old vs. new widget ids,
   delete any dropped `featured` grid's curated list in the same commit).
   Unit tests for the migration-free dual-shape read, per-grid isolation
   (writing grid A must never touch grid B's list), and the purge-on-delete
   behavior (delete a grid, confirm its list is gone from
   `.unstacked-home.json`; recreate a widget with the same id, confirm it
   starts empty rather than recovering the old members).
2. **Rendering**: `_render_featured`'s per-instance curation + optional
   title in `app/home_widgets.py`; the mirrored change in
   `app/web.py::_public_home_widgets`; `tree.html` reintroduces a
   conditional `<h2>` per widget (`{% if widget.title %}`). Tests: two
   configured grids show disjoint, correctly-filtered item sets and only
   the grid(s) with a set title render a heading.
3. **API**: `grid_id` on `/home/feature`/`/home/remove`, rejecting an
   unknown grid id; tests for the reject case and for a target ending up
   in exactly the grids it was toggled into.
4. **Editor UI**: add/remove/edit-title controls in `home_editor.html`'s
   widget tray; tests cover the full round trip (add a grid, give it a
   title, save, reload, see it) through the existing `widgets_json` path,
   plus the delete confirmation and its resulting empty-on-recreate
   behavior end to end through the browser route.
5. **Card popover**: extract the shared Jinja macro, convert all four
   templates' ★ button to the grid-checkbox popover, including the
   zero-grids-configured empty state; tests cover a target toggled into
   multiple grids from one card and the popover's ACL gating (`is_admin`,
   matching today's).

## Verification

- Full existing test suite stays green (in particular the single-grid
  tests from the original widget-home plan, which must still pass
  unmodified against a repo whose `.unstacked-home.json` is still in the
  old flat shape).
- New tests per phase above.
- Manual/Playwright check against a real local Docker deployment: create
  three grids (Research, IT, News), feature different, overlapping, and
  disjoint content into each, confirm anonymous public rendering (Home
  published) only shows the public subset per grid, and confirm deleting
  a grid then re-adding one with the same id starts it empty rather than
  restoring its prior curated list.
