"""Safe management of awesome-nav v3 ``.pages`` files.

The content service owns the surrounding Git transaction.  This module only
reads and atomically writes a single navigation file, so callers can include
it with the content paths in one commit.
"""

from __future__ import annotations

import copy
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class NavigationError(ValueError):
    """A ``.pages`` file cannot safely be interpreted or changed."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader which treats duplicate keys as malformed configuration."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise NavigationError("navigation keys must be strings")
        if key in mapping:
            raise NavigationError(f"duplicate key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


@dataclass(frozen=True)
class Navigation:
    """A parsed ``.pages`` mapping, including pass-through plugin settings."""

    values: dict[str, Any]

    @property
    def title(self) -> str | None:
        value = self.values.get("title")
        return value if isinstance(value, str) else None

    @property
    def entries(self) -> list[Any] | None:
        value = self.values.get("nav")
        return copy.deepcopy(value) if isinstance(value, list) else None


def new_navigation(title: str) -> Navigation:
    """Return the default explicit container navigation used by Unstacked."""

    _validate_title(title)
    return Navigation({"title": title, "nav": ["*"]})


def parse_navigation(text: str, *, source: str = ".pages") -> Navigation:
    """Parse ``.pages`` text without performing filesystem I/O.

    Content lifecycle operations use this boundary when their directory access
    is confined to a descriptor rooted at ``docs/``.  ``source`` is only used
    in operator-facing validation errors; it never identifies a path to read.
    """

    if not isinstance(text, str):
        raise NavigationError(f"malformed navigation file {source}: expected text")
    try:
        parsed = yaml.load(text, Loader=_UniqueKeyLoader)
    except (yaml.YAMLError, NavigationError) as exc:
        raise NavigationError(f"malformed navigation file {source}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise NavigationError(f"malformed navigation file {source}: top level must be a mapping")
    if any(not isinstance(key, str) for key in parsed):
        raise NavigationError(f"malformed navigation file {source}: keys must be strings")
    _validate_values(source, parsed)
    return Navigation(copy.deepcopy(parsed))


def serialize_navigation(navigation: Navigation, *, source: str = ".pages") -> str:
    """Validate and serialize navigation as UTF-8-safe YAML without I/O."""

    values = copy.deepcopy(navigation.values)
    _validate_values(source, values)
    return yaml.safe_dump(values, allow_unicode=True, default_flow_style=False, sort_keys=False)


def read_navigation(path: Path) -> Navigation:
    """Parse one existing ``.pages`` file without changing it on failure."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NavigationError(f"cannot read navigation file {path}: {exc.strerror}") from exc
    return parse_navigation(raw, source=str(path))


def write_navigation(path: Path, navigation: Navigation) -> None:
    """Atomically replace a valid navigation file, retaining all its keys."""

    serialized = serialize_navigation(navigation, source=str(path))
    _atomic_write(path, serialized)


def create_navigation(path: Path, title: str) -> None:
    """Create a new container navigation file; never silently overwrite one."""

    if path.exists():
        raise NavigationError(f"navigation file already exists: {path}")
    write_navigation(path, new_navigation(title))


def set_title(path: Path, title: str) -> Navigation:
    """Set a container display title while preserving all other settings."""

    _validate_title(title)
    navigation = read_navigation(path)
    values = copy.deepcopy(navigation.values)
    values["title"] = title
    result = Navigation(values)
    write_navigation(path, result)
    return result


def set_order(path: Path, entries: list[str]) -> Navigation:
    """Set an explicit awesome-nav order while retaining pass-through keys."""

    if not isinstance(entries, list) or any(
        not isinstance(entry, str) or not entry for entry in entries
    ):
        raise NavigationError("navigation entries must be non-empty strings")
    if len(set(entries)) != len(entries):
        raise NavigationError("navigation entries must not contain duplicates")
    navigation = read_navigation(path)
    values = copy.deepcopy(navigation.values)
    values["nav"] = list(entries)
    result = Navigation(values)
    write_navigation(path, result)
    return result


def remove_stale_entry(path: Path, entry: str) -> Navigation:
    """Remove direct stale entries after a delete, leaving globs/maps intact."""

    if not isinstance(entry, str) or not entry:
        raise NavigationError("navigation entry must be a non-empty string")
    navigation = read_navigation(path)
    values = copy.deepcopy(navigation.values)
    entries = values.get("nav")
    if entries is None:
        return navigation
    # A mapping can be a supported awesome-nav nested declaration.  It is not
    # safe to infer its target, so only exact direct entries are removed.
    values["nav"] = [candidate for candidate in entries if candidate != entry]
    result = Navigation(values)
    write_navigation(path, result)
    return result


def _validate_title(title: object) -> None:
    if not isinstance(title, str) or not title.strip():
        raise NavigationError("navigation title must be a non-empty string")


def _validate_values(source: str, values: dict[str, Any]) -> None:
    title = values.get("title")
    if title is not None:
        try:
            _validate_title(title)
        except NavigationError as exc:
            raise NavigationError(f"malformed navigation file {source}: {exc}") from exc
    entries = values.get("nav")
    if entries is not None and not isinstance(entries, list):
        raise NavigationError(f"malformed navigation file {source}: nav must be a list")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary_path = Path(temporary)
    try:
        if current_mode is not None:
            os.fchmod(descriptor, current_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
