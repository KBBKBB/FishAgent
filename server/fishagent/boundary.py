"""M2-B11 禁钓过滤：权威矢量边界（GeoJSON）+ 保守排除（R5）。

R5 要求：**高危类型不得依赖人工维护名单**，必须接入权威矢量边界，或**保守排除**。

本模块提供：
  · GeoJSON（Polygon / MultiPolygon）加载；
  · 射线法 point-in-polygon（零依赖）；
  · 分级（high=高危 / general=一般）；
  · 无矢量命中时的**关键词兜底**与「无边界数据即保守排除」开关。

⚠️ 生产须接入官方矢量数据（保护区/禁渔区）；本仓库提供机制与样例数据。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BanZone:
    name: str
    level: str  # high | general
    rings: list[list[list[float]]] = field(default_factory=list)  # 每个 ring 为 [[lng,lat], ...]


def _iter_rings(geometry: dict):
    t = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if t == "Polygon":
        for ring in coords:
            yield ring
    elif t == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                yield ring


def load_geojson(path: str | Path) -> list[BanZone]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("type") == "FeatureCollection":
        feats = data.get("features") or []
    elif data.get("type") == "Feature":
        feats = [data]
    else:
        feats = [{"geometry": data, "properties": {}}]
    zones: list[BanZone] = []
    for f in feats:
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        level = str(props.get("level") or props.get("risk") or "general").lower()
        name = str(props.get("name") or "未命名禁钓区")
        rings = [list(r) for r in _iter_rings(geom)]
        if rings:
            zones.append(BanZone(name=name, level=level, rings=rings))
    return zones


def point_in_ring(lng: float, lat: float, ring: list[list[float]]) -> bool:
    """射线法（ray casting）。ring 为 [[lng,lat], ...]。"""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_in_zone(lng: float, lat: float, zone: BanZone) -> bool:
    return any(point_in_ring(lng, lat, ring) for ring in zone.rings)


class BanZoneIndex:
    """禁钓边界索引 + 判定。"""

    def __init__(
        self,
        zones: list[BanZone] | None = None,
        *,
        fallback_keywords: tuple[str, ...] = (),
        unknown_is_banned: bool = False,
    ) -> None:
        self.zones = zones or []
        self.fallback_keywords = tuple(fallback_keywords)
        self.unknown_is_banned = unknown_is_banned

    @classmethod
    def from_geojson(cls, path: str | Path, **kw) -> "BanZoneIndex":
        return cls(load_geojson(path), **kw)

    def classify(self, lng: float, lat: float) -> tuple[str, str] | None:
        """返回 (level, zone_name) 或 None。命中多个时取**最高危**。"""
        hits = [z for z in self.zones if point_in_zone(lng, lat, z)]
        if not hits:
            return None
        hits.sort(key=lambda z: 0 if z.level == "high" else 1)
        return hits[0].level, hits[0].name

    def is_banned(self, lng: float, lat: float, *, name: str = "", type_: str = "", address: str = "") -> tuple[bool, str]:
        hit = self.classify(lng, lat)
        if hit:
            level, zone_name = hit
            return True, f"落入禁钓边界：{zone_name}（{level}）"
        text = f"{name}{type_}{address}"
        for kw in self.fallback_keywords:
            if kw in text:
                return True, f"名称/类型命中禁钓关键词：{kw}"
        if not self.zones and self.unknown_is_banned:
            return True, "无权威边界数据，按 R5 保守排除"
        return False, ""
