"""离线 Mock 高德客户端 —— 让 M1 原型在无 Key 环境下也能跑通端到端链路。

用途: 演示与单元测试。数据为合成 (fixtures/water_pois.json), **不可用于任何实测结论**。
真实实测必须用 AmapClient + 真实 Key, 结果记入 Spec/M1 报告。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .config import AMAP_AROUND_MAX_RADIUS
from .coord import haversine_m

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "water_pois.json"

# 合成车速: 去程/回程取不同均值, 用于演示「往返分别计算、非单程×2」(R4)
SPEED_OUT_KMH = 45.0
SPEED_BACK_KMH = 32.0


def _load_pois() -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["pois"]


def _parse_loc(loc: str) -> tuple[float, float]:
    lng, lat = loc.split(",")
    return float(lat), float(lng)


class MockAmapClient:
    """与 AmapClient 同接口的离线实现。"""

    def __init__(self, pois: list[dict] | None = None, user_location: str | None = None) -> None:
        self.pois = pois or _load_pois()
        self.calls = 0
        # 用户位置 (GCJ-02 'lng,lat'), 用于区分去程/回程的合成车速
        self.user_location = user_location

    # —— 与 AmapClient 同名接口, 便于在 demo 中无差别替换 ——
    def place_around(self, location: str, radius: int, **kw: Any) -> dict[str, Any]:
        return self.call("v3/place/around", {"location": location, "radius": radius, **kw})

    def place_text(self, keywords: str, **kw: Any) -> dict[str, Any]:
        return self.call("v3/place/text", {"keywords": keywords, **kw})

    def place_polygon(self, polygon: str, **kw: Any) -> dict[str, Any]:
        return self.call("v3/place/polygon", {"polygon": polygon, **kw})

    def distance(self, origins: str, destination: str, distance_type: int = 1) -> dict[str, Any]:
        return self.call("v3/distance", {"origins": origins, "destination": destination, "type": distance_type})

    def call(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if path.endswith("place/around"):
            return self._around(params)
        if path.endswith("place/text"):
            return self._text(params)
        if path.endswith("place/polygon"):
            return self._polygon(params)
        if path.endswith("v3/distance"):
            return self._distance(params)
        return {"status": "0", "info": "mock unsupported: " + path}

    # —— 接口实现 ——

    def _around(self, params: dict[str, Any]) -> dict[str, Any]:
        radius = int(params.get("radius") or 0)
        if radius > AMAP_AROUND_MAX_RADIUS:
            # 真实高德会静默降级; mock 显式暴露该风险供测试断言
            return {"status": "0", "info": "MOCK_RADIUS_OVER_LIMIT", "infocode": "MOCK"}
        clat, clng = _parse_loc(params["location"])
        kw = str(params.get("keywords") or "")
        keywords = [k for k in kw.split("|") if k]
        out = []
        for p in self.pois:
            plat, plng = _parse_loc(p["location"])
            if haversine_m(clat, clng, plat, plng) <= radius:
                if not keywords or any(k in p["name"] for k in keywords):
                    out.append(p)
        return {"status": "1", "info": "OK", "infocode": "10000", "count": str(len(out)), "pois": out}

    def _text(self, params: dict[str, Any]) -> dict[str, Any]:
        kw = str(params.get("keywords") or "")
        out = [p for p in self.pois if kw in p["name"]]
        return {"status": "1", "info": "OK", "infocode": "10000", "count": str(len(out)), "pois": out}

    def _polygon(self, params: dict[str, Any]) -> dict[str, Any]:
        pts = [_parse_loc(p) for p in str(params.get("polygon") or "").split(";") if p]
        if not pts:
            return {"status": "0", "info": "EMPTY_POLYGON", "infocode": "MOCK"}
        lats = [p[0] for p in pts]
        lngs = [p[1] for p in pts]
        out = []
        for p in self.pois:
            plat, plng = _parse_loc(p["location"])
            if min(lats) <= plat <= max(lats) and min(lngs) <= plng <= max(lngs):
                out.append(p)
        return {"status": "1", "info": "OK", "infocode": "10000", "count": str(len(out)), "pois": out}

    def _distance(self, params: dict[str, Any]) -> dict[str, Any]:
        dest_lat, dest_lng = _parse_loc(params["destination"])
        origins = [o for o in str(params.get("origins") or "").split("|") if o]
        results = []
        for i, o in enumerate(origins, 1):
            olat, olng = _parse_loc(o)
            dist = haversine_m(olat, olng, dest_lat, dest_lng)
            # 回程更慢 (返程跨晚高峰的合成模拟): 当终点是用户位置时视为回程
            is_back = (
                self.user_location is not None
                and str(params.get("destination")) == self.user_location
            )
            speed = SPEED_BACK_KMH if is_back else SPEED_OUT_KMH
            dur = dist / 1000.0 / speed * 3600.0
            results.append(
                {
                    "origin_id": str(i),
                    "dest_id": "1",
                    "distance": str(int(round(dist))),
                    "duration": str(int(round(dur))),
                }
            )
        return {"status": "1", "info": "OK", "infocode": "10000", "results": results}
