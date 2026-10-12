"""鱼口活跃度规则引擎 F1–F7 (Phase 1) —— 严格对齐立项文档 §2.4。

⚠️ 所有权重与阈值均为**待校准的初始假设** (公开钓鱼经验共识), M2 内测后须按 §2.4.5 回溯校准。
本模块产出 0-100 分 + 分档 + 可解释性明细 (Top 3 因子) + 强制提示。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .weather import WeatherSeries, percentile

# 各因子上限 (合计 100)
F_MAX = {"F1": 25, "F2": 20, "F3": 15, "F4": 15, "F5": 10, "F6": 10, "F7": 5}
F_NAME = {
    "F1": "气压变化趋势",
    "F2": "气压绝对值(当地归一化)",
    "F3": "气温与变温",
    "F4": "风力风向",
    "F5": "降水与降水窗口",
    "F6": "季节/时段",
    "F7": "云量/光照",
}


@dataclass
class FactorScore:
    code: str
    score: float
    max_score: float
    reason: str


@dataclass
class ActivityScore:
    total: float
    level: str
    action: str
    factors: list[FactorScore] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)

    @property
    def top3(self) -> list[FactorScore]:
        return sorted(self.factors, key=lambda f: f.score / f.max_score, reverse=True)[:3]


def level_of(total: float) -> tuple[str, str]:
    """总分 -> (档位, 产品动作)。见立项文档 §2.4.3。"""
    if total >= 85:
        return "极佳", "强烈建议出钓，给全天窗口"
    if total >= 70:
        return "良好", "适合出钓，给最佳时段"
    if total >= 55:
        return "一般", "有机会，建议挑时段，给 2 个候选窗口"
    if total >= 40:
        return "偏差", "不太理想，建议缩短行程 / 就近作钓"
    return "劝退", "今天不建议出钓 + 明确理由"


def score_f1(d24: float, d3: float, d6: float) -> FactorScore:
    """F1 气压变化趋势 (满分 25)。优先用未来 24h 变化量 (决策价值更高)。"""
    ad = abs(d24)
    extra = ""
    if d6 is not None and abs(d6) >= 3:
        extra = f"；近 6h 快速变压 {d6:+.1f}hPa"
    if -8 <= d24 <= -3:
        s, r = 25, f"气压正在缓降（24h {d24:+.1f}hPa），典型鱼口活跃信号{extra}"
    elif ad <= 2:
        s, r = 18, f"气压基本稳定（24h {d24:+.1f}hPa）{extra}"
    elif d24 < -8:
        s, r = 15, f"气压骤降（24h {d24:+.1f}hPa），短窗口高活性{extra}"
    elif 3 <= d24 <= 8:
        s, r = 12, f"气压缓升（24h {d24:+.1f}hPa），偏偏差{extra}"
    else:
        s, r = 5, f"气压骤升（24h {d24:+.1f}hPa），典型停口信号{extra}"
    return FactorScore("F1", s, 25, r)


def score_f2(p_now: float, archive: list[float]) -> FactorScore:
    """F2 气压绝对值 (满分 20), 相对当地近 30 天分布归一化 (消除海拔与季节性误判)。"""
    if archive:
        pct = percentile(archive, p_now)
        if 30 <= pct <= 70:
            s, tag = 20, "位于当地 30~70 百分位（最佳区间）"
        elif 15 <= pct < 30 or 70 < pct <= 85:
            s, tag = 12, "位于当地 15~30 / 70~85 百分位"
        else:
            s, tag = 6, "位于当地 <15 或 >85 百分位（异常低/高）"
        return FactorScore("F2", s, 20, f"气压 {p_now:.1f}hPa，{tag}（当地百分位 {pct:.0f}）")
    # 兜底: 无历史分布
    s = 20 if 1005 <= p_now <= 1020 else 6
    return FactorScore("F2", s, 20, f"气压 {p_now:.1f}hPa（无 30 天分布，用 1005~1020 兜底）")


def score_f3(t_now: float, d24: float, diurnal: float) -> FactorScore:
    """F3 气温与变温 (满分 15)。"""
    s, r = 15, f"日均温 {t_now:.0f}℃ 且 24h 变温 {d24:+.1f}℃（≤3℃）"
    if abs(d24) > 8:
        s, r = 3, f"24h 变温 {d24:+.1f}℃（寒潮过境），鱼层剧烈扰动"
    elif 3 < abs(d24) <= 8:
        s, r = 10, f"24h 变温 {d24:+.1f}℃（3~6℃ 区间附近），鱼层不稳"
    elif not (15 <= t_now <= 28):
        s, r = 10, f"日均温 {t_now:.0f}℃（偏离 15~28℃ 适温区）"
    if diurnal > 12:
        s = max(0, s - 3)
        r += f"；昼夜温差 {diurnal:.0f}℃（>12℃）额外 −3"
    return FactorScore("F3", s, 15, r)


def score_f4(wind_ms: float) -> tuple[FactorScore, list[str]]:
    """F4 风力风向 (满分 15)。风向修正 (下风口/迎风岸) 需水域朝向, MVP 暂不计算。"""
    advisories: list[str] = []
    if 3.4 <= wind_ms <= 5.4:
        s, r = 15, f"风力 2~3 级（{wind_ms:.1f} m/s 微风），增氧且不影响观漂（最佳）"
    elif wind_ms < 3.4:
        s, r = 9, f"风力 1 级或无风（{wind_ms:.1f} m/s）"
    elif wind_ms < 5.5:
        s, r = 8, f"风力 4 级（{wind_ms:.1f} m/s）"
    else:
        s, r = 2, f"风力 ≥5 级（{wind_ms:.1f} m/s）"
        advisories.append("⚠️ 安全提示：风力 ≥5 级，出钓需注意人身安全，建议改期。")
    return FactorScore("F4", s, 15, r), advisories


def score_f5(precip_24h_mm: float, thunder: bool = False) -> tuple[FactorScore, list[str]]:
    """F5 降水与降水窗口 (满分 10)。雷雨/暴雨强制劝退。"""
    advisories: list[str] = []
    if thunder or precip_24h_mm >= 25:
        advisories.append("⛔ 暴雨/雷雨：触发「不建议出钓」强制提示。")
        return FactorScore("F5", 0, 10, f"暴雨/雷雨（24h {precip_24h_mm:.1f}mm）"), advisories
    if precip_24h_mm == 0:
        s, r = 8, "阴天/无雨"
    elif precip_24h_mm < 5:
        s, r = 10, f"小雨（24h {precip_24h_mm:.1f}mm），入水口含氧与饵料增加"
    elif precip_24h_mm < 25:
        s, r = 7, f"中雨或雨后窗口（24h {precip_24h_mm:.1f}mm）"
    else:
        s, r = 5, f"降水偏多（24h {precip_24h_mm:.1f}mm）"
    return FactorScore("F5", s, 10, r), advisories


def score_f6(ref: dt.datetime, sunrise: str | None, sunset: str | None, t_now: float) -> FactorScore:
    """F6 季节/时段 (满分 10), 日出日落窗口为核心。"""
    month = ref.month
    hh = ref.hour
    try:
        sr = dt.datetime.fromisoformat(sunrise) if sunrise else None
        ss = dt.datetime.fromisoformat(sunset) if sunset else None
    except ValueError:
        sr = ss = None
    if sr and ss:
        in_sunrise = (sr - dt.timedelta(hours=1.5)) <= ref <= (sr + dt.timedelta(hours=1.5))
        in_sunset = (ss - dt.timedelta(hours=2)) <= ref <= ss
        if in_sunrise or in_sunset:
            return FactorScore("F6", 10, 10, "处于日出/日落窗口期（典型上鱼时段）")
    if month in (3, 4, 5, 9, 10, 11):
        return FactorScore("F6", 7, 10, f"春秋季（{month} 月）其他时段")
    if 11 <= hh <= 15 and t_now > 32:
        return FactorScore("F6", 3, 10, "盛夏正午（11-15 时且气温 >32℃）")
    return FactorScore("F6", 2, 10, "冬季/低水温时段")


def score_f7(cloud: float) -> FactorScore:
    """F7 云量/光照 (满分 5)。"""
    if 30 <= cloud <= 70:
        return FactorScore("F7", 5, 5, f"多云（云量 {cloud:.0f}%）")
    if cloud > 70:
        return FactorScore("F7", 4, 5, f"阴（云量 {cloud:.0f}%）")
    return FactorScore("F7", 3, 5, f"晴（云量 {cloud:.0f}%）")



def evaluate(
    series: WeatherSeries,
    idx: int,
    *,
    archive_pressure: list[float] | None = None,
) -> ActivityScore:
    """对给定小时下标 idx 计算活跃度总分与分档。"""
    p_now = series.value_at("pressure_msl", idx)
    if p_now is None:
        raise ValueError("该时刻缺少 pressure_msl 数据")
    p_future24 = series.value_at("pressure_msl", idx + 24)
    p_past24 = series.value_at("pressure_msl", idx - 24)
    # F1 优先未来 24h 预报变化量 (文档要求)
    if p_future24 is not None:
        d24 = p_future24 - p_now
    elif p_past24 is not None:
        d24 = p_now - p_past24
    else:
        d24 = 0.0
    d3 = series.delta("pressure_msl", idx, 3)
    d6 = series.delta("pressure_msl", idx, 6)

    t_now = series.value_at("temperature_2m", idx) or 20.0
    t_past24 = series.value_at("temperature_2m", idx - 24) or t_now
    dt24 = t_now - t_past24
    tmax = (series.daily.get("temperature_2m_max") or [None])[0]
    tmin = (series.daily.get("temperature_2m_min") or [None])[0]
    diurnal = (tmax - tmin) if (tmax is not None and tmin is not None) else 0.0

    wind_kmh = series.value_at("wind_speed_10m", idx) or 0.0
    wind_ms = wind_kmh / 3.6  # Open-Meteo 默认 km/h

    precip_vals = [
        v for v in (series.variables.get("precipitation") or [])[idx : idx + 24] if v is not None
    ]
    precip_24h = sum(precip_vals)
    cloud = series.value_at("cloud_cover", idx) or 0.0

    ref = _parse_time(series.times[idx])
    sunrise = (series.daily.get("sunrise") or [None])[0]
    sunset = (series.daily.get("sunset") or [None])[0]

    f4, adv4 = score_f4(wind_ms)
    f5, adv5 = score_f5(precip_24h)
    factors = [
        score_f1(d24, d3, d6),
        score_f2(p_now, archive_pressure or []),
        score_f3(t_now, dt24, diurnal),
        f4,
        f5,
        score_f6(ref, sunrise, sunset, t_now),
        score_f7(cloud),
    ]
    total = round(sum(f.score for f in factors), 1)
    level, action = level_of(total)
    advisories = adv4 + adv5
    if total < 40:
        advisories.append("⛔ 总分 < 40：按产品原则 P1，明确输出「今天不建议出钓」。")
    if d24 < -8:
        advisories.append("⏱️ 气压骤降：有效窗口仅 2~4 小时，请抓住出钓窗口。")
    return ActivityScore(total=total, level=level, action=action, factors=factors, advisories=advisories)


def _parse_time(s: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return dt.datetime.now()


def render_explanation(score: ActivityScore, *, note_ai: bool = True) -> str:
    """可解释性输出模板 (立项文档 §2.4.4, 产品原则 P2)。"""
    lines = [f"鱼口活跃度：{score.total:.0f} / 100（{score.level}）", "核心原因（Top 3）："]
    for i, f in enumerate(score.top3, 1):
        lines.append(f"  {i}. {F_NAME[f.code]}：{f.reason}  [{f.score:+.0f}/{f.max_score:.0f}]")
    lines.append(f"产品动作：{score.action}")
    for a in score.advisories:
        lines.append(a)
    if note_ai:
        lines.append("（本结论为 AI 生成的参考建议，非气象预报，不保证渔获）")
    return "\n".join(lines)
