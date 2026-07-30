"""Deterministically compose title-only novel cover PNGs."""

from __future__ import annotations

import io
import os
import re
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError


CANVAS_SIZE = (768, 1024)
DEFAULT_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("C:/Windows/Fonts/simkai.ttf"),
    Path("C:/Windows/Fonts/Deng.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf"),
    Path("/usr/share/fonts/opentype/source-han-serif/SourceHanSerifSC-Regular.otf"),
)

_SAFE_LEFT = 64
_SAFE_TOP = 64
_SAFE_RIGHT = 704
_SAFE_BOTTOM = 960
_TITLE_FILL = (255, 242, 186)
_STROKE_FILL = (34, 19, 25)
_SHADOW_FILL = (0, 0, 0)
_STROKE_WIDTH = 2
_SHADOW_OFFSET = (6, 7)
_SHADOW_BLUR_RADIUS = 3
_SHADOW_ALPHA = 190
_MAX_TITLE_CHARACTERS = 80


class CoverRenderError(ValueError):
    """A stable, user-safe cover rendering failure."""


def render_cover(base_bytes: bytes, title: str, font_path: str | Path | None = None) -> bytes:
    """Render *title* over normalized base art and return an encoded PNG.

    The API deliberately has no author or attribution input: the renderer draws
    only the requested title over the supplied base artwork.
    """

    text = _normalise_title(title)
    base = _load_base_image(base_bytes)
    try:
        font_file = _resolve_font(text, font_path)
        canvas = ImageOps.fit(base, CANVAS_SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    finally:
        base.close()
    try:
        if canvas.mode != "RGB":
            converted = canvas.convert("RGB")
            canvas.close()
            canvas = converted
        _draw_title(canvas, text, font_file)
        canvas.info.clear()
        output = io.BytesIO()
        canvas.save(output, format="PNG")
        return output.getvalue()
    except CoverRenderError:
        raise
    except (OSError, ValueError, UnicodeError) as exc:
        raise CoverRenderError("cover_render_failed") from exc
    finally:
        canvas.close()


def _normalise_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise CoverRenderError("cover_title_required")
    text = re.sub(r"\s+", " ", title.strip())
    if len(text) > _MAX_TITLE_CHARACTERS:
        raise CoverRenderError("cover_title_too_long")
    return text


def _load_base_image(base_bytes: bytes) -> Image.Image:
    if not isinstance(base_bytes, bytes) or not base_bytes:
        raise CoverRenderError("invalid_cover_image")
    try:
        with Image.open(io.BytesIO(base_bytes)) as source:
            source.verify()
        with Image.open(io.BytesIO(base_bytes)) as source:
            source.load()
            return source.convert("RGB")
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
    ) as exc:
        raise CoverRenderError("invalid_cover_image") from exc


def _resolve_font(title: str, explicit_path: str | Path | None) -> Path:
    if explicit_path is not None:
        candidate = Path(explicit_path)
        if _font_supports(candidate, title):
            return candidate
        raise CoverRenderError("cover_font_unavailable")

    environment_path = os.environ.get("NOVEL_COVER_FONT_PATH")
    candidates = (Path(environment_path),) if environment_path else ()
    candidates += DEFAULT_FONT_CANDIDATES
    for candidate in candidates:
        if _font_supports(candidate, title):
            return candidate
    raise CoverRenderError("cover_font_unavailable")


def _font_supports(path: Path, title: str) -> bool:
    if not path.is_file():
        return False
    try:
        ImageFont.truetype(str(path), size=32)
        codepoints = {ord(char) for char in title if not char.isspace()}
        return _cmap_supports_all(path, codepoints)
    except (OSError, ValueError, struct.error):
        return False


