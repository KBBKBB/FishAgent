#!/usr/bin/env python3
"""FishAgent M1 可行原型 Demo —— 跑通「坐标转换 + POI 召回 + 车程精算 + 鱼情规则」。

用法:
    # 离线演示 (无需任何 Key, 用合成 POI)
    python3 demo.py --mock

    # 真实链路 (需服务端环境变量 AMAP_KEY)
    AMAP_KEY=xxx python3 demo.py --lat 30.657 --lng 104.066

对应 Spec/Roadmap.md 产出物: 「可行原型 demo (POI 召回 + 车程精算 + 坐标转换可跑通)」。
"""

from __future__ import annotations

import argparse
import datetime as dt

from fishagent_m1 import factors, sharding
from fishagent_m1.amap import AmapClient
from fishagent_m1.config import AMAP_AROUND_MAX_RADIUS, Config
from fishagent_m1.coord import offset_meters, wgs84_to_gcj02
from fishagent_m1.mock import MockAmapClient
from fishagent_m1.poi import WaterPoi, dedup_by_id, recall_around, recall_text
from fishagent_m1.route import filter_within_2h, measure_round_trip_batch
from fishagent_m1.weather import WeatherSeries, fetch_archive_pressure, fetch_forecast


def build_client(mock: bool):
    if mock:
        return MockAmapClient(), True
    cfg = Config()
    cfg.require_amap()
    return AmapClient(cfg), False


def recall_over_plan(client, plan: sharding.ShardPlan, city: str | None) -> list[WaterPoi]:
    """按网格分片逐片 around 召回, 再叠加关键词搜索, 最后去重 (M1-T02 覆盖策略)。"""
    collected: list[WaterPoi] = []
    for tile in plan.tiles:
        collected.extend(recall_around(client, tile.location, tile.radius))
    for kw in ("水库", "湖", "河", "塘", "野钓"):
        collected.extend(recall_text(client, kw, city=city))
    return dedup_by_id(collected)


def _synthetic_weather(lat: float, lng: float) -> WeatherSeries:
    """Open-Meteo 不可达时的离线兜底序列 (仅演示)。"""
    base = dt.datetime(2026, 10, 10, 0, 0)
    times, pres, temp, wind, prec, cloud = [], [], [], [], [], []
    for h in range(72):
        t = base + dt.timedelta(hours=h)
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        pres.append(1010.0 - 0.2 * h)  # 缓慢下降
        temp.append(20.0 + 4 * ((h % 24) - 12) / 12)
        wind.append(12.0)
        prec.append(0.0)
        cloud.append(50.0)
    return WeatherSeries(
        latitude=lat, longitude=lng, timezone="Asia/Shanghai", times=times,
        variables={"pressure_msl": pres, "temperature_2m": temp, "wind_speed_10m": wind,
                   "precipitation": prec, "cloud_cover": cloud},
        daily={"sunrise": ["2026-10-10T07:05"], "sunset": ["2026-10-10T18:55"],
               "temperature_2m_max": [24.0], "temperature_2m_min": [14.0]},
    )


