"""Bait guidance: the table, and the species resolution feeding it.

The user-visible bug was that a bait question about 白条 got the generic guide
while 鲫鱼 was answered. That had two independent causes -- no bait intent, and
a four-name species list -- so both are pinned here.
"""

from __future__ import annotations

import pytest

from fishagent.core.bait import (
    BAIT_GUIDE,
    advice_for,
    bait_summary,
    supported_species,
)
from fishagent.core.species import KNOWN_SPECIES, canonical_species


@pytest.mark.parametrize("name", sorted(BAIT_GUIDE))
def test_every_entry_is_usable(name):
    advice = BAIT_GUIDE[name]
    assert advice.main.strip(), name
    assert advice.tip.strip(), name
    # nest may legitimately be empty only for species that are not nest-fed;
    # here every entry has one, so an empty value means it was forgotten.
    assert advice.nest.strip(), name


def test_guide_covers_the_common_activity_species():
    """The four species the activity calculator models must have bait advice."""
    for name in ("鲫鱼", "鲤鱼", "草鱼", "鲢鳙"):
        advice, generic = advice_for(name)
        assert advice is not None, name
        assert not generic, name


def test_guide_covers_what_spot_cards_recommend():
    """A card can recommend 白条 and then offer no bait for it -- the exact
    inconsistency this table exists to prevent."""
    from fishagent.core.species import WATER_TYPE_SPECIES

    recommended = {name for names in WATER_TYPE_SPECIES.values() for name in names}
    missing = sorted(recommended - set(BAIT_GUIDE))
    assert not missing, f"spot cards can recommend these with no bait plan: {missing}"


def test_guide_only_names_known_species():
    """A key the normaliser cannot produce is dead weight that will never hit."""
    unknown = sorted(set(BAIT_GUIDE) - set(KNOWN_SPECIES))
    assert not unknown, unknown


def test_known_species_without_an_entry_gets_a_flagged_generic_plan(monkeypatch):
    """Known to us, but no dedicated plan -- usable, and labelled as generic.

    Every current KNOWN_SPECIES has an entry, so this branch cannot be reached
    with real data today. It still has to work: the moment a species is added
    without bait advice, the alternative is either a crash or -- worse -- bait
    advice for the wrong fish presented as if it were specific to this one.
    Removing an entry simulates exactly that, without waiting for it.
    """
    from fishagent.core import bait as bait_module

    patched = dict(BAIT_GUIDE)
    del patched["鲴鱼"]
    monkeypatch.setattr(bait_module, "BAIT_GUIDE", patched)

    advice, generic = bait_module.advice_for("鲴鱼")
    assert advice is not None
    assert generic is True
    assert advice is bait_module.GENERIC_BAIT


@pytest.mark.parametrize("value", [None, "", "   ", "不存在的鱼"])
def test_unrecognised_species_gets_no_advice(value):
    """Inventing advice for a name we cannot resolve is worse than silence."""
    advice, generic = advice_for(value)
    assert advice is None
    assert generic is False


@pytest.mark.parametrize(
    "sentence,expected",
    [
        ("白条用什么饵料", "白条"),
        ("今天钓翘嘴怎么样", "翘嘴"),
        ("马口怎么钓", "马口"),
        ("胖头鱼用什么饵", "鲢鳙"),
        ("罗非鱼口好吗", "罗非鱼"),
        ("鲫鱼和鲤鱼哪个好钓", "鲫鱼"),  # first match wins; either is valid
        ("今天天气怎么样", None),
    ],
)
def test_species_is_found_inside_a_whole_question(sentence, expected):
    """The chat box sends sentences, not bare names.

    Only 鲫 and 鲤 had aliases before, which is why "鲫鱼用什么饵料" resolved by
    accident and "白条用什么饵料" resolved to nothing.
    """
    found = canonical_species(sentence)
    if expected is None:
        assert found is None
    elif sentence == "鲫鱼和鲤鱼哪个好钓":
        assert found in {"鲫鱼", "鲤鱼"}
    else:
        assert found == expected


def test_supported_species_is_the_intersection():
    supported = supported_species()
    assert set(supported) <= set(KNOWN_SPECIES)
    assert set(supported) == set(BAIT_GUIDE)


def test_bait_summary_caps_and_labels():
    lines = bait_summary(["鲫鱼", "鲤鱼", "草鱼"], limit=2)
    assert len(lines) == 2
    assert all("：" in line for line in lines)
    assert "鲫鱼" in lines[0]


def test_bait_summary_skips_names_it_cannot_resolve():
    lines = bait_summary(["不存在的鱼", "鲫鱼"])
    assert len(lines) == 1
    assert "鲫鱼" in lines[0]
