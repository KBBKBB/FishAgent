"""radius 硬校验测试 —— 对应 M1-T02 与红线 R2。"""

import pytest

from fishagent_m1.config import AMAP_AROUND_MAX_RADIUS
from fishagent_m1.mock import MockAmapClient
from fishagent_m1.poi import RadiusTooLargeError, validate_radius


def test_radius_at_limit_ok():
    assert validate_radius(AMAP_AROUND_MAX_RADIUS) == 50000


def test_radius_over_limit_raises():
    with pytest.raises(RadiusTooLargeError):
        validate_radius(50001)


def test_radius_zero_raises():
    with pytest.raises(RadiusTooLargeError):
        validate_radius(0)


def test_mock_exposes_silent_degradation_risk():
    # 真实高德超限会静默降级为 3000m 且 status=1; mock 用 status=0 显式暴露该风险
    c = MockAmapClient()
    resp = c.place_around("104.066,30.657", 60000)
    assert resp["status"] == "0"
    assert resp["info"] == "MOCK_RADIUS_OVER_LIMIT"
