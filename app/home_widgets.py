"""A small, explicit widget registry for the Home page.

``docs/index.md``'s front matter carries a ``widgets`` list; each entry is
``{"id": str, "type": str, "config": dict}`` (see
``plans/plan_editable_widget_home.md``).  This module renders only the
handful of widget types it explicitly knows about -- it is never an
arbitrary-code executor.  An entry with an unrecognized ``type`` renders
nothing, but it is never silently dropped: it is preserved byte-for-byte by
``ContentRepository.update_home_page`` (this module does no writing) and
surfaced here as an editor-visible :class:`WidgetError` instead of raising,
so one malformed or unknown entry never takes down the whole Home page.

This module deliberately does not import ``app.web``: it is a content/ACL
concern, reusable by any transport (web UI, a future API), not a
web-templating one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.acl import AuthorizationContext
from app.content import ContentError, ContentRepository
from app.nav import NavigationError, read_navigation
from app.paths import UnsafePath, normalize_relative_path, path_depth


@dataclass(frozen=True)
class WidgetEntry:
    """One validated, well-shaped ``widgets`` front-matter entry."""

    id: str
    type: str
    config: dict[str, Any]


@dataclass(frozen=True)
class RenderedWidget:
    """JSON/template-friendly output of one rendered widget slot.

    ``data`` is intentionally plain data (lists/dicts/strings/bools), never
    markup, so the UI layer can render it with whatever templates fit --
    this module has no opinion on HTML.
    """

    id: str
    type: str
    title: str
    data: dict[str, Any]


@dataclass(frozen=True)
class WidgetError:
    """One ``widgets`` entry this module could not render.

    ``entry_id`` is ``None`` when the entry was too malformed to even have a
    usable id (e.g. not a mapping, or missing ``id`` itself). Callers are
    expected to surface ``message`` to an editor rather than fail the page.
    """

    entry_id: str | None
    message: str


@dataclass(frozen=True)
class HomeWidgetsResult:
    """Everything a Home page render needs from one ``widgets`` value."""

    rendered: list[RenderedWidget]
    errors: list[WidgetError]


def parse_widget_entries(raw: Any) -> tuple[list[WidgetEntry], list[WidgetError]]:
    """Validate a page's raw ``widgets`` front-matter value.

    Never raises. ``raw`` is whatever ``ContentRepository.read_home_page``
    returned for the ``widgets`` metadata key -- possibly ``None`` (no
    widgets configured), possibly something malformed a hand-edit produced.
    A malformed list, a non-mapping entry, or a missing field each produce
    one :class:`WidgetError` rather than stopping the well-formed entries
    from parsing.
    """

    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [WidgetError(None, "'widgets' front matter must be a list")]
    entries: list[WidgetEntry] = []
    errors: list[WidgetError] = []
    for item in raw:
        if not isinstance(item, dict):
            errors.append(WidgetError(None, "a widget entry must be a mapping"))
            continue
        entry_id = item.get("id")
        entry_type = item.get("type")
        config = item.get("config", {})
        if not isinstance(entry_id, str) or not entry_id.strip():
            errors.append(WidgetError(None, "a widget entry is missing a string 'id'"))
            continue
        if not isinstance(entry_type, str) or not entry_type.strip():
            errors.append(WidgetError(entry_id, f"widget '{entry_id}' is missing a string 'type'"))
            continue
        if not isinstance(config, dict):
            errors.append(WidgetError(entry_id, f"widget '{entry_id}' has a non-mapping 'config'"))
            continue
        entries.append(WidgetEntry(id=entry_id, type=entry_type, config=config))
    return entries, errors


WidgetRenderer = Callable[[WidgetEntry, AuthorizationContext, ContentRepository], RenderedWidget]


def _humanize_slug(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title() or slug


def _describe_target(content: ContentRepository, target: str) -> dict[str, Any]:
    """Resolve one ``home_items()`` target's display shape.

    Mirrors the minimal lookup ``app/web.py``'s ``_container_title`` and
    ``_page_view`` already do for the tree/book views (a book's title comes
    from its ``.pages`` file, a page's from its own front matter) without
    importing anything from the web layer.
    """

    if target.endswith(".md"):
        slug = target.rsplit("/", 1)[-1].removesuffix(".md")
        try:
            metadata, _body, _raw = content.read_page(target)
        except (ContentError, UnsafePath):
            metadata = {}
        title = metadata.get("title")
        if not isinstance(title, str) or not title.strip():
            title = _humanize_slug(slug)
        card_image = metadata.get("card_image")
        return {
            "kind": "page",
            "target": target.removesuffix(".md"),
            "title": title,
            "card_image": card_image if isinstance(card_image, str) else None,
        }
    try:
        title = read_navigation(content.docs / target / ".pages").title
    except NavigationError:
        title = None
    return {
        "kind": "book",
        "target": target,
        "title": title if title else _humanize_slug(target),
        "card_image": None,
    }


def _render_featured(
    entry: WidgetEntry, authorization: AuthorizationContext, content: ContentRepository
) -> RenderedWidget:
    """Render one widget instance's own curated grid, filtered to what this user may read.

    Each ``featured`` widget instance curates its own grid, keyed by its own
    ``entry.id`` -- order matches ``content.home_items(entry.id)``'s stored
    order; a target the viewer cannot read is filtered out entirely rather
    than shown redacted. ``title`` comes from this instance's own
    ``config['title']`` (default ``""``, meaning no visible header) rather
    than a shared constant, since independent grids may each be named
    differently or left untitled.
    """

    items = [
        _describe_target(content, target)
        for target in content.home_items(entry.id)
        if authorization.policy.decide(target).can_read
    ]
    title = entry.config.get("title")
    return RenderedWidget(
        id=entry.id,
        type=entry.type,
        title=title.strip() if isinstance(title, str) else "",
        data={"items": items},
    )


def _render_data_cards(
    entry: WidgetEntry, authorization: AuthorizationContext, content: ContentRepository
) -> RenderedWidget:
    """Render generic cards declared in one permission-checked Markdown page.

    The source page uses front matter rather than an application table. Its
    ``widget`` mapping supplies the title, introductory text, and optional
    filters, while ``cards`` supplies the cards themselves. It can be a draft
    helper page; its book ACL still governs whether a Home viewer may see the
    card data.
    """

    source = entry.config.get("source")
    if not isinstance(source, str):
        raise ValueError("requires a Markdown source page")
    try:
        source = normalize_relative_path(source)
    except UnsafePath as exc:
        raise ValueError("has an invalid source page") from exc
    if not source.endswith(".md") or path_depth(source) != 2:
        raise ValueError("source must be a book page such as research/grants.md")
    if not authorization.policy.decide(source).can_read:
        return RenderedWidget(id=entry.id, type=entry.type, title="", data={"items": []})
    try:
        metadata, _body, _raw = content.read_page(source)
    except (ContentError, UnsafePath):
        raise ValueError("source page could not be read") from None
    cards = metadata.get("cards")
    if not isinstance(cards, list):
        raise ValueError("source page needs a 'cards' front-matter list")
    if len(cards) > 100:
        raise ValueError("source page may list at most 100 cards")
    widget = metadata.get("widget")
    if widget is None:
        widget = {}
    if not isinstance(widget, dict):
        raise ValueError("source page 'widget' must be a mapping")
    widget_title = widget.get("title")
    intro_text = widget.get("text")
    for name, value in (("title", widget_title), ("text", intro_text)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"widget {name} must be text")
    raw_filters = widget.get("filters", [])
    if not isinstance(raw_filters, list):
        raise ValueError("widget filters must be a list")
    if len(raw_filters) > 20:
        raise ValueError("widget may have at most 20 filters")
    filters: list[dict[str, str]] = []
    filter_ids: set[str] = set()
    for item in raw_filters:
        if not isinstance(item, dict):
            raise ValueError("each widget filter must be a mapping")
        filter_id = item.get("id")
        filter_label = item.get("label")
        if (
            not isinstance(filter_id, str)
            or not filter_id
            or not filter_id.replace("-", "").replace("_", "").isalnum()
            or filter_id in filter_ids
        ):
            raise ValueError("widget filters need unique letter, number, dash, or underscore ids")
        if not isinstance(filter_label, str) or not filter_label.strip():
            raise ValueError("widget filters need labels")
        filter_ids.add(filter_id)
        filters.append({"id": filter_id, "label": filter_label.strip()})

    items: list[dict[str, str | list[str] | None]] = []
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError("each card must be a mapping")
        title = card.get("title")
        text = card.get("text")
        label = card.get("label")
        date = card.get("date")
        url = card.get("url")
        target = card.get("target")
        card_filters = card.get("filters", [])
        if not isinstance(title, str) or not title.strip():
            raise ValueError("each card needs a title")
        for name, value in (("text", text), ("label", label), ("date", date)):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"card {name} values must be text")
        if not isinstance(card_filters, list) or not all(
            isinstance(value, str) for value in card_filters
        ):
            raise ValueError("card filters must be a list of filter ids")
        if unknown_filters := set(card_filters) - filter_ids:
            raise ValueError(f"card uses unknown filter '{sorted(unknown_filters)[0]}'")
        if url is not None and (not isinstance(url, str) or not url.startswith(("https://", "http://"))):
            raise ValueError("card links must use http or https")
        target_url: str | None = None
        if target is not None:
            if not isinstance(target, str):
                raise ValueError("card targets must be book or page paths")
            try:
                normalized_target = normalize_relative_path(target)
            except UnsafePath as exc:
                raise ValueError("card targets must be book or page paths") from exc
            if normalized_target.endswith(".md"):
                if path_depth(normalized_target) != 2:
                    raise ValueError("page targets must look like research/project.md")
                try:
                    content.read_page(normalized_target)
                except (ContentError, UnsafePath):
                    raise ValueError("card target page could not be read") from None
                if authorization.policy.decide(normalized_target).can_read:
                    target_url = f"/pages/{normalized_target.removesuffix('.md')}"
            else:
                if path_depth(normalized_target) != 1:
                    raise ValueError("book targets must be a book path")
                try:
                    read_navigation(content.docs / normalized_target / ".pages")
                except NavigationError:
                    raise ValueError("card target book could not be read") from None
                if authorization.policy.decide(normalized_target).can_read:
                    target_url = f"/books/{normalized_target}"
        items.append(
            {
                "title": title.strip(),
                "text": text.strip() if isinstance(text, str) else None,
                "label": label.strip() if isinstance(label, str) else None,
                "date": date.strip() if isinstance(date, str) else None,
                "url": url,
                "target_url": target_url,
                "filters": card_filters,
            }
        )
    # Old layouts stored the heading and text on the widget entry itself.
    # Keep that small fallback so existing Home pages remain readable, but
    # newly-authored data-card widgets place all display data in this source.
    if widget_title is None:
        widget_title = entry.config.get("title")
    if intro_text is None:
        intro_text = entry.config.get("text")
    return RenderedWidget(
        id=entry.id,
        type=entry.type,
        title=widget_title.strip() if isinstance(widget_title, str) else "",
        data={
            "items": items,
            "source": source,
            "text": intro_text.strip() if isinstance(intro_text, str) else None,
            "filters": filters,
        },
    )


def _render_text(
    entry: WidgetEntry, authorization: AuthorizationContext, content: ContentRepository
) -> RenderedWidget:
    """Load a permission-checked Markdown page for a reusable text widget."""

    source = entry.config.get("source")
    if not isinstance(source, str):
        raise ValueError("requires a Markdown source page")
    try:
        source = normalize_relative_path(source)
    except UnsafePath as exc:
        raise ValueError("has an invalid source page") from exc
    if not source.endswith(".md") or path_depth(source) != 2:
        raise ValueError("source must be a book page such as research/about.md")
    if not authorization.policy.decide(source).can_read:
        return RenderedWidget(id=entry.id, type=entry.type, title="", data={"html": ""})
    try:
        _metadata, markdown, _raw = content.read_page(source)
    except (ContentError, UnsafePath):
        raise ValueError("source page could not be read") from None
    return RenderedWidget(
        id=entry.id,
        type=entry.type,
        title="",
        data={"source": source, "markdown": markdown},
    )


WIDGET_REGISTRY: dict[str, WidgetRenderer] = {
    "featured": _render_featured,
    "data-cards": _render_data_cards,
    # This is intentionally a named variant rather than a front-end-only
    # label: authors can select it directly when they want ADC Lab-style
    # category switches, while it shares the same portable source schema.
    "switching-cards": _render_data_cards,
    "text": _render_text,
}


def render_widgets(
    entries: list[WidgetEntry], authorization: AuthorizationContext, content: ContentRepository
) -> tuple[list[RenderedWidget], list[WidgetError]]:
    """Render every known widget entry, in its authored order.

    An entry whose ``type`` is not in :data:`WIDGET_REGISTRY` renders
    nothing; it is reported as a :class:`WidgetError` instead of raising, so
    a widget type from a newer version (or a hand-edited front matter)
    never takes down the rest of the page.
    """

    rendered: list[RenderedWidget] = []
    errors: list[WidgetError] = []
    for entry in entries:
        renderer = WIDGET_REGISTRY.get(entry.type)
        if renderer is None:
            errors.append(WidgetError(entry.id, f"unknown widget type '{entry.type}'"))
            continue
        try:
            rendered.append(renderer(entry, authorization, content))
        except ValueError as exc:
            errors.append(WidgetError(entry.id, f"widget '{entry.id}' {exc}"))
    return rendered, errors


def build_home_widgets(
    raw_widgets: Any, authorization: AuthorizationContext, content: ContentRepository
) -> HomeWidgetsResult:
    """Parse and render a Home page's ``widgets`` front matter in one call.

    This is the one entry point the editor/UI layer needs: it never raises.
    A malformed ``widgets`` value or an unknown widget type shows up in
    ``HomeWidgetsResult.errors`` instead of stopping Home from rendering the
    entries that are well-formed and known.
    """

    entries, parse_errors = parse_widget_entries(raw_widgets)
    rendered, render_errors = render_widgets(entries, authorization, content)
    return HomeWidgetsResult(rendered=rendered, errors=[*parse_errors, *render_errors])
