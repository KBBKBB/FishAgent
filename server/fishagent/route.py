"""车程精算 —— 对应 M1-T03 / M1-T04 与红线 R4。

R4【强制】:
  · 终点必须取 POI 入口坐标 entr_location, 缺失回退中心点并标记精度较低;
  · 往返口径不得用「单程 × 2」近似, 必须 duration_去 + duration_回 ≤ 7200s 分别计算;
  · 距离测量 API 是 1 个终点 × 最多 100 个起点 (origins 以 | 分隔, 上限 100)。

⚠️ M1 待验证的关键点 (M1-T04): 「以用户为唯一起点、多水域为终点合并为一次请求」
   与该接口「1 终点 × N 起点」的实际参数结构可能不符 —— 详见 measure_round_trip 的注释
   与 Spec/M1/route-measurement.md 的实测结论。本模块把两种口径都显式实现, 以便实测对比。
"""

from __future__ import annotations

from dataclasses import dataclass

from .amap import AmapClient, amap_error, is_amap_ok
from .config import AMAP_DISTANCE_MAX_ORIGINS, ROUND_TRIP_MAX_SECONDS
from .poi import WaterPoi


def chunked(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


@dataclass
class DistanceResult:
    origin_id: str
    dest_id: str
    distance_m: float
    duration_s: float


def distance_batch(
    client: AmapClient,
    origins: list[str],
    destination: str,
    *,
    distance_type: int = 1,
) -> list[DistanceResult]:
    """批量距离测量: 1 个终点 × ≤100 个起点 (R4)。

    origins/destination 均为 'lng,lat' (GCJ-02)。
    超过 100 个起点会自动分片 (每片一次调用)。
    """
    results: list[DistanceResult] = []
    for chunk in chunked(origins, AMAP_DISTANCE_MAX_ORIGINS):
        resp = client.distance("|".join(chunk), destination, distance_type)
        if not is_amap_ok(resp):
            raise RuntimeError(f"v3/distance 失败: {amap_error(resp)}")
        for r in resp.get("results") or []:
            results.append(
                DistanceResult(
                    origin_id=str(r.get("origin_id") or ""),
                    dest_id=str(r.get("dest_id") or ""),
                    distance_m=float(r.get("distance") or 0),
                    duration_s=float(r.get("duration") or 0),
                )
            )
    return results


@dataclass
class RoundTrip:
    poi: WaterPoi
    outbound_s: float  # 去程: 用户 -> 钓位
    return_s: float  # 回程: 钓位 -> 用户
    outbound_m: float = 0.0
    return_m: float = 0.0
    # 口径: base=基准路况 / realtime=实时路况 (R4 记录口径与时刻)
    route_profile: str = "base"
    computed_at: str = ""

    @property
    def total_s(self) -> float:
        return self.outbound_s + self.return_s

    @property
    def within_2h(self) -> bool:
        """往返口径过滤: 去 + 回 ≤ 7200 秒 (R4)。"""
        return self.total_s <= ROUND_TRIP_MAX_SECONDS

    @property
    def one_way_estimated_min(self) -> float:
        return self.outbound_s / 60.0


def measure_round_trip_single(
    client: AmapClient,
    user_gcj: str,
    poi: WaterPoi,
    *,
    computed_at: str = "",
) -> RoundTrip:
    """精确往返: 去/回各调用一次 (方向敏感, 不用单程×2)。"""
    endpoint = poi.nav_point  # R4: 优先 entr_location
    out = distance_batch(client, [user_gcj], endpoint)
    back = distance_batch(client, [endpoint], user_gcj)
    return RoundTrip(
        poi=poi,
        outbound_s=out[0].duration_s if out else 0.0,
        return_s=back[0].duration_s if back else 0.0,
        outbound_m=out[0].distance_m if out else 0.0,
        return_m=back[0].distance_m if back else 0.0,
        computed_at=computed_at,
    )


def measure_round_trip_batch(
    client: AmapClient,
    user_gcj: str,
    pois: list[WaterPoi],
    *,
    computed_at: str = "",
) -> list[RoundTrip]:
    """批量往返: 复用「1 终点 × N 起点」结构。

    ⚠️ 实测要点 (M1-T04): 该接口每片只允许 **1 个终点**。
      · 回程 (钓位 -> 用户): 以用户为唯一终点, 钓位作起点 → 一次请求覆盖 ≤100 个候选 ✓
      · 去程 (用户 -> 钓位): 终点必须逐个为钓位 → 无法在同一次请求内覆盖多个候选 ✗
    因此「2 次请求覆盖 100 个候选」在参数结构上不成立, 需要 per-POI 调用或用
    v5/direction/driving 并行。本函数按此真实结构实现, 供成本核算 (T11)。
    """
    endpoints = [(p, p.nav_point) for p in pois if p.nav_point]
    # 回程: 一次批量 (destination=user, origins=多钓位)
    return_map: dict[str, DistanceResult] = {}
    for chunk in chunked(endpoints, AMAP_DISTANCE_MAX_ORIGINS):
        res = distance_batch(client, [ep for _, ep in chunk], user_gcj)
        for (poi, ep), r in zip(chunk, res):
            return_map[poi.key] = r
    trips: list[RoundTrip] = []
    for poi, ep in endpoints:
        out = distance_batch(client, [user_gcj], ep)
        r = return_map.get(poi.key)
        trips.append(
            RoundTrip(
                poi=poi,
                outbound_s=out[0].duration_s if out else 0.0,
                outbound_m=out[0].distance_m if out else 0.0,
                return_s=r.duration_s if r else 0.0,
                return_m=r.distance_m if r else 0.0,
                computed_at=computed_at,
            )
        )
    return trips


def filter_within_2h(trips: list[RoundTrip]) -> list[RoundTrip]:
    """往返 ≤ 2 小时的候选 (R4)。"""
    return [t for t in trips if t.within_2h]
