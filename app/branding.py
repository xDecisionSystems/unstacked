"""Small, operator-owned branding configuration for the web header."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.assets import detect_image
from app.backup_config import write_private_bytes

DEFAULT_NAME = "Unstacked"
DEFAULT_LOGO_URL = "/static/branding/badger-typewriter.png"
DEFAULT_HOME_EYEBROW = "KNOWLEDGE WORKSPACE"
DEFAULT_HOME_TITLE = "Home"
DEFAULT_HOME_DESCRIPTION = "Your featured books and pages."
DEFAULT_FEATURED_LABEL = "Featured"


@dataclass(frozen=True)
class Branding:
    name: str = DEFAULT_NAME
    logo_url: str = DEFAULT_LOGO_URL
    updated_at: str | None = None
    home_eyebrow: str = DEFAULT_HOME_EYEBROW
    home_title: str = DEFAULT_HOME_TITLE
    home_description: str = DEFAULT_HOME_DESCRIPTION
    featured_label: str = DEFAULT_FEATURED_LABEL


def load(path: Path) -> Branding:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Branding()
    name = data.get("name") if isinstance(data, dict) else None
    logo_url = data.get("logo_url") if isinstance(data, dict) else None
    updated_at = data.get("updated_at") if isinstance(data, dict) else None
    def text(key: str, default: str, *, blank: bool = False) -> str:
        value = data.get(key) if isinstance(data, dict) else None
        return value.strip() if isinstance(value, str) and (value.strip() or blank) else default
    return Branding(
        name=name.strip() if isinstance(name, str) and name.strip() else DEFAULT_NAME,
        logo_url=(
            logo_url if isinstance(logo_url, str) and logo_url.startswith("/") else DEFAULT_LOGO_URL
        ),
        updated_at=updated_at if isinstance(updated_at, str) else None,
        home_eyebrow=text("home_eyebrow", DEFAULT_HOME_EYEBROW),
        home_title=text("home_title", DEFAULT_HOME_TITLE),
        home_description=text("home_description", DEFAULT_HOME_DESCRIPTION, blank=True),
        featured_label=text("featured_label", DEFAULT_FEATURED_LABEL, blank=True),
    )


def save(
    path: Path, *, name: str, logo_url: str | None = None,
    home_eyebrow: str | None = None, home_title: str | None = None,
    home_description: str | None = None, featured_label: str | None = None,
) -> Branding:
    current = load(path)
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 100:
        raise ValueError("Brand name must be between 1 and 100 characters")
    state = Branding(
        cleaned, logo_url or current.logo_url, datetime.now(timezone.utc).isoformat(),
        home_eyebrow if home_eyebrow is not None else current.home_eyebrow,
        home_title if home_title is not None else current.home_title,
        home_description if home_description is not None else current.home_description,
        featured_label if featured_label is not None else current.featured_label,
    )
    write_private_bytes(path, (json.dumps(state.__dict__, indent=2) + "\n").encode())
    return state


def store_logo(path: Path, data: bytes, *, max_pixels: int, max_dimension: int) -> Branding:
    detect_image(data, max_pixels=max_pixels, max_dimension=max_dimension)
    logo_path = path.with_name("branding-logo")
    write_private_bytes(logo_path, data)
    return save(path, name=load(path).name, logo_url="/branding/logo")
