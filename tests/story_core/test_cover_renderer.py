from __future__ import annotations

import io
import inspect
import struct
import warnings
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageFile, ImageFont, PngImagePlugin

from packages.story_core import cover_renderer
from packages.story_core.cover_renderer import CoverRenderError, render_cover


CANVAS = (768, 1024)
BASE = (19, 45, 79)
REAL_RESOLVE_FONT = cover_renderer._resolve_font


def _font_path() -> Path:
    return Path("pillow-default.ttf")


@pytest.fixture(autouse=True)
def portable_renderer_font(monkeypatch):
    """Keep visual renderer tests independent of host-installed CJK fonts."""

    default_font = ImageFont.load_default()
    monkeypatch.setattr(cover_renderer, "_resolve_font", lambda *_args, **_kwargs: _font_path())
    monkeypatch.setattr(cover_renderer.ImageFont, "truetype", lambda *_args, **_kwargs: default_font)


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


def _pixel_bbox(image: Image.Image, predicate) -> tuple[int, int, int, int]:
    points = [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if predicate(image.getpixel((x, y)))
    ]
    assert points
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def test_render_cover_returns_a_metadata_free_768_by_1024_png() -> None:
    rendered = render_cover(_image_bytes(), "星河", font_path=_font_path())

    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.size == CANVAS
        assert image.info == {}


def test_render_cover_strips_icc_and_text_metadata_from_source_png() -> None:
    source = Image.new("RGB", (400, 400), BASE)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "source attribution must not survive")
    encoded = io.BytesIO()
    source.save(encoded, format="PNG", pnginfo=metadata, icc_profile=b"test-icc-profile")
    with Image.open(io.BytesIO(encoded.getvalue())) as image:
        assert image.info["Comment"] == "source attribution must not survive"
        assert image.info["icc_profile"] == b"test-icc-profile"

    rendered = render_cover(encoded.getvalue(), "星河", font_path=_font_path())

    with Image.open(io.BytesIO(rendered)) as image:
        assert "Comment" not in image.info
        assert "icc_profile" not in image.info
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
    assert bottom - top > (right - left) * 3
    assert 32 <= left < right <= 736
    assert 48 <= top < bottom <= 976


def test_six_character_chinese_title_still_uses_vertical_layout() -> None:
    rendered = _cover(_image_bytes(), "星河长明万古")
    left, top, right, bottom = _title_bbox(rendered)

    assert right - left < 300
    assert bottom - top > (right - left) * 3


def test_seven_character_title_switches_to_wrapped_horizontal_layout() -> None:
    rendered = _cover(_image_bytes(), "星河长明万古不")
    left, top, right, bottom = _title_bbox(rendered)

    assert right - left > bottom - top


def test_mixed_ascii_and_chinese_title_wraps_without_clipping() -> None:
    rendered = _cover(_image_bytes(), "The Last 星河守夜人 Chronicles")
    left, top, right, bottom = _title_bbox(rendered)

    assert 32 <= left < right <= 736
    assert 48 <= top < bottom <= 976
    assert right - left > bottom - top


def test_title_has_light_fill_dark_stroke_and_offset_shadow() -> None:
    rendered = _cover(_image_bytes(), "星河")
    colors = {color for _count, color in rendered.getcolors(CANVAS[0] * CANVAS[1]) or []}

    assert (255, 242, 186) in colors
    assert (34, 19, 25) in colors
    assert any(all(channel < base for channel, base in zip(color, BASE)) for color in colors)


def test_title_shadow_is_softened_and_extends_down_right_of_the_title() -> None:
    rendered = _cover(_image_bytes(), "星河")
    fill_box = _pixel_bbox(rendered, lambda pixel: pixel == (255, 242, 186))
    shadow_box = _pixel_bbox(
        rendered,
        lambda pixel: all(channel < base for channel, base in zip(pixel, BASE)),
    )
    blurred_colours = {
        color
        for _count, color in rendered.getcolors(CANVAS[0] * CANVAS[1]) or []
        if all(0 < channel < base for channel, base in zip(color, BASE))
    }

    assert shadow_box[2] >= fill_box[2] + 10
    assert shadow_box[3] >= fill_box[3] + 11
    assert len(blurred_colours) >= 4


@pytest.mark.parametrize("image_format", ["JPEG", "WEBP"])
def test_render_cover_always_encodes_png_from_supported_source_formats(image_format: str) -> None:
    rendered = render_cover(_image_bytes(image_format), "星河", font_path=_font_path())
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.size == CANVAS


def test_explicit_font_path_takes_precedence_over_environment(monkeypatch, tmp_path) -> None:
    explicit_font = tmp_path / "explicit.ttf"
    environment_font = tmp_path / "missing.ttf"
    monkeypatch.setenv("NOVEL_COVER_FONT_PATH", str(environment_font))
    monkeypatch.setattr(cover_renderer, "_font_supports", lambda path, _title: path == explicit_font)

    assert REAL_RESOLVE_FONT("星河", explicit_font) == explicit_font


