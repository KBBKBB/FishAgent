"""分片覆盖测试 —— 对应 M1-T02 (突破 radius 50km 上限)。"""

import math

from fishagent_m1 import sharding
from fishagent_m1.config import AMAP_AROUND_MAX_RADIUS


def test_grid_tiles_respect_radius_limit():
    plan = sharding.plan_grid(30.657, 104.066, 150_000)
    assert plan.tiles
    assert all(t.radius <= AMAP_AROUND_MAX_RADIUS for t in plan.tiles)


def test_grid_covers_full_disk():
    """圆盘内任意采样点都应落在某个 tile 的半径内 (无空洞)。"""
    lat0, lng0, cov = 30.657, 104.066, 150_000
    plan = sharding.plan_grid(lat0, lng0, cov)
    for ang in range(0, 360, 15):
        for frac in (0.25, 0.5, 0.75, 1.0):
            r = cov * frac
            lat = lat0 + (r * math.sin(math.radians(ang))) / sharding.M_PER_DEG_LAT
            lng = lng0 + (r * math.cos(math.radians(ang))) / sharding._m_per_deg_lng(lat0)
            nearest = min(t.distance_to(lat, lng) for t in plan.tiles)
            assert nearest <= plan.tile_radius + 1.0


def test_reachability_bound_matches_doc():
    # 文档: 市区 30km/h -> ~60km; 高速 90~100km/h -> ~160~200km
    assert 55 <= sharding.reachability_upper_bound_km(30) <= 65
    assert 170 <= sharding.reachability_upper_bound_km(95) <= 200


def test_rings_plan_nonempty():
    p = sharding.plan_rings(30.657, 104.066, 150_000)
    assert p.estimated_calls > 0
