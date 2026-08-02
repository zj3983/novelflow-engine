"""Deterministically compose title-only novel cover PNGs.

Baseline JPEG scans are bounded by a deterministic MCU/block ceiling and
validated through their Huffman entropy stream. Progressive JPEG remains
supported through Pillow's decoder, whose multi-scan EOB-run grammar is not
duplicated by this lightweight validator.
"""

from __future__ import annotations

import io
import os
import re
import stat
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import regex
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError


CANVAS_SIZE = (768, 1024)
MAX_IMAGE_PIXELS = 40_000_000
MAX_FONT_BYTES = 64 * 1024 * 1024
MAX_JPEG_VALIDATION_BLOCKS = 200_000
_SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP"}
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
MAX_COVER_TITLE_LENGTH = 120


class CoverRenderError(ValueError):
    """A stable, user-safe cover rendering failure."""


@dataclass(frozen=True)
class _ResolvedFont:
    path: Path
    data: bytes


def render_cover(base_bytes: bytes, title: str, font_path: str | Path | None = None) -> bytes:
    """Render *title* over normalized base art and return an encoded PNG.

    The API deliberately has no author or attribution input: the renderer draws
    only the requested title over the supplied base artwork.
    """

    text = normalize_cover_title(title)
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


def normalize_cover_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise CoverRenderError("cover_title_required")
    text = re.sub(r"\s+", " ", title.strip())
    if not _title_clusters_have_visible_bases(text):
        raise CoverRenderError("cover_title_required")
    if len(text) > MAX_COVER_TITLE_LENGTH:
        raise CoverRenderError("cover_title_too_long")
    return text


def _load_base_image(base_bytes: bytes) -> Image.Image:
    if not isinstance(base_bytes, bytes) or not base_bytes:
        raise CoverRenderError("invalid_cover_image")
    try:
        with Image.open(io.BytesIO(base_bytes)) as source:
            if source.format not in _SUPPORTED_FORMATS:
                raise ValueError("unsupported_format")
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError("image_too_large")
            _validate_image_container(base_bytes, source.format)
            source.verify()
        with Image.open(io.BytesIO(base_bytes)) as source:
            source.load()
            oriented = ImageOps.exif_transpose(source)
            try:
                return oriented.convert("RGB")
            finally:
                if oriented is not source:
                    oriented.close()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
    ) as exc:
        raise CoverRenderError("invalid_cover_image") from exc


def _validate_image_container(data: bytes, image_format: str) -> None:
    if image_format == "PNG":
        _validate_png_container(data)
    elif image_format == "JPEG":
        if len(data) < 4 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            raise ValueError("incomplete_jpeg")
        _validate_baseline_jpeg_entropy(data)
    elif image_format == "WEBP":
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise ValueError("incomplete_webp")
        if struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
            raise ValueError("incomplete_webp")
    else:
        raise ValueError("unsupported_format")


def _validate_png_container(data: bytes) -> None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid_png")
    position = 8
    chunks_seen: list[bytes] = []
    idat = bytearray()
    ihdr: tuple[int, int, int, int, int] | None = None
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError("truncated_png")
        length = _u32(data, position)
        end = position + 12 + length
        if end > len(data):
            raise ValueError("truncated_png")
        chunk_type = data[position + 4 : position + 8]
        payload = data[position + 8 : end - 4]
        expected_crc = _u32(data, end - 4)
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
            raise ValueError("png_crc")
        if not chunks_seen and chunk_type != b"IHDR":
            raise ValueError("png_order")
        if chunk_type == b"IHDR":
            if chunks_seen or length != 13:
                raise ValueError("png_ihdr")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack_from(
                ">IIBBBBB", payload
            )
            if compression != 0 or filter_method != 0:
                raise ValueError("unsupported_png")
            ihdr = width, height, bit_depth, color_type, interlace
        elif chunk_type == b"IDAT":
            if ihdr is None or (b"IEND" in chunks_seen):
                raise ValueError("png_order")
            idat.extend(payload)
        elif chunk_type == b"IEND":
            if length != 0 or end != len(data):
                raise ValueError("invalid_png_end")
            if ihdr is None or not idat:
                raise ValueError("png_missing_data")
            _validate_png_idat_stream(bytes(idat), *ihdr)
            return
        chunks_seen.append(chunk_type)
        position = end
    raise ValueError("missing_png_end")


