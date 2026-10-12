"""网格/同心环分片 —— 对应 M1-T02 (突破 radius 50km 上限的覆盖方案)。

背景 (R2): v3/place/around 单次 radius ≤ 50000 米, 超限静默降级为 3000 米。
要覆盖「可达性上界」量级的范围 (约 150km), 必须用多个 ≤50km 的圆分批覆盖。

本模块给出「网格多圆心」方案: 以固定间距布点, 每点一次 around(radius=50km)。
- 间距 s ≤ r·√2 时可保证无空洞 (格点四角到最近圆心的最大距离 s/√2 ≤ r)。
- 默认 spacing_factor=1.0 (s = r = 50km), 偏保守, 优先保证召回率 (M1 目标)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import AMAP_AROUND_MAX_RADIUS

# 每度纬度约 111.32 km; 经度随纬度收缩
M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lng(lat: float) -> float:
    return M_PER_DEG_LAT * math.cos(math.radians(lat))


def _offset(center_lat: float, center_lng: float, dx_m: float, dy_m: float) -> tuple[float, float]:
    """从中心点按东(x)北(y)方向偏移米, 返回 (lat, lng)。"""
    lat = center_lat + dy_m / M_PER_DEG_LAT
    lng = center_lng + dx_m / _m_per_deg_lng(center_lat)
    return lat, lng


@dataclass
class Tile:
    lat: float
    lng: float
    radius: int

    @property
    def location(self) -> str:
        """高德 location 参数格式: 'lng,lat'。"""
        return f"{self.lng:.6f},{self.lat:.6f}"

    def distance_to(self, lat: float, lng: float) -> float:
        # 近似平面距离 (M1 内部用, 足够)
        dx = (self.lng - lng) * _m_per_deg_lng(lat)
        dy = (self.lat - lat) * M_PER_DEG_LAT
        return math.hypot(dx, dy)


@dataclass
class ShardPlan:
    center_lat: float
    center_lng: float
    coverage_radius_m: float
    tile_radius: int
    tiles: list[Tile] = field(default_factory=list)
    note: str = ""

    @property
    def estimated_calls(self) -> int:
        return len(self.tiles)

    def to_dict(self) -> dict:
        return {
            "center": [round(self.center_lat, 6), round(self.center_lng, 6)],
            "coverage_radius_km": round(self.coverage_radius_m / 1000, 1),
            "tile_radius_m": self.tile_radius,
            "tile_count": len(self.tiles),
            "estimated_calls": self.estimated_calls,
            "note": self.note,
        }


def plan_grid(
    center_lat: float,
    center_lng: float,
    coverage_radius_m: float,
    *,
    tile_radius: int = AMAP_AROUND_MAX_RADIUS,
    spacing_factor: float = 1.0,
) -> ShardPlan:
    """生成覆盖以中心为原点、半径 coverage_radius_m 的网格分片。"""
    if tile_radius > AMAP_AROUND_MAX_RADIUS:
        raise ValueError(f"tile_radius 超过 {AMAP_AROUND_MAX_RADIUS} (R2)")
    spacing = tile_radius * spacing_factor
    step_lat = spacing / M_PER_DEG_LAT
    step_lng = spacing / _m_per_deg_lng(center_lat)
    n_lat = math.ceil(coverage_radius_m / spacing)
    n_lng = math.ceil(coverage_radius_m / spacing)

    tiles: list[Tile] = []
    for i in range(-n_lat, n_lat + 1):
        for j in range(-n_lng, n_lng + 1):
            dx, dy = j * spacing, i * spacing
            # 只保留「圆」相关的格点: 圆心仍在覆盖半径 + 一个半径冗余内
            if math.hypot(dx, dy) > coverage_radius_m + tile_radius:
                continue
            lat, lng = _offset(center_lat, center_lng, dx, dy)
            tiles.append(Tile(lat=lat, lng=lng, radius=tile_radius))
    note = (
        f"网格间距 {spacing/1000:.1f}km (tile_radius={tile_radius/1000:.1f}km, "
        f"factor={spacing_factor}); spacing≤r·√2 时无空洞"
    )
    return ShardPlan(center_lat, center_lng, coverage_radius_m, tile_radius, tiles, note)


def plan_rings(
    center_lat: float,
    center_lng: float,
    coverage_radius_m: float,
    *,
    tile_radius: int = AMAP_AROUND_MAX_RADIUS,
    min_ring_radius_m: float = 0.0,
) -> ShardPlan:
    """同心环方案 (作为网格的对照): 中心 1 点 + 若干同心圆上的均布点。"""
    if tile_radius > AMAP_AROUND_MAX_RADIUS:
        raise ValueError(f"tile_radius 超过 {AMAP_AROUND_MAX_RADIUS} (R2)")
    tiles = [Tile(center_lat, center_lng, tile_radius)]
    # 环间距 r, 圆周点数按周长均分
    ring_index = 1
    ring_r = tile_radius
    while ring_r <= coverage_radius_m:
        circumference = 2 * math.pi * ring_r
        n_points = max(6, math.ceil(circumference / (tile_radius * 1.5)))
        for k in range(n_points):
            angle = 2 * math.pi * k / n_points
            dx = ring_r * math.cos(angle)
            dy = ring_r * math.sin(angle)
            lat, lng = _offset(center_lat, center_lng, dx, dy)
            tiles.append(Tile(lat=lat, lng=lng, radius=tile_radius))
        ring_index += 1
        ring_r = ring_index * tile_radius
    return ShardPlan(
        center_lat, center_lng, coverage_radius_m, tile_radius, tiles,
        note="同心环方案 (对照用; 圆周点间距近似, 可能有空洞)",
    )


def reachability_upper_bound_km(avg_speed_kmh: float, hours: float = 2.0, margin: float = 1.0) -> float:
    """由「2 小时 × 平均车速 × 冗余」推算粗筛可达性上界 (立项文档 2.2)。

    市区 ~30km/h → ~60km; 高速 80~100km/h → ~160~200km。
    分片必须按可达性上界设界, 否则会系统性漏掉城市间高速沿线的水库。
    """
    return avg_speed_kmh * hours * margin
