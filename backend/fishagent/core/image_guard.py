"""Validate and normalise an uploaded photo, entirely in memory.

CR-05 §3: the upload is bounded while streaming, decoded by Pillow (neither
Content-Type nor the filename is trusted), resized and re-encoded as JPEG.
Nothing is written to disk or cached, and the original bytes are dropped as
soon as the request ends.
"""

from __future__ import annotations

import asyncio
import io
import warnings
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from fishagent.errors import ApiError

ACCEPTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})

# 40 megapixels accepts a 4000x3000 phone photo (~12 MP) with headroom while
# still rejecting decompression bombs. Pillow raises a hard
# DecompressionBombError only above 2x this limit and merely emits
# DecompressionBombWarning in the 1x-2x band, so the warning is promoted to an
# error below and width*height is checked explicitly as well.
MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

JPEG_QUALITY = 85
READ_CHUNK_BYTES = 64 * 1024

_UNSUPPORTED_MESSAGE = "不支持的图片格式，请上传 JPEG/PNG/WEBP/GIF 图片"


class AsyncByteReader(Protocol):
    """The slice of ``starlette.datastructures.UploadFile`` used here."""

    async def read(self, size: int = -1) -> bytes: ...


def _too_large(max_upload_bytes: int) -> ApiError:
    return ApiError(
        status_code=413,
        code="PAYLOAD_TOO_LARGE",
        message=f"图片超过大小上限（{max_upload_bytes} 字节），请压缩后重试",
    )


def _unsupported(message: str = _UNSUPPORTED_MESSAGE) -> ApiError:
    return ApiError(
        status_code=415,
        code="UNSUPPORTED_MEDIA_TYPE",
        message=message,
    )


async def read_upload(upload: AsyncByteReader, *, max_upload_bytes: int) -> bytes:
    """Stream the upload, aborting as soon as the size cap is crossed.

    The body is read in fixed-size chunks instead of one ``read()`` so an
    oversized upload never materialises in memory in full.
    """
    if max_upload_bytes <= 0:
        raise _too_large(max_upload_bytes)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_upload_bytes:
            raise _too_large(max_upload_bytes)
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise _unsupported("图片内容为空")
    return data


def decode_and_normalize(data: bytes, *, max_side: int) -> tuple[bytes, str]:
    """Decode, downscale, flatten to RGB and re-encode as JPEG.

    Returns ``(jpeg_bytes, "image/jpeg")``. The JPEG is encoded without any
    ``exif=`` argument and from a cleaned ``Image.info``, so EXIF (including the
    GPS tag phone cameras write) can never be carried into the bytes sent to
    the vision model.
    """
    source = _open_verified(data)
    try:
        flattened = _flatten_transparency(source)
        resized = _resize(flattened, max_side)
        rgb = resized.convert("RGB")
        try:
            # Intent: never write EXIF back. ``Image.convert`` copies the source
            # ``info`` dict, and Pillow's JPEG encoder falls back to
            # ``im.info["comment"]``; clearing it (plus never passing ``exif=``)
            # guarantees the re-encoded photo carries no metadata, so the GPS
            # coordinates of a phone photo cannot leak to the model provider.
            rgb.info.clear()

            buffer = io.BytesIO()
            rgb.save(buffer, format="JPEG", quality=JPEG_QUALITY)
            jpeg = buffer.getvalue()
        finally:
            rgb.close()
            if resized is not flattened:
                resized.close()
            if flattened is not source:
                flattened.close()
    except ApiError:
        raise
    except (OSError, ValueError, SyntaxError):
        # A file that decodes just enough to pass the header check but fails
        # during resize/convert is still an unusable image, not a server error.
        raise _unsupported() from None
    finally:
        source.close()
    if not jpeg:
        raise _unsupported("图片重新编码失败")
    return jpeg, "image/jpeg"


async def prepare_image(
    upload: AsyncByteReader,
    *,
    max_upload_bytes: int,
    max_side: int,
) -> tuple[bytes, str]:
    """Read a streamed upload and normalise it off the event loop."""
    data = await read_upload(upload, max_upload_bytes=max_upload_bytes)
    return await asyncio.to_thread(decode_and_normalize, data, max_side=max_side)


def _open_verified(data: bytes) -> Image.Image:
    image: Image.Image | None = None
    try:
        with warnings.catch_warnings():
            # Pillow only hard-fails above 2x MAX_IMAGE_PIXELS; promote the
            # warning so the 1x-2x band is rejected too. The filter stays in
            # place for the decode below, which is where Pillow re-checks.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.format not in ACCEPTED_FORMATS:
                raise _unsupported()
            width, height = image.size
            if width <= 0 or height <= 0:
                raise _unsupported()
            # Explicit pixel check: never rely on Pillow's threshold alone.
            if width * height > MAX_IMAGE_PIXELS:
                raise _unsupported("图片尺寸过大")
            # Force a real decode: a valid header with a truncated or corrupt
            # body must fail here rather than surface as a 500 later.
            image.seek(0)
            image.load()
    except ApiError:
        if image is not None:
            image.close()
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        if image is not None:
            image.close()
        raise _unsupported("图片尺寸过大") from None
    except UnidentifiedImageError:
        if image is not None:
            image.close()
        raise _unsupported() from None
    except (OSError, ValueError, SyntaxError, EOFError):
        if image is not None:
            image.close()
        raise _unsupported() from None
    return image


def _flatten_transparency(image: Image.Image) -> Image.Image:
    """Composite alpha/palette transparency onto white before JPEG encoding."""
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        rgba.close()
        return background
    return image


def _resize(image: Image.Image, max_side: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)
