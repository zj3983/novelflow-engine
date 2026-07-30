from __future__ import annotations

import base64
import binascii
import io
import json
import socket
import struct
import warnings
from urllib.error import HTTPError, URLError

import pytest
from PIL import Image

from packages.story_core.cover_image_provider import CoverImageError, OpenAICoverImageProvider
from packages.story_core.http_retry import RetryConfig
from packages.story_core.runtime_config import ImageRuntimeSettings


def _image_bytes(image_format: str = "PNG", *, size: tuple[int, int] = (3, 2)) -> bytes:
    image = Image.new("RGB", size, color=(10, 20, 30))
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def _runtime() -> ImageRuntimeSettings:
    return ImageRuntimeSettings(
        api_key="image-key",
        base_url="https://images.example.test/v1",
        model="cover-model",
    )


def _provider(response, *, calls=None) -> OpenAICoverImageProvider:
    calls = calls if calls is not None else []

    def post_json(base_url, path, payload, api_key, **kwargs):
        calls.append((base_url, path, payload, api_key, kwargs))
        if isinstance(response, Exception):
            raise response
        return response

    return OpenAICoverImageProvider(post_json=post_json, runtime_resolver=_runtime)


def _b64_response(data: bytes) -> dict[str, object]:
    encoded = base64.b64encode(data).decode("ascii")
    return {"data": [{"b64_json": encoded}]}


def test_generate_posts_one_openai_compatible_base64_request_and_returns_image_bytes() -> None:
    calls: list[tuple] = []
    source = _image_bytes()
    provider = _provider(_b64_response(source), calls=calls)

    assert provider.generate("moonlit fantasy cover") == source
    assert calls == [
        (
            "https://images.example.test/v1",
            "/images/generations",
            {
                "model": "cover-model",
                "prompt": "moonlit fantasy cover",
                "n": 1,
                "response_format": "b64_json",
            },
            "image-key",
            {
                "config": RetryConfig(timeout=180, allow_compatibility_fallback=False),
                "provider": "openai",
                "codex_command": "",
            },
        )
    ]


def test_generate_rejects_url_only_response() -> None:
    with pytest.raises(CoverImageError, match="^unsupported_image_response$"):
        _provider({"data": [{"url": "https://example.test/cover.png"}]}).generate("cover")


@pytest.mark.parametrize("base64_value", [None, "", False, "not base64!"])
def test_generate_treats_url_with_no_usable_base64_as_an_unsupported_url_response(base64_value) -> None:
    with pytest.raises(CoverImageError, match="^unsupported_image_response$"):
        _provider(
            {"data": [{"url": "https://example.test/cover.png", "b64_json": base64_value}]}
        ).generate("cover")


@pytest.mark.parametrize("url", ["", "   "])
def test_generate_rejects_empty_url_as_malformed_provider_payload(url: str) -> None:
    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        _provider({"data": [{"url": url}]}).generate("cover")


@pytest.mark.parametrize(
    "response",
    [
        {"data": [{"b64_json": "not base64!"}]},
        {"data": [{"b64_json": "é"}]},
        {"data": [{"b64_json": ""}]},
        {"data": [{"b64_json": base64.b64encode(b"not-an-image").decode("ascii")}]} ,
        {"data": [{"b64_json": base64.b64encode(_image_bytes()[:-8]).decode("ascii")}]} ,
        {"data": []},
        {},
    ],
)
def test_generate_rejects_malformed_or_invalid_image_payload(response) -> None:
    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        _provider(response).generate("cover")


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_generate_accepts_supported_image_formats(image_format: str) -> None:
    source = _image_bytes(image_format)
    assert _provider(_b64_response(source)).generate("cover") == source


def test_generate_rejects_unsupported_image_format() -> None:
    source = _image_bytes("GIF")
    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        _provider(_b64_response(source)).generate("cover")


@pytest.mark.parametrize("status", [401, 403])
def test_generate_maps_unauthorized_errors(status: int) -> None:
    unauthorized = HTTPError("https://images.example.test/v1/images/generations", status, "no", None, None)
    with pytest.raises(CoverImageError, match="^image_provider_unauthorized$") as unauthorized_error:
        _provider(unauthorized).generate("cover")
    assert unauthorized_error.value.__cause__ is unauthorized