def test_explicit_missing_or_broken_font_is_a_terminal_stable_error(tmp_path) -> None:
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font")

    with pytest.raises(CoverRenderError, match="^cover_font_unavailable$"):
        REAL_RESOLVE_FONT("星河", broken)


def test_environment_font_is_used_before_default_candidates(monkeypatch) -> None:
    environment_font = Path("environment.ttf")
    monkeypatch.setenv("NOVEL_COVER_FONT_PATH", str(environment_font))
    monkeypatch.setattr(
        "packages.story_core.cover_renderer.DEFAULT_FONT_CANDIDATES", (Path("missing.ttf"),)
    )
    monkeypatch.setattr(cover_renderer, "_font_supports", lambda path, _title: path == environment_font)

    assert REAL_RESOLVE_FONT("星河", None) == environment_font


def test_missing_environment_and_default_fonts_raise_stable_error(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_COVER_FONT_PATH", raising=False)
    monkeypatch.setattr(
        "packages.story_core.cover_renderer.DEFAULT_FONT_CANDIDATES", (Path("missing.ttf"),)
    )

    with pytest.raises(CoverRenderError, match="^cover_font_unavailable$"):
        REAL_RESOLVE_FONT("星河", None)


def test_glyph_incomplete_candidate_is_skipped_for_glyph_complete_font(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_COVER_FONT_PATH", raising=False)
    monkeypatch.setattr(
        "packages.story_core.cover_renderer.DEFAULT_FONT_CANDIDATES",
        (Path("C:/Windows/Fonts/arial.ttf"),),
    )
    monkeypatch.setattr(cover_renderer, "_font_supports", lambda _path, _title: False)
    with pytest.raises(CoverRenderError, match="^cover_font_unavailable$"):
        REAL_RESOLVE_FONT("星河", None)

    complete = Path("complete-cjk.ttf")
    monkeypatch.setattr(
        "packages.story_core.cover_renderer.DEFAULT_FONT_CANDIDATES",
        (Path("C:/Windows/Fonts/arial.ttf"), complete),
    )
    monkeypatch.setattr(cover_renderer, "_font_supports", lambda path, _title: path == complete)

    assert REAL_RESOLVE_FONT("星河", None) == complete


def test_whitespace_title_and_invalid_image_use_stable_errors() -> None:
    with pytest.raises(CoverRenderError, match="^cover_title_required$"):
        render_cover(_image_bytes(), " \t\n", font_path=_font_path())
    with pytest.raises(CoverRenderError, match="^invalid_cover_image$"):
        render_cover(b"not-an-image", "星河", font_path=_font_path())
    with pytest.raises(CoverRenderError, match="^invalid_cover_image$"):
        render_cover(_image_bytes()[:-8], "星河", font_path=_font_path())


def test_renderer_accepts_only_base_art_title_and_font_configuration() -> None:
    assert tuple(inspect.signature(render_cover).parameters) == ("base_bytes", "title", "font_path")


def test_renderer_enforces_its_own_pixel_limit_before_loading(monkeypatch) -> None:
    monkeypatch.setattr(cover_renderer, "MAX_IMAGE_PIXELS", 1)
    with pytest.raises(CoverRenderError, match="^invalid_cover_image$"):
        render_cover(_image_bytes(size=(2, 2)), "星河", font_path=_font_path())


def test_renderer_maps_an_externally_lowered_pillow_bomb_threshold_stably(monkeypatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 2)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with pytest.raises(CoverRenderError, match="^invalid_cover_image$"):
            render_cover(_image_bytes(size=(3, 2)), "星河", font_path=_font_path())


def test_renderer_rejects_png_missing_iend_even_when_pillow_allows_truncation(monkeypatch) -> None:
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    source = _image_bytes()
    with pytest.raises(CoverRenderError, match="^invalid_cover_image$"):
        render_cover(source[:-12], "星河", font_path=_font_path())


def test_strict_load_applies_exif_orientation_before_cropping() -> None:
    source = Image.new("RGB", (20, 40), color=(0, 0, 0))
    source.paste((255, 0, 0), (0, 0, 10, 20))
    exif = Image.Exif()
    exif[274] = 6
    encoded = io.BytesIO()
    source.save(encoded, format="JPEG", exif=exif)

    loaded = cover_renderer._load_base_image(encoded.getvalue())
    try:
        assert loaded.size == (40, 20)
        assert loaded.getpixel((39, 0))[0] > 240
        assert loaded.getpixel((0, 0))[0] < 20
    finally:
        loaded.close()


@pytest.mark.parametrize("title", ["㐀㐁", "豈更", "𠀀𠀁"])
def test_all_han_extensions_and_compatibility_ideographs_select_vertical_layout(title: str) -> None:
    assert cover_renderer._is_short_han_title(title)


def test_grapheme_clusters_keep_zwj_combining_and_variation_sequences_whole() -> None:
    assert cover_renderer._grapheme_clusters("A👩‍💻e\u0301✈️B") == ["A", "👩‍💻", "e\u0301", "✈️", "B"]


def test_font_coverage_ignores_joiners_and_variation_selectors_but_keeps_combining_marks() -> None:
    required = cover_renderer._required_glyph_codepoints("👩‍💻e\u0301✈️")

    assert ord("\u200d") not in required
    assert ord("\ufe0f") not in required
    assert {ord("👩"), ord("💻"), ord("e"), ord("\u0301"), ord("✈")} <= required


def test_wrapping_never_splits_extended_grapheme_clusters() -> None:
    class FixedMeasure:
        def textbbox(self, _position, text, **_kwargs):
            return (0, 0, len(cover_renderer._grapheme_clusters(text)) * 10, 10)

    assert cover_renderer._wrap_lines(FixedMeasure(), "A👩‍💻e\u0301✈️B", ImageFont.load_default(), 20) == ["A👩‍💻", "e\u0301✈️", "B"]


def _synthetic_sfnt(*, platform: int, encoding: int, glyph: int, glyph_count: int = 8, malformed=False) -> bytes:
    cmap = struct.pack(">HHHHI", 0, 1, platform, encoding, 12)
    cmap += struct.pack(">HHLLL", 12, 0, 28, 0, 1)
    cmap += struct.pack(">LLL", 0x4E00, 0x4E00, glyph)
    if malformed:
        cmap = cmap[:8] + struct.pack(">I", 0xFFFF_FFF0) + cmap[12:]
    maxp = struct.pack(">LH", 0x00010000, glyph_count)
    cmap_offset = 64
    maxp_offset = cmap_offset + len(cmap)
    header = struct.pack(">LHHHH", 0x00010000, 2, 0, 0, 0)
    directory = b"cmap" + struct.pack(">LLL", 0, cmap_offset, len(cmap))
    directory += b"maxp" + struct.pack(">LLL", 0, maxp_offset, len(maxp))
    return header + directory + b"\0" * (cmap_offset - len(header) - len(directory)) + cmap + maxp


def test_cmap_accepts_only_unicode_records_and_valid_glyph_ids(tmp_path) -> None:
    unicode_font = tmp_path / "unicode.ttf"
    unicode_font.write_bytes(_synthetic_sfnt(platform=3, encoding=10, glyph=1))
    symbol_font = tmp_path / "symbol.ttf"
    symbol_font.write_bytes(_synthetic_sfnt(platform=3, encoding=0, glyph=1))
    bad_gid_font = tmp_path / "bad-gid.ttf"
    bad_gid_font.write_bytes(_synthetic_sfnt(platform=3, encoding=10, glyph=8))
    malformed_font = tmp_path / "malformed.ttf"
    malformed_font.write_bytes(_synthetic_sfnt(platform=3, encoding=10, glyph=1, malformed=True))

    assert cover_renderer._cmap_supports_all(unicode_font, {0x4E00})
    assert not cover_renderer._cmap_supports_all(symbol_font, {0x4E00})
    assert not cover_renderer._cmap_supports_all(bad_gid_font, {0x4E00})
    assert not cover_renderer._cmap_supports_all(malformed_font, {0x4E00})


def test_font_cmap_read_is_bounded_by_file_size_before_reading(monkeypatch, tmp_path) -> None:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"small")
    monkeypatch.setattr(cover_renderer, "MAX_FONT_BYTES", 4)
    assert not cover_renderer._cmap_supports_all(font, {ord("A")})


def test_cmap_parser_accepts_format4_and_ttc_unicode_faces(tmp_path) -> None:
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12)
    cmap += struct.pack(">HHHHHHH", 4, 24, 0, 2, 2, 0, 0)
    cmap += struct.pack(">HHHHH", 0x41, 0, 0x41, (1 - 0x41) & 0xFFFF, 0)
    maxp = struct.pack(">LH", 0x00010000, 2)
    cmap_offset = 64
    maxp_offset = cmap_offset + len(cmap)
    header = struct.pack(">LHHHH", 0x00010000, 2, 0, 0, 0)
    directory = b"cmap" + struct.pack(">LLL", 0, cmap_offset, len(cmap))
    directory += b"maxp" + struct.pack(">LLL", 0, maxp_offset, len(maxp))
    sfnt = bytearray(header + directory + b"\0" * (cmap_offset - len(header) - len(directory)) + cmap + maxp)
    assert cover_renderer._cmap_supports_all(_write_font(tmp_path / "format4.ttf", sfnt), {0x41})

    for offset in (20, 36):
        struct.pack_into(">L", sfnt, offset, struct.unpack_from(">L", sfnt, offset)[0] + 16)
    ttc = b"ttcf" + struct.pack(">LLL", 0x00010000, 1, 16) + bytes(sfnt)
    assert cover_renderer._cmap_supports_all(_write_font(tmp_path / "font.ttc", ttc), {0x41})


def _write_font(path: Path, data: bytes | bytearray) -> Path:
    path.write_bytes(data)
    return path
