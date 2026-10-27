"""CR-05: photo fish identification, image guard and vision adapter.

Covers the behaviours the contract pins down: upload bounds, real decode
(never trusting Content-Type), EXIF/GPS stripping, decompression-bomb guards,
the empty-``content`` trap, placeholder species, guardrail degradation and the
unified error bodies.
"""

from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from conftest import assert_unified_error
from PIL import Image

from fishagent.api.identify import PLACEHOLDER_SPECIES, _is_placeholder, _to_response
from fishagent.core.image_guard import (
    _HEIF_AVAILABLE,
    ACCEPTED_FORMATS,
    MAX_IMAGE_PIXELS,
    _DecodeAdmission,
    decode_and_normalize,
    prepare_image,
    read_upload,
)
from fishagent.errors import ApiError
from fishagent.providers.vision_fish import VisionFish, VisionFishIdentifier, _parse_payload


def run(coro):
    return asyncio.run(coro)


def _png(size: tuple[int, int] = (120, 90), mode: str = "RGB") -> bytes:
    image = Image.new(mode, size, (30, 95, 135) if mode == "RGB" else 128)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    return buffer.getvalue()


def _jpeg_with_gps() -> bytes:
    """A JPEG carrying a Make tag and a GPS block, as a phone would."""
    image = Image.new("RGB", (300, 200), (10, 100, 200))
    exif = image.getexif()
    exif[271] = "SecretPhone"
    exif[272] = "ModelX"
    exif[34853] = {1: "N", 2: (30.0, 15.0, 0.0), 3: "E", 4: (120.0, 10.0, 0.0)}
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    image.close()
    return buffer.getvalue()


class _Upload:
    """Minimal UploadFile stand-in: read(size) only."""

    def __init__(self, data: bytes, chunk: int = 64 * 1024) -> None:
        self._data = data
        self._chunk = chunk
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        size = self._chunk if size < 0 else size
        piece = self._data[self._offset : self._offset + size]
        self._offset += len(piece)
        return piece


# --- image guard: upload bounds ---------------------------------------------


def test_read_upload_stops_when_cap_is_crossed():
    """An oversized upload must abort mid-stream, not after full buffering."""
    payload = b"x" * (200 * 1024)
    with pytest.raises(ApiError) as excinfo:
        run(read_upload(_Upload(payload), max_upload_bytes=100 * 1024))
    assert excinfo.value.status_code == 413
    assert excinfo.value.code == "PAYLOAD_TOO_LARGE"


def test_read_upload_accepts_exactly_at_cap():
    payload = b"x" * (100 * 1024)
    assert run(read_upload(_Upload(payload), max_upload_bytes=100 * 1024)) == payload


def test_read_upload_rejects_empty_body():
    with pytest.raises(ApiError) as excinfo:
        run(read_upload(_Upload(b""), max_upload_bytes=1024))
    assert excinfo.value.status_code == 415


# --- image guard: decode, resize, EXIF ---------------------------------------


def test_decode_strips_exif_and_gps():
    """Phone photos carry GPS; the bytes sent to the model must not."""
    source = Image.open(io.BytesIO(_jpeg_with_gps()))
    assert source.getexif().get(271) == "SecretPhone"
    assert 34853 in source.getexif()
    source.close()

    jpeg, media_type = decode_and_normalize(_jpeg_with_gps(), max_side=1280)

    assert media_type == "image/jpeg"
    result = Image.open(io.BytesIO(jpeg))
    assert dict(result.getexif()) == {}, "EXIF must be dropped entirely"
    assert 34853 not in result.getexif(), "GPS tag must not survive re-encoding"
    result.close()
    assert b"SecretPhone" not in jpeg


def test_decode_downscales_long_side_but_keeps_aspect():
    jpeg, _ = decode_and_normalize(_png((400, 200)), max_side=100)
    image = Image.open(io.BytesIO(jpeg))
    assert max(image.size) == 100
    assert image.size[0] > image.size[1], "aspect ratio must be preserved"
    image.close()


def test_decode_does_not_upscale_small_images():
    jpeg, _ = decode_and_normalize(_png((80, 60)), max_side=1280)
    image = Image.open(io.BytesIO(jpeg))
    assert image.size == (80, 60)
    image.close()


def test_decode_trusts_pillow_not_the_extension():
    """A real PNG must pass even though nothing told us it was a PNG."""
    jpeg, _ = decode_and_normalize(_png(), max_side=1280)
    assert jpeg[:2] == b"\xff\xd8", "output must be a real JPEG regardless of input"


