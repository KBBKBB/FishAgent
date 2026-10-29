"""Deterministic POI/routing mock around the user's location.

Candidate mix required by the contract: two <=2h round trips, one candidate
whose single trip exceeds 1h but round trip stays <=2h, two candidates over 2h,
two forbidden waters (one also over 2h) and one missing entry coordinate.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Any

from fishagent.core.coords import gcj02_to_wgs84, haversine_m, wgs84_to_gcj02
from fishagent.schemas import LatLon, PlaceCandidate, SpotCandidate

_MAX_RADIUS_M = 50_000

_SPOT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "mock_spot_001",
        "name": "青山水库",
        "water_type": "水库",
        "address": "杭州市示例区青山镇东岸",
        "east_km": 12.0,
        "north_km": 10.0,
        "downwind": True,
    },
    {
        "id": "mock_spot_002",
        "name": "白鹭湾野塘",
        "water_type": "野塘",
        "address": "杭州市示例区白鹭湾村北",
        "east_km": -18.0,
        "north_km": 8.0,
        "downwind": False,
    },
    {
        "id": "mock_spot_003",
        "name": "环城河湾",
        "water_type": "河流",
        "address": "杭州市示例区环城河道弯口",
        "east_km": 34.0,
        "north_km": 12.0,
        "downwind": False,
    },
    {
        "id": "mock_spot_004",
        "name": "云岭湖",
        "water_type": "湖泊",
        "address": "杭州市示例区云岭乡南岸",
        "east_km": 50.0,
        "north_km": 23.0,
        "downwind": True,
    },
    {
        "id": "mock_spot_005",
        "name": "西溪一级保护区水域",
        "water_type": "湖泊",
        "address": "杭州市示例区西溪水源保护范围",
        "east_km": 6.0,
        "north_km": -6.0,
        "downwind": False,
    },
    {
        "id": "mock_spot_006",
        "name": "南湖湿地",
        "water_type": "野塘",
        "address": "杭州市示例区南湖湿地西侧",
        "east_km": -30.0,
        "north_km": -25.0,
        "downwind": False,
        "missing_entry": True,
    },
    {
        "id": "mock_spot_007",
        "name": "竹溪河",
        "water_type": "河流",
        "address": "杭州市示例区竹溪镇河段",
        "east_km": 62.0,
        "north_km": -22.0,
        "downwind": False,
    },
    {
        "id": "mock_spot_008",
        "name": "北山一级保护区水库",
        "water_type": "水库",
        "address": "杭州市示例区北山水源保护范围",
        "east_km": -70.0,
        "north_km": 25.0,
        "downwind": False,
    },
    {
        "id": "mock_spot_009",
        "name": "远山湖",
        "water_type": "湖泊",
        "address": "杭州市示例区远山乡北岸",
        "east_km": -80.0,
        "north_km": -36.0,
        "downwind": False,
    },
)

_TRAVEL_FACTORS: dict[str, tuple[float, float]] = {
    "mock_spot_001": (1.00, 0.97),
    "mock_spot_002": (1.02, 0.98),
    "mock_spot_003": (1.00, 1.00),
    "mock_spot_004": (1.06, 0.90),
    "mock_spot_005": (1.01, 0.99),
    "mock_spot_006": (1.03, 0.98),
    "mock_spot_007": (1.05, 0.95),
    "mock_spot_008": (1.04, 0.96),
    "mock_spot_009": (1.05, 0.95),
}


def _in_china(lat: float, lon: float) -> bool:
    return 72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271


def _build_candidates(origin_gcj: LatLon) -> list[SpotCandidate]:
    lat_factor = 111.32
    lon_factor = 111.32 * math.cos(math.radians(origin_gcj.lat))
    candidates: list[SpotCandidate] = []
    for spec in _SPOT_SPECS:
        lat = round(origin_gcj.lat + spec["north_km"] / lat_factor, 6)
        lon = round(origin_gcj.lon + spec["east_km"] / lon_factor, 6)
        entry = None
        if not spec.get("missing_entry"):
            entry = LatLon(lat=round(lat + 0.0012, 6), lon=round(lon - 0.0009, 6))
        candidates.append(
            SpotCandidate(
                id=spec["id"],
                name=spec["name"],
                water_type=spec["water_type"],
                address=spec["address"],
                location_gcj02=LatLon(lat=lat, lon=lon),
                entry_location_gcj02=entry,
                downwind=bool(spec.get("downwind")),
            )
        )
    return candidates


class MockGeoProvider:
    """Mock POI search around the user; each call still honours <=50 km."""

    # The mock models asymmetric out/back travel factors, so the service must
    # ask for both directions. The live AMap provider ignores ``direction`` and
    # leaves this False, halving its calls.
    direction_affects_result = True

    async def find_water_spots(
        self,
        origin: LatLon,
        center: LatLon,
        radius_m: int,
    ) -> list[SpotCandidate]:
        if radius_m > _MAX_RADIUS_M:
            raise ValueError("radius_m must be <= 50000")
        if radius_m <= 0 or not _in_china(origin.lat, origin.lon):
            return []

        origin_gcj = wgs84_to_gcj02(origin.lat, origin.lon)
        center_gcj = wgs84_to_gcj02(center.lat, center.lon)
        origin_gcj_model = LatLon(lat=origin_gcj.lat, lon=origin_gcj.lon)
        center_gcj_model = LatLon(lat=center_gcj.lat, lon=center_gcj.lon)

        result: list[SpotCandidate] = []
        for candidate in _build_candidates(origin_gcj_model):
            location = candidate.location_gcj02
            distance = haversine_m(
                center_gcj_model.lat,
                center_gcj_model.lon,
                location.lat,
                location.lon,
            )
            if distance <= radius_m:
                result.append(candidate)
        return result

    async def search_places(self, keyword: str, *, limit: int = 8) -> list[PlaceCandidate]:
        """Deterministic name search so the picker works without a real key."""
        text = (keyword or "").strip()
        if not text:
            return []
        # Match against the known demo spots first, then fall back to a single
        # synthetic result so the UI always has something to select.
        matches = [spec for spec in _SPOT_SPECS if text in spec["name"]]
        results: list[PlaceCandidate] = []
        for spec in matches[:limit]:
            results.append(
                PlaceCandidate(
                    name=spec["name"],
                    address=spec["address"],
                    lat=round(30.657 + spec["north_km"] / 111.32, 4),
                    lon=round(104.066 + spec["east_km"] / 86.0, 4),
                    kind="place",
                )
            )
        if results:
            return results
        return [
            PlaceCandidate(
                name=text,
                address="Mock 地名解析结果",
                lat=30.657,
                lon=104.066,
                kind="place",
            )
        ]

    async def nearby_water(
        self, origin: LatLon, *, radius_m: int = 30_000, limit: int = 8
    ) -> list[PlaceCandidate]:
        """Nearby demo water bodies, in the same shape as the live provider."""
        if radius_m <= 0:
            return []
        origin_gcj = wgs84_to_gcj02(origin.lat, origin.lon)
        places: list[PlaceCandidate] = []
        for candidate in _build_candidates(
            LatLon(lat=origin_gcj.lat, lon=origin_gcj.lon)
        ):
            location = candidate.location_gcj02
            distance = haversine_m(
                origin_gcj.lat, origin_gcj.lon, location.lat, location.lon
            )
            if distance > radius_m:
                continue
            wgs = gcj02_to_wgs84(location.lat, location.lon)
            places.append(
                PlaceCandidate(
                    name=candidate.name,
                    address=candidate.address,
                    lat=round(wgs.lat, 4),
                    lon=round(wgs.lon, 4),
                    kind=candidate.water_type,
                    distance_m=int(distance),
                )
            )
        places.sort(key=lambda item: item.distance_m or 0)
        return places[:limit]

    async def estimate_drive_seconds(
        self,
        origin: LatLon,
        destination: LatLon,
        departure_at: datetime,
        direction: str,
        route_key: str = "",
    ) -> int:
        destination_wgs = gcj02_to_wgs84(destination.lat, destination.lon)
        distance_km = haversine_m(
            origin.lat,
            origin.lon,
            destination_wgs.lat,
            destination_wgs.lon,
        ) / 1000.0

        out_factor, back_factor = _TRAVEL_FACTORS.get(route_key, (1.0, 1.0))
        if route_key not in _TRAVEL_FACTORS:
            digest = int(
                hashlib.sha256(f"{route_key}|{direction}".encode("utf-8")).hexdigest()[:6],
                16,
            )
            jitter = 0.97 + (digest % 61) / 1000.0
            out_factor = back_factor = jitter

        base_minutes = distance_km / 55.0 * 60.0
        factor = out_factor if direction == "out" else back_factor
        return max(60, round(base_minutes * factor * 60.0))
