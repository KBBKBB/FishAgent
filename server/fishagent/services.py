"""M2 服务编排层 —— 把「鱼情分析」与「钓位推荐」两个核心用例串起来。

对应 Spec/Roadmap.md §3.1/3.2：
  M2-B03 气象接入 · M2-B04/B05 规则引擎与可解释输出
  M2-B06 双路召回 · M2-B07 网格分片 · M2-B08/B09 往返精算与过滤
  M2-B10 综合排序 · M2-B11 禁钓过滤(R5, 保守启发式)

设计要点：
  · 所有外部依赖（高德/气象）通过 ServiceContext 注入，便于单测与离线演示；
  · 坐标一律经 coord.wgs84_to_gcj02（R1）；
  · 输出含 AI 生成标识与免责声明（R6/R8）。
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict

from . import factors, sharding
from .amap import AmapClient
from .config import WATER_KEYWORDS, Config
from .coord import haversine_m, wgs84_to_gcj02
from .mock import MockAmapClient
from .poi import WaterPoi, dedup_by_id, recall_around, recall_by_type
from .route import RoundTrip, measure_round_trip_batch
from .weather import WeatherSeries, fetch_archive_pressure, fetch_forecast

DISCLAIMER = "本结论为 AI 生成的参考建议，非气象预报，不保证渔获。"

# R5 禁钓过滤（MVP 保守启发式；M2-B11 须接入权威矢量边界，不得仅依赖名单）
BANNED_KEYWORDS = ("饮用水源", "一级保护区", "禁渔", "军事", "自然保护区核心", "禁钓")


class ServiceContext:
    """聚合外部客户端与开关，便于测试注入 mock / 合成气象。"""

    def __init__(
        self,
        amap,
        *,
        offline: bool = False,
        weather_forecast=None,
        weather_archive=None,
    ) -> None:
        self.amap = amap
        self.offline = offline
        self._forecast = weather_forecast or fetch_forecast
        self._archive = weather_archive or fetch_archive_pressure

    def forecast(self, lat: float, lng: float, **kw) -> WeatherSeries:
        return self._forecast(lat, lng, **kw)

    def archive(self, lat: float, lng: float, **kw) -> list[float]:
        return self._archive(lat, lng, **kw)


def build_context(offline: bool = False) -> ServiceContext:
    """构造服务上下文。offline=True 用 mock 高德 + 合成气象（无需任何 Key）。"""
    if offline:
        return ServiceContext(
            MockAmapClient(),
            offline=True,
            weather_forecast=lambda lat, lng, **kw: synthetic_weather_series(),
            weather_archive=lambda lat, lng, **kw: [1010.0 + i * 0.02 for i in range(720)],
        )
    cfg = Config()
    cfg.require_amap()  # R3: 密钥仅服务端持有
    return ServiceContext(AmapClient(cfg), offline=False)


def synthetic_weather_series(*, hours: int = 96, base_pressure: float = 1015.0) -> WeatherSeries:
    """合成气象序列（仅离线演示 / 单测；不可作实测结论）。"""
    start = dt.datetime.now().replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=24)
    times, pressure, temp, wind, precip, cloud = [], [], [], [], [], []
    for h in range(hours):
        t = start + dt.timedelta(hours=h)
        times.append(t.isoformat())
        pressure.append(base_pressure + 4 * math.sin(h / 24 * math.pi))
        temp.append(20 + 5 * math.sin((h % 24 - 6) / 24 * 2 * math.pi))
        wind.append(12.0)
        precip.append(0.0)
        cloud.append(50.0)
    return WeatherSeries(
        latitude=0.0, longitude=0.0, timezone="Asia/Shanghai", times=times,
        variables={
            "pressure_msl": pressure, "temperature_2m": temp,
            "wind_speed_10m": wind, "precipitation": precip, "cloud_cover": cloud,
        },
        daily={"sunrise": [times[6]], "sunset": [times[18]],
               "temperature_2m_max": [25.0], "temperature_2m_min": [15.0]},
    )


def _index_for(series: WeatherSeries, when: dt.datetime | None) -> int:
    """取与 when（默认现在）最接近的小时下标。"""
    if not series.times:
        raise ValueError("空气象序列")
    when = when or dt.datetime.now()
    best, best_d = 0, None
    for i, t in enumerate(series.times):
        try:
            ti = dt.datetime.fromisoformat(t)
        except ValueError:
            continue
        d = abs((ti - when).total_seconds())
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


# ---------------------------------------------------------------- 用例 1：鱼情分析

def analyze_fish_activity(
    ctx: ServiceContext,
    lat: float,
    lng: float,
    *,
    when: dt.datetime | None = None,
    archive_days: int = 30,
) -> dict:
    """鱼情活跃度分析（M2-B03/B04/B05）。"""
    series = ctx.forecast(lat, lng)
    idx = _index_for(series, when)
    archive: list[float] = []
    if archive_days:
        try:
            archive = ctx.archive(lat, lng, days=archive_days)
        except Exception:  # noqa: BLE001 归档失败不致命，F2 会走兜底
            archive = []
    score = factors.evaluate(series, idx, archive_pressure=archive)
    glat, glng = wgs84_to_gcj02(lat, lng)
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "location": {"wgs84": [lat, lng], "gcj02": [round(glat, 6), round(glng, 6)]},
        "time": series.times[idx],
        "score": round(score.total, 1),
        "level": score.level,
        "action": score.action,
        "top_factors": [asdict(f) for f in score.top3],
        "factors": [asdict(f) for f in score.factors],
        "advisories": score.advisories,
        "explanation": factors.render_explanation(score),
        "ai_generated": True,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- 用例 2：钓位推荐

def is_banned(poi: WaterPoi) -> bool:
    """R5 禁钓保守过滤（启发式）。⚠️ MVP 临时实现，M2-B11 须换权威矢量边界。"""
    text = f"{poi.name}{poi.type}{poi.address}"
    return any(k in text for k in BANNED_KEYWORDS)


def _trip_to_dict(t: RoundTrip) -> dict:
    return {
        "name": t.poi.name,
        "type": t.poi.type,
        "location": t.poi.location,
        "entr_location": t.poi.entr_location,
        "endpoint_precision": "low" if t.poi.entr_missing else "ok",
        "address": t.poi.address,
        "outbound_min": round(t.outbound_s / 60, 1),
        "return_min": round(t.return_s / 60, 1),
        "round_trip_min": round(t.total_s / 60, 1),
        "estimated": True,
    }


def recommend_spots(
    ctx: ServiceContext,
    lat: float,
    lng: float,
    *,
    limit: int = 5,
    coverage_km: float = 150.0,
    spacing_factor: float = 1.414,
    max_pages: int = 2,
    max_candidates: int = 40,
) -> dict:
    """钓位推荐（M2-B06/B07/B08/B09/B10/B11）。"""
    glat, glng = wgs84_to_gcj02(lat, lng)
    user = f"{glng:.6f},{glat:.6f}"
    plan = sharding.plan_grid(lat, lng, coverage_km * 1000, spacing_factor=spacing_factor)

    collected: list[WaterPoi] = []
    for tile in plan.tiles:
        # type 码路（190200 自然地名）+ 关键词周边路（M1 实测：两路互补）
        collected += recall_by_type(ctx.amap, tile.location, tile.radius, max_pages=max_pages)
        collected += recall_around(ctx.amap, tile.location, tile.radius, max_pages=max_pages)
    pois = dedup_by_id(collected)

    def _ll(p: WaterPoi) -> tuple[float, float]:
        lng_, la_ = p.nav_point.split(",")
        return float(la_), float(lng_)

    # 去程不可批量（R4），只对直线距离最近的 N 个候选做往返精算
    pois.sort(key=lambda p: haversine_m(lat, lng, *_ll(p)))
    candidates = pois[:max_candidates]

    trips = measure_round_trip_batch(
        ctx.amap, user, candidates,
        computed_at=dt.datetime.now().isoformat(timespec="seconds"),
    )
    within = [t for t in trips if t.within_2h and not is_banned(t.poi)]  # R4 + R5
    within.sort(key=lambda t: t.total_s)

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "origin": {"wgs84": [lat, lng], "gcj02": [round(glat, 6), round(glng, 6)]},
        "coverage_km": coverage_km,
        "recalled": len(pois),
        "evaluated": len(candidates),
        "within_2h": len(within),
        "spots": [_trip_to_dict(t) for t in within[:limit]],
        "disclaimer": DISCLAIMER,
    }