def _cmap_supports_all(path: Path, codepoints: set[int]) -> bool:
    """Check a font cmap rather than trusting FreeType's `.notdef` glyph mask."""

    if not codepoints:
        return True
    try:
        data = path.read_bytes()
        face_offset = _sfnt_face_offset(data)
        cmap_offset, cmap_length = _table_location(data, face_offset, b"cmap")
        cmap_end = cmap_offset + cmap_length
        if cmap_end > len(data) or cmap_length < 4:
            return False
        table_count = _u16(data, cmap_offset + 2)
        records_end = cmap_offset + 4 + (table_count * 8)
        if records_end > cmap_end:
            return False
        subtables: list[int] = []
        for index in range(table_count):
            record = cmap_offset + 4 + (index * 8)
            subtable = cmap_offset + _u32(data, record + 4)
            if cmap_offset <= subtable < cmap_end:
                subtables.append(subtable)
        for codepoint in codepoints:
            if not any(_subtable_has_glyph(data, offset, cmap_end, codepoint) for offset in subtables):
                return False
        return True
    except (IndexError, OSError, ValueError, struct.error):
        return False


def _sfnt_face_offset(data: bytes) -> int:
    if data[:4] != b"ttcf":
        return 0
    if len(data) < 16:
        raise ValueError("invalid_ttc")
    count = _u32(data, 8)
    if count < 1 or 12 + (count * 4) > len(data):
        raise ValueError("invalid_ttc")
    offset = _u32(data, 12)
    if offset + 12 > len(data):
        raise ValueError("invalid_ttc")
    return offset


def _table_location(data: bytes, face_offset: int, tag: bytes) -> tuple[int, int]:
    if face_offset + 12 > len(data):
        raise ValueError("invalid_sfnt")
    table_count = _u16(data, face_offset + 4)
    directory_end = face_offset + 12 + (table_count * 16)
    if directory_end > len(data):
        raise ValueError("invalid_sfnt")
    for index in range(table_count):
        record = face_offset + 12 + (index * 16)
        if data[record : record + 4] == tag:
            return _u32(data, record + 8), _u32(data, record + 12)
    raise ValueError("table_missing")


def _subtable_has_glyph(data: bytes, offset: int, limit: int, codepoint: int) -> bool:
    if offset + 2 > limit:
        return False
    format_number = _u16(data, offset)
    if format_number == 4:
        return _format4_has_glyph(data, offset, limit, codepoint)
    if format_number == 12:
        return _format12_has_glyph(data, offset, limit, codepoint)
    return False


def _format12_has_glyph(data: bytes, offset: int, limit: int, codepoint: int) -> bool:
    if offset + 16 > limit:
        return False
    length = _u32(data, offset + 4)
    group_count = _u32(data, offset + 12)
    end = offset + length
    if length < 16 or end > limit or offset + 16 + (group_count * 12) > end:
        return False
    for index in range(group_count):
        group = offset + 16 + (index * 12)
        start, finish, glyph = _u32(data, group), _u32(data, group + 4), _u32(data, group + 8)
        if start <= codepoint <= finish:
            return glyph + codepoint - start != 0
        if codepoint < start:
            return False
    return False


def _format4_has_glyph(data: bytes, offset: int, limit: int, codepoint: int) -> bool:
    if codepoint > 0xFFFF or offset + 14 > limit:
        return False
    length = _u16(data, offset + 2)
    end = offset + length
    seg_count = _u16(data, offset + 6) // 2
    if length < 16 or end > limit or seg_count == 0:
        return False
    end_codes = offset + 14
    start_codes = end_codes + (seg_count * 2) + 2
    deltas = start_codes + (seg_count * 2)
    ranges = deltas + (seg_count * 2)
    if ranges + (seg_count * 2) > end:
        return False
    for index in range(seg_count):
        start = _u16(data, start_codes + (index * 2))
        finish = _u16(data, end_codes + (index * 2))
        if start <= codepoint <= finish:
            delta = _u16(data, deltas + (index * 2))
            range_offset_address = ranges + (index * 2)
            range_offset = _u16(data, range_offset_address)
            if range_offset == 0:
                return (codepoint + delta) & 0xFFFF != 0
            glyph_address = range_offset_address + range_offset + ((codepoint - start) * 2)
            if glyph_address + 2 > end:
                return False
            glyph = _u16(data, glyph_address)
            return glyph != 0 and ((glyph + delta) & 0xFFFF) != 0
        if codepoint < start:
            return False
    return False


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _draw_title(canvas: Image.Image, title: str, font_file: Path) -> None:
    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    try:
        shadow_draw = ImageDraw.Draw(shadow)
        if _is_short_chinese_title(title):
            _draw_vertical_title(shadow_draw, title, font_file, shadow=True)
        else:
            _draw_wrapped_title(shadow_draw, title, font_file, shadow=True)
        softened_shadow = shadow.filter(ImageFilter.GaussianBlur(_SHADOW_BLUR_RADIUS))
        try:
            canvas.paste(softened_shadow, (0, 0), softened_shadow)
        finally:
            softened_shadow.close()
    finally:
        shadow.close()

    draw = ImageDraw.Draw(canvas)
    if _is_short_chinese_title(title):
        _draw_vertical_title(draw, title, font_file)
    else:
        _draw_wrapped_title(draw, title, font_file)


