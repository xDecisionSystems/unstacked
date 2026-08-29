"""Palette math and persistence: app/theme.py and app/theme_config.py.

A wrong color is cosmetic, but a crash on a malformed palette record is not --
every page render depends on `theme_config.load` succeeding, so its
degrade-to-default behavior is exercised as thoroughly as the happy path.
"""

import json
from pathlib import Path

import pytest

from app import theme, theme_config
from app.theme import Palette

SAMPLE_PALETTE = Palette(
    accent="#123456", accent_secondary="#654321", warm="#abcdef", muted="#999999", text="#000000"
)


def test_normalize_hex_lowercases_and_strips():
    assert theme.normalize_hex(" #ABCDEF ") == "#abcdef"


@pytest.mark.parametrize(
    "value", ["abcdef", "#abcde", "#abcdefg", "#12345", "not-a-color", "#gggggg", ""]
)
def test_normalize_hex_rejects_malformed_input(value: str):
    with pytest.raises(ValueError, match="hex color"):
        theme.normalize_hex(value)


def test_palette_normalizes_every_field_on_construction():
    palette = Palette(
        accent=" #00CA8C ",
        accent_secondary="#8CD47E",
        warm="#FFB54C",
        muted="#808080",
        text="#002E5D",
    )
    assert palette.accent == "#00ca8c"
    assert palette.text == "#002e5d"


def test_palette_rejects_a_malformed_field():
    with pytest.raises(ValueError, match="hex color"):
        Palette(
            accent="not-a-color",
            accent_secondary="#8cd47e",
            warm="#ffb54c",
            muted="#808080",
            text="#002e5d",
        )


def test_every_preset_is_internally_consistent():
    assert set(theme.PRESETS) == set(theme.PRESET_LABELS)
    assert theme.DEFAULT_PRESET in theme.PRESETS
    for palette in theme.PRESETS.values():
        for field in theme.PALETTE_FIELDS:
            value = getattr(palette, field)
            assert theme.normalize_hex(value) == value


def test_darken_moves_every_channel_toward_black():
    assert theme.darken("#ffffff", 0.5) == "#808080"
    assert theme.darken("#00ca8c", 0.0) == "#00ca8c"


def test_tint_moves_every_channel_toward_white():
    assert theme.tint("#000000", 0.5) == "#808080"
    assert theme.tint("#00ca8c", 1.0) == "#ffffff"


def test_derived_variables_include_the_two_computed_shades():
    palette = theme.PRESETS[theme.DEFAULT_PRESET]
    variables = theme.derived_variables(palette)
    assert variables["accent"] == palette.accent
    assert variables["accent-dark"] != palette.accent
    assert variables["bg-alt"] != palette.accent
    assert theme.normalize_hex(variables["accent-dark"]) == variables["accent-dark"]
    assert theme.normalize_hex(variables["bg-alt"]) == variables["bg-alt"]


def test_css_block_is_a_single_root_rule_with_every_variable():
    palette = theme.PRESETS[theme.DEFAULT_PRESET]
    block = theme.css_block(palette)
    assert block.startswith(":root{") and block.endswith("}")
    for name in ("accent", "accent-secondary", "warm", "muted", "text", "accent-dark", "bg-alt"):
        assert f"--{name}:" in block


# --------------------------------------------------------------------------
# theme_config persistence
# --------------------------------------------------------------------------


def test_load_with_no_file_returns_the_default_preset(tmp_path: Path):
    state = theme_config.load(tmp_path / "theme.json")
    assert state.mode == "preset"
    assert state.preset == theme.DEFAULT_PRESET
    assert state.palette == theme.PRESETS[theme.DEFAULT_PRESET]


def test_save_preset_then_load_round_trips(tmp_path: Path):
    path = tmp_path / "theme.json"
    saved = theme_config.save_preset(path, "ocean-blue")
    assert saved.mode == "preset"
    assert saved.preset == "ocean-blue"
    assert saved.updated_at is not None
    loaded = theme_config.load(path)
    assert loaded.mode == "preset"
    assert loaded.preset == "ocean-blue"
    assert loaded.palette == theme.PRESETS["ocean-blue"]


def test_save_preset_rejects_an_unknown_preset(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown palette preset"):
        theme_config.save_preset(tmp_path / "theme.json", "no-such-preset")


def test_save_custom_then_load_round_trips(tmp_path: Path):
    path = tmp_path / "theme.json"
    palette = SAMPLE_PALETTE
    saved = theme_config.save_custom(path, palette)
    assert saved.mode == "custom"
    assert saved.preset is None
    loaded = theme_config.load(path)
    assert loaded.mode == "custom"
    assert loaded.preset is None
    assert loaded.palette == palette


def test_a_missing_file_is_the_default_not_an_error(tmp_path: Path):
    assert theme_config.load(tmp_path / "nested" / "theme.json") == theme_config.DEFAULT_STATE


def test_unreadable_json_falls_back_to_the_default(tmp_path: Path):
    path = tmp_path / "theme.json"
    path.write_text("not json at all", encoding="utf-8")
    assert theme_config.load(path) == theme_config.DEFAULT_STATE


def test_an_unknown_version_falls_back_to_the_default(tmp_path: Path):
    path = tmp_path / "theme.json"
    record = {"version": 999, "mode": "preset", "preset": "ocean-blue"}
    path.write_text(json.dumps(record), encoding="utf-8")
    assert theme_config.load(path) == theme_config.DEFAULT_STATE


def test_a_preset_record_naming_an_unknown_preset_falls_back_to_the_default(tmp_path: Path):
    path = tmp_path / "theme.json"
    path.write_text(
        json.dumps({"version": 1, "mode": "preset", "preset": "no-such-preset"}), encoding="utf-8"
    )
    assert theme_config.load(path) == theme_config.DEFAULT_STATE


def test_a_custom_record_with_an_invalid_color_falls_back_to_the_default(tmp_path: Path):
    path = tmp_path / "theme.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "mode": "custom",
                "palette": {
                    "accent": "not-a-color",
                    "accent_secondary": "#654321",
                    "warm": "#abcdef",
                    "muted": "#999999",
                    "text": "#000000",
                },
            }
        ),
        encoding="utf-8",
    )
    assert theme_config.load(path) == theme_config.DEFAULT_STATE


def test_a_record_naming_an_unknown_mode_falls_back_to_the_default(tmp_path: Path):
    path = tmp_path / "theme.json"
    path.write_text(json.dumps({"version": 1, "mode": "psychedelic"}), encoding="utf-8")
    assert theme_config.load(path) == theme_config.DEFAULT_STATE


def test_saving_again_replaces_the_previous_selection(tmp_path: Path):
    path = tmp_path / "theme.json"
    theme_config.save_preset(path, "ocean-blue")
    theme_config.save_custom(path, SAMPLE_PALETTE)
    loaded = theme_config.load(path)
    assert loaded.mode == "custom"
    assert loaded.palette == SAMPLE_PALETTE
