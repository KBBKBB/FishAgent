from __future__ import annotations

import pytest
from conftest import haversine_m


@pytest.fixture(scope="module")
def coords_module():
    from fishagent.core import coords

    return coords


@pytest.mark.parametrize(
    "wgs84,expected_gcj02,tolerance",
    [
        ((39.915, 116.404), (39.916404, 116.410244), 1e-4),
        # eviltransform canonical output; WGS84->GCJ-02 offset in Hangzhou is ~520 m.
        ((30.2741, 120.1551), (30.271771, 120.159794), 1e-3),
    ],
)
def test_wgs84_to_gcj02_known_points(coords_module, wgs84, expected_gcj02, tolerance):
    lat, lon = coords_module.wgs84_to_gcj02(*wgs84)
    assert abs(lat - expected_gcj02[0]) <= tolerance, (lat, expected_gcj02)
    assert abs(lon - expected_gcj02[1]) <= tolerance, (lon, expected_gcj02)


@pytest.mark.parametrize("point", [(39.915, 116.404), (30.2741, 120.1551), (22.5431, 114.0579)])
def test_gcj02_to_wgs84_round_trip(coords_module, point):
    gcj = coords_module.wgs84_to_gcj02(*point)
    back = coords_module.gcj02_to_wgs84(*gcj)
    assert abs(back[0] - point[0]) <= 1e-5, (point, back)
    assert abs(back[1] - point[1]) <= 1e-5, (point, back)


def test_domestic_offset_is_in_expected_range(coords_module):
    wgs = (30.2741, 120.1551)
    gcj = coords_module.wgs84_to_gcj02(*wgs)
    offset = haversine_m(wgs[0], wgs[1], gcj[0], gcj[1])
    # Hangzhou ~520 m; Beijing ~555 m and Shenzhen ~606 m stay valid if points are added.
    assert 50 <= offset <= 700, f"unexpected WGS84->GCJ02 offset: {offset:.1f}m"
