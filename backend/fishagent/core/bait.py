"""Bait guidance per species.

A deterministic table rather than a model call: the same reason
``core/species.py`` describes water types locally. Two properties matter here
and neither survives a prompt -- the advice must be identical every time it is
asked (a user comparing two sessions should not get two answers), and it must
work with the LLM switched off, because mock mode is how the app is checked.

The agent answers bait questions from this table and the spot cards read the
same entries, so "what should I use here" cannot disagree with itself.

What this is NOT: a claim about a specific lake. It describes the species, in
the same spirit as ``WATER_TYPE_SPECIES``, and callers must say so.
"""

from __future__ import annotations

from dataclasses import dataclass

from fishagent.core.species import KNOWN_SPECIES, canonical_species


@dataclass(frozen=True)
class BaitAdvice:
    """One species' bait plan.

    ``main`` is what to actually put on the hook; ``nest`` is how to hold fish
    in the swim (empty for species that are not nest-fed); ``tip`` is the one
    thing that most often decides the session.
    """

    main: str
    nest: str
    tip: str


BAIT_GUIDE: dict[str, BaitAdvice] = {
    "鲫鱼": BaitAdvice(
        main="腥香型商品饵，冬春偏腥、夏秋偏香，可搭配少量红虫或蚯蚓",
        nest="酒米打窝，少量勤补",
        tip="鲫鱼口轻，用细线小钩、调低目抓小动作",
    ),
    "鲤鱼": BaitAdvice(
        main="甜香谷物味商品饵，或嫩玉米、红薯块",
        nest="老玉米、麦粒提前做窝，窝量宜大",
        tip="鲤鱼谨慎，钓点保持安静，中鱼后迅速带离窝点",
    ),
    "草鱼": BaitAdvice(
        main="草香或微酸味商品饵，嫩玉米、芦苇芯、嫩草尖",
        nest="玉米或草捆做窝，可钓半水",
        tip="气温高时草鱼上浮，钓浮往往优于钓底",
    ),
    "鲢鳙": BaitAdvice(
        main="酸臭或蒜味、草莓味鲢鳙专用饵，追求高雾化",
        nest="靠饵料雾化形成立体窝，不必另打重窝",
        tip="钓浮为主，从水深一半开始找鱼层，见口再调",
    ),
    "青鱼": BaitAdvice(
        main="螺蛳、蚌肉，或腥味颗粒饵",
        nest="螺蛳砸碎掺颗粒做大窝，需守",
        tip="青鱼体型大，用大钩粗线并提前放失手绳",
    ),
    "鳊鱼": BaitAdvice(
        main="香腥商品饵，嫩玉米、麦粒",
        nest="酒米或麦粒轻窝",
        tip="鳊鱼常在中上层活动，可试离底或半水",
    ),
    "黑鱼": BaitAdvice(
        main="路亚雷蛙、软虫；或活饵小鱼、泥鳅",
        nest="不打窝，靠找鱼",
        tip="沿水草边和明水交界处搜索，中鱼后快速提离草区",
    ),
    "翘嘴": BaitAdvice(
        main="路亚亮片、米诺为主；手竿可用腥香雾化饵或活小鱼",
        nest="手竿靠持续抛投雾化诱鱼，不打重窝",
        tip="清晨和傍晚在水面有炸水时效率最高",
    ),
    "鲈鱼": BaitAdvice(
        main="路亚软虫、米诺、VIB；或活虾",
        nest="不打窝，找结构",
        tip="重点搜桥墩、乱石、倒树等障碍区",
    ),
    "罗非鱼": BaitAdvice(
        main="腥香或肝味商品饵，蚯蚓也可",
        nest="少量腥味窝料",
        tip="罗非喜温，水温低时口差，正午前后往往更好",
    ),
    "黄颡鱼": BaitAdvice(
        main="蚯蚓、红虫，或腥味商品饵",
        nest="腥味窝料少量，或直接找鱼",
        tip="夜钓效果明显更好，注意背鳍硬刺扎手",
    ),
    "鲶鱼": BaitAdvice(
        main="蚯蚓、鸡肝、腥臭味饵",
        nest="腥臭窝料，或用动物内脏做窝",
        tip="夜钓为主，钓点选深水或障碍旁",
    ),
    "白条": BaitAdvice(
        main="细小腥香商品饵，或红虫、蚯蚓段",
        nest="不必打窝，靠饵料雾化聚鱼",
        tip="用细线小钩、饵球要小，勤抛保持节奏",
    ),
    "马口": BaitAdvice(
        main="红虫、小蚯蚓；或路亚小亮片、微物饵",
        nest="不打窝，找流水",
        tip="马口在流水急缓交界处，顺流抛、逆流收",
    ),
    "鳜鱼": BaitAdvice(
        main="路亚软虫、德州钓组；或活饵小鱼",
        nest="不打窝，找鱼",
        tip="贴底慢拖，重点搜石缝和硬底结构",
    ),
    "鲴鱼": BaitAdvice(
        main="腥香商品饵，饵球宜小",
        nest="少量雾化窝料",
        tip="鲴鱼多在水底刮食，钓钝一些更稳",
    ),
}

# A species with no entry is not an error -- the catalogue deliberately holds
# fewer names than anglers ask about. Answering nothing would look like a bug,
# so the caller gets a usable generic plan plus this flag, and must present it
# as generic rather than species-specific.
GENERIC_BAIT = BaitAdvice(
    main="腥香型商品饵，可搭配蚯蚓或红虫",
    nest="酒米少量打窝，视鱼口补窝",
    tip="先用腥香找口，再根据实际鱼口调整味型",
)
GENERIC_NOTE = "该鱼种暂无专属饵料方案，以下为通用建议"


def advice_for(species: str | None) -> tuple[BaitAdvice | None, bool]:
    """Return ``(advice, is_generic)`` for a species name.

    Returns ``(None, False)`` for a missing or unrecognised species: the caller
    has nothing to answer, and inventing advice for a name we cannot even
    normalise is how "草鱼用什么" turns into a confident answer about carp.
    """
    canonical = canonical_species(species)
    if canonical is None:
        return None, False
    entry = BAIT_GUIDE.get(canonical)
    if entry is not None:
        return entry, False
    return GENERIC_BAIT, True


def resolve_species(value: str | None) -> str | None:
    """Canonical name if known, else ``None``.

    Re-exported so the agent and the API validate species against one list
    instead of the two that used to disagree -- that disagreement is what made
    a question about 白条 fall through to the generic guide while 鲫鱼 worked.
    """
    return canonical_species(value)


def supported_species() -> tuple[str, ...]:
    return tuple(name for name in KNOWN_SPECIES if name in BAIT_GUIDE)


def bait_summary(species_list: list[str], limit: int = 2) -> list[str]:
    """Bait lines for the first few species, for display under a spot card."""
    lines: list[str] = []
    for name in species_list[:limit]:
        advice, generic = advice_for(name)
        if advice is None:
            continue
        line = f"{canonical_species(name)}：{advice.main}"
        if generic:
            line += "（通用建议）"
        lines.append(line)
    return lines