def test_generate_maps_timeout_error() -> None:
    timeout = TimeoutError("timed out")
    with pytest.raises(CoverImageError, match="^image_generation_timeout$") as timeout_error:
        _provider(timeout).generate("cover")
    assert timeout_error.value.__cause__ is timeout


@pytest.mark.parametrize(
    "timeout",
    [socket.timeout("timed out"), URLError(socket.timeout("timed out"))],
)
def test_generate_maps_direct_and_wrapped_socket_timeouts(timeout: Exception) -> None:
    with pytest.raises(CoverImageError, match="^image_generation_timeout$") as timeout_error:
        _provider(timeout).generate("cover")
    assert timeout_error.value.__cause__ is timeout


@pytest.mark.parametrize(
    "transport_error",
    [
        URLError("offline"),
        HTTPError("https://images.example.test/v1/images/generations", 503, "unavailable", None, None),
    ],
)
def test_generate_preserves_unrelated_transport_errors(transport_error: Exception) -> None:
    with pytest.raises(type(transport_error)) as error:
        _provider(transport_error).generate("cover")
    assert error.value is transport_error
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "parsing_error",
    [
        json.JSONDecodeError("invalid response JSON", "{", 1),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
)
def test_generate_maps_response_parsing_errors_to_invalid_image_payload(parsing_error: Exception) -> None:
    with pytest.raises(CoverImageError, match="^invalid_image_payload$") as error:
        _provider(parsing_error).generate("cover")
    assert error.value.__cause__ is parsing_error


def test_generate_enforces_encoded_decoded_and_dimension_limits(monkeypatch) -> None:
    provider = _provider(_b64_response(_image_bytes()))
    monkeypatch.setattr("packages.story_core.cover_image_provider.MAX_ENCODED_IMAGE_BYTES", 8)
    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        provider.generate("cover")

    monkeypatch.setattr("packages.story_core.cover_image_provider.MAX_ENCODED_IMAGE_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr("packages.story_core.cover_image_provider.MAX_DECODED_IMAGE_BYTES", 8)
    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        provider.generate("cover")

    monkeypatch.setattr("packages.story_core.cover_image_provider.MAX_DECODED_IMAGE_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr("packages.story_core.cover_image_provider.MAX_IMAGE_PIXELS", 1)
    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        provider.generate("cover")


def test_generate_accepts_image_at_encoded_and_decoded_size_boundaries(monkeypatch) -> None:
    source = _image_bytes()
    encoded_length = len(base64.b64encode(source))
    monkeypatch.setattr("packages.story_core.cover_image_provider.MAX_ENCODED_IMAGE_BYTES", encoded_length)
    monkeypatch.setattr("packages.story_core.cover_image_provider.MAX_DECODED_IMAGE_BYTES", len(source))

    assert _provider(_b64_response(source)).generate("cover") == source


def test_generate_rejects_failed_base64_preflight_without_decoding(monkeypatch) -> None:
    source = _image_bytes()
    response = _b64_response(source)
    decode_calls = []

    def forbidden_decode(*args, **kwargs):
        decode_calls.append((args, kwargs))
        raise AssertionError("base64 decoder should not run after failed preflight")

    monkeypatch.setattr("packages.story_core.cover_image_provider.MAX_DECODED_IMAGE_BYTES", len(source) - 1)
    monkeypatch.setattr("packages.story_core.cover_image_provider.base64.b64decode", forbidden_decode)

    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        _provider(response).generate("cover")
    assert decode_calls == []


def test_generate_rejects_image_over_40_megapixels_without_loading_pixels() -> None:
    width, height = 7_500, 6_000
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
    png += struct.pack(">I", binascii.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)

    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        _provider(_b64_response(png)).generate("cover")


def test_generate_rejects_pillow_decompression_bomb_error_without_warning_filter_mutation(monkeypatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 2)

    with pytest.raises(CoverImageError, match="^invalid_image_payload$"):
        _provider(_b64_response(_image_bytes(size=(3, 2)))).generate("cover")


def test_generate_maps_externally_escalated_pillow_bomb_warning_without_changing_filter(monkeypatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 4)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        ambient_filters = list(warnings.filters)

        with pytest.raises(CoverImageError, match="^invalid_image_payload$") as error:
            _provider(_b64_response(_image_bytes(size=(3, 2)))).generate("cover")

        assert isinstance(error.value.__cause__, Image.DecompressionBombWarning)
        assert warnings.filters == ambient_filters