def _is_short_chinese_title(title: str) -> bool:
    return 2 <= len(title) <= 6 and all("\u4e00" <= char <= "\u9fff" for char in title)


def _draw_vertical_title(
    draw: ImageDraw.ImageDraw, title: str, font_file: Path, *, shadow: bool = False
) -> None:
    font = ImageFont.truetype(str(font_file), size=100)
    sample_box = draw.textbbox((0, 0), title[0], font=font, stroke_width=_STROKE_WIDTH)
    glyph_height = sample_box[3] - sample_box[1]
    gap = 14
    total_height = len(title) * glyph_height + (len(title) - 1) * gap
    y = (CANVAS_SIZE[1] - total_height) // 2
    for character in title:
        box = draw.textbbox((0, 0), character, font=font, stroke_width=_STROKE_WIDTH)
        x = (CANVAS_SIZE[0] - (box[2] - box[0])) // 2 - box[0]
        _draw_text(draw, (x, y - box[1]), character, font, shadow=shadow)
        y += glyph_height + gap


def _draw_wrapped_title(
    draw: ImageDraw.ImageDraw, title: str, font_file: Path, *, shadow: bool = False
) -> None:
    max_width = _SAFE_RIGHT - _SAFE_LEFT - _SHADOW_OFFSET[0] - _SHADOW_BLUR_RADIUS
    max_height = _SAFE_BOTTOM - _SAFE_TOP - _SHADOW_OFFSET[1] - _SHADOW_BLUR_RADIUS
    chosen: tuple[ImageFont.FreeTypeFont, list[str], int, int] | None = None
    for size in range(96, 23, -2):
        font = ImageFont.truetype(str(font_file), size=size)
        lines = _wrap_lines(draw, title, font, max_width)
        line_boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=_STROKE_WIDTH) for line in lines]
        line_height = max(box[3] - box[1] for box in line_boxes)
        gap = max(10, size // 5)
        total_height = len(lines) * line_height + (len(lines) - 1) * gap
        if total_height <= max_height:
            chosen = font, lines, line_height, gap
            break
    if chosen is None:
        raise CoverRenderError("cover_title_too_long")
    font, lines, line_height, gap = chosen
    total_height = len(lines) * line_height + (len(lines) - 1) * gap
    y = (CANVAS_SIZE[1] - total_height) // 2
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font, stroke_width=_STROKE_WIDTH)
        x = (CANVAS_SIZE[0] - (box[2] - box[0])) // 2 - box[0]
        _draw_text(draw, (x, y - box[1]), line, font, shadow=shadow)
        y += line_height + gap


def _wrap_lines(draw: ImageDraw.ImageDraw, title: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in title:
        candidate = current + character
        width = draw.textbbox((0, 0), candidate, font=font, stroke_width=_STROKE_WIDTH)[2]
        if current and width > max_width:
            lines.append(current.rstrip())
            current = character.lstrip()
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())
    return [line for line in lines if line] or [title]


def _draw_text(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    shadow: bool = False,
) -> None:
    if shadow:
        shadow_position = (position[0] + _SHADOW_OFFSET[0], position[1] + _SHADOW_OFFSET[1])
        draw.text(shadow_position, text, font=font, fill=(*_SHADOW_FILL, _SHADOW_ALPHA))
        return
    draw.text(
        position,
        text,
        font=font,
        fill=_TITLE_FILL,
        stroke_width=_STROKE_WIDTH,
        stroke_fill=_STROKE_FILL,
    )
