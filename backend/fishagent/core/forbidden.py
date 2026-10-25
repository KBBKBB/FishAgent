"""Forbidden-water filtering under the D11 default-allow policy (TechStack R5).

All waters are allowed by default; a spot is excluded only when its name hits
the protection-area / no-fishing / water-source / military keyword list or it
falls inside a configured forbidden circle. Name matching is a heuristic, not
an authoritative legal boundary: callers must keep the "check local notices"
disclaimer and must not promise that every no-fishing water is excluded.
"""

from __future__ import annotations

from typing import NamedTuple

from fishagent.core.coords import haversine_m
from fishagent.schemas import LatLon

FORBIDDEN_NAME_KEYWORDS = (
    "一级保护区",
    "二级保护区",
    "饮用水源",
    "水源保护",
    "禁钓",
    "禁渔",
    "养殖",
    "承包",
    "泄洪",
    "高压线",
    "军事",
    "自然保护区",
    "国家公园",
    "自然保护地",
    "风景名胜区",
    "森林公园",
    "湿地公园",
    "地质公园",
    "水产种质资源保护区",
    "种质资源保护区",
)


class ForbiddenZone(NamedTuple):
    name: str
    center: LatLon
    radius_m: float


# GCJ-02 demo zone; mock spot names cover the same rule for generated spots.
DEMO_FORBIDDEN_ZONES = (
    ForbiddenZone(
        name="示例禁钓圆区（西湖水源保护区）",
        center=LatLon(lat=30.2460, lon=120.1490),
        radius_m=2500.0,
    ),
)


def forbidden_reason(name: str, location_gcj02: LatLon) -> str | None:
    text = name or ""
    for keyword in FORBIDDEN_NAME_KEYWORDS:
        if keyword in text:
            return f"名称命中禁钓关键词「{keyword}」"
    for zone in DEMO_FORBIDDEN_ZONES:
        distance = haversine_m(
            location_gcj02.lat,
            location_gcj02.lon,
            zone.center.lat,
            zone.center.lon,
        )
        if distance <= zone.radius_m:
            return f"位于{zone.name}"
    return None
