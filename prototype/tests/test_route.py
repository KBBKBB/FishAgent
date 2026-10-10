"""车程精算测试 —— 对应 M1-T04 与红线 R4。"""

from fishagent_m1.mock import MockAmapClient
from fishagent_m1.poi import WaterPoi
from fishagent_m1.route import RoundTrip, filter_within_2h, measure_round_trip_batch


def _poi(pid="p1", name="测试湖", loc="104.288,30.429", entr=None):
    return WaterPoi(pid, name, "湖泊", "110101", loc, entr, "", "around")


def test_roundtrip_uses_sum_not_double():
    # 去 4000 + 回 4000 = 8000 > 7200 -> 剔除 (若误用单程×2 结果相同, 但语义不同)
    assert not RoundTrip(poi=_poi(), outbound_s=4000, return_s=4000).within_2h
    assert RoundTrip(poi=_poi(), outbound_s=3500, return_s=3500).within_2h
    # 不对称: 去 3000 + 回 4500 = 7500 > 7200 -> 剔除, 但单程×2=6000 会误判通过
    assert not RoundTrip(poi=_poi(), outbound_s=3000, return_s=4500).within_2h


def test_nav_point_prefers_entrance():
    assert _poi(entr="104.290,30.431").nav_point == "104.290,30.431"
    assert _poi(entr=None).nav_point == "104.288,30.429"
    assert _poi(entr=None).entr_missing is True


def test_batch_roundtrip_asymmetric_with_mock():
    user = "104.068508,30.654578"
    c = MockAmapClient(user_location=user)
    pois = [_poi("p1", "近湖", "104.090,30.660"), _poi("p2", "远湖", "104.288,30.429")]
    trips = measure_round_trip_batch(c, user, pois)
    assert len(trips) == 2
    for t in trips:
        assert t.return_s > t.outbound_s  # 合成模型: 回程更慢
    assert len(filter_within_2h(trips)) >= 1
