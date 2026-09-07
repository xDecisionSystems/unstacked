"""The web UI's color palette: four built-in presets plus a validated custom one.

The palette has six editable roles, not the full set of CSS custom properties in
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

PALETTE_FIELDS = ("accent", "accent_secondary", "warm", "muted", "text", "chrome")

# Uniform, not hand-picked per palette: a custom palette gets the same
# treatment as a preset. This keeps hover shades and background tints
# coherent without requiring extra manual colors.
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
    """Six hex colors, normalized on construction."""

    accent: str
    accent_secondary: str
    warm: str
    muted: str
    text: str
    chrome: str

    def __post_init__(self) -> None:
        for name in PALETTE_FIELDS:
            object.__setattr__(self, name, normalize_hex(getattr(self, name)))


# Slug -> display label, in the order the admin UI presents them.
PRESET_LABELS: dict[str, str] = {
    "future-green": "Heritage Orange",
    "ocean-blue": "Harbor Ink",
    "sunset-coral": "Orchard Editorial",
    "slate-mono": "Slate Apricot",
    "ucf-black-gold": "Pegasus Nights",
}

PRESETS: dict[str, Palette] = {
    # Figma palette review directions. The stable keys preserve existing
    # saved preset selections while their visible names and values evolve.
    "future-green": Palette(
        accent="#e76f25",
        accent_secondary="#4d7c57",
        warm="#fce1cf",
        muted="#8c847c",
        text="#3b0d1b",
        chrome="#fffdf9",
    ),
    "ocean-blue": Palette(
        accent="#167c80",
        accent_secondary="#5c9a83",
        warm="#d9eeee",
        muted="#71808a",
        text="#17263c",
        chrome="#17263c",
    ),
    "sunset-coral": Palette(
        accent="#4d7c57",
        accent_secondary="#7c9c6d",
        warm="#dce8d2",
        muted="#72806d",
        text="#2f3a27",
        chrome="#e1ecd7",
    ),
    "slate-mono": Palette(
        accent="#4255a4",
        accent_secondary="#8092d1",
        warm="#d8def8",
        muted="#747b92",
        text="#212836",
        chrome="#e5e9fa",
    ),
    # UCF's official digital colors are black and bright gold (#FFC904).
    # Warm and secondary tones support readable controls without introducing
    # a competing brand color.
    "ucf-black-gold": Palette(
        accent="#ffc904",
        accent_secondary="#7a5e00",
        warm="#fff0b3",
        muted="#5c5c5c",
        text="#000000",
        chrome="#000000",
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


def relative_luminance(hex_color: str) -> float:
    """Return the WCAG relative luminance of a hex color."""

    channels = _hex_to_rgb(hex_color)

    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def derived_variables(palette: Palette) -> dict[str, str]:
    """CSS custom-property names (hyphenated) to values for one palette."""

    dark_chrome = relative_luminance(palette.chrome) < 0.4
    light_accent = relative_luminance(palette.accent) > 0.45
    return {
        "accent": palette.accent,
        "accent-secondary": palette.accent_secondary,
        "warm": palette.warm,
        "muted": palette.muted,
        "text": palette.text,
        "chrome": palette.chrome,
        "chrome-text": "#fffdf9" if dark_chrome else palette.text,
        "chrome-text-soft": "#dce5ed" if dark_chrome else darken(palette.text, 0.18),
        "accent-text": "#000000" if light_accent else "#fffdf9",
        "accent-dark": darken(palette.accent, ACCENT_DARK_AMOUNT),
        "bg-alt": tint(palette.accent, BG_ALT_TINT_AMOUNT),
    }


def css_block(palette: Palette) -> str:
    """A ``:root{...}`` declaration that applies the palette to the live UI.

    The stylesheet predates the palette feature and uses its original semantic
    names (``--orange``, ``--burgundy``, and ``--tag``) throughout. Override
    those names too; setting only the newer ``--accent`` aliases would save a
    palette successfully but leave the rendered interface unchanged.
    """

    values = derived_variables(palette)
    values.update(
        {
            "orange": palette.accent,
            "orange-dark": values["accent-dark"],
            "tag": palette.warm,
            "burgundy": palette.text,
            "burgundy-soft": darken(palette.text, 0.18),
            "canvas": values["bg-alt"],
            "surface-subtle": tint(palette.warm, 0.78),
            "green": palette.accent_secondary,
            "selection": tint(palette.warm, 0.68),
        }
    )
    body = "".join(f"--{name}:{value};" for name, value in values.items())
    return f":root{{{body}}}"
