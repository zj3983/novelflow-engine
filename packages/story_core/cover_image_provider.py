"""OpenAI-compatible cover-image generation with strict image validation."""

from __future__ import annotations

import base64
import binascii
import io
import socket
import urllib.error
import warnings
from collections.abc import Callable
from typing import Any

from PIL import Image, UnidentifiedImageError

from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.runtime_config import ImageRuntimeSettings, resolve_image_runtime


MAX_ENCODED_IMAGE_BYTES = 20 * 1024 * 1024
MAX_DECODED_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
_SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP"}


class CoverImageError(ValueError):
    """A stable, user-safe cover image generation failure."""


def _invalid_image_payload() -> CoverImageError:
    return CoverImageError("invalid_image_payload")


def _has_usable_base64(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        return False
    if len(encoded) > MAX_ENCODED_IMAGE_BYTES:
        return False
    try:
        return bool(base64.b64decode(encoded, validate=True))
    except (binascii.Error, ValueError):
        return False


def _decode_and_validate_image(encoded: str) -> bytes:
    if not isinstance(encoded, str) or not encoded.strip():
        raise _invalid_image_payload()
    try:
        encoded_bytes = encoded.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise _invalid_image_payload() from exc
    if len(encoded_bytes) > MAX_ENCODED_IMAGE_BYTES:
        raise _invalid_image_payload()
    try:
        image_bytes = base64.b64decode(encoded_bytes, validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise _invalid_image_payload() from exc
    if not image_bytes or len(image_bytes) > MAX_DECODED_IMAGE_BYTES:
        raise _invalid_image_payload()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_bytes)) as image:
                if image.format not in _SUPPORTED_FORMATS:
                    raise _invalid_image_payload()
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise _invalid_image_payload()
                image.verify()
            with Image.open(io.BytesIO(image_bytes)) as image:
                image.load()
    except CoverImageError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
    ) as exc:
        raise _invalid_image_payload() from exc
    return image_bytes


class OpenAICoverImageProvider:
    """Generate one cover image through an OpenAI-compatible image endpoint."""

    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[], ImageRuntimeSettings] = resolve_image_runtime,
    ) -> None:
        self._post_json = post_json
        self._runtime_resolver = runtime_resolver

    def generate(self, prompt: str) -> bytes:
        runtime = ImageRuntimeSettings.model_validate(self._runtime_resolver())
        payload = {
            "model": runtime.model,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
        }
        try:
            response = self._post_json(
                runtime.base_url,
                "/images/generations",
                payload,
                runtime.api_key,
                provider="openai",
                codex_command="",
            )
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise CoverImageError("image_provider_unauthorized") from exc
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise CoverImageError("image_generation_timeout") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise CoverImageError("image_generation_timeout") from exc
            raise

        try:
            data = response["data"]
            first = data[0]
        except (KeyError, IndexError, TypeError) as exc:
            raise _invalid_image_payload() from exc
        if not isinstance(first, dict):
            raise _invalid_image_payload()
        url = first.get("url")
        encoded = first.get("b64_json")
        has_usable_url = isinstance(url, str) and bool(url.strip())
        has_usable_base64 = _has_usable_base64(encoded)
        if has_usable_url and not has_usable_base64:
            raise CoverImageError("unsupported_image_response")
        return _decode_and_validate_image(encoded)


CoverImageProvider = OpenAICoverImageProvider
