from __future__ import annotations

import pytest

from fishagent.core.forbidden import forbidden_reason
from fishagent.schemas import LatLon

# Chengdu coordinates keep these cases clear of the Hangzhou demo circle.
CHENGDU = LatLon(lat=30.6570, lon=104.0660)

PROTECTED_AREA_NAMES = (
    "三江源国家公园",
    "大熊猫国家公园",
    "龙泉山自然保护地",
    "青城山—都江堰风景名胜区",
    "白云森林公园",
    "青龙湖湿地公园",
    "龙门山地质公园",
    "长江上游珍稀特有鱼类国家级水产种质资源保护区",
    "某县种质资源保护区",
)

WATER_SOURCE_NAMES = (
    "东风水库一级保护区",
    "北山水库二级保护区",
    "XX市饮用水源水库",
    "XX水源保护地",
)

OTHER_EXCLUDED_NAMES = (
    "军事管理区河段",
    "长江禁渔水域",
    "某村养殖塘",
    "某公司承包水库",
    "泄洪河道",
    "高压线下方水域",
    "某自然保护区核心区",
)


@pytest.mark.parametrize("name", PROTECTED_AREA_NAMES)
def test_protected_area_names_are_excluded(name: str) -> None:
    assert forbidden_reason(name, CHENGDU) is not None


@pytest.mark.parametrize("name", WATER_SOURCE_NAMES + OTHER_EXCLUDED_NAMES)
def test_legacy_keyword_names_still_excluded(name: str) -> None:
    assert forbidden_reason(name, CHENGDU) is not None


@pytest.mark.parametrize(
    "name",
    ("锦江", "府河", "西郊河", "东湖", "古新河", "菜子湖"),
)
def test_ordinary_water_names_are_allowed(name: str) -> None:
    assert forbidden_reason(name, CHENGDU) is None


def test_configured_forbidden_circle_still_excludes() -> None:
    inside_demo_zone = LatLon(lat=30.2460, lon=120.1490)
    assert forbidden_reason("无名水域", inside_demo_zone) is not None


def test_empty_name_outside_zones_is_allowed() -> None:
    assert forbidden_reason("", CHENGDU) is None
