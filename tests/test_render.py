import os
from pathlib import Path

import pytest

from app.render import MarkdownRenderer, RenderConfigurationError, rewrite_contextual_url


def _renderer(tmp_path: Path, config: str | None = None) -> MarkdownRenderer:
    root = tmp_path / "content"
    (root / "docs").mkdir(parents=True)
    (root / "mkdocs.yml").write_text(
        config
        or """site_name: Render test
plugins:
  - search
  - awesome-nav:
      filename: .pages
markdown_extensions:
  - admonition
  - fenced_code
  - tables
""",
        encoding="utf-8",
    )
    return MarkdownRenderer(root)


def test_preview_uses_mkdocs_markdown_extensions(tmp_path: Path) -> None:
    html = _renderer(tmp_path).render(
        "book/chapter/page.md",
        """!!! note "A note"
    Preview semantics matter.

```python
print("safe")
```

| heading | value |
| --- | --- |
| one | two |
""",
    )
    assert "admonition" in html
    assert "<pre><code" in html
    assert "language-python" in html
    assert "<table>" in html


def test_preview_rewrites_relative_links_and_assets(tmp_path: Path) -> None:
    html = _renderer(tmp_path).render(
        "book/chapter/page.md",
        "[Sibling](other.md?mode=edit#part) ![Diagram](../../assets/book/diagram.png)",
    )
    assert 'href="/pages/book/chapter/other?mode=edit#part"' in html
    assert 'src="/assets/assets/book/diagram.png"' in html


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.test/path", "https://example.test/path"),
        ("#heading", "#heading"),
        ("../../../../secret.md", ""),
    ],
)
def test_contextual_rewrite_preserves_external_and_blocks_escapes(url: str, expected: str) -> None:
    assert rewrite_contextual_url(url, "book/chapter/page.md") == expected


def test_preview_strips_active_html_and_unsafe_urls(tmp_path: Path) -> None:
    html = _renderer(tmp_path).render(
        "book/page.md",
        '<script>alert(1)</script><a href="javascript:alert(1)" onclick="run()">bad</a>'
        '<img src="data:text/html,boom" onerror="run()">**kept**',
    )
    assert "script" not in html
    assert "javascript:" not in html
    assert "onerror" not in html
    assert "onclick" not in html
    assert "data:" not in html
    assert "<strong>kept</strong>" in html


def test_unsupported_plugin_has_actionable_error(tmp_path: Path) -> None:
    renderer = _renderer(
        tmp_path,
        """site_name: Render test
plugins:
  - search
  - macros
""",
    )
    with pytest.raises(RenderConfigurationError, match="macros"):
        renderer.render("book/page.md", "hello")


def test_unknown_markdown_extension_has_actionable_error(tmp_path: Path) -> None:
    renderer = _renderer(
        tmp_path,
        """site_name: Render test
plugins:
  - search
markdown_extensions:
  - definitely.not.an.extension
""",
    )
    with pytest.raises(RenderConfigurationError, match="Markdown extension"):
        renderer.render("book/page.md", "hello")


def test_repeated_renders_reuse_the_cached_mkdocs_config(tmp_path: Path, monkeypatch) -> None:
    """A page with several source-backed widgets calls render() once per
    widget/card in one request. Before caching, each call independently
    re-ran MkDocs' full config loader against the same unchanged file.
    """

    import app.render as render_module

    renderer = _renderer(tmp_path)
    calls = []
    real_load_config = render_module.load_config

    def counting_load_config(*args, **kwargs):
        calls.append(1)
        return real_load_config(*args, **kwargs)

    monkeypatch.setattr(render_module, "load_config", counting_load_config)

    renderer.render("book/page.md", "one")
    renderer.render("book/page.md", "two")
    assert len(calls) == 1, "second render() must reuse the cached config, not reload it"

    # Touching the file (even with unchanged content, to guarantee a new
    # mtime on any filesystem's timestamp resolution) must invalidate the
    # cache -- editing mkdocs.yml must not require restarting the app.
    config_path = tmp_path / "content" / "mkdocs.yml"
    new_mtime = config_path.stat().st_mtime + 1
    config_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    os.utime(config_path, (new_mtime, new_mtime))
    renderer.render("book/page.md", "three")
    assert len(calls) == 2, "a changed config file must trigger a fresh load"