def test_decode_rejects_non_images():
    with pytest.raises(ApiError) as excinfo:
        decode_and_normalize(b"this is not an image at all", max_side=1280)
    assert excinfo.value.status_code == 415


def test_decode_rejects_truncated_image():
    truncated = _png()[:40]
    with pytest.raises(ApiError) as excinfo:
        decode_and_normalize(truncated, max_side=1280)
    assert excinfo.value.status_code == 415


@pytest.mark.parametrize("fmt", ["BMP", "TIFF"])
def test_decode_rejects_unlisted_formats(fmt):
    image = Image.new("RGB", (60, 40), (1, 2, 3))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    image.close()
    with pytest.raises(ApiError) as excinfo:
        decode_and_normalize(buffer.getvalue(), max_side=1280)
    assert excinfo.value.status_code == 415


# --- HEIC / AVIF: the iPhone default ---------------------------------------


def _heif_bytes(fmt: str = "HEIF", size: tuple[int, int] = (320, 240)) -> bytes:
    image = Image.new("RGB", size, (45, 105, 145))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    image.close()
    return buffer.getvalue()


@pytest.mark.parametrize("fmt", ["HEIF", "AVIF"])
def test_decode_accepts_heif_family(fmt):
    """iPhones shoot HEIC; Safari does not always transcode on upload."""
    if not _HEIF_AVAILABLE:
        pytest.skip("pillow-heif not installed")
    jpeg, media_type = decode_and_normalize(_heif_bytes(fmt), max_side=1280)
    assert media_type == "image/jpeg"
    result = Image.open(io.BytesIO(jpeg))
    assert result.format == "JPEG"
    assert max(result.size) <= 1280
    result.close()


def test_decode_heic_strips_exif():
    """The privacy promise must hold for the iPhone format too."""
    if not _HEIF_AVAILABLE:
        pytest.skip("pillow-heif not installed")
    image = Image.new("RGB", (300, 200), (60, 120, 160))
    exif = image.getexif()
    exif[271] = "iPhoneSecret"
    exif[34853] = {1: "N", 2: (31.0, 12.0, 0.0), 3: "E", 4: (121.0, 28.0, 0.0)}
    buffer = io.BytesIO()
    image.save(buffer, format="HEIF", exif=exif)
    image.close()

    jpeg, _ = decode_and_normalize(buffer.getvalue(), max_side=1280)
    result = Image.open(io.BytesIO(jpeg))
    assert dict(result.getexif()) == {}
    result.close()
    assert b"iPhoneSecret" not in jpeg


def test_decode_multiframe_heic_takes_first_frame():
    """Burst-style HEIC files carry several frames; only one must be used."""
    if not _HEIF_AVAILABLE:
        pytest.skip("pillow-heif not installed")
    frames = [Image.new("RGB", (200, 150), (i * 60, 90, 120)) for i in range(3)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="HEIF", save_all=True, append_images=frames[1:])
    for frame in frames:
        frame.close()

    jpeg, _ = decode_and_normalize(buffer.getvalue(), max_side=1280)
    result = Image.open(io.BytesIO(jpeg))
    assert result.size == (200, 150)
    result.close()


def test_heic_is_listed_as_accepted():
    assert "HEIF" in ACCEPTED_FORMATS
    assert "AVIF" in ACCEPTED_FORMATS


def test_unsupported_message_lists_every_accepted_family():
    """The 415 hint must not understate what the endpoint accepts."""
    from fishagent.core.image_guard import _UNSUPPORTED_MESSAGE

    for token in ("JPEG", "PNG", "WEBP", "GIF", "HEIC"):
        assert token in _UNSUPPORTED_MESSAGE, f"415 hint omits {token}"