def run(lat: float, lng: float, mock: bool, coverage_km: float, city: str | None) -> None:
    line = "=" * 64
    print(line)
    print("FishAgent M1 可行原型 Demo")
    print(line)

    # 1) 坐标转换 (R1)
    glat, glng = wgs84_to_gcj02(lat, lng)
    print("\n[1] 坐标转换 (R1)")
    print(f"    用户 WGS84: {lat:.6f},{lng:.6f}")
    print(f"    -> GCJ-02 : {glat:.6f},{glng:.6f}  (偏移 {offset_meters(lat, lng):.0f} m)")
    user_gcj = f"{glng:.6f},{glat:.6f}"

    # 2) 分片方案 (M1-T02)
    print(f"\n[2] 覆盖分片 (M1-T02, R2 上限 {AMAP_AROUND_MAX_RADIUS/1000:.0f}km/次)")
    plan = sharding.plan_grid(lat, lng, coverage_km * 1000)
    print(f"    覆盖半径 {coverage_km:.0f}km -> 网格 {plan.estimated_calls} 片; {plan.note}")
    rings = sharding.plan_rings(lat, lng, coverage_km * 1000)
    print(f"    对照(同心环): {rings.estimated_calls} 片")
    print(f"    可达性上界参考: 市区30km/h -> {sharding.reachability_upper_bound_km(30):.0f}km; "
          f"高速90km/h -> {sharding.reachability_upper_bound_km(90):.0f}km")

    # 3) POI 双路召回 (M1-T01 / M1-T03)
    client, is_mock = build_client(mock)
    if is_mock:
        client.user_location = user_gcj
    print(f"\n[3] 水域 POI 双路召回 (M1-T01/T03) {'[MOCK 合成数据]' if is_mock else '[真实高德]'}")
    pois = recall_over_plan(client, plan, city)
    missing = sum(1 for p in pois if p.entr_missing)
    print(f"    召回水域 POI: {len(pois)} 个; entr_location 缺失 {missing} 个 "
          f"({(missing/len(pois)*100 if pois else 0):.0f}% 回退中心点)")
    for p in pois[:6]:
        flag = " [入口缺失→回退]" if p.entr_missing else ""
        print(f"      · {p.name:<8} {p.type.split(';')[-1]:<4} @ {p.nav_point}{flag}")

    # 4) 车程精算 (M1-T03/T04, R4)
    print("\n[4] 车程精算 + 往返 ≤2h 过滤 (R4)")
    trips = measure_round_trip_batch(
        client, user_gcj, pois, computed_at=dt.datetime.now().isoformat(timespec="seconds")
    )
    trips.sort(key=lambda t: t.total_s)
    within = filter_within_2h(trips)
    print(f"    候选 {len(trips)} 个 -> 往返 ≤2h 保留 {len(within)} 个")
    for t in within[:6]:
        print(f"      · {t.poi.name:<8} 去 {t.outbound_s/60:5.1f}min + 回 {t.return_s/60:5.1f}min "
              f"= {t.total_s/60:5.1f}min  单程约{t.outbound_m/1000:.1f}km")
    for t in trips:
        if not t.within_2h:
            print(f"      ✗ {t.poi.name:<8} 往返 {t.total_s/60:.0f}min 超 2h, 已剔除")

    # 5) 鱼情规则引擎 (M1-T08 数据源)
    print("\n[5] 鱼情规则引擎 F1–F7 (Open-Meteo)")
    try:
        series = fetch_forecast(lat, lng)
        print(f"    气象数据: 真实 Open-Meteo ({series.timezone}, {len(series.times)} 小时)")
    except Exception as exc:  # noqa: BLE001
        series = _synthetic_weather(lat, lng)
        print(f"    气象数据: 离线兜底 (Open-Meteo 不可达: {exc})")
    archive: list[float] = []
    try:
        archive = fetch_archive_pressure(lat, lng, days=30)
    except Exception:  # noqa: BLE001
        pass
    idx = series.index_of(dt.date.today().strftime("%Y-%m-%dT14")) or len(series.times) // 2
    score = factors.evaluate(series, idx, archive_pressure=archive)
    print()
    print(factors.render_explanation(score))

    print(f"\n{line}")
    print("完成: 坐标转换 / 分片 / 双路召回 / 车程精算 / 鱼情规则 五条链路已跑通。")
    if is_mock:
        print("注意: 本次为 MOCK 合成数据, 不可作为实测结论; 实测请配置 AMAP_KEY。")
    print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="FishAgent M1 可行原型")
    ap.add_argument("--lat", type=float, default=30.657, help="用户 WGS84 纬度")
    ap.add_argument("--lng", type=float, default=104.066, help="用户 WGS84 经度")
    ap.add_argument("--coverage-km", type=float, default=150.0, help="粗筛可达性上界 (km)")
    ap.add_argument("--city", default="成都", help="关键词搜索限定城市")
    ap.add_argument("--mock", action="store_true", help="离线模式 (无 Key, 合成 POI)")
    args = ap.parse_args()
    run(args.lat, args.lng, args.mock, args.coverage_km, args.city)


if __name__ == "__main__":
    main()
