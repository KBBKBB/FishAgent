from __future__ import annotations

import pytest

from fishagent.providers.amap import AMapGeoProvider
from fishagent.schemas import LatLon

HANGZHOU = LatLon(lat=30.2741, lon=120.1551)


def _poi(poi_id: str, name: str, typecode: str, location: str, **extra: str) -> dict:
    return {
        "id": poi_id,
        "name": name,
        "typecode": typecode,
        "location": location,
        "type": "自然地名;自然地名",
        **extra,
    }


@pytest.mark.asyncio
async def test_around_search_uses_water_types_and_filters_business_pois(monkeypatch):
    provider = AMapGeoProvider(api_key="test-key", qps=50)
    captured: dict[str, dict] = {}

    payload = {
        "status": "1",
        "pois": [
            _poi("r1", "泸溪河桃酥", "050000", "120.1600,30.2700"),
            _poi("r2", "桃花河小区", "120302", "120.1610,30.2710"),
            _poi("r3", "千岛湖鱼味馆", "050100", "120.1620,30.2720"),
            _poi("r4", "沿山河社区", "120303", "120.1630,30.2730"),
            _poi("w1", "古新河", "190204", "120.1555,30.2750"),
            _poi(
                "w2",
                "西湖",
                "110202",
                "120.1500,30.2500",
                entr_location="120.1510,30.2510",
            ),
            _poi("w3", "青山水库", "190205", "119.9800,30.3000"),
        ],
    }

    async def fake_get(path: str, params: dict) -> dict:
        captured["path"] = path
        captured["params"] = params
        return payload

    monkeypatch.setattr(provider, "_get", fake_get)

    spots = await provider.find_water_spots(HANGZHOU, HANGZHOU, 50_000)

    assert [spot.name for spot in spots] == ["古新河", "西湖", "青山水库"]
    assert [spot.water_type for spot in spots] == ["河流", "湖泊", "水库"]
    assert spots[1].entry_location_gcj02 == LatLon(lat=30.2510, lon=120.1510)

    params = captured["params"]
    assert captured["path"] == "/v3/place/around"
    assert params["types"] == "190204|190205"
    assert params["sortrule"] == "distance"
    assert params["extensions"] == "all"
    assert params["radius"] == 50_000
    assert "keywords" not in params


@pytest.mark.asyncio
async def test_batch_distance_uses_single_destination_and_parses_results(monkeypatch):
    provider = AMapGeoProvider(api_key="test-key", qps=50)
    captured: dict[str, dict] = {}

    payload = {
        "status": "1",
        "results": [
            {"origin_id": "1", "distance": "760", "duration": "180"},
            {"origin_id": "2", "distance": "3200", "duration": "540"},
            {"origin_id": "3", "distance": "9999", "duration": "6000"},
        ],
    }

    async def fake_get(path: str, params: dict) -> dict:
        captured["path"] = path
        captured["params"] = params
        return payload

    monkeypatch.setattr(provider, "_get", fake_get)

    destinations = [
        LatLon(lat=30.2750, lon=120.1555),
        LatLon(lat=30.2600, lon=120.1700),
        LatLon(lat=30.3000, lon=120.1200),
    ]
    durations = await provider.estimate_batch_drive_seconds(HANGZHOU, destinations)

    assert durations == [180, 540, 6000]
    params = captured["params"]
    assert captured["path"] == "/v3/distance"
    assert params["type"] == 1
    assert params["origins"].count("|") == 2
    assert "," in params["destination"] and "|" not in params["destination"]


@pytest.mark.asyncio
async def test_around_search_rejects_water_like_names_without_water_typecode(monkeypatch):
    provider = AMapGeoProvider(api_key="test-key", qps=50)
    payload = {
        "status": "1",
        "pois": [
            _poi("r1", "桃花河小区", "120302", "120.1610,30.2710"),
            _poi("r2", "千岛湖鱼味馆", "050100", "120.1620,30.2720"),
        ],
    }

    async def fake_get(path: str, params: dict) -> dict:
        return payload

    monkeypatch.setattr(provider, "_get", fake_get)

    assert await provider.find_water_spots(HANGZHOU, HANGZHOU, 50_000) == []


