"""The web UI's color palette: four built-in presets plus a validated custom one.

Deliberately five roles, not the full set of CSS custom properties in
``style.css``.  ``--border``, ``--bg`` and ``--danger`` stay fixed regardless
of palette -- a delete/revoke control reading as "danger" matters more than
palette purism, and a neutral border/background keeps every palette legible.
``--accent-dark`` and ``--bg-alt`` are not stored themselves; they are
*derived* from ``accent`` by :func:`derived_variables` so a custom palette
never has to supply a hover shade or a tint by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

PALETTE_FIELDS = ("accent", "accent_secondary", "warm", "muted", "text")

# Uniform, not hand-picked per palette: a custom palette gets the same
# treatment as a preset.  Chosen to land close to the original hand-tuned
# Future Green shades (`--accent-dark: #00a374`, `--bg-alt: #eefaf5`) without
# depending on values that only existed for that one palette.
ACCENT_DARK_AMOUNT = 0.18
BG_ALT_TINT_AMOUNT = 0.92


def normalize_hex(value: str) -> str:
    """Return ``value`` as a lowercase ``#rrggbb`` string, or raise ``ValueError``."""

    candidate = value.strip()
    if not _HEX_RE.match(candidate):
        raise ValueError(f"{value!r} must be a #rrggbb hex color")
    return candidate.lower()


@dataclass(frozen=True)
class Palette:
    """Five hex colors, normalized on construction."""

    accent: str
    accent_secondary: str
    warm: str
    muted: str
    text: str

    def __post_init__(self) -> None:
        for name in PALETTE_FIELDS:
            object.__setattr__(self, name, normalize_hex(getattr(self, name)))


# Slug -> display label, in the order the admin UI presents them.
PRESET_LABELS: dict[str, str] = {
    "future-green": "Future Green",
    "ocean-blue": "Ocean Blue",
    "sunset-coral": "Sunset Coral",
    "slate-mono": "Slate Mono",
}

PRESETS: dict[str, Palette] = {
    # The brand palette applied earlier: eco-conscious mint green, warm
    # orange, soft lime, neutral gray, deep navy text.
    "future-green": Palette(
        accent="#00ca8c",
        accent_secondary="#8cd47e",
        warm="#ffb54c",
        muted="#808080",
        text="#002e5d",
    ),
    "ocean-blue": Palette(
        accent="#0077b6",
        accent_secondary="#48cae4",
        warm="#f4a261",
        muted="#6c757d",
        text="#03045e",
    ),
    "sunset-coral": Palette(
        accent="#e85d04",
        accent_secondary="#2a9d8f",
        warm="#ffba08",
        muted="#6c757d",
        text="#6a040f",
    ),
    "slate-mono": Palette(
        accent="#3b5bdb",
        accent_secondary="#748ffc",
        warm="#f08c00",
        muted="#868e96",
        text="#212529",
    ),
}

DEFAULT_PRESET = "future-green"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(channel))):02x}" for channel in rgb)


def darken(hex_color: str, amount: float) -> str:
    """Multiply each channel by ``1 - amount``, moving the color toward black."""

    r, g, b = _hex_to_rgb(hex_color)
    factor = 1 - amount
    return _rgb_to_hex((r * factor, g * factor, b * factor))


def tint(hex_color: str, amount: float) -> str:
    """Mix each channel toward white by ``amount``."""

    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(
        (
            r + (255 - r) * amount,
            g + (255 - g) * amount,
            b + (255 - b) * amount,
        )
    )


def derived_variables(palette: Palette) -> dict[str, str]:
    """CSS custom-property names (hyphenated) to values for one palette."""

    return {
        "accent": palette.accent,
        "accent-secondary": palette.accent_secondary,
        "warm": palette.warm,
        "muted": palette.muted,
        "text": palette.text,
        "accent-dark": darken(palette.accent, ACCENT_DARK_AMOUNT),
        "bg-alt": tint(palette.accent, BG_ALT_TINT_AMOUNT),
    }


def css_block(palette: Palette) -> str:
    """A ``:root{...}`` declaration overriding just the palette variables."""

    body = "".join(f"--{name}:{value};" for name, value in derived_variables(palette).items())
    return f":root{{{body}}}"