def test_identify_endpoint_accepts_heic_upload(client):
    if not _HEIF_AVAILABLE:
        pytest.skip("pillow-heif not installed")
    response = client.post(
        "/api/agent/identify-fish",
        files={"image": ("IMG_0001.HEIC", _heif_bytes(), "image/heic")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["identified"] is True


def test_decode_rejects_decompression_bomb():
    """Pixel count alone must reject, well below Pillow's 2x hard-error line."""
    image = Image.new("L", (12000, 8000), 0)  # 96 MP > 80 MP cap
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    assert 12000 * 8000 > MAX_IMAGE_PIXELS
    with pytest.raises(ApiError) as excinfo:
        decode_and_normalize(buffer.getvalue(), max_side=1280)
    assert excinfo.value.status_code == 413
    assert excinfo.value.code == "IMAGE_TOO_LARGE"


def test_oversize_is_not_reported_as_an_unsupported_format():
    """Regression: a 48 MP iPhone photo was rejected as 415 "unsupported".

    The format *is* supported — the client's remedy is a smaller photo, not a
    different format, so the two failures must stay distinguishable.
    """
    image = Image.new("L", (12000, 8000), 0)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    with pytest.raises(ApiError) as excinfo:
        decode_and_normalize(buffer.getvalue(), max_side=1280)
    assert excinfo.value.code != "UNSUPPORTED_MEDIA_TYPE"
    assert "12000" in excinfo.value.message and "8000" in excinfo.value.message


@pytest.mark.parametrize(
    ("width", "height", "label"),
    [
        (4032, 3024, "12 MP default"),
        (5712, 4284, "24 MP"),
        (8064, 6048, "48 MP Pro"),
        (10800, 4000, "panorama"),
    ],
)
def test_decode_accepts_every_iphone_camera_resolution(width, height, label):
    """Real iPhone outputs must pass the guard; 48 MP used to be rejected."""
    assert width * height <= MAX_IMAGE_PIXELS, f"{label} no longer fits the cap"
    image = Image.new("RGB", (width, height), (20, 60, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=45)
    image.close()
    jpeg, _ = decode_and_normalize(buffer.getvalue(), max_side=1280)
    result = Image.open(io.BytesIO(jpeg))
    assert max(result.size) == 1280
    result.close()


@pytest.mark.skipif(not _HEIF_AVAILABLE, reason="pillow-heif not installed")
def test_decode_accepts_48mp_heic():
    """The exact combination that failed in production: 48 MP *and* HEIC."""
    image = Image.new("RGB", (8064, 6048), (20, 60, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="HEIF", quality=40)
    image.close()
    jpeg, media_type = decode_and_normalize(buffer.getvalue(), max_side=1280)
    assert media_type == "image/jpeg"
    result = Image.open(io.BytesIO(jpeg))
    assert max(result.size) == 1280
    result.close()


def test_decode_accepts_normal_phone_photo_size():
    """A 12 MP phone photo must not be rejected by the bomb guard."""
    image = Image.new("RGB", (4000, 3000), (20, 60, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=70)
    image.close()
    jpeg, _ = decode_and_normalize(buffer.getvalue(), max_side=1280)
    result = Image.open(io.BytesIO(jpeg))
    assert max(result.size) == 1280
    result.close()


# --- decode admission -------------------------------------------------------
#
# Decoding is the memory cost (~7.5 bytes/pixel, measured), so admission is
# priced per photo rather than by a fixed slot count. These tests assert peak
# concurrency directly rather than wall-clock time, which is machine-dependent.


def _track_decodes(monkeypatch, gate: float = 0.05):
    """Stub decode_and_normalize to record how many run at once."""
    state = {"current": 0, "peak": 0, "calls": 0}

    def fake_decode(data, *, max_side):
        state["calls"] += 1
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        try:
            import time

            time.sleep(gate)
            return b"\xff\xd8fake", "image/jpeg"
        finally:
            state["current"] -= 1

    monkeypatch.setattr("fishagent.core.image_guard.decode_and_normalize", fake_decode)
    return state


def _jpeg_of(size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, (20, 60, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=40)
    image.close()
    return buffer.getvalue()


def _prepare(payload: bytes, **kwargs):
    async def one():
        return await prepare_image(
            _Upload(payload),
            max_upload_bytes=64 * 1024 * 1024,
            max_side=1280,
            **kwargs,
        )

    return one()


def _gather(payload: bytes, count: int, **kwargs):
    async def all_of_them():
        return await asyncio.gather(
            *(_prepare(payload, **kwargs) for _ in range(count))
        )

    return run(all_of_them())


# --- weight estimation ------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "height", "low", "high"),
    [
        (4032, 3024, 80, 100),  # 12 MP measured ~91 MB
        (5712, 4284, 165, 195),  # 24 MP measured ~179 MB
        (8064, 6048, 330, 380),  # 48 MP measured ~356 MB
        (12000, 6000, 500, 550),  # 72 MP measured ~524 MB
    ],
)
def test_weight_estimate_tracks_the_measured_peak(width, height, low, high):
    """The estimate must stay close to real RSS, or the budget is fiction."""
    admission = _DecodeAdmission(max_concurrent=4, budget_mb=8192)
    weight = admission.weight_for(width, height)
    assert low <= weight <= high, f"{width}x{height} priced at {weight} MB"


def test_weight_is_clamped_to_the_budget():
    """An oversized request must not wait forever for more than the budget."""
    admission = _DecodeAdmission(max_concurrent=1, budget_mb=256)
    assert admission.weight_for(8000, 6000) == 256


def test_weight_of_unknown_size_is_the_minimum():
    admission = _DecodeAdmission(max_concurrent=1, budget_mb=256)
    assert admission.weight_for(0, 0) == 1


# --- admission behaviour ----------------------------------------------------


def test_small_photos_run_concurrently_within_the_memory_budget(monkeypatch):
    """Four 12 MP photos (~364 MB) fit in a 1 GB budget, so all run together."""
    state = _track_decodes(monkeypatch, gate=0.05)
    payload = _jpeg_of((4032, 3024))  # 12 MP -> ~91 MB each

    results = _gather(
        payload, 4, max_concurrent_decodes=4, decode_memory_budget_mb=1024
    )

    assert len(results) == 4
    assert state["calls"] == 4
    assert state["peak"] == 4, "small photos must not serialise on memory"


def test_large_photos_serialise_on_the_memory_budget(monkeypatch):
    """Two 48 MP photos (~356 MB each) cannot fit a 512 MB budget together."""
    state = _track_decodes(monkeypatch, gate=0.05)
    payload = _jpeg_of((8064, 6048))

    _gather(payload, 2, max_concurrent_decodes=8, decode_memory_budget_mb=512)

    assert state["calls"] == 2, "both must still be decoded, just not at once"
    assert state["peak"] == 1, "memory budget must serialise large photos"


def test_count_cap_applies_even_when_memory_is_plentiful(monkeypatch):
    """Small photos are cheap in RAM but each still burns a CPU core."""
    state = _track_decodes(monkeypatch, gate=0.05)
    payload = _jpeg_of((800, 600))

    _gather(payload, 6, max_concurrent_decodes=2, decode_memory_budget_mb=4096)

    assert state["calls"] == 6
    assert state["peak"] == 2, "the CPU cap must bind independently of memory"


def test_mixed_sizes_share_the_budget(monkeypatch):
    """A big photo must not be admitted beside another when it exhausts the budget."""
    state = _track_decodes(monkeypatch, gate=0.05)
    big = _jpeg_of((8064, 6048))  # ~366 MB at 7.5 bytes/px
    small = _jpeg_of((800, 600))  # ~4 MB

    # 360 MB cannot hold 366 + 4, so the pair must serialise even though the
    # count cap (4) would happily admit both.
    async def mixed():
        return await asyncio.gather(
            _prepare(big, max_concurrent_decodes=4, decode_memory_budget_mb=360),
            _prepare(small, max_concurrent_decodes=4, decode_memory_budget_mb=360),
        )

    run(mixed())
    assert state["calls"] == 2
    assert state["peak"] == 1, "the 360 MB budget cannot hold the 366 MB photo plus another"


def test_a_photo_larger_than_the_budget_still_runs(monkeypatch):
    """70 MP exceeds a small budget; clamping must let it through, not hang."""
    state = _track_decodes(monkeypatch, gate=0.01)
    huge = _jpeg_of((10800, 6000))  # ~486 MB estimated

    assert run(_prepare(huge, decode_memory_budget_mb=256))
    assert state["calls"] == 1


def test_admission_survives_a_second_event_loop(monkeypatch):
    """Each ``asyncio.run`` is a fresh loop; a global semaphore would explode."""
    _track_decodes(monkeypatch)

    assert run(_prepare(_png()))
    assert run(_prepare(_png())), "second run() on a new loop must not raise"


def test_zero_concurrency_is_coerced_to_one(monkeypatch):
    """A misconfigured 0 must not deadlock every upload."""
    state = _track_decodes(monkeypatch)

    assert run(_prepare(_png(), max_concurrent_decodes=0))
    assert state["calls"] == 1


def test_zero_memory_budget_cannot_deadlock():
    """A 0 MB budget would make every acquire block forever if not clamped."""
    assert run(_prepare(_png(), decode_memory_budget_mb=0))


def test_oversized_upload_never_claims_a_decode_slot(monkeypatch):
    """The size check must reject before any admission happens."""
    state = _track_decodes(monkeypatch)

    async def once():
        return await prepare_image(
            _Upload(b"x" * 4096),
            max_upload_bytes=1024,
            max_side=1280,
        )

    with pytest.raises(ApiError) as excinfo:
        run(once())
    assert excinfo.value.status_code == 413
    assert state["calls"] == 0, "an over-size upload must not reach the decoder"


# --- vision adapter ---------------------------------------------------------


class _Completions:
    def __init__(self, content: str | None, *, exc: Exception | None = None) -> None:
        self._content = content
        self._exc = exc
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        message = SimpleNamespace(content=self._content, reasoning_content="推理草稿")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _Client:
    def __init__(self, content: str | None, *, exc: Exception | None = None) -> None:
        self.chat = SimpleNamespace(completions=_Completions(content, exc=exc))


def test_identifier_parses_valid_payload():
    payload = json.dumps(
        {
            "identified": True,
            "species": "鲫鱼",
            "confidence": "high",
            "summary": "常见淡水鱼",
            "habits": "底层",
            "baits": ["蚯蚓"],
            "tips": "钓底",
            "caveats": "光线影响",
        },
        ensure_ascii=False,
    )
    result = run(VisionFishIdentifier(_Client(payload), "m").identify(_png()))
    assert result is not None
    assert result.identified is True
    assert result.species == "鲫鱼"
    assert result.confidence == "high"
    assert result.baits == ["蚯蚓"]


def test_identifier_never_uses_reasoning_content():
    """Empty content is a failure even when reasoning_content is present."""
    client = _Client("")
    identifier = VisionFishIdentifier(client, "m")
    assert run(identifier.identify(_png())) is None
    assert client.chat.completions.calls == 1


def test_identifier_tolerates_fenced_json():
    fenced = '```json\n{"identified":true,"species":"鲤鱼","confidence":"medium"}\n```'
    result = run(VisionFishIdentifier(_Client(fenced), "m").identify(_png()))
    assert result is not None and result.species == "鲤鱼"


def test_identifier_returns_none_on_call_failure():
    identifier = VisionFishIdentifier(_Client(None, exc=RuntimeError("boom")), "m")
    assert run(identifier.identify(_png())) is None


def test_identifier_returns_none_without_image():
    identifier = VisionFishIdentifier(_Client('{"identified":true}'), "m")
    assert run(identifier.identify(b"")) is None


def test_parse_payload_rejects_garbage():
    assert _parse_payload("no json here") is None
    assert _parse_payload("{broken") is None
    assert _parse_payload("[1,2,3]") is None


def test_parse_payload_normalises_invalid_confidence():
    result = _parse_payload('{"identified":true,"species":"鲫鱼","confidence":"certain"}')
    assert result is not None
    assert result.confidence is None


def test_parse_payload_treats_non_boolean_identified_as_false():
    result = _parse_payload('{"identified":"yes","species":"鲫鱼"}')
    assert result is not None
    assert result.identified is False


# --- response mapping: placeholders and guardrails --------------------------


@pytest.mark.parametrize(
    "placeholder",
    ["无法识别", "不确定", "未知", "none", "unknown", "无法识别（照片模糊）", "  "],
)
def test_placeholder_species_is_detected(placeholder):
    assert _is_placeholder(placeholder) is True


@pytest.mark.parametrize("species", ["鲫鱼", "翘嘴", "黄颡鱼", "鸭嘴鱼"])
def test_real_species_is_not_a_placeholder(species):
    assert species not in PLACEHOLDER_SPECIES
    assert _is_placeholder(species) is False


def test_unidentified_response_nulls_species_even_with_placeholder():
    """The model answers identified=false but still fills species."""
    result = VisionFish(identified=False, species="无法识别", confidence="low")
    response = _to_response(result)
    assert response.identified is False
    assert response.species is None
    assert response.raw_species is None
    assert response.message


def test_identified_with_placeholder_species_degrades():
    result = VisionFish(identified=True, species="无法识别")
    response = _to_response(result)
    assert response.identified is False
    assert response.species is None


def test_unknown_species_keeps_raw_name_and_flags_catalog():
    result = VisionFish(identified=True, species="鸭嘴鱼", confidence="medium")
    response = _to_response(result)
    assert response.identified is True
    assert response.species == "鸭嘴鱼"
    assert response.in_catalog is False


def test_alias_species_is_normalised_into_catalog():
    result = VisionFish(identified=True, species="胖头鱼", confidence="high")
    response = _to_response(result)
    assert response.species == "鲢鳙"
    assert response.in_catalog is True


def test_promissory_text_degrades_whole_answer():
    """A catch promise anywhere must not ship a partially sanitised result."""
    result = VisionFish(
        identified=True,
        species="鲫鱼",
        summary="这片水域保证爆护",
        baits=["蚯蚓"],
    )
    response = _to_response(result)
    assert response.identified is False
    assert response.species is None
    assert response.baits == []


def test_baits_are_cleaned_and_capped():
    result = VisionFish(
        identified=True,
        species="鲫鱼",
        baits=["蚯蚓", "蚯蚓", "", "红虫", "玉米", "商品饵", "麦粒"],
    )
    response = _to_response(result)
    assert response.baits == ["蚯蚓", "红虫", "玉米", "商品饵"]


def test_text_fields_are_clipped():
    result = VisionFish(identified=True, species="鲫鱼", summary="很长的描述" * 100)
    response = _to_response(result)
    assert response.summary is not None
    assert len(response.summary) <= 200


# --- API surface ------------------------------------------------------------


def test_identify_endpoint_returns_mock_result(client):
    response = client.post(
        "/api/agent/identify-fish",
        files={"image": ("fish.png", _png(), "image/png")},
        data={"note": "水库钓的"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["identified"] is True
    assert body["mode"] == "mock"
    assert body["ai_disclosure"]
    for key in (
        "species",
        "raw_species",
        "in_catalog",
        "confidence",
        "summary",
        "habits",
        "baits",
        "tips",
        "caveats",
        "generated_at",
    ):
        assert key in body, f"missing field: {key}"
    assert "message" not in body, "success response must not carry the message field"
    assert isinstance(body["baits"], list)


def test_identify_is_deterministic_in_mock_mode(client):
    files = {"image": ("fish.png", _png(), "image/png")}
    first = client.post("/api/agent/identify-fish", files=files).json()
    second = client.post("/api/agent/identify-fish", files=files).json()
    assert first["species"] == second["species"]
    assert first["summary"] == second["summary"]


def test_identify_rejects_non_image_with_unified_body(client):
    response = client.post(
        "/api/agent/identify-fish",
        files={"image": ("note.txt", b"not an image", "text/plain")},
    )
    detail = assert_unified_error(response, 415, "UNSUPPORTED_MEDIA_TYPE")
    assert detail["message"]


def test_identify_requires_image_field(client):
    response = client.post("/api/agent/identify-fish", data={"note": "x"})
    assert_unified_error(response, 422, "VALIDATION_ERROR")


def test_identify_rejects_overlong_note(client):
    response = client.post(
        "/api/agent/identify-fish",
        files={"image": ("fish.png", _png(), "image/png")},
        data={"note": "长" * 101},
    )
    assert response.status_code == 422


def test_identify_rejects_oversized_upload(client, monkeypatch):
    from fishagent.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "identify_max_upload_bytes", 1024, raising=False)
    response = client.post(
        "/api/agent/identify-fish",
        files={"image": ("big.png", b"x" * 4096, "image/png")},
    )
    assert_unified_error(response, 413, "PAYLOAD_TOO_LARGE")


def test_identify_route_is_registered(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/agent/identify-fish" in paths


def test_identify_reports_oversize_resolution_as_its_own_code(client, monkeypatch):
    """End-to-end: the client must be able to tell "too big" from "wrong format".

    This is the production failure: a 48 MP iPhone photo came back as 415 and
    the UI told the user the format was unsupported.
    """
    monkeypatch.setattr(
        "fishagent.core.image_guard.MAX_IMAGE_PIXELS", 1_000_000, raising=True
    )
    image = Image.new("RGB", (2000, 1500), (20, 60, 90))  # 3 MP, over the cap
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=40)
    image.close()

    response = client.post(
        "/api/agent/identify-fish",
        files={"image": ("IMG_0001.JPG", buffer.getvalue(), "image/jpeg")},
    )
    detail = assert_unified_error(response, 413, "IMAGE_TOO_LARGE")
    assert "2000" in detail["message"] and "1500" in detail["message"]