def _validate_baseline_jpeg_entropy(data: bytes) -> None:
    """Verify a baseline JPEG scan has enough Huffman-coded blocks for its MCU grid."""

    position = 2
    frame: dict[int, tuple[int, int]] | None = None
    huffman: dict[tuple[int, int], dict[tuple[int, int], int]] = {}
    while position + 1 < len(data):
        if data[position] != 0xFF:
            raise ValueError("jpeg_marker")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            raise ValueError("jpeg_marker")
        marker = data[position]
        position += 1
        if marker == 0xD9:
            raise ValueError("jpeg_missing_scan")
        if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(data):
            raise ValueError("jpeg_segment")
        length = struct.unpack_from(">H", data, position)[0]
        end = position + length
        if length < 2 or end > len(data):
            raise ValueError("jpeg_segment")
        payload = data[position + 2 : end]
        position = end
        if marker == 0xC0:
            if len(payload) < 6 or payload[0] != 8 or len(payload) != 6 + payload[5] * 3:
                raise ValueError("unsupported_jpeg")
            frame = {payload[6 + index * 3]: (payload[7 + index * 3] >> 4, payload[7 + index * 3] & 15) for index in range(payload[5])}
            width, height = struct.unpack_from(">HH", payload, 1)
        elif marker == 0xC4:
            _read_jpeg_huffman_tables(payload, huffman)
        elif marker == 0xDA:
            if frame is None or len(payload) < 3 or payload[-3:] != b"\x00\x3f\x00":
                raise ValueError("unsupported_jpeg")
            count = payload[0]
            if len(payload) != 1 + count * 2 + 3:
                raise ValueError("jpeg_scan")
            scan = [(payload[1 + index * 2], payload[2 + index * 2]) for index in range(count)]
            _validate_jpeg_scan(data, position, width, height, frame, scan, huffman)
            return
        elif marker == 0xC2:  # Progressive JPEG has multi-scan EOB-run semantics.
            return
        elif marker in {0xC1, 0xC3, 0xC9, 0xCA, 0xCB}:  # extended/lossless/arithmetic
            raise ValueError("unsupported_jpeg")
    raise ValueError("jpeg_missing_scan")


def _read_jpeg_huffman_tables(payload: bytes, tables: dict[tuple[int, int], dict[tuple[int, int], int]]) -> None:
    position = 0
    while position < len(payload):
        if position + 17 > len(payload):
            raise ValueError("jpeg_dht")
        table_id = payload[position]
        table_class, table_number = table_id >> 4, table_id & 15
        if table_class > 1 or table_number > 3:
            raise ValueError("jpeg_dht")
        counts = payload[position + 1 : position + 17]
        value_count = sum(counts)
        end = position + 17 + value_count
        if end > len(payload):
            raise ValueError("jpeg_dht")
        code = 0
        values = iter(payload[position + 17 : end])
        table: dict[tuple[int, int], int] = {}
        for length, count in enumerate(counts, start=1):
            for _ in range(count):
                table[length, code] = next(values)
                code += 1
            code <<= 1
        tables[table_class, table_number] = table
        position = end


class _JpegBitReader:
    def __init__(self, data: bytes, position: int, *, symbol_budget: int) -> None:
        self.data, self.position, self.buffer, self.bits = data, position, 0, 0
        self.symbol_budget = symbol_budget

    def read(self, count: int) -> int:
        while self.bits < count:
            if self.position >= len(self.data):
                raise ValueError("truncated_jpeg_entropy")
            value = self.data[self.position]
            self.position += 1
            if value == 0xFF:
                if self.position >= len(self.data):
                    raise ValueError("truncated_jpeg_entropy")
                following = self.data[self.position]
                self.position += 1
                if following == 0x00:
                    value = 0xFF
                elif 0xD0 <= following <= 0xD7:
                    self.buffer = self.bits = 0
                    continue
                else:
                    raise ValueError("premature_jpeg_marker")
            self.buffer = (self.buffer << 8) | value
            self.bits += 8
        self.bits -= count
        result = (self.buffer >> self.bits) & ((1 << count) - 1)
        self.buffer &= (1 << self.bits) - 1 if self.bits else 0
        return result


