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


@dataclass(frozen=True)
class Branding:
    name: str = DEFAULT_NAME
    logo_url: str = DEFAULT_LOGO_URL
    updated_at: str | None = None


def load(path: Path) -> Branding:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Branding()
    name = data.get("name") if isinstance(data, dict) else None
    logo_url = data.get("logo_url") if isinstance(data, dict) else None
    updated_at = data.get("updated_at") if isinstance(data, dict) else None
    return Branding(
        name=name.strip() if isinstance(name, str) and name.strip() else DEFAULT_NAME,
        logo_url=(
            logo_url if isinstance(logo_url, str) and logo_url.startswith("/") else DEFAULT_LOGO_URL
        ),
        updated_at=updated_at if isinstance(updated_at, str) else None,
    )


def save(path: Path, *, name: str, logo_url: str | None = None) -> Branding:
    current = load(path)
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 100:
        raise ValueError("Brand name must be between 1 and 100 characters")
    state = Branding(cleaned, logo_url or current.logo_url, datetime.now(timezone.utc).isoformat())
    write_private_bytes(path, (json.dumps(state.__dict__, indent=2) + "\n").encode())
    return state


def store_logo(path: Path, data: bytes, *, max_pixels: int, max_dimension: int) -> Branding:
    detect_image(data, max_pixels=max_pixels, max_dimension=max_dimension)
    logo_path = path.with_name("branding-logo")
    write_private_bytes(logo_path, data)
    return save(path, name=load(path).name, logo_url="/branding/logo")
