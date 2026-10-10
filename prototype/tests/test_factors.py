"""规则引擎测试 —— 对应立项文档 §2.4 与产品原则 P1/P2。"""

from fishagent_m1 import factors


def test_level_thresholds_match_doc():
    assert factors.level_of(90)[0] == "极佳"
    assert factors.level_of(75)[0] == "良好"
    assert factors.level_of(60)[0] == "一般"
    assert factors.level_of(45)[0] == "偏差"
    assert factors.level_of(30)[0] == "劝退"


def test_f1_best_and_worst():
    assert factors.score_f1(-5, None, None).score == 25   # 缓降
    assert factors.score_f1(0, None, None).score == 18    # 稳定
    assert factors.score_f1(10, None, None).score == 5    # 骤升
    assert factors.score_f1(-10, None, None).score == 15  # 骤降


def test_f2_fallback_without_archive():
    assert factors.score_f2(1010, []).score == 20
    assert factors.score_f2(1000, []).score == 6


def test_f5_thunder_forces_zero_and_advisory():
    f, adv = factors.score_f5(0, thunder=True)
    assert f.score == 0 and adv


def test_weights_sum_to_100():
    assert sum(factors.F_MAX.values()) == 100


def test_top3_excludes_lowest():
    score = factors.ActivityScore(
        total=50, level="偏差", action="x",
        factors=[
            factors.FactorScore("F1", 25, 25, "a"),
            factors.FactorScore("F2", 6, 20, "b"),
            factors.FactorScore("F3", 15, 15, "c"),
            factors.FactorScore("F4", 0, 15, "d"),
            factors.FactorScore("F5", 4, 10, "e"),
            factors.FactorScore("F6", 2, 10, "f"),
            factors.FactorScore("F7", 5, 5, "g"),
        ],
    )
    assert len(score.top3) == 3
    assert all(f.code != "F4" for f in score.top3)