@pytest.mark.asyncio
async def test_around_search_keeps_multi_typecode_water_pois(monkeypatch):
    provider = AMapGeoProvider(api_key="test-key", qps=50)
    payload = {
        "status": "1",
        "pois": [
            _poi("w4", "华家池", "190301|120302|190204", "120.1700,30.2800"),
            _poi("r5", "华家池餐厅", "050100|120302", "120.1701,30.2801"),
            _poi("r6", "华家池小区", "120302|120303", "120.1702,30.2802"),
        ],
    }

    async def fake_get(path: str, params: dict) -> dict:
        return payload

    monkeypatch.setattr(provider, "_get", fake_get)

    spots = await provider.find_water_spots(HANGZHOU, HANGZHOU, 50_000)

    assert [spot.name for spot in spots] == ["华家池"]
    assert spots[0].water_type == "河流"


@pytest.mark.asyncio
async def test_around_search_excludes_business_pois_tagged_as_water(monkeypatch):
    provider = AMapGeoProvider(api_key="test-key", qps=50)
    payload = {
        "status": "1",
        "pois": [
            _poi(
                "b1",
                "碗山河·西南风味菜·现炒浇头面(水璟唐店)",
                "190204",
                "104.085373,30.643728",
            ),
            _poi("b2", "碗山河", "050000", "104.085373,30.643728"),
            _poi(
                "w1",
                "华家池",
                "190301|120302|190204",
                "120.1942,30.2669",
            ),
            _poi("b3", "华家池餐厅", "050100|120302", "120.1943,30.2670"),
            _poi("w2", "古新河", "190204", "120.1555,30.2750"),
            _poi("w3", "菜子湖", "190205", "117.0000,30.6000"),
        ],
    }

    async def fake_get(path: str, params: dict) -> dict:
        return payload

    monkeypatch.setattr(provider, "_get", fake_get)

    spots = await provider.find_water_spots(HANGZHOU, HANGZHOU, 50_000)

    assert [spot.name for spot in spots] == ["华家池", "古新河", "菜子湖"]


COMMERCIAL_WATER_SUFFIXES = (
    "经营部",
    "商行",
    "公司",
    "工厂",
    "加工厂",
    "建材",
    "沙石",
    "砂石",
    "五金",
    "超市",
    "商店",
    "门市",
    "批发部",
    "经销部",
    "商贸",
)


@pytest.mark.parametrize("suffix", COMMERCIAL_WATER_SUFFIXES)
@pytest.mark.asyncio
async def test_around_search_excludes_commercial_name_suffixes(monkeypatch, suffix):
    provider = AMapGeoProvider(api_key="test-key", qps=50)
    payload = {
        "status": "1",
        "pois": [
            _poi("b1", f"示例{suffix}", "190204", "120.1600,30.2700"),
            _poi("w1", "锦江", "190204", "120.1555,30.2750"),
        ],
    }

    async def fake_get(path: str, params: dict) -> dict:
        return payload

    monkeypatch.setattr(provider, "_get", fake_get)

    spots = await provider.find_water_spots(HANGZHOU, HANGZHOU, 50_000)

    assert [spot.name for spot in spots] == ["锦江"]


@pytest.mark.asyncio
async def test_around_search_excludes_commercial_poi_and_keeps_plain_waters(monkeypatch):
    provider = AMapGeoProvider(api_key="test-key", qps=50)
    payload = {
        "status": "1",
        "pois": [
            _poi("b1", "水泥河沙经营部", "190204", "104.085373,30.643728"),
            _poi("w1", "锦江", "190204", "104.080000,30.640000"),
            _poi("w2", "府河", "190204", "104.070000,30.630000"),
            _poi("w3", "西郊河", "190204", "104.060000,30.650000"),
            _poi("w4", "沙河", "190204", "104.090000,30.660000"),
        ],
    }

    async def fake_get(path: str, params: dict) -> dict:
        return payload

    monkeypatch.setattr(provider, "_get", fake_get)

    spots = await provider.find_water_spots(HANGZHOU, HANGZHOU, 50_000)

    assert [spot.name for spot in spots] == ["锦江", "府河", "西郊河", "沙河"]
