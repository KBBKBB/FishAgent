"""AMap Web Service adapter for water POIs and driving durations.

All map calls receive GCJ-02 coordinates; WGS84 is converted only at this
boundary. Requires AMAP_WEB_KEY and real network access (not exercised by the
Mock acceptance path).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

import httpx

from fishagent.core.coords import gcj02_to_wgs84, wgs84_to_gcj02
from fishagent.providers.base import ProviderError
from fishagent.schemas import LatLon, PlaceCandidate, SpotCandidate

logger = logging.getLogger(__name__)

_MAX_RADIUS_M = 50_000
_MAX_ATTEMPTS = 3
_QPS_HINTS = ("QPS", "TOO_FREQUENT")
_NATURAL_WATER_TYPES = "190204|190205"
_WATER_TYPE_CODES = {"190204": "河流", "190205": "湖泊"}
_SCENIC_TYPE_CODE = "110202"
_WATER_NAME_HINTS = ("湖", "河", "江", "溪", "水库", "塘", "湿地", "湾", "泊", "淀")
_BUSINESS_NAME_KEYWORDS = (
    "餐厅",
    "饭店",
    "饭馆",
    "餐馆",
    "菜馆",
    "面馆",
    "食府",
    "食坊",
    "酒楼",
    "酒家",
    "火锅",
    "烧烤",
    "小吃",
    "快餐",
    "料理",
    "咖啡",
    "茶楼",
    "茶餐厅",
    "农家乐",
    "鱼庄",
    "鱼馆",
    "鱼味馆",
    "桃酥",
    "风味菜",
    "浇头面",
    "现炒",
    "餐饮",
    "美食",
    "分店",
    "门店",
    "旗舰店",
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
_BUSINESS_STORE_PATTERN = re.compile(r"[（(][^（）()]*店[）)]")


def _parse_location(value: Any) -> LatLon | None:
    if not isinstance(value, str) or "," not in value:
        return None
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        lon, lat = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (72.0 <= lon <= 138.0 and 0.0 <= lat <= 56.0):
        return None
    return LatLon(lat=lat, lon=lon)


def _coerce_distance(value: Any) -> int | None:
    """AMap reports distance as a metres string; absent for some POI types."""
    try:
        metres = float(value)
    except (TypeError, ValueError):
        return None
    return int(metres) if metres >= 0 else None


def _parse_batch_durations(payload: dict[str, Any], count: int) -> list[int | None]:
    durations: list[int | None] = [None] * count
    for position, item in enumerate(payload.get("results") or []):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("origin_id", position + 1)) - 1
            duration = int(float(item.get("duration")))
        except (TypeError, ValueError):
            continue
        if 0 <= index < count and duration > 0:
            durations[index] = duration
    return durations


def _typecodes(typecode: str) -> list[str]:
    return [code.strip() for code in typecode.split("|") if code.strip()]


def _has_business_name(name: str) -> bool:
    if any(keyword in name for keyword in _BUSINESS_NAME_KEYWORDS):
        return True
    return bool(_BUSINESS_STORE_PATTERN.search(name))


def _is_water_poi(name: str, typecode: str) -> bool:
    codes = _typecodes(typecode)
    is_water = any(code in _WATER_TYPE_CODES for code in codes) or (
        _SCENIC_TYPE_CODE in codes
        and any(hint in name for hint in _WATER_NAME_HINTS)
    )
    if not is_water:
        return False
    return not _has_business_name(name)


def _is_water_place(name: str, typecode: str) -> bool:
    """Looser water test for TEXT search results.

    ``/v3/place/text`` returns coarse category codes (``110200`` 风景名胜区,
    ``110203`` 水库, ``110000`` 景区) where ``/v3/place/around`` returns the
    leaf codes ``_is_water_poi`` was written against (``190204`` 河流,
    ``190205`` 湖泊). Reusing the strict test here matched nothing at all, so
    the ranking silently did nothing on every live search.

    The rule is therefore prefix-based, with the name as the deciding signal:
    anything under 风景名胜/公园 that names a water body counts, as does a
    name carrying a water word regardless of category (bridges and dams do not
    name a body of water, so they stay out).
    """
    if _has_business_name(name):
        return False
    codes = _typecodes(typecode)
    named_water = any(hint in name for hint in _WATER_NAME_HINTS)
    if not named_water:
        return False
    scenic = any(code.startswith(("1102", "1100")) for code in codes)
    strict = any(code in _WATER_TYPE_CODES for code in codes)
    # 桥梁/码头/收费站 describe access to water, not a place to fish from.
    if any(word in name for word in ("桥", "码头", "收费站", "闸", "堤")):
        return False
    return bool(scenic or strict)


def _water_type(name: str, typecode: str) -> str:
    codes = _typecodes(typecode)
    if "水库" in name:
        return "水库"
    if "塘" in name or "湿地" in name:
        return "野塘"
    if "190204" in codes or any(hint in name for hint in ("河", "江", "溪")):
        return "河流"
    if "190205" in codes or any(hint in name for hint in ("湖", "泊", "淀")):
        return "湖泊"
    return "水域"


class AMapGeoProvider:
    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 10.0,
        qps: float = 2.0,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._base_url = "https://restapi.amap.com"
        self._min_interval = 1.0 / max(qps, 0.1)
        self._pace_lock = asyncio.Lock()
        self._next_slot = 0.0

    async def _wait_for_slot(self) -> None:
        async with self._pace_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next_slot:
                await asyncio.sleep(self._next_slot - now)
                now = loop.time()
            self._next_slot = now + self._min_interval

    async def find_water_spots(
        self,
        origin: LatLon,
        center: LatLon,
        radius_m: int,
    ) -> list[SpotCandidate]:
        if radius_m > _MAX_RADIUS_M:
            raise ValueError("AMap around search radius must be <= 50000")
        if radius_m <= 0:
            return []

        center_gcj = wgs84_to_gcj02(center.lat, center.lon)
        payload = await self._get(
            "/v3/place/around",
            {
                "key": self._api_key,
                "location": f"{center_gcj.lon:.6f},{center_gcj.lat:.6f}",
                "radius": int(radius_m),
                "types": _NATURAL_WATER_TYPES,
                "sortrule": "distance",
                "offset": 50,
                "page": 1,
                "extensions": "all",
            },
        )

        spots: list[SpotCandidate] = []
        for poi in payload.get("pois") or []:
            if not isinstance(poi, dict):
                continue
            name = str(poi.get("name") or "").strip()
            typecode = str(poi.get("typecode") or "").strip()
            location = _parse_location(poi.get("location"))
            if not name or location is None or not _is_water_poi(name, typecode):
                continue
            entry = _parse_location(poi.get("entr_location"))
            spots.append(
                SpotCandidate(
                    id=str(poi.get("id") or f"amap_{len(spots)}"),
                    name=name,
                    water_type=_water_type(name, typecode),
                    address=str(poi.get("address") or "").strip(),
                    location_gcj02=location,
                    entry_location_gcj02=entry,
                )
            )
        if not spots:
            logger.warning("AMap around search returned no usable POIs")
        return spots

    async def search_places(self, keyword: str, *, limit: int = 8) -> list[PlaceCandidate]:
        """Text search for a place by name, for the location picker.

        Separate from ``find_water_spots``: the user typed something they know
        by name ("青龙湖"), and it may be an administrative area, a scenic spot
        or a water body. Nothing is filtered out — a village or a park gate is a
        perfectly good place to start from — but water is ranked first, because
        that is nearly always what an angler meant.

        Coordinates come back converted to WGS84, because that is what the rest
        of the API accepts; the datum shift happens at this boundary only.
        """
        text = (keyword or "").strip()
        if not text:
            return []
        payload = await self._get(
            "/v3/place/text",
            {
                "key": self._api_key,
                "keywords": text,
                "offset": max(1, min(limit, 20)),
                "page": 1,
                "extensions": "base",
            },
        )
        # Water first. Searching "三岔湖" returned the lake, the reservoir and a
        # hotel, then a motorway toll gate: all correct matches, but only the
        # water is somewhere an angler can fish from. Ranking is stable, so
        # AMap's own relevance order survives inside each group.
        water: list[PlaceCandidate] = []
        others: list[PlaceCandidate] = []
        for poi in payload.get("pois") or []:
            if not isinstance(poi, dict):
                continue
            name = str(poi.get("name") or "").strip()
            location = _parse_location(poi.get("location"))
            if not name or location is None:
                continue
            # AMap answers in GCJ-02; the API accepts WGS84 everywhere else.
            wgs = gcj02_to_wgs84(location.lat, location.lon)
            typecode = str(poi.get("typecode") or "").strip()
            # Text search reports coarse category codes, not the leaf codes
            # _is_water_poi expects; see _is_water_place.
            is_water = _is_water_place(name, typecode)
            entry = PlaceCandidate(
                name=name,
                address=str(poi.get("address") or "").strip(),
                lat=round(wgs.lat, 4),
                lon=round(wgs.lon, 4),
                kind=_water_type(name, typecode) if is_water else "place",
            )
            (water if is_water else others).append(entry)
        return water + others

    async def nearby_water(
        self, origin: LatLon, *, radius_m: int = 30_000, limit: int = 8
    ) -> list[PlaceCandidate]:
        """Water bodies around a point, as tappable choices.

        Shares the classification used by the spot recommender, so the list
        cannot offer a river that the recommender would then reject.
        """
        if radius_m <= 0:
            return []
        center = wgs84_to_gcj02(origin.lat, origin.lon)
        payload = await self._get(
            "/v3/place/around",
            {
                "key": self._api_key,
                "location": f"{center.lon:.6f},{center.lat:.6f}",
                "radius": int(min(radius_m, _MAX_RADIUS_M)),
                "types": _NATURAL_WATER_TYPES,
                "sortrule": "distance",
                "offset": max(1, min(limit, 25)),
                "page": 1,
                "extensions": "base",
            },
        )
        places: list[PlaceCandidate] = []
        for poi in payload.get("pois") or []:
            if not isinstance(poi, dict):
                continue
            name = str(poi.get("name") or "").strip()
            typecode = str(poi.get("typecode") or "").strip()
            location = _parse_location(poi.get("location"))
            if not name or location is None or not _is_water_poi(name, typecode):
                continue
            distance = poi.get("distance")
            wgs = gcj02_to_wgs84(location.lat, location.lon)
            places.append(
                PlaceCandidate(
                    name=name,
                    address=str(poi.get("address") or "").strip(),
                    lat=round(wgs.lat, 4),
                    lon=round(wgs.lon, 4),
                    kind=_water_type(name, typecode),
                    distance_m=_coerce_distance(distance),
                )
            )
        return places

    async def estimate_drive_seconds(
        self,
        origin: LatLon,
        destination: LatLon,
        departure_at: datetime,
        direction: str,
        route_key: str = "",
    ) -> int:
        # Baseline traffic per R4: sort with baseline, display as an estimate.
        origin_gcj = wgs84_to_gcj02(origin.lat, origin.lon)
        payload = await self._get(
            "/v5/direction/driving",
            {
                "key": self._api_key,
                "origin": f"{origin_gcj.lon:.6f},{origin_gcj.lat:.6f}",
                "destination": f"{destination.lon:.6f},{destination.lat:.6f}",
                "strategy": 0,
                "show_fields": "cost",
            },
        )
        paths = (payload.get("route") or {}).get("paths") or []
        if not paths:
            raise ProviderError("路径规划失败，无法获得车程")
        path = paths[0] if isinstance(paths[0], dict) else {}
        duration = (path.get("cost") or {}).get("duration") or path.get("duration")
        try:
            seconds = int(float(duration))
        except (TypeError, ValueError) as exc:
            raise ProviderError("路径规划返回缺少时长") from exc
        if seconds <= 0:
            raise ProviderError("路径规划返回时长不合法")
        return seconds

    async def estimate_batch_drive_seconds(
        self,
        origin: LatLon,
        destinations: list[LatLon],
    ) -> list[int | None]:
        if not destinations:
            return []
        capped = destinations[:100]
        origin_gcj = wgs84_to_gcj02(origin.lat, origin.lon)
        payload = await self._get(
            "/v3/distance",
            {
                "key": self._api_key,
                "origins": "|".join(
                    f"{point.lon:.6f},{point.lat:.6f}" for point in capped
                ),
                "destination": f"{origin_gcj.lon:.6f},{origin_gcj.lat:.6f}",
                "type": 1,
            },
        )
        return _parse_batch_durations(payload, len(capped))

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(_MAX_ATTEMPTS):
            await self._wait_for_slot()
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(f"{self._base_url}{path}", params=params)
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                if attempt + 1 < _MAX_ATTEMPTS:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                raise ProviderError("高德服务暂时不可用") from exc

            if isinstance(payload, dict) and str(payload.get("status")) == "1":
                return payload
            info = str(payload.get("info") or "") if isinstance(payload, dict) else ""
            if attempt + 1 < _MAX_ATTEMPTS and any(hint in info.upper() for hint in _QPS_HINTS):
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise ProviderError(f"高德接口调用失败：{info or '未知错误'}")
        raise ProviderError("高德服务暂时不可用")
