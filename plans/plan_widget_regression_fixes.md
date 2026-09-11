# Plan: fix widget-feature regressions, then harden the widget system

## Context

A code review of `c43f737..HEAD` (20 commits building the reusable-widget
feature: data-cards, switching-cards, text, horizontal-rule) found several
regressions and correctness bugs shipped alongside the new functionality.
Some are independently confirmed by a currently-failing test; others were
verified directly by reading the relevant code. This plan fixes those, then
addresses the duplication/efficiency issues the same review turned up.

Every phase below fixes exactly one class of bug. Land and verify each phase
independently rather than batching fixes together, since several touch the
same files (`app/web.py`, `app/home_widgets.py`, `app/content.py`) and a
combined diff would make it harder to tell which fix caused a regression if
one appears.

## Phase 1 — Currently-broken user-facing behavior

**Status: done** (commit `02ffb45`).

1. **Home widgets invisible to non-admin viewers.** `_render_data_cards` and
   `_render_text` (`app/home_widgets.py:205,345`) check
   `authorization.policy.decide(source).can_read` against the widget's raw
   synthetic path (`widget-sources/home-<id>.md`), which never qualifies for
   the `index.md`-only default-read bypass in `app/acl.py`. Fix: when the
   widget's source path is a Home widget source, decide against `"index.md"`
   instead of the literal source path — the same substitution
   `_is_home_widget_source`/the write path already makes in `app/web.py`, just
   missing from the read path used at render time.
2. **"Remove from Home" admin control missing.** The shared widget-rendering
   macro (`app/templates/_content_widgets.html`) dropped the per-item removal
   form the old inline `tree.html` loop had, and doesn't receive
   `is_admin`/`csrf_token`/`return_to` at all. Restore it for the `featured`
   branch specifically (the other widget types never had a removal control).
   `tests/test_web.py::test_tree_widget_remove_control_targets_its_own_grid_id_not_a_hardcoded_default`
   already exists and currently fails — this phase is done when it passes
   again with no other test regressed.
3. **`switching-cards` widgets drop all their text.** `_render_content_widgets`
   (`app/web.py:558`) only Markdown-renders `text`/`text_html` for the literal
   type `"data-cards"`, even though `WIDGET_REGISTRY` maps `"switching-cards"`
   to the identical renderer and the template displays both identically. Fix
   the type check to cover both (e.g. match on the same list the template
   already groups them with, rather than a second hard-coded literal).
4. **A book can be named `widget-sources`.** Add `"widget-sources"` to
   `app/paths.py`'s `RESERVED_ROOT_NAMES` so `create_book`/`make_slug` refuse
   it, the same way `"assets"` is already refused. Add a regression test
   creating a book with that title and asserting rejection.
5. **ACL routing confusion for pages under a colliding book name.**
   `_is_home_widget_source` (`app/web.py:594`) recognizes a Home widget source
   by string shape alone (`widget-sources/*.md`). Once (4) is fixed this can
   no longer be triggered by an ordinary book, but add a test proving it (a
   book literally cannot be created there) rather than leaving the routing
   logic's fragility undocumented.

## Phase 2 — Data-loss risks

**Status: done.** Item 8 took the fallback this phase already named (visibly
report partial success) rather than merging the two commits into one: true
atomicity would mean restructuring `update_page`/`update_home_page`/
`set_container_description` themselves, a larger and riskier change than
this phase's other items. A failure in `ensure_widget_sources` after the
main content commit already succeeded no longer routes through the error-
redisplay path (which claimed nothing was saved) or, for non-`ContentError`
failures like a bare `OSError`, crashes as an unhandled 500 -- it's caught,
logged, and the save still redirects as the success it is. The affected
widget surfaces its own error via the existing `widget_errors` mechanism on
the next render.

