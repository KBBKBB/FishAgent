#!/usr/bin/env python3
"""M1 A1–A4 实测工具 —— 插上真实 AMAP_KEY 即可跑出可粘贴的报告数据。

⚠️ 本工具**不编造数据**：无 Key 时请用 `--dry-run`（mock 合成数据）仅自检工具链，
其结果**不可**作为实测结论。真实结果写入 `Spec/M1/measurements/`。

用法:
    export AMAP_KEY=xxxx
    python3 measure_m1.py a4 --lat 30.657 --lng 104.066
    python3 measure_m1.py a1 --truth fixtures/ground_truth.chengdu.json
    python3 measure_m1.py a2 --cities fixtures/cities.json
    python3 measure_m1.py a3
    python3 measure_m1.py all --lat 30.657 --lng 104.066 \
        --truth fixtures/ground_truth.chengdu.json --cities fixtures/cities.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

from fishagent_m1 import sharding
from fishagent_m1.amap import AmapClient, amap_error, is_amap_ok
from fishagent_m1.config import Config
from fishagent_m1.coord import wgs84_to_gcj02
from fishagent_m1.mock import MockAmapClient
from fishagent_m1.poi import measure_recall, recall_dual
from fishagent_m1.route import filter_within_2h, measure_round_trip_batch

OUT_DIR = Path(__file__).resolve().parent.parent / "Spec" / "M1" / "measurements"
TODAY = dt.date.today().isoformat()


def build(mock: bool):
    if mock:
        return MockAmapClient()
    cfg = Config()
    cfg.require_amap()
    return AmapClient(cfg)


def _user_gcj(lat: float, lng: float) -> str:
    glat, glng = wgs84_to_gcj02(lat, lng)
    return f"{glng:.6f},{glat:.6f}"


# ---------------------------------------------------------------- A4

def a4(client, lat: float, lng: float, city: str) -> dict:
    """A4 地图接口能力：v3/distance 开放性 / duration / 实时路况 / entr_location 缺失率。"""
    user = _user_gcj(lat, lng)
    pois = recall_dual(client, user, 50000, city=city)
    with_entr = [p for p in pois if not p.entr_missing]
    miss_rate = (1 - len(with_entr) / len(pois)) if pois else None
    endpoint = (with_entr or pois)[0].nav_point if pois else None

    checks: dict = {
        "recalled_pois": len(pois),
        "entr_location_missing_rate": None if miss_rate is None else round(miss_rate, 4),
    }
    if not endpoint:
        checks["note"] = "未召回 POI，无法测试距离接口"
        return {"task": "A4", "date": TODAY, "checks": checks}

    d_straight = _one_distance(client, user, endpoint, 0)  # type=0 直线距离（实测无 duration）
    d_drive = _one_distance(client, user, endpoint, 1)  # type=1 驾车（返回 duration）
    v5 = _one_driving(client, user, endpoint)  # v5 路径规划（show_fields=cost）
    checks["v3_distance_type0_straight"] = d_straight
    checks["v3_distance_type1_driving"] = d_drive
    checks["v5_driving"] = v5

    checks["check1_v3_distance_open"] = bool(d_drive and d_drive.get("ok"))
    checks["check2_returns_duration"] = bool(d_drive and (d_drive.get("duration_s") or 0) > 0)
    checks["check3_realtime_traffic"] = _realtime_verdict(d_drive, v5)
    checks["check4_entr_missing_rate"] = None if miss_rate is None else round(miss_rate, 4)
    checks["check4_entr_missing_rate_ok"] = None if miss_rate is None else miss_rate <= 0.5
    checks["endpoint_used"] = endpoint
    checks["A4_verdict"] = _a4_verdict(checks)
    return {"task": "A4", "date": TODAY, "city": city, "checks": checks}


def _one_distance(client, origin: str, destination: str, dtype: int) -> dict | None:
    try:
        resp = client.distance(origin, destination, dtype)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if not is_amap_ok(resp):
        return {"ok": False, "error": amap_error(resp)}
    r = (resp.get("results") or [{}])[0]
    return {
        "ok": True,
        "duration_s": float(r.get("duration") or 0),
        "distance_m": float(r.get("distance") or 0),
    }


def _one_driving(client, origin: str, destination: str) -> dict | None:
    try:
        # 注意: v5/direction/driving 默认不返回 cost.duration, 必须 show_fields=cost (M1 实测发现)
        resp = client.driving(origin, destination, show_fields="cost")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if not is_amap_ok(resp):
        return {"ok": False, "error": amap_error(resp)}
    route = resp.get("route") or resp.get("routes") or {}
    if isinstance(route, list):
        route = route[0] if route else {}
    paths = route.get("paths") or [{}]
    cost = paths[0].get("cost") or {}
    return {
        "ok": True,
        "duration_s": float(cost.get("duration") or paths[0].get("duration") or 0),
        "has_traffic_fields": any(
            k in paths[0] for k in ("traffic_lights", "tmc", "traffic_status")
        ),
    }


def _realtime_verdict(d1, v5) -> str:
    if not d1 or not d1.get("ok"):
        return "unknown（v3/distance type=1 不可用）"
    if not v5 or not v5.get("ok"):
        return "unknown（v5 不可用，无法交叉校验）"
    a, b = d1.get("duration_s") or 0, v5.get("duration_s") or 0
    if not a or not b:
        return "unknown（缺 duration）"
    diff = abs(a - b) / max(a, b)
    if diff <= 0.25:
        return f"一致：v3 type=1={a:.0f}s 与 v5={b:.0f}s 相差 {diff*100:.0f}%（均为路网时长）"
    return f"不一致：v3 type=1={a:.0f}s vs v5={b:.0f}s（相差 {diff*100:.0f}%）"


def _a4_verdict(checks: dict) -> str:
    if checks.get("check1_v3_distance_open") and checks.get("check2_returns_duration"):
        return "PASS（v3/distance type=1 可用且返回 duration；type=0 为直线距离无 duration）"
    return "FAIL → 改用 v5/direction/driving（注意需 show_fields=cost 才返回 cost.duration）"


# ---------------------------------------------------------------- A1

def a1(
    client,
    truth_path: str,
    *,
    coverage_km: float = 150.0,
    spacing_factor: float = 1.414,
    max_pages: int = 4,
) -> dict:
    """A1 召回率 —— 按【生产召回策略】实测：网格分片（突破 50km 上限）+ 关键词双路 + 去重。

    ⚠️ 早期版本仅用「城市中心 50km 单圆 + 翻页上限」，会低估召回率（半径与翻页双重截断）。
    """
    from fishagent_m1.config import WATER_KEYWORDS
    from fishagent_m1.poi import dedup_by_id, recall_around, recall_by_type, recall_text

    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    lat, lng = truth["center_wgs84"]
    plan = sharding.plan_grid(lat, lng, coverage_km * 1000, spacing_factor=spacing_factor)
    collected = []
    for tile in plan.tiles:
        # type 码路 (立项文档 4.2): 召回「江/浜/溪」类命名
        collected.extend(recall_by_type(client, tile.location, tile.radius, max_pages=max_pages))
        # 关键词路 (周边搜索带关键词)
        collected.extend(recall_around(client, tile.location, tile.radius, max_pages=max_pages))
    for kw in WATER_KEYWORDS:
        collected.extend(recall_text(client, kw, city=truth.get("city"), max_pages=max_pages))
    pois = dedup_by_id(collected)
    res = measure_recall(set(truth["names"]), pois)
    rate = round(res.recall_rate, 4)
    return {
        "task": "A1",
        "date": TODAY,
        "city": truth.get("city"),
        "tier": truth.get("tier"),
        "ground_truth_status": truth.get("status", "unknown"),
        "coverage_km": coverage_km,
        "spacing_factor": spacing_factor,
        "max_pages": max_pages,
        "tiles": len(plan.tiles),
        "ground_truth_n": len(res.ground_truth),
        "recalled_n": len(pois),
        "matched_n": len(res.matched),
        "matched": res.matched,
        "missed": [n for n in res.ground_truth if n not in res.matched],
        "recall_rate": rate,
        "threshold": 0.70,
        "pass": rate >= 0.70,
    }


# ---------------------------------------------------------------- A2 / T07

def a2(
    client,
    cities_path: str,
    coverage_km: float,
    *,
    spacing_factor: float = 1.414,
    max_pages: int = 2,
    max_candidates: int = 40,
) -> dict:
    """A2 / M1-T07：三档城市各 5 个随机城区点，2h 车程内有效水域数取中位数。

    spacing_factor / max_pages / max_candidates 用于控制调用量。
    ⚠️ max_candidates：因去程不可批量（R4），对每个点只取【直线距离最近】的 N 个候选做往返精算，
    否则单点可能产生数百次去程调用（实测耗时与配额风险极高）。
    """
    from fishagent_m1.config import WATER_KEYWORDS
    from fishagent_m1.coord import haversine_m
    from fishagent_m1.poi import dedup_by_id, recall_around, recall_by_type, recall_text

    data = json.loads(Path(cities_path).read_text(encoding="utf-8"))
    out: list[dict] = []
    for c in data["cities"]:
        counts: list[int] = []
        for lat, lng in c["points"]:
            user = _user_gcj(lat, lng)
            plan = sharding.plan_grid(
                lat, lng, coverage_km * 1000, spacing_factor=spacing_factor
            )
            collected = []
            for tile in plan.tiles:
                # type 码路 (立项文档 4.2)
                collected.extend(
                    recall_by_type(client, tile.location, tile.radius, max_pages=max_pages)
                )
                # 关键词路
                collected.extend(
                    recall_around(client, tile.location, tile.radius, max_pages=max_pages)
                )
            for kw in WATER_KEYWORDS:
                collected.extend(
                    recall_text(client, kw, city=c["name"], max_pages=max_pages)
                )
            pois = dedup_by_id(collected)
            # 按直线距离排序, 只对最近的 N 个候选做往返精算 (R4: 去程不可批量, 否则调用爆炸)
            def _ll(point: str) -> tuple[float, float]:
                lng_, la_ = point.split(",")
                return float(la_), float(lng_)

            pois.sort(key=lambda p: haversine_m(lat, lng, *_ll(p.nav_point)))
            pois = pois[:max_candidates]
            trips = measure_round_trip_batch(client, user, pois)
            counts.append(len(filter_within_2h(trips)))
        med = statistics.median(counts) if counts else 0
        thr = c.get("threshold", 3)
        out.append({
            "city": c["name"], "tier": c.get("tier"),
            "per_point_counts": counts, "median": med,
            "threshold": thr, "pass": med >= thr,
        })
    return {
        "task": "A2", "date": TODAY, "coverage_km": coverage_km,
        "spacing_factor": spacing_factor, "max_pages": max_pages,
        "max_candidates": max_candidates, "cities": out,
    }


# ---------------------------------------------------------------- A3

def _probe(fn) -> dict:
    try:
        resp = fn()
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": str(exc)}
    return {
        "reachable": True,
        "status": str(resp.get("status")),
        "infocode": str(resp.get("infocode")),
        "info": str(resp.get("info")),
    }


def a3(client, lat: float = 30.657, lng: float = 104.066) -> dict:
    """A3 各接口独立配额：验证可达性 + 是否触发配额类错误。

    说明：高德不在响应中返回「剩余额度」，**绝对日配额必须在高德控制台核对**。
    本工具只做「各接口是否可用 / 是否报配额类 infocode」的探测，避免刷爆配额。
    """
    user = _user_gcj(lat, lng)
    probes = {
        "v3/place/around": _probe(lambda: client.place_around(user, 3000)),
        "v3/place/text": _probe(lambda: client.place_text("水库", city="成都")),
        "v3/place/polygon": _probe(lambda: client.place_polygon(
            f"{lng - 0.1:.4f},{lat - 0.1:.4f}|{lng + 0.1:.4f},{lat - 0.1:.4f}|"
            f"{lng + 0.1:.4f},{lat + 0.1:.4f}|{lng - 0.1:.4f},{lat + 0.1:.4f}"
        )),
        "v3/distance": _probe(lambda: client.distance(user, user)),
        "v5/direction/driving": _probe(lambda: client.driving(user, user)),
        "v3/assistant/coordinate/convert": _probe(
            lambda: client.convert_amap(f"{lng:.6f},{lat:.6f}", "gps")
        ),
    }
    # 配额类 infocode（高德）: 10003 访问已超出日调用量 / 10044 等
    quota_codes = {"10003", "10044", "10019"}
    quota_hit = [k for k, v in probes.items() if v.get("infocode") in quota_codes]
    return {
        "task": "A3", "date": TODAY, "probes": probes,
        "quota_error_interfaces": quota_hit,
        "note": "绝对日配额须在高德控制台核对；本结果仅记录各接口可达性与配额类错误。",
    }


# ---------------------------------------------------------------- 渲染与落盘

def render_md(results: dict, dry: bool) -> str:
    lines = [f"# M1 实测结果（{TODAY}）", ""]
    if dry:
        lines += ["> ⚠️ **DRY-RUN：使用 mock 合成数据，不可作为实测结论。**", ""]
    r = results.get("a1")
    if r:
        lines += ["## A1 水域 POI 双路召回率", "",
                  "| 城市 | 档位 | 真值数 | 召回命中 | 召回率 | 阈值 | 达标 |",
                  "|---|---|---|---|---|---|---|",
                  f"| {r['city']} | {r['tier']} | {r['ground_truth_n']} | {r['matched_n']} | "
                  f"{r['recall_rate']*100:.1f}% | 70% | {'✅' if r['pass'] else '❌'} |", ""]
        if r.get("missed"):
            lines += [f"未命中：{'、'.join(r['missed'])}", ""]
    r = results.get("a2")
    if r:
        lines += ["## A2 / T07 城区有效水域存量（往返 ≤2h）", "",
                  "| 城市 | 档位 | 5 点计数 | 中位数 | 阈值 | 达标 |",
                  "|---|---|---|---|---|---|"]
        for c in r["cities"]:
            lines.append(f"| {c['city']} | {c['tier']} | {c['per_point_counts']} | "
                         f"{c['median']} | {c['threshold']} | {'✅' if c['pass'] else '❌'} |")
        lines.append("")
    r = results.get("a4")
    if r:
        c = r["checks"]
        lines += ["## A4 距离接口能力", "",
                  "| 检查项 | 结果 |", "|---|---|",
                  f"| v3/distance 可用 | {c.get('check1_v3_distance_open')} |",
                  f"| 返回 duration | {c.get('check2_returns_duration')} |",
                  f"| 实时路况 | {c.get('check3_realtime_traffic')} |",
                  f"| entr_location 缺失率 | {c.get('check4_entr_missing_rate')} |",
                  f"| **A4 结论** | **{c.get('A4_verdict')}** |", ""]
        lines += ["```json", json.dumps(c, ensure_ascii=False, indent=2), "```", ""]
    r = results.get("a3")
    if r:
        lines += ["## A3 各接口可达性 / 配额探测", "",
                  "| 接口 | 可达 | status | infocode | info |", "|---|---|---|---|---|"]
        for k, v in r["probes"].items():
            lines.append(f"| {k} | {v.get('reachable')} | {v.get('status')} | "
                         f"{v.get('infocode')} | {v.get('info')} |")
        lines += ["", f"配额类错误接口：{r['quota_error_interfaces'] or '无'}", "",
                  f"> {r['note']}", ""]
    return "\n".join(lines)


def save(results: dict, dry: bool) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = "dryrun" if dry else TODAY
    for k, v in results.items():
        (OUT_DIR / f"{k}-{tag}.json").write_text(
            json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    md = render_md(results, dry)
    path = OUT_DIR / ("latest-dryrun.md" if dry else "latest.md")
    path.write_text(md, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="M1 A1–A4 实测工具")
    ap.add_argument("task", choices=["a1", "a2", "a3", "a4", "all"])
    ap.add_argument("--lat", type=float, default=30.657)
    ap.add_argument("--lng", type=float, default=104.066)
    ap.add_argument("--city", default="成都")
    ap.add_argument("--truth", help="A1 真值集 JSON")
    ap.add_argument("--cities", help="A2 城市测试点 JSON")
    ap.add_argument("--coverage-km", type=float, default=150.0)
    ap.add_argument("--spacing-factor", type=float, default=1.414, help="A2 网格间距系数（越大调用越少）")
    ap.add_argument("--max-pages", type=int, default=2, help="A2 每片翻页上限（控制调用量）")
    ap.add_argument("--max-candidates", type=int, default=40, help="A2 每点参与往返精算的最近候选数上限")
    ap.add_argument("--dry-run", action="store_true", help="mock 合成数据自检（结果不可作实测结论）")
    args = ap.parse_args()

    client = build(args.dry_run)
    if args.dry_run and isinstance(client, MockAmapClient):
        client.user_location = _user_gcj(args.lat, args.lng)

    results: dict = {}
    if args.task in ("a4", "all"):
        results["a4"] = a4(client, args.lat, args.lng, args.city)
    if args.task in ("a1", "all"):
        if not args.truth:
            print("A1 需要 --truth <真值集 JSON>（模板见 fixtures/ground_truth.example.json）", file=sys.stderr)
            return 2
        results["a1"] = a1(
            client, args.truth, coverage_km=args.coverage_km,
            spacing_factor=args.spacing_factor, max_pages=args.max_pages,
        )
    if args.task in ("a2", "all"):
        if not args.cities:
            print("A2 需要 --cities <城市测试点 JSON>（模板见 fixtures/cities.example.json）", file=sys.stderr)
            return 2
        results["a2"] = a2(
            client, args.cities, args.coverage_km,
            spacing_factor=args.spacing_factor, max_pages=args.max_pages,
            max_candidates=args.max_candidates,
        )
    if args.task in ("a3", "all"):
        results["a3"] = a3(client, args.lat, args.lng)

    path = save(results, args.dry_run)
    print(render_md(results, args.dry_run))
    print(f"\n[已写入] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