def _jpeg_huffman_symbol(reader: _JpegBitReader, table: dict[tuple[int, int], int]) -> int:
    reader.symbol_budget -= 1
    if reader.symbol_budget < 0:
        raise ValueError("jpeg_validation_budget")
    code = 0
    for length in range(1, 17):
        code = (code << 1) | reader.read(1)
        if (length, code) in table:
            return table[length, code]
    raise ValueError("jpeg_huffman")


def _validate_jpeg_scan(
    data: bytes,
    position: int,
    width: int,
    height: int,
    frame: dict[int, tuple[int, int]],
    scan: list[tuple[int, int]],
    tables: dict[tuple[int, int], dict[tuple[int, int], int]],
) -> None:
    if set(component for component, _ in scan) != set(frame):
        raise ValueError("unsupported_jpeg_scan")
    max_h = max(horizontal for horizontal, _vertical in frame.values())
    max_v = max(vertical for _horizontal, vertical in frame.values())
    blocks: list[tuple[dict[tuple[int, int], int], dict[tuple[int, int], int], int]] = []
    for component, selectors in scan:
        dc = tables.get((0, selectors >> 4))
        ac = tables.get((1, selectors & 15))
        if dc is None or ac is None:
            raise ValueError("jpeg_huffman")
        horizontal, vertical = frame[component]
        blocks.extend((dc, ac, 0) for _ in range(horizontal * vertical))
    mcu_count = ((width + (8 * max_h) - 1) // (8 * max_h)) * ((height + (8 * max_v) - 1) // (8 * max_v))
    block_count = mcu_count * len(blocks)
    if block_count > MAX_JPEG_VALIDATION_BLOCKS:
        raise ValueError("jpeg_validation_budget")
    reader = _JpegBitReader(data, position, symbol_budget=block_count * 65)
    for _ in range(mcu_count):
        for dc, ac, _unused in blocks:
            _ = _jpeg_huffman_symbol(reader, dc)
            reader.read(_)
            coefficient = 1
            while coefficient < 64:
                symbol = _jpeg_huffman_symbol(reader, ac)
                run, size = symbol >> 4, symbol & 15
                if size == 0:
                    if run == 0:
                        break
                    if run != 15:
                        raise ValueError("jpeg_ac")
                    coefficient += 16
                else:
                    coefficient += run + 1
                    if coefficient > 64:
                        raise ValueError("jpeg_ac")
                    reader.read(size)


def _validate_png_idat_stream(
    compressed: bytes, width: int, height: int, bit_depth: int, color_type: int, interlace: int
) -> None:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None or bit_depth not in {1, 2, 4, 8, 16} or interlace not in {0, 1}:
        raise ValueError("unsupported_png")
    bits_per_pixel = channels * bit_depth
    if interlace == 0:
        expected = height * (1 + ((width * bits_per_pixel + 7) // 8))
    else:
        expected = 0
        for start_x, start_y, step_x, step_y in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)):
            pass_width = max(0, (width - start_x + step_x - 1) // step_x)
            pass_height = max(0, (height - start_y + step_y - 1) // step_y)
            if pass_width and pass_height:
                expected += pass_height * (1 + ((pass_width * bits_per_pixel + 7) // 8))
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(compressed, expected + 1)
    if len(decoded) > expected or decoder.unconsumed_tail:
        raise ValueError("png_scanline_length")
    decoded += decoder.flush(expected + 1 - len(decoded))
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("truncated_png_idat")
    if len(decoded) != expected:
        raise ValueError("png_scanline_length")


def _resolve_font(title: str, explicit_path: str | Path | None) -> _ResolvedFont:
    if explicit_path is not None:
        candidate = Path(explicit_path)
        resolved = _load_usable_font(candidate, title)
        if resolved is not None:
            return resolved
        raise CoverRenderError("cover_font_unavailable")

    environment_path = os.environ.get("NOVEL_COVER_FONT_PATH")
    candidates = (Path(environment_path),) if environment_path else ()
    candidates += DEFAULT_FONT_CANDIDATES
    for candidate in candidates:
        resolved = _load_usable_font(candidate, title)
        if resolved is not None:
            return resolved
    raise CoverRenderError("cover_font_unavailable")


def _font_supports(path: Path, title: str) -> bool:
    return _load_usable_font(path, title) is not None


def _load_usable_font(path: Path, title: str) -> _ResolvedFont | None:
    try:
        data = _read_font_bytes(path)
        if data is None:
            return None
        if not _variation_sequences_supported(title):
            return None
        ImageFont.truetype(io.BytesIO(data), size=32)
        codepoints = _required_glyph_codepoints(title)
        return _ResolvedFont(path, data) if _cmap_supports_data(data, codepoints) else None
    except (OSError, ValueError, struct.error):
        return None


def _cmap_supports_all(path: Path, codepoints: set[int]) -> bool:
    """Check a font cmap rather than trusting FreeType's `.notdef` glyph mask."""

    if not codepoints:
        return True
    try:
        data = _read_font_bytes(path)
        if data is None:
            return False
        return _cmap_supports_data(data, codepoints)
    except (IndexError, OSError, ValueError, struct.error):
        return False


def _read_font_bytes(path: Path) -> bytes | None:
    """Open once, fstat the opened target, and bound the read from that handle.

    Symlinks are allowed only when their opened target is a regular file.
    """

    try:
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode) or size < 1 or size > MAX_FONT_BYTES:
                return None
            data = handle.read(MAX_FONT_BYTES + 1)
    except OSError:
        return None
    return data if len(data) == size and len(data) <= MAX_FONT_BYTES else None


def _cmap_supports_data(data: bytes, codepoints: set[int]) -> bool:
    try:
        face_offset = _sfnt_face_offset(data)
        cmap_offset, cmap_length = _table_location(data, face_offset, b"cmap")
        maxp_offset, maxp_length = _table_location(data, face_offset, b"maxp")
        if maxp_length < 6 or maxp_offset + 6 > len(data):
            return False
        if _u32(data, maxp_offset) not in {0x00005000, 0x00010000}:
            return False
        glyph_count = _u16(data, maxp_offset + 4)
        if glyph_count < 1:
            return False
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
            platform = _u16(data, record)
            encoding = _u16(data, record + 2)
            subtable = cmap_offset + _u32(data, record + 4)
            if _unicode_cmap_record(platform, encoding) and cmap_offset <= subtable < cmap_end:
                subtables.append(subtable)
        for codepoint in codepoints:
            glyphs = (_subtable_glyph(data, offset, cmap_end, codepoint) for offset in subtables)
            if not any(glyph is not None and 0 < glyph < glyph_count for glyph in glyphs):
                return False
        return True
    except (IndexError, OSError, ValueError, struct.error):
        return False


def _unicode_cmap_record(platform: int, encoding: int) -> bool:
    """Return whether a cmap record uses a Unicode encoding FreeType selects."""

    return platform == 0 or (platform == 3 and encoding in {1, 10})


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
            offset, length = _u32(data, record + 8), _u32(data, record + 12)
            if offset > len(data) or length > len(data) - offset:
                raise ValueError("table_out_of_bounds")
            return offset, length
    raise ValueError("table_missing")


def _subtable_glyph(data: bytes, offset: int, limit: int, codepoint: int) -> int | None:
    if offset + 2 > limit:
        return None
    format_number = _u16(data, offset)
    if format_number == 4:
        return _format4_glyph(data, offset, limit, codepoint)
    if format_number == 12:
        return _format12_glyph(data, offset, limit, codepoint)
    return None


def _format12_glyph(data: bytes, offset: int, limit: int, codepoint: int) -> int | None:
    if offset + 16 > limit:
        return None
    length = _u32(data, offset + 4)
    group_count = _u32(data, offset + 12)
    end = offset + length
    if length < 16 or end > limit or offset + 16 + (group_count * 12) > end:
        return None
    for index in range(group_count):
        group = offset + 16 + (index * 12)
        start, finish, glyph = _u32(data, group), _u32(data, group + 4), _u32(data, group + 8)
        if start <= codepoint <= finish:
            return glyph + codepoint - start
        if codepoint < start:
            return None
    return None


def _format4_glyph(data: bytes, offset: int, limit: int, codepoint: int) -> int | None:
    if codepoint > 0xFFFF or offset + 14 > limit:
        return None
    length = _u16(data, offset + 2)
    end = offset + length
    seg_count_x2 = _u16(data, offset + 6)
    seg_count = seg_count_x2 // 2
    if length < 16 or end > limit or seg_count == 0 or seg_count_x2 % 2:
        return None
    end_codes = offset + 14
    start_codes = end_codes + (seg_count * 2) + 2
    deltas = start_codes + (seg_count * 2)
    ranges = deltas + (seg_count * 2)
    if ranges + (seg_count * 2) > end:
        return None
    if _u16(data, end_codes + (seg_count * 2)) != 0:
        return None
    for index in range(seg_count):
        start = _u16(data, start_codes + (index * 2))
        finish = _u16(data, end_codes + (index * 2))
        if start <= codepoint <= finish:
            delta = _u16(data, deltas + (index * 2))
            range_offset_address = ranges + (index * 2)
            range_offset = _u16(data, range_offset_address)
            if range_offset == 0:
                return (codepoint + delta) & 0xFFFF
            glyph_address = range_offset_address + range_offset + ((codepoint - start) * 2)
            if glyph_address + 2 > end:
                return None
            glyph = _u16(data, glyph_address)
            return (glyph + delta) & 0xFFFF if glyph else 0
        if codepoint < start:
            return None
    return None


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _grapheme_clusters(text: str) -> list[str]:
    return regex.findall(r"\X", text)


def _is_short_han_title(title: str) -> bool:
    clusters = _grapheme_clusters(title)
    return 2 <= len(clusters) <= 6 and all(
        regex.fullmatch(r"\p{Script=Han}+", _visible_cluster_bases(cluster)) is not None for cluster in clusters
    )


def _title_clusters_have_visible_bases(title: str) -> bool:
    return all(_visible_cluster_bases(cluster) for cluster in _grapheme_clusters(title))


def _visible_cluster_bases(cluster: str) -> str:
    return "".join(
        character
        for character in cluster
        if character not in {"\u200c", "\u200d"}
        and not _is_variation_selector(character)
        and not regex.fullmatch(r"\p{M}", character)
    )


def _variation_sequences_supported(title: str) -> bool:
    """Fail closed until a selected font proves each Unicode variation sequence."""

    return not any(_is_variation_selector(character) for character in title)


def _required_glyph_codepoints(title: str) -> set[int]:
    return {
        ord(character)
        for character in title
        if not character.isspace()
        and not _is_variation_selector(character)
    }


def _is_variation_selector(character: str) -> bool:
    codepoint = ord(character)
    return 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF


def _draw_title(canvas: Image.Image, title: str, font_file: _ResolvedFont) -> None:
    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    try:
        shadow_draw = ImageDraw.Draw(shadow)
        if _is_short_han_title(title):
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
    if _is_short_han_title(title):
        _draw_vertical_title(draw, title, font_file)
    else:
        _draw_wrapped_title(draw, title, font_file)


def _draw_vertical_title(
    draw: ImageDraw.ImageDraw, title: str, font_file: _ResolvedFont, *, shadow: bool = False
) -> None:
    font = ImageFont.truetype(io.BytesIO(font_file.data), size=100)
    clusters = _grapheme_clusters(title)
    sample_box = draw.textbbox((0, 0), clusters[0], font=font, stroke_width=_STROKE_WIDTH)
    glyph_height = sample_box[3] - sample_box[1]
    gap = 14
    total_height = len(clusters) * glyph_height + (len(clusters) - 1) * gap
    y = (CANVAS_SIZE[1] - total_height) // 2
    for character in clusters:
        box = draw.textbbox((0, 0), character, font=font, stroke_width=_STROKE_WIDTH)
        x = (CANVAS_SIZE[0] - (box[2] - box[0])) // 2 - box[0]
        _draw_text(draw, (x, y - box[1]), character, font, shadow=shadow)
        y += glyph_height + gap


def _draw_wrapped_title(
    draw: ImageDraw.ImageDraw, title: str, font_file: _ResolvedFont, *, shadow: bool = False
) -> None:
    max_width = _SAFE_RIGHT - _SAFE_LEFT - _SHADOW_OFFSET[0] - _SHADOW_BLUR_RADIUS
    max_height = _SAFE_BOTTOM - _SAFE_TOP - _SHADOW_OFFSET[1] - _SHADOW_BLUR_RADIUS
    chosen: tuple[ImageFont.FreeTypeFont, list[str], int, int] | None = None
    for size in range(96, 23, -2):
        font = ImageFont.truetype(io.BytesIO(font_file.data), size=size)
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
    for character in _grapheme_clusters(title):
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
