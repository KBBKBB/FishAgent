"""Validate and normalise an uploaded photo, entirely in memory.

CR-05 §3: the upload is bounded while streaming, decoded by Pillow (neither
Content-Type nor the filename is trusted), resized and re-encoded as JPEG.
Nothing is written to disk or cached, and the original bytes are dropped as
soon as the request ends.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import warnings
import weakref
from contextlib import asynccontextmanager
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from fishagent.errors import ApiError

logger = logging.getLogger(__name__)

# HEIF/AVIF come from ``pillow-heif``: iPhones shoot HEIC by default, and Safari
# only sometimes transcodes on upload, so a photo picked from Files can arrive
# as-is. Registering the opener is what makes Pillow able to decode them at all.
try:  # pragma: no cover - exercised by the HEIC tests when the extra is present
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_AVAILABLE = True
except ImportError:  # pragma: no cover - the dependency is declared, not optional
    _HEIF_AVAILABLE = False

ACCEPTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF", "HEIF", "AVIF"})

READ_CHUNK_BYTES = 64 * 1024
_MB = 1_000_000

# The pixel ceiling and the decode pricing live in Settings (identify_*), not
# here: a hardcoded ceiling is exactly what caused the 2026-10-27 outage, when
# 40 MP rejected every 48 MP iPhone photo and accepting a new camera resolution
# required a code change. Pillow's own ``Image.MAX_IMAGE_PIXELS`` is a process
# global, so it is synced from settings once at startup (``sync_pillow_limits``)
# rather than mutated per request — concurrent requests would race on it.


# Keyed by event loop: ``asyncio.Semaphore`` binds to the loop it first waits
# on, so a single global instance raises "bound to a different event loop"
# wherever a second loop exists (every test using ``asyncio.run``).
_DECODE_ADMISSION: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, tuple[tuple[int, int, float], _DecodeAdmission]
] = weakref.WeakKeyDictionary()


class _DecodeAdmission:
    """Weighted admission control: a concurrent-decode cap plus a memory budget.

    Deliberately hand-rolled: ``asyncio.Semaphore`` cannot be acquired with a
    weight (only ``threading.Semaphore`` can), so pricing each decode by
    megabytes needs an explicit condition. Checking both constraints under one
    lock also means there is no acquire ordering to get wrong, so the pair
    cannot deadlock against each other.
    """

    def __init__(
        self, max_concurrent: int, budget_mb: int, bytes_per_pixel: float = 7.5
    ) -> None:
        self.max_concurrent = max_concurrent
        self.budget_mb = budget_mb
        self.bytes_per_pixel = bytes_per_pixel
        self._active = 0
        self._in_use_mb = 0
        self._cond = asyncio.Condition()

    def weight_for(self, width: int, height: int) -> int:
        """Megabytes this decode is expected to claim, clamped to the budget.

        Clamping matters: a request larger than the entire budget could never
        be admitted, so it would wait forever rather than fail.
        """
        if width <= 0 or height <= 0:
            return 1  # unknown header; assume the cheapest ticket
        estimated = (width * height) * self.bytes_per_pixel / _MB
        return max(1, min(int(estimated + 0.999), self.budget_mb))

    @asynccontextmanager
    async def admit(self, weight_mb: int):
        async with self._cond:
            while not (
                self._active < self.max_concurrent
                and self._in_use_mb + weight_mb <= self.budget_mb
            ):
                await self._cond.wait()
            self._active += 1
            self._in_use_mb += weight_mb
        try:
            yield
        finally:
            async with self._cond:
                self._active -= 1
                self._in_use_mb -= weight_mb
                # notify_all, not notify(1): waiters have different sizes, so
                # the one woken arbitrarily may still not fit and would stall
                # the whole queue behind it.
                self._cond.notify_all()


def _decode_admission(
    max_concurrent: int, budget_mb: int, bytes_per_pixel: float
) -> _DecodeAdmission:
    loop = asyncio.get_running_loop()
    key = (max_concurrent, budget_mb, bytes_per_pixel)
    entry = _DECODE_ADMISSION.get(loop)
    if entry is None or entry[0] != key:
        admission = _DecodeAdmission(max_concurrent, budget_mb, bytes_per_pixel)
        _DECODE_ADMISSION[loop] = (key, admission)
        return admission
    return entry[1]

# Three different failures used to share one message ("unsupported format"),
# which is only true for the first of them. A photo truncated in transit or a
# file that merely isn't an image are not a format problem, and telling the user
# to change formats sends them looking for the wrong fix.
_UNSUPPORTED_MESSAGE = "不支持的图片格式，请上传 JPEG/PNG/WEBP/GIF/HEIC 图片"
_CORRUPT_MESSAGE = "图片文件已损坏或不完整，请重新选择或重新拍摄"
# Pillow raises ``UnidentifiedImageError`` when it cannot read a header at all.
# That covers two causes we cannot tell apart from the bytes alone — the file
# is not an image (a PDF, a text file), or it is an image in a format Pillow has
# no opener for (camera RAW). The message therefore claims neither: it says the
# file could not be read as an image, and still lists what would work.
_NOT_IMAGE_MESSAGE = "这个文件无法作为图片读取，请选择一张 JPEG/PNG/WEBP/GIF/HEIC 鱼获照片"


class AsyncByteReader(Protocol):
    """The slice of ``starlette.datastructures.UploadFile`` used here."""

    async def read(self, size: int = -1) -> bytes: ...


def sync_pillow_limits(max_image_pixels: int) -> None:
    """Point Pillow's process-global bomb threshold at the configured ceiling.

    Pillow reads ``Image.MAX_IMAGE_PIXELS`` itself and raises
    ``DecompressionBombError`` above twice that value, so the global has to
    agree with ours or Pillow's hard error would fire at a different point than
    the explicit check below. Called once at startup because writing global
    state per request would race between concurrent uploads.

    The explicit ``width * height`` comparison in ``_open_verified`` stays the
    authority: Pillow's warning band is 1x-2x, and the configured ceiling must
    be what actually applies.
    """
    Image.MAX_IMAGE_PIXELS = int(max_image_pixels)


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


def _not_an_image() -> ApiError:
    """Pillow could not read a header: not a format we handle, or not a file.

    Shares the 415 status and ``UNSUPPORTED_MEDIA_TYPE`` code with a rejected
    format — from the bytes alone the two are indistinguishable — but carries
    its own wording so a user who uploaded a PDF is not told to "change format".
    """
    return _unsupported(_NOT_IMAGE_MESSAGE)


def _corrupt() -> ApiError:
    """The header parsed but the body did not: a truncated or damaged file."""
    return ApiError(
        status_code=415,
        code="IMAGE_CORRUPT",
        message=_CORRUPT_MESSAGE,
    )


def _too_many_pixels(width: int = 0, height: int = 0) -> ApiError:
    """A resolvable image that is simply too big to decode safely.

    Deliberately *not* a 415: the format is supported and the client's only
    remedy is to send a smaller photo, so this carries its own code and a
    message that says what to do rather than blaming the format.
    """
    if width > 0 and height > 0:
        detail = f"（{width}×{height}）"
    else:
        detail = ""
    return ApiError(
        status_code=413,
        code="IMAGE_TOO_LARGE",
        message=f"图片分辨率过大{detail}，请使用较小的照片或先在相册中缩小后重试",
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
        raise ApiError(
            status_code=415,
            code="IMAGE_EMPTY",
            message="图片内容为空，请重新选择文件",
        )
    return data


def decode_and_normalize(
    data: bytes,
    *,
    max_side: int,
    max_image_pixels: int,
    jpeg_quality: int,
) -> tuple[bytes, str]:
    """Decode, downscale, flatten to RGB and re-encode as JPEG.

    Returns ``(jpeg_bytes, "image/jpeg")``. The JPEG is encoded without any
    ``exif=`` argument and from a cleaned ``Image.info``, so EXIF (including the
    GPS tag phone cameras write) can never be carried into the bytes sent to
    the vision model.
    """
    source = _open_verified(data, max_image_pixels=max_image_pixels)
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
            rgb.save(buffer, format="JPEG", quality=jpeg_quality)
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
        # The header and body decoded (``_open_verified`` forced a full load),
        # but resize/convert still failed. That is a damaged or partly decodable
        # file, not a format we do not accept — the format is one of ours.
        raise _corrupt() from None
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
    max_image_pixels: int,
    jpeg_quality: int,
    max_concurrent_decodes: int,
    decode_memory_budget_mb: int,
    decode_bytes_per_pixel: float,
) -> tuple[bytes, str]:
    """Read a streamed upload and normalise it off the event loop.

    Every limit is a caller-supplied setting; nothing here is hardcoded, so a
    deployment can retune any of them without a code change.

    Admission is priced per photo: the header is peeked first (0.1 ms, no pixel
    decode) so a small photo can be admitted alongside others while an 80 MP
    one waits for the budget to clear. The streaming read and the header peek
    both happen outside admission, so a queued upload holds only its bytes.
    """
    data = await read_upload(upload, max_upload_bytes=max_upload_bytes)
    width, height = _peek_size(data)
    admission = _decode_admission(
        max(1, int(max_concurrent_decodes)),
        max(1, int(decode_memory_budget_mb)),
        float(decode_bytes_per_pixel),
    )
    weight = admission.weight_for(width, height)
    logger.info(
        "decode admission: %sx%s ~%d MB of %d MB budget (%d slots)",
        width,
        height,
        weight,
        admission.budget_mb,
        admission.max_concurrent,
    )
    started = time.monotonic()
    async with admission.admit(weight):
        queued = time.monotonic() - started
        if queued >= 0.1:
            logger.info("decode queue: waited %.2fs for %d MB", queued, weight)
        return await asyncio.to_thread(
            decode_and_normalize,
            data,
            max_side=max_side,
            max_image_pixels=max_image_pixels,
            jpeg_quality=jpeg_quality,
        )


def _open_verified(data: bytes, *, max_image_pixels: int) -> Image.Image:
    image: Image.Image | None = None
    try:
        with warnings.catch_warnings():
            # Pillow only hard-fails above 2x MAX_IMAGE_PIXELS; promote the
            # warning so the 1x-2x band is rejected too. The filter stays in
            # place for the decode below, which is where Pillow re-checks.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.format not in ACCEPTED_FORMATS:
                # Only the format name is logged — never the bytes or a digest
                # that could identify the photo.
                logger.info("upload rejected: format=%s not accepted", image.format)
                raise _unsupported()
            width, height = image.size
            if width <= 0 or height <= 0:
                logger.info("upload rejected: empty %s image %sx%s", image.format, width, height)
                raise _unsupported()
            # Explicit pixel check: never rely on Pillow's threshold alone.
            if width * height > max_image_pixels:
                logger.info(
                    "upload rejected: %s %sx%s = %s px exceeds %s",
                    image.format,
                    width,
                    height,
                    width * height,
                    max_image_pixels,
                )
                raise _too_many_pixels(width, height)
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
            size = image.size
            image.close()
        else:
            # Pillow raises the bomb warning *inside* ``Image.open`` before it
            # ever returns, so no handle exists yet. Re-read only the header,
            # with the warning silenced, to report the dimensions to the user.
            size = _peek_size(data)
        logger.info("upload rejected: decompression bomb %sx%s", *size)
        raise _too_many_pixels(*size) from None
    except UnidentifiedImageError:
        if image is not None:
            image.close()
        # Pillow could not read a header at all. That is either "not an image"
        # (a PDF, a text file) or an image in a format no installed opener
        # handles — we cannot tell which, so we do not claim it is a format
        # problem, and we still name the formats that do work.
        logger.info("upload rejected: no readable image header (unidentified)")
        raise _not_an_image() from None
    except (OSError, ValueError, SyntaxError, EOFError) as exc:
        if image is not None:
            image.close()
        # The header parsed (format was accepted above) but the body did not:
        # a truncated or corrupt file. The format is fine — telling the user to
        # switch formats would be wrong advice.
        logger.info("upload rejected: corrupt image body (%s)", type(exc).__name__)
        raise _corrupt() from None
    return image


def _peek_size(data: bytes) -> tuple[int, int]:
    """Read only the header for a size, ignoring bomb warnings.

    Used purely to put real dimensions in an error message; the header was
    already proven too large by the time this runs.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            header = Image.open(io.BytesIO(data))
            try:
                return header.size
            finally:
                header.close()
    except Exception:  # noqa: BLE001 - diagnostics only, never worth a 500
        return (0, 0)


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