6. **Widget tray emptied on save conflict/validation error.** The editor's
   error-response context (`app/web.py:1112` and the equivalent in
   `save_home`) rebuilds the form from the raw submission instead of the
   parsed widget list when a `ContentError`/conflict occurs, so
   `widgets_json` renders as `[]`. A user who doesn't notice and resubmits
   deletes every widget on that page. Fix: derive the redisplayed widget list
   from the submitted `widgets_json` on every error path, not only on the
   initial (no-form) render. Add a test that forces a 409 with widgets
   configured and asserts the redisplayed editor still lists them.
7. **Stale widget content resurrected on id reuse.** `ensure_widget_sources`
   (`app/content.py:1062`) only creates a widget's backing file when one
   doesn't already exist, with no cleanup when a widget is removed. Decide and
   implement one of: (a) delete a widget's backing file when the widget is
   removed from its owning page/Home, or (b) generate backing paths that can't
   collide across a widget's create/delete/recreate lifecycle (e.g. suffix
   with a creation timestamp or short random component). Prefer (a) if nothing
   else references a widget's source path once orphaned; confirm that before
   choosing.
8. **Non-atomic two-commit save.** `save_page`/`save_home`/
   `save_book_description` commit the front-matter widgets list, then
   `ensure_widget_sources` commits the backing files in a second, independent
   `write_lock()`. If the second commit fails, the first has already
   succeeded even though the request reports failure. Fold both into one
   commit under one lock, or make the failure path visibly report the partial
   success rather than a plain error.

## Phase 3 — Resource correctness

**Status: done.** Bundled in Phase 5 item 15's `book_view` efficiency fix
(reusing one `AuthorizationContext` and one `read_navigation()` result)
since it's the same lines already being widened into the `with` block --
splitting it into a separate pass later would have touched the same code
twice for no benefit. Verified with a session that raises the moment it's
queried after `close()`, using a non-admin reader (an admin's
`AuthorizationContext` short-circuits in `load_policy()` before ever
touching the database, so it never exercised the buggy path).

9. **`book_view` uses a closed DB session.** `app/web.py:950,958` call
   `_authorization(session, user)` twice after the `with Session(...) as
   session:` block that owns `session` has already exited. Widen the `with`
   block to cover the whole function body (or open a second explicit session
   for the later calls), so nothing runs queries against a session outside
   its own context manager. This is the kind of bug that doesn't show up in
   normal test runs — verify by checking connection-pool checkout/checkin
   counts in a test, not just that the response still renders.

## Phase 4 — Cleanup (safe, no behavior change)

**Status: done**, with two notes:

- Item 11's two Jinja checks are expressed as `source_widget_types` (the
  3-type "needs a generated source" set) and
  `source_widget_types + ['horizontal-rule']` (the 4-type "doesn't get a
  free-text Title field" set) rather than one shared list -- they're
  genuinely different concepts that happened to overlap by 3 of 4 types,
  and collapsing them to one list would have been incorrect, not simpler.
  While verifying this in a real browser, found and fixed a real,
  pre-existing bug (predates this plan) in the same area: the "Add widget"
  form's Title-field visibility toggle never accounted for
  `horizontal-rule` at all, unlike the already-added row's own logic --
  confirmed via `git log -p` that this has been wrong since before
  `horizontal-rule` existed as a type.
- Item 13 turned out not to have a live bug once traced fully: the client's
  slug-based check and the server's deeper `widget_entries_for_location`
  check already agree (both slug-based); only the shallower
  `_validate_widget_entries` casefold check is weaker, and tightening it to
  match would reject currently-valid ids on non-source-backed widget types
  (e.g. `horizontal-rule`) that don't need to slugify cleanly at all --  a
  real behavior change, not safe for this phase. Clarified the relationship
  with comments at all three sites instead of changing validation logic.

10. **Dead code from the anonymous-access removal.** `app/web.py`'s
    `_public_page`, `_public_context`, `_home_public`,
    `_unauthenticated_destination`, `_public_home_widgets`, and
    `_public_home_context` have zero remaining callers since commit `335af35`.
    Delete them. Fix the docstring in `app/admin_api.py:1519`, which still
    describes the removed anonymous-redirect-to-Home behavior as current.
11. **Duplicated "source-backed widget type" list.** Six near-identical
    literals across `app/templates/home_editor.html` (two Jinja conditionals,
    four inline-JS arrays) classify which widget types use a generated
    source. Drive all six from one list — ideally the same
    `_SOURCE_WIDGET_TYPES`-shaped registry already in `app/content.py`, passed
    into the template context once.
12. **Duplicated "is this a widget-source path" predicate.** Three different
    implementations exist across `app/content.py` (two spots) and
    `app/search.py`. Factor into one `is_widget_source_path()` in
    `app/content.py`, imported where needed.
13. **Duplicated slug/uniqueness logic between server and client.** The
    server (`app/content.py`, casefold-based) and the book/page widget editor
    (`app/static/widget_editor.js`, regex-slug-based) each reimplement widget
    id normalization and duplicate-id checking independently, with different
    normalization rules. Align them (client mirrors the server's exact rule,
    or the server's error message clarifies the mismatch) so a client-accepted
    id can't be server-rejected as a surprise after what looked like a
    successful add.
14. **Duplicated CSS rule block.** `app/static/style.css` defines the same
    `.home-widget`/`.data-cards-*` ruleset twice back to back, differing only
    by an added `.widget-divider` rule in the second copy. Merge into one
    block.

## Phase 5 — Efficiency (only after Phases 1-4 are done and tested)

**Status: done** (15 bundled into Phase 3; 16 fixed; 17 deliberately
skipped, see below).

15. ~~**Redundant per-request work in `book_view`.**~~ Done already, bundled
    into Phase 3 (see its status note) rather than deferred here.
16. **Redundant `MarkdownRenderer` construction and mkdocs-config reload.**
    Fixed by caching `_load_markdown_settings`'s result in `app/render.py`,
    keyed by the config file's path and mtime -- MkDocs' loader does full
    schema validation (plus a separate plugin-name parse pass first), and a
    page with several source-backed widgets was redoing that once per
    card. Verified a changed config still invalidates the cache (no restart
    needed to pick up an edited `mkdocs.yml`). Left `MarkdownRenderer`
    object construction itself untouched -- its `__init__` is cheap (just
    stores two paths); the expensive work was always inside `render()`,
    not in how many renderer instances exist.
17. ~~**Triple widget-list validation on save.**~~ Skipped deliberately.
    `_validate_widget_entries` is a cheap, pure, in-memory check over a
    short list (typically single digits of widgets) -- unlike item 16's
    genuine I/O- and schema-validation-bound cost, this redundancy is
    microseconds, not milliseconds. Removing it would mean threading a
    "trust me, already validated" state through `ContentRepository`'s
    public write methods (`update_page`, `update_home_page`,
    `set_container_description`, `ensure_widget_sources`) -- real API
    surface changes to security/data-integrity-sensitive write paths,
    risking a validation-bypass bug for a gain nobody would ever measure.
    Not worth it.

## Verification

- After each phase: run the full test suite (`pytest`), plus a manual check
  in a running instance for anything UI-visible (the remove button, a
  non-admin viewing a Home data-cards widget, the editor after a forced
  conflict).
- `tests/test_web.py::test_tree_widget_remove_control_targets_its_own_grid_id_not_a_hardcoded_default`
  must pass by the end of Phase 1 and stay passing through every later phase.
- No phase should widen what an unauthenticated visitor can reach — Phase 1
  item 1 fixes a case where legitimate readers see *less* than they should,
  not more; verify it doesn't accidentally grant *more* than Home's own
  permission would.
- Re-run the two pre-existing, unrelated failing tests
  (`test_content_bootstrap.py::test_existing_content_repo_receives_missing_ci_once_and_preserves_custom_workflow`,
  `test_web.py::test_settings_nav_has_a_dedicated_home_page_entry_pointing_to_home`)
  at the end and confirm they're still the *only* pre-existing failures, not
  masking a new one.

## Non-goals

- No new widget types.
- No change to the underlying four-table ACL model or the `.pages`
  navigation-file format.
- No change to the public/management site split or its build pipeline —
  this plan is scoped to the widget feature and the management app only.
