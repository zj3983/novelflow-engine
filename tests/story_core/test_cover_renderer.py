from __future__ import annotations

import io
import inspect
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageFont

from packages.story_core.cover_renderer import CoverRenderError, render_cover


CANVAS = (768, 1024)
BASE = (19, 45, 79)
WINDOWS_CJK_FONT = Path("C:/Windows/Fonts/msyh.ttc")


def _font_path() -> Path:
    if WINDOWS_CJK_FONT.is_file():
        return WINDOWS_CJK_FONT
    pytest.skip("a Windows CJK font is required for deterministic renderer tests")


def _image_bytes(
    image_format: str = "PNG", *, size: tuple[int, int] = (400, 400), color=BASE
) -> bytes:
    image = Image.new("RGB", size, color=color)
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def _cover(data: bytes, title: str, *, font: Path | None = None) -> Image.Image:
    rendered = render_cover(data, title, font_path=font or _font_path())
    result = Image.open(io.BytesIO(rendered))
    result.load()
    return result.convert("RGB")


def _title_bbox(rendered: Image.Image) -> tuple[int, int, int, int]:
    background = Image.new("RGB", CANVAS, BASE)
    box = ImageChops.difference(rendered.convert("RGB"), background).getbbox()
    assert box is not None
    return box


def test_render_cover_returns_a_metadata_free_768_by_1024_png() -> None:
    rendered = render_cover(_image_bytes(), "星河", font_path=_font_path())

    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.size == CANVAS
        assert image.info == {}


def test_render_cover_center_crops_base_art_without_stretching() -> None:
    source = Image.new("RGB", (400, 100), color=(0, 0, 0))
    source.paste((255, 0, 0), (0, 0, 100, 100))
    source.paste((0, 0, 255), (300, 0, 400, 100))
    output = io.BytesIO()
    source.save(output, format="PNG")

    rendered = _cover(output.getvalue(), "星河")

    assert rendered.getpixel((20, 20)) == (0, 0, 0)
    assert rendered.getpixel((748, 20)) == (0, 0, 0)


def test_short_chinese_title_uses_tall_vertical_layout_inside_safe_margins() -> None:
    rendered = _cover(_image_bytes(), "星河长明")
    left, top, right, bottom = _title_bbox(rendered)

    assert right - left < 300
    assert bottom - top > 350
    assert 32 <= left < right <= 736
    assert 48 <= top < bottom <= 976


def test_six_character_chinese_title_still_uses_vertical_layout() -> None:
    rendered = _cover(_image_bytes(), "星河长明万古")
    left, top, right, bottom = _title_bbox(rendered)

    assert right - left < 300
    assert bottom - top > 500


def test_seven_character_title_switches_to_wrapped_horizontal_layout() -> None:
    rendered = _cover(_image_bytes(), "星河长明万古不")
    left, top, right, bottom = _title_bbox(rendered)

    assert right - left > bottom - top
    assert right - left > 350


def test_mixed_ascii_and_chinese_title_wraps_without_clipping() -> None:
    rendered = _cover(_image_bytes(), "The Last 星河守夜人 Chronicles")
    left, top, right, bottom = _title_bbox(rendered)

    assert 32 <= left < right <= 736
    assert 48 <= top < bottom <= 976
    assert right - left > 350


def test_title_has_light_fill_dark_stroke_and_offset_shadow() -> None:
    rendered = _cover(_image_bytes(), "星河")
    colors = {color for _count, color in rendered.getcolors(CANVAS[0] * CANVAS[1]) or []}

    assert (255, 242, 186) in colors
    assert (34, 19, 25) in colors
    assert (0, 0, 0) in colors


@pytest.mark.parametrize("image_format", ["JPEG", "WEBP"])
def test_render_cover_always_encodes_png_from_supported_source_formats(image_format: str) -> None:
    rendered = render_cover(_image_bytes(image_format), "星河", font_path=_font_path())
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.size == CANVAS


def test_explicit_font_path_takes_precedence_over_environment(monkeypatch, tmp_path) -> None:
    environment_font = tmp_path / "missing.ttf"
    monkeypatch.setenv("NOVEL_COVER_FONT_PATH", str(environment_font))

    assert render_cover(_image_bytes(), "星河", font_path=_font_path()).startswith(b"\x89PNG")


def test_explicit_missing_or_broken_font_is_a_terminal_stable_error(tmp_path) -> None:
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font")

    with pytest.raises(CoverRenderError, match="^cover_font_unavailable$"):
        render_cover(_image_bytes(), "星河", font_path=broken)


def test_environment_font_is_used_before_default_candidates(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_COVER_FONT_PATH", str(_font_path()))
    monkeypatch.setattr(
        "packages.story_core.cover_renderer.DEFAULT_FONT_CANDIDATES", (Path("missing.ttf"),)
    )

    assert render_cover(_image_bytes(), "星河").startswith(b"\x89PNG")


def test_missing_environment_and_default_fonts_raise_stable_error(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_COVER_FONT_PATH", raising=False)
    monkeypatch.setattr(
        "packages.story_core.cover_renderer.DEFAULT_FONT_CANDIDATES", (Path("missing.ttf"),)
    )

    with pytest.raises(CoverRenderError, match="^cover_font_unavailable$"):
        render_cover(_image_bytes(), "星河")


def test_glyph_incomplete_candidate_is_skipped_for_glyph_complete_font(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_COVER_FONT_PATH", raising=False)
    monkeypatch.setattr(
        "packages.story_core.cover_renderer.DEFAULT_FONT_CANDIDATES",
        (Path("C:/Windows/Fonts/arial.ttf"),),
    )
    with pytest.raises(CoverRenderError, match="^cover_font_unavailable$"):
        render_cover(_image_bytes(), "星河")

    monkeypatch.setattr(
        "packages.story_core.cover_renderer.DEFAULT_FONT_CANDIDATES",
        (Path("C:/Windows/Fonts/arial.ttf"), _font_path()),
    )

    assert render_cover(_image_bytes(), "星河").startswith(b"\x89PNG")


def test_whitespace_title_and_invalid_image_use_stable_errors() -> None:
    with pytest.raises(CoverRenderError, match="^cover_title_required$"):
        render_cover(_image_bytes(), " \t\n", font_path=_font_path())
    with pytest.raises(CoverRenderError, match="^invalid_cover_image$"):
        render_cover(b"not-an-image", "星河", font_path=_font_path())
    with pytest.raises(CoverRenderError, match="^invalid_cover_image$"):
        render_cover(_image_bytes()[:-8], "星河", font_path=_font_path())


def test_renderer_accepts_only_base_art_title_and_font_configuration() -> None:
    assert tuple(inspect.signature(render_cover).parameters) == ("base_bytes", "title", "font_path")
