"""水域 POI 召回 —— 对应 M1-T01 / M1-T02 / M1-T03 与红线 R2 / R4。

双路召回: type/around 周边搜索 ∪ 关键词搜索 (水库|湖|河|塘|野钓)。
radius 硬校验 (R2): v3/place/around 的 radius 超 50000 会被静默降级为 3000 且不报错,
因此必须在代码层断言, 禁止 > 50000 的值进入请求。
终点坐标 (R4): 优先使用 extensions=all 返回的 entr_location (POI 入口), 缺失回退中心点。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .amap import AmapClient, amap_error, is_amap_ok
from .config import (
    AMAP_AROUND_MAX_RADIUS,
    WATER_KEYWORDS,
    WATER_TYPECODES,
    Config,
)


class RadiusTooLargeError(ValueError):
    """R2: 半径超过 50000 米必须硬失败, 而不是静默降级。"""


def validate_radius(radius: int) -> int:
    """radius 硬校验 (R2)。"""
    if radius is None:
        raise RadiusTooLargeError("radius 不能为空")
    if radius <= 0:
        raise RadiusTooLargeError(f"radius 必须为正数, 收到 {radius}")
    if radius > AMAP_AROUND_MAX_RADIUS:
        raise RadiusTooLargeError(
            f"radius={radius} 超过硬上限 {AMAP_AROUND_MAX_RADIUS} 米; "
            "超出会被高德静默降级为 3000 米且不报错 (R2)。改用 sharding 网格分片。"
        )
    return radius


@dataclass
class WaterPoi:
    poi_id: str
    name: str
    type: str
    typecode: str
    location: str  # 中心点 "lng,lat" (GCJ-02)
    entr_location: str | None  # 入口坐标 "lng,lat" (GCJ-02), 可能缺失
    address: str
    source: str  # 召回路径: around | text | polygon

    @property
    def nav_point(self) -> str:
        """导航/精算终点: 优先入口坐标, 缺失回退中心点 (R4)。"""
        return self.entr_location or self.location

    @property
    def entr_missing(self) -> bool:
        """入口坐标缺失 -> 标记「端点精度较低」(M1-T03)。"""
        return not self.entr_location

    @property
    def key(self) -> str:
        return self.poi_id or f"{self.name}@{self.location}"


def _parse_pois(resp: dict[str, Any], source: str) -> list[WaterPoi]:
    out: list[WaterPoi] = []
    for p in resp.get("pois") or []:
        loc = p.get("location") or ""
        if not loc:
            continue
        entr = p.get("entr_location")
        out.append(
            WaterPoi(
                poi_id=str(p.get("id") or ""),
                name=str(p.get("name") or ""),
                type=str(p.get("type") or ""),
                typecode=str(p.get("typecode") or ""),
                location=str(loc),
                entr_location=str(entr) if entr else None,
                address=str(p.get("address")) if p.get("address") not in (None, []) else "",
                source=source,
            )
        )
    return out


def recall_around(
    client: AmapClient,
    location: str,
    radius: int,
    *,
    keywords: str = "|".join(WATER_KEYWORDS),
    page_size: int = 25,
    max_pages: int = 4,
) -> list[WaterPoi]:
    """路径 A: 周边搜索。location 必须已是 GCJ-02。"""
    validate_radius(radius)  # R2 硬校验
    pois: list[WaterPoi] = []
    for page in range(1, max_pages + 1):
        resp = client.place_around(
            location=location,
            radius=radius,
            keywords=keywords,
            extensions="all",  # 取 entr_location
            offset=page_size,
            page=page,
        )
        if not is_amap_ok(resp):
            raise RuntimeError(f"place/around 失败: {amap_error(resp)}")
        batch = _parse_pois(resp, "around")
        pois.extend(batch)
        if len(batch) < page_size:
            break
    return pois


def recall_by_type(
    client: AmapClient,
    location: str,
    radius: int,
    *,
    types: str = WATER_TYPECODES,
    page_size: int = 25,
    max_pages: int = 4,
) -> list[WaterPoi]:
    """路径 C: type 码搜索 (立项文档 4.2 的「type 码」路)。

    实测 (2026-10-11): 水系 POI 归入 190200 自然地名 (含 190204 河流 / 190205 湖泊),
    可按类型召回「江/浜/溪/淀」等【关键词路会漏掉】的水体。
    """
    validate_radius(radius)  # R2 硬校验
    pois: list[WaterPoi] = []
    for page in range(1, max_pages + 1):
        resp = client.place_around(
            location=location,
            radius=radius,
            types=types,
            extensions="all",
            offset=page_size,
            page=page,
        )
        if not is_amap_ok(resp):
            raise RuntimeError(f"place/around(types) 失败: {amap_error(resp)}")
        batch = _parse_pois(resp, "type")
        pois.extend(batch)
        if len(batch) < page_size:
            break
    return pois


def recall_text(
    client: AmapClient,
    keyword: str,
    *,
    city: str | None = None,
    page_size: int = 25,
    max_pages: int = 4,
) -> list[WaterPoi]:
    """路径 B: 关键字搜索 (双路召回之一)。"""
    pois: list[WaterPoi] = []
    for page in range(1, max_pages + 1):
        resp = client.place_text(
            keywords=keyword,
            city=city,
            citylimit="true" if city else None,
            extensions="all",
            offset=page_size,
            page=page,
        )
        if not is_amap_ok(resp):
            raise RuntimeError(f"place/text 失败: {amap_error(resp)}")
        batch = _parse_pois(resp, "text")
        pois.extend(batch)
        if len(batch) < page_size:
            break
    return pois


def recall_dual(
    client: AmapClient,
    location: str,
    radius: int,
    *,
    city: str | None = None,
    keywords: tuple[str, ...] = tuple(WATER_KEYWORDS),
    types: str = WATER_TYPECODES,
    dedup: bool = True,
) -> list[WaterPoi]:
    """双路召回并集 (M1-T01): type 码 ∪ 关键词搜索, 按 id 去重。

    注: 立项文档 4.2 的「双路」= type 码 + 关键词。早期实现把 type 码路写成
    「带关键词的周边搜索」, 与关键词路同源, 会系统性漏掉「江/浜/溪」类命名 (2026-10-11 实测)。
    """
    merged: dict[str, WaterPoi] = {}
    for poi in recall_by_type(client, location, radius, types=types):
        merged.setdefault(poi.key, poi)
    for kw in keywords:
        for poi in recall_text(client, kw, city=city):
            merged.setdefault(poi.key, poi)
    return list(merged.values())


def dedup_by_id(pois: list[WaterPoi]) -> list[WaterPoi]:
    seen: dict[str, WaterPoi] = {}
    for p in pois:
        seen.setdefault(p.key, p)
    return list(seen.values())


@dataclass
class RecallResult:
    """召回率实测结果 (M1-T01 / A1)。"""

    ground_truth: list[str]
    recalled: list[WaterPoi]
    matched: list[str] = field(default_factory=list)

    @property
    def recall_rate(self) -> float:
        if not self.ground_truth:
            return 0.0
        return len(self.matched) / len(self.ground_truth)


def measure_recall(ground_truth_names: set[str], recalled: list[WaterPoi]) -> RecallResult:
    """按名称集合计算召回率 (宽松口径: 名称包含即视为命中)。"""
    names = [p.name for p in recalled]
    matched = [gt for gt in ground_truth_names if any(gt in n or n in gt for n in names)]
    return RecallResult(ground_truth=sorted(ground_truth_names), recalled=recalled, matched=matched)
