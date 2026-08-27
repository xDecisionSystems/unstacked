from pathlib import Path

import pytest

from app.paths import UnsafePath, normalize_relative_path, safe_join


@pytest.mark.parametrize("value", ["../secret", "/absolute", "book\\page.md", ".git/config"])
def test_unsafe_relative_paths_are_rejected(value: str):
    with pytest.raises(UnsafePath):
        normalize_relative_path(value)


def test_symlink_escape_is_rejected(tmp_path: Path):
    docs = tmp_path / "docs"
    outside = tmp_path / "outside"
    docs.mkdir()
    outside.mkdir()
    (docs / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePath):
        safe_join(docs, "escape/secret.md")
