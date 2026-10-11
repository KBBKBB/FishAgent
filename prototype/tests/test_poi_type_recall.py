"""type 码召回路径测试 —— 对应立项文档 4.2「type 码 + 关键词」双路召回。

2026-10-11 补：实测发现水系 POI 归入 190200「自然地名」大类，且关键词路对
「江/浜/溪/淀」等命名会系统性漏召回，故补齐 type 码路（`recall_by_type`）。
"""

import pytest

from fishagent_m1.config import WATER_TYPECODES
from fishagent_m1.mock import MockAmapClient
from fishagent_m1.poi import (
    RadiusTooLargeError,
    recall_by_type,
    recall_dual,
)


def test_water_typecodes_default_is_natural_place_name():
    assert WATER_TYPECODES == "190200"


def test_recall_by_type_returns_pois_and_tags_source():
    c = MockAmapClient()
    pois = recall_by_type(c, "104.066,30.657", 50000)
    assert pois, "type 码路应能召回 POI"
    assert all(p.source == "type" for p in pois)


def test_recall_by_type_respects_radius_hard_limit():
    c = MockAmapClient()
    with pytest.raises(RadiusTooLargeError):
        recall_by_type(c, "104.066,30.657", 60000)  # > 50000 (R2)


def test_recall_dual_merges_and_dedups():
    c = MockAmapClient()
    pois = recall_dual(c, "104.066,30.657", 50000, city="成都")
    assert pois
    keys = [p.key for p in pois]
    assert len(keys) == len(set(keys)), "并集去重后不应有重复 key"
