"""Runtime-editable persistence for the admin-selected color palette.

Same precedent as :mod:`app.backup_config`: a small operator-facing record
lives in a file under ``data/`` rather than a table, because it is deployment
/ presentation configuration, not wiki data. The database keeps exactly four
tables (see ``app/models.py``); a color palette is not a fifth.

There is no environment-variable fallback here (unlike the backup target):
a palette has no deployment-time equivalent to precede it, so the only two
states are "no file yet" (the default preset applies) and "a saved record"
(it wins outright). A missing or unparsable file is treated as "no file yet"
rather than an error -- a bad record must never stop the wiki from serving
pages, and a wrong palette is cosmetic, never a correctness or security
concern.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import theme
from app.backup_config import write_private_bytes
from app.theme import Palette

logger = logging.getLogger("unstacked.theme")

RECORD_VERSION = 1

MODE_PRESET = "preset"
MODE_CUSTOM = "custom"


@dataclass(frozen=True)
class ThemeState:
    """The effective palette selection, whatever its source."""

    mode: str
    preset: str | None
    palette: Palette
    updated_at: str | None = None


DEFAULT_STATE = ThemeState(
    mode=MODE_PRESET,
    preset=theme.DEFAULT_PRESET,
    palette=theme.PRESETS[theme.DEFAULT_PRESET],
)


def load(path: Path) -> ThemeState:
    """Read the persisted selection, or the default preset if there is none.

    Mirrors :func:`app.backup_config.load`'s degrade-don't-crash shape: any
    problem with the file (missing, unreadable, malformed, an unknown preset
    key, an unknown version) falls back to :data:`DEFAULT_STATE` rather than
    raising, since every page render depends on this succeeding.
    """

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULT_STATE
    except OSError:
        logger.warning("theme configuration at %s could not be read; using the default", path)
        return DEFAULT_STATE
    try:
        record = json.loads(raw)
    except ValueError:
        logger.warning("theme configuration at %s is not valid JSON; using the default", path)
        return DEFAULT_STATE
    if not isinstance(record, dict) or record.get("version") != RECORD_VERSION:
        logger.warning("theme configuration at %s has an unknown shape; using the default", path)
        return DEFAULT_STATE
    updated_at = record.get("updated_at")
    updated_at = updated_at if isinstance(updated_at, str) else None
    mode = record.get("mode")
    if mode == MODE_PRESET:
        preset = record.get("preset")
        palette = theme.PRESETS.get(preset) if isinstance(preset, str) else None
        if palette is None:
            logger.warning("theme configuration at %s names an unknown preset", path)
            return DEFAULT_STATE
        return ThemeState(mode=MODE_PRESET, preset=preset, palette=palette, updated_at=updated_at)
    if mode == MODE_CUSTOM:
        raw_palette = record.get("palette")
        if not isinstance(raw_palette, dict):
            logger.warning("theme configuration at %s has no custom palette", path)
            return DEFAULT_STATE
        try:
            palette = Palette(
                **{field: raw_palette.get(field, "") for field in theme.PALETTE_FIELDS}
            )
        except (ValueError, TypeError):
            logger.warning("theme configuration at %s has an invalid custom palette", path)
            return DEFAULT_STATE
        return ThemeState(mode=MODE_CUSTOM, preset=None, palette=palette, updated_at=updated_at)
    logger.warning("theme configuration at %s names an unknown mode", path)
    return DEFAULT_STATE


def save_preset(path: Path, preset: str) -> ThemeState:
    """Select a built-in preset by its slug."""

    if preset not in theme.PRESETS:
        raise ValueError(f"unknown palette preset {preset!r}")
    state = ThemeState(
        mode=MODE_PRESET,
        preset=preset,
        palette=theme.PRESETS[preset],
        updated_at=_now(),
    )
    _write(path, state)
    return state


def save_custom(path: Path, palette: Palette) -> ThemeState:
    """Select an explicit, already-validated custom palette."""

    state = ThemeState(mode=MODE_CUSTOM, preset=None, palette=palette, updated_at=_now())
    _write(path, state)
    return state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, state: ThemeState) -> None:
    record: dict[str, object] = {
        "version": RECORD_VERSION,
        "mode": state.mode,
        "updated_at": state.updated_at,
    }
    if state.mode == MODE_PRESET:
        record["preset"] = state.preset
    else:
        record["palette"] = {field: getattr(state.palette, field) for field in theme.PALETTE_FIELDS}
    write_private_bytes(path, json.dumps(record, indent=2).encode("utf-8") + b"\n")
