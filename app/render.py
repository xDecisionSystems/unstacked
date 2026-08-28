"""Safe, MkDocs-aligned Markdown rendering for the authenticated preview.

The preview deliberately is not a second static-site generator.  It shares
MkDocs' Markdown configuration, then renders one document and sanitizes the
result because wiki authors are not trusted to provide executable HTML.  A
future web route is responsible for authorizing and serving the ``/pages``
and ``/assets`` URLs produced here; this module never reads a linked file.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import bleach
import markdown
import yaml
from mkdocs.config import load_config

from app.paths import UnsafePath, normalize_relative_path


class RenderConfigurationError(RuntimeError):
    """The operator's MkDocs configuration cannot be used for preview."""


# These are presentation-only MkDocs plugins.  They do not alter how a single
# Markdown document is converted, so allowing one in a preview would make its
# presence look meaningful while silently ignoring it.  Keep the supported
# set explicit until a plugin has a tested preview equivalent.
_SUPPORTED_PLUGINS = frozenset({"search", "awesome-nav"})

# No style/event attributes, SVG, forms, embedded documents, or media are
# permitted.  Syntax-highlighting classes are harmless and make fenced code
# useful when a configured extension adds them.
_ALLOWED_TAGS = frozenset(
    {
        "a",
        "abbr",
        "blockquote",
        "br",
        "code",
        "del",
        "details",
        "div",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "img",
        "kbd",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strong",
        "summary",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_ALLOWED_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "a": ("href", "title"),
    "abbr": ("title",),
    "code": ("class",),
    "div": ("class",),
    "img": ("src", "alt", "title", "width", "height", "loading"),
    "span": ("class",),
    "td": ("align",),
    "th": ("align",),
}
_ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})

# These prefixes are deliberately route contracts rather than static-file
# paths.  T5.2/T2.5 will supply authenticated handlers; using a relative link
# here would make a page nested under a chapter resolve against the browser
# route instead of its Markdown location.
PREVIEW_PAGE_PREFIX = "/pages/"
PREVIEW_ASSET_PREFIX = "/assets/"


def _configured_plugin_names(config_path: Path) -> set[str]:
    """Read just enough YAML to reject plugins without a preview contract."""

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RenderConfigurationError("Cannot read MkDocs configuration for preview") from exc
    if not isinstance(raw, dict):
        raise RenderConfigurationError("MkDocs configuration must be a YAML mapping")
    plugins = raw.get("plugins", [])
    if plugins is None:
        return set()
    if not isinstance(plugins, list):
        raise RenderConfigurationError("MkDocs plugins must be a list for preview")
    names: set[str] = set()
    for entry in plugins:
        if isinstance(entry, str):
            names.add(entry)
        elif isinstance(entry, dict) and len(entry) == 1:
            name = next(iter(entry))
            if not isinstance(name, str):
                raise RenderConfigurationError("MkDocs plugin names must be strings")
            names.add(name)
        else:
            raise RenderConfigurationError("MkDocs plugin configuration is malformed")
    unsupported = sorted(names - _SUPPORTED_PLUGINS)
    if unsupported:
        joined = ", ".join(unsupported)
        raise RenderConfigurationError(
            f"Preview does not support configured MkDocs plugin(s): {joined}"
        )
    return names


def _load_markdown_settings(config_path: Path) -> tuple[list[str], dict[str, Any]]:
    """Use MkDocs' loader so preview follows its extension/default semantics."""

    _configured_plugin_names(config_path)
    try:
        config = load_config(config_file=str(config_path))
    except BaseException as exc:  # MkDocs can terminate config loading via SystemExit.
        if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
            raise
        raise RenderConfigurationError(
            "MkDocs configuration is invalid for preview; check configured Markdown extensions"
        ) from exc
    extensions = config["markdown_extensions"]
    extension_configs = config["mdx_configs"]
    if not isinstance(extensions, list) or not isinstance(extension_configs, dict):
        raise RenderConfigurationError("MkDocs Markdown configuration is malformed")
    return extensions, extension_configs


def _resolve_relative(source_path: str, target: str) -> str | None:
    """Resolve a docs-relative target, rejecting root escapes rather than repairing them."""

    if not target or target.startswith("/") or target.startswith("\\"):
        return None
    resolved: list[str] = []
    for part in (*PurePosixPath(source_path).parent.parts, *PurePosixPath(target).parts):
        if part in {"", "."}:
            continue
        if part == "..":
            if not resolved:
                return None
            resolved.pop()
        else:
            resolved.append(part)
    if not resolved:
        return None
    try:
        return normalize_relative_path("/".join(resolved))
    except UnsafePath:
        return None


def rewrite_contextual_url(url: str, source_path: str) -> str:
    """Map a safe Markdown-relative URL onto the authenticated preview routes.

    Absolute web/mail links and same-document fragments remain intact.  Links
    which attempt to traverse above ``docs/`` are not made clickable; Bleach
    will remove unsafe schemes in the final sanitization pass.
    """

    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return url
    target = _resolve_relative(source_path, parsed.path)
    if target is None:
        return ""
    if target.endswith(".md"):
        target = target[:-3]
        prefix = PREVIEW_PAGE_PREFIX
    else:
        prefix = PREVIEW_ASSET_PREFIX
    return urlunsplit(("", "", prefix + quote(target, safe="/"), parsed.query, parsed.fragment))


class MarkdownRenderer:
    """Render one content document with the repository's supported MkDocs config.

    Preview is semantically aligned with the static build's Markdown
    extensions.  It intentionally is not theme- or HTML-byte-identical to
    MkDocs, whose templates and page-wide plugins run only during a build.
    """

    def __init__(self, content_root: Path):
        self.content_root = Path(content_root)
        self.config_path = self.content_root / "mkdocs.yml"

    def render(self, source_path: str, source: str) -> str:
        """Return sanitized HTML for the validated docs-relative Markdown page."""

        try:
            normalized_source = normalize_relative_path(source_path)
        except UnsafePath as exc:
            raise ValueError("source path must be a docs-relative page path") from exc
        if not normalized_source.endswith(".md"):
            raise ValueError("source path must name a Markdown page")
        extensions, extension_configs = _load_markdown_settings(self.config_path)
        try:
            renderer = markdown.Markdown(
                extensions=extensions,
                extension_configs=extension_configs,
                output_format="html5",
            )
            rendered = renderer.convert(source)
        except (ImportError, KeyError, TypeError, ValueError) as exc:
            raise RenderConfigurationError(
                "Unsupported MkDocs Markdown extension for preview"
            ) from exc
        rewritten = _rewrite_html_urls(rendered, normalized_source)
        return bleach.clean(
            rewritten,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
            protocols=_ALLOWED_PROTOCOLS,
            strip=True,
        )


def _rewrite_html_urls(html: str, source_path: str) -> str:
    """Rewrite only href/src values in generated or input HTML before cleaning."""

    # Bleach's token filters are intentionally used instead of a regex: HTML
    # supplied by a wiki author may be malformed, quoted oddly, or repeated.
    class _ContextualLinkFilter(bleach.html5lib_shim.Filter):
        def __iter__(self):
            for token in super().__iter__():
                if token.get("type") in {"StartTag", "EmptyTag"}:
                    data = token.get("data", {})
                    for attribute in ((None, "href"), (None, "src")):
                        if attribute in data:
                            data[attribute] = rewrite_contextual_url(data[attribute], source_path)
                yield token

    cleaner = bleach.Cleaner(
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        filters=[_ContextualLinkFilter],
    )
    return cleaner.clean(html)
