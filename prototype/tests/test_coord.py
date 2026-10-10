"""坐标转换回归测试 —— 对应 M1-T05 与红线 R1。"""

from fishagent_m1 import coord

# 已知 WGS84 点 (成都/北京/上海/广州)
POINTS = [(30.657, 104.066), (39.9087, 116.3975), (31.2304, 121.4737), (23.1291, 113.2644)]


def test_roundtrip_sub_millimeter():
    for lat, lng in POINTS:
        glat, glng = coord.wgs84_to_gcj02(lat, lng)
        wlat, wlng = coord.gcj02_to_wgs84(glat, glng)
        assert coord.haversine_m(lat, lng, wlat, wlng) < 0.001  # < 1mm


def test_offset_in_documented_range():
    # 境内偏差约 50~600m (文档写 50~500m 为典型值)
    for lat, lng in POINTS:
        off = coord.offset_meters(lat, lng)
        assert 50 < off < 800


def test_out_of_china_unchanged():
    assert coord.wgs84_to_gcj02(35.68, 139.76) == (35.68, 139.76)
    assert coord.gcj02_to_wgs84(35.68, 139.76) == (35.68, 139.76)


def test_offset_is_nonzero_for_haidian():
    # 若误用裸坐标, 偏移可达数百米 (R1 的核心风险)
    assert coord.offset_meters(39.9087, 116.3975) > 100
