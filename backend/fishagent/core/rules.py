"""F1-F7 fish-activity rule engine.

`compute_fish_activity` is pure: the same WeatherSnapshot and local time always
produce the same result, which keeps the HTTP layer and tests deterministic.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fishagent.schemas import (
    AlertOut,
    BestWindow,
    FactorOut,
    FishActivityResult,
    WeatherSnapshot,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")

ALLOWED_SPECIES = ("鲫鱼", "鲤鱼", "草鱼", "鲢鳙")

ADVICE_BY_BAND = {
    "极佳": "强烈建议出钓",
    "良好": "适合出钓",
    "一般": "有机会，建议挑时段",
    "偏差": "不太理想，建议就近作钓",
    "劝退": "今天不建议出钓",
}

FACTOR_NAMES = {
    "F1": "气压变化趋势",
    "F2": "气压绝对值",
    "F3": "气温与变温",
    "F4": "风力风向",
    "F5": "降水与降水窗口",
    "F6": "季节与时段",
    "F7": "云量光照",
}

_ALERT_ORDER = {"danger": 0, "warning": 1, "info": 2}


def band_for_score(score: int) -> str:
    if score >= 85:
        return "极佳"
    if score >= 70:
        return "良好"
    if score >= 55:
        return "一般"
    if score >= 40:
        return "偏差"
    return "劝退"


def impact_for(score: int, max_score: int) -> str:
    ratio = score / max_score if max_score else 0.0
    if ratio >= 0.8:
        return "positive"
    if ratio <= 0.5:
        return "negative"
    return "neutral"


def wind_level_from_speed(speed_ms: float) -> int:
    thresholds = (0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2)
    for level, upper in enumerate(thresholds):
        if speed_ms < upper:
            return level
    return len(thresholds)


def ensure_shanghai(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(SHANGHAI)
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _factor(
    code: str,
    score: int,
    detail: str,
) -> FactorOut:
    max_score = {"F1": 25, "F2": 20, "F3": 15, "F4": 15, "F5": 10, "F6": 10, "F7": 5}[code]
    return FactorOut(
        code=code,
        name=FACTOR_NAMES[code],
        score=score,
        max_score=max_score,
        impact=impact_for(score, max_score),
        detail=detail,
    )


def _score_f1(weather: WeatherSnapshot, alerts: list[AlertOut]) -> FactorOut:
    delta = weather.pressure_change_24h
    short = f"近3h {weather.pressure_change_3h:+.1f}hPa，近6h {weather.pressure_change_6h:+.1f}hPa"
    if abs(delta) <= 2:
        score, lead, comment = 18, "未来24h气压基本稳定", "鱼口预期平稳"
    elif -8 <= delta < -2:
        score, lead, comment = 25, f"未来24h气压缓降 {abs(delta):.1f}hPa", "鱼口活跃信号"
    elif delta < -8:
        score, lead, comment = 15, f"未来24h气压骤降 {abs(delta):.1f}hPa", "短窗口高活性"
        alerts.append(
            AlertOut(
                code="PRESSURE_PLUNGE",
                level="warning",
                message=f"气压24h骤降 {abs(delta):.1f}hPa，有效窗口仅 2–4 小时",
                forced=True,
            )
        )
    elif 2 < delta <= 8:
        score, lead, comment = 12, f"未来24h气压缓升 {delta:.1f}hPa", "鱼口偏弱"
    else:
        score, lead, comment = 5, f"未来24h气压骤升 {delta:.1f}hPa", "典型停口信号"
    return _factor("F1", score, f"{lead}（{short}），{comment}")


def _score_f2(weather: WeatherSnapshot) -> FactorOut:
    pressure = weather.pressure_msl
    percentile = weather.pressure_percentile
    if percentile is not None:
        if 30 <= percentile <= 70:
            score, comment = 20, "处于当地气候态舒适区间"
        elif 15 <= percentile < 30 or 70 < percentile <= 85:
            score, comment = 12, "处于气候态边缘区间"
        else:
            score, comment = 6, "处于气候态异常区间"
        detail = f"近30天分布第 {percentile:.0f} 百分位（{pressure:.1f}hPa），{comment}"
    elif 1005 <= pressure <= 1020:
        score = 20
        detail = (
            f"无近30天历史分布，按兜底口径 1005–1020hPa 为佳"
            f"（当前 {pressure:.1f}hPa）"
        )
    elif 1000 <= pressure < 1005 or 1020 < pressure <= 1025:
        score = 12
        detail = (
            f"无近30天历史分布，气压处于兜底口径边缘区间"
            f"（当前 {pressure:.1f}hPa）"
        )
    else:
        score = 6
        detail = (
            f"无近30天历史分布，气压偏离兜底口径 1005–1020hPa"
            f"（当前 {pressure:.1f}hPa）"
        )
    return _factor("F2", score, detail)


def _score_f3(weather: WeatherSnapshot) -> FactorOut:
    change = abs(weather.temperature_change_24h)
    if change <= 3:
        score = 15
    elif change <= 6:
        score = 10
    elif change <= 8:
        score = 6
    else:
        score = 3

    notes: list[str] = []
    if not 15 <= weather.temperature <= 28:
        score = max(score - 3, 0)
        notes.append("日均温不在15–28℃，-3")
    if weather.diurnal_range > 12:
        score = max(score - 3, 0)
        notes.append("昼夜温差>12℃，-3")

    detail = (
        f"日均温 {weather.temperature:.1f}℃，24h变温 {weather.temperature_change_24h:+.1f}℃，"
        f"昼夜温差 {weather.diurnal_range:.1f}℃"
    )
    if notes:
        detail += "；" + "；".join(notes)
    return _factor("F3", score, detail)


def _score_f4(weather: WeatherSnapshot, alerts: list[AlertOut]) -> FactorOut:
    level = (
        weather.wind_level
        if weather.wind_level is not None
        else wind_level_from_speed(weather.wind_speed_ms)
    )
    if level <= 1:
        score, comment = 9, "风力偏小，水体溶氧一般"
    elif level <= 3:
        score, comment = 15, "微风增氧，适合观漂"
    elif level == 4:
        score, comment = 8, "风力偏大，观漂受影响"
    elif level == 5:
        score, comment = 3, "风力较大，注意安全"
    else:
        score, comment = 0, "大风天气，不建议出钓"

    if level >= 5:
        alerts.append(
            AlertOut(
                code="GALE",
                level="danger",
                message=(
                    f"风力≥5级（{weather.wind_speed_ms:.1f}m/s），水面风浪大，"
                    "注意涉水安全"
                ),
                forced=True,
            )
        )

    detail = (
        f"{weather.wind_direction} {weather.wind_speed_ms:.1f}m/s（{level}级），{comment}"
    )
    return _factor("F4", score, detail)


def _score_f5(weather: WeatherSnapshot, alerts: list[AlertOut]) -> FactorOut:
    precipitation = weather.precipitation_mm
    if weather.is_thunderstorm or precipitation >= 50:
        label = "雷雨" if weather.is_thunderstorm else "暴雨"
        alerts.append(
            AlertOut(
                code="RAINSTORM",
                level="danger",
                message=f"{label}天气存在安全风险，不建议出钓",
                forced=True,
            )
        )
        return _factor("F5", 0, f"{label}天气（日降水 {precipitation:.1f}mm），安全风险高")

    if 25 <= precipitation < 50:
        return _factor("F5", 3, f"大雨 {precipitation:.1f}mm/日，鱼口与安全均承压")
    if 5 <= precipitation < 25:
        return _factor("F5", 7, f"中雨 {precipitation:.1f}mm/日，鱼口可能受影响")
    if 0.1 <= precipitation < 5:
        return _factor("F5", 10, f"小雨 {precipitation:.1f}mm/日，适合作钓")

    if (
        weather.last_rain_hours_ago is not None
        and weather.last_rain_hours_ago <= 6
    ):
        return _factor(
            "F5",
            7,
            f"雨后 {weather.last_rain_hours_ago:.1f} 小时，窗口期内鱼口较好",
        )
    if weather.consecutive_hot_dry_days > 3:
        return _factor(
            "F5",
            5,
            f"连续晴热 {weather.consecutive_hot_dry_days} 天，水体溶氧承压",
        )
    return _factor("F5", 8, "无降水，天气条件平稳")


def _parse_hhmm(value: str, fallback_minutes: int) -> int:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, ValueError):
        return fallback_minutes
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback_minutes
    return hour * 60 + minute


def _fmt_hhmm(minutes: int) -> str:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _sunrise_window(weather: WeatherSnapshot) -> BestWindow:
    sunrise = _parse_hhmm(weather.sunrise, 6 * 60)
    return BestWindow(
        start=_fmt_hhmm(sunrise - 90),
        end=_fmt_hhmm(sunrise + 90),
        label="日出窗口",
    )


def _sunset_window(weather: WeatherSnapshot) -> BestWindow:
    sunset = _parse_hhmm(weather.sunset, 18 * 60)
    return BestWindow(
        start=_fmt_hhmm(sunset - 120),
        end=_fmt_hhmm(sunset),
        label="日落窗口",
    )


def _score_f6(weather: WeatherSnapshot, local_now: datetime) -> FactorOut:
    minutes = local_now.hour * 60 + local_now.minute
    sunrise = _parse_hhmm(weather.sunrise, 6 * 60)
    sunset = _parse_hhmm(weather.sunset, 18 * 60)
    in_sunrise = abs(minutes - sunrise) <= 90
    in_sunset = sunset - 120 <= minutes <= sunset

    if in_sunrise or in_sunset:
        window_label = "日出前后" if in_sunrise else "日落前"
        return _factor("F6", 10, f"{window_label}窗口（本地 {local_now:%H:%M}），鱼口活跃")

    if weather.temperature < 5:
        return _factor(
            "F6",
            2,
            f"冬季低温（日均气温 {weather.temperature:.1f}℃ 代理水温<5℃），鱼活性低",
        )
    if (
        local_now.month in (6, 7, 8)
        and 11 * 60 <= minutes < 15 * 60
        and weather.temperature > 32
    ):
        return _factor("F6", 3, f"盛夏正午高温（{weather.temperature:.1f}℃），鱼口不佳")
    if local_now.month in (3, 4, 5, 9, 10, 11):
        return _factor("F6", 7, f"春秋季非窗口时段（本地 {local_now:%H:%M}）")
    return _factor("F6", 5, f"常规时段（本地 {local_now:%H:%M}）")


def _score_f7(weather: WeatherSnapshot) -> FactorOut:
    cloud = weather.cloud_cover_pct
    if 30 <= cloud <= 70:
        return _factor("F7", 5, f"云量 {cloud:.0f}%，多云散射光适中")
    if cloud > 70:
        return _factor("F7", 4, f"云量 {cloud:.0f}%，阴天光照偏弱")
    return _factor("F7", 3, f"云量 {cloud:.0f}%，晴天光照较强")


def _best_windows(band: str, weather: WeatherSnapshot) -> list[BestWindow]:
    if band == "劝退":
        return []
    sunrise = _sunrise_window(weather)
    if band == "偏差":
        return [sunrise]
    return [sunrise, _sunset_window(weather)]


def _suitable_species(temperature: float, species: str | None) -> list[str]:
    if temperature >= 25:
        base = ["草鱼", "鲢鳙"]
    elif temperature >= 15:
        base = ["鲫鱼", "鲤鱼"]
    else:
        base = ["鲫鱼"]
    if species and species in ALLOWED_SPECIES:
        return [species] + [item for item in base if item != species]
    return base


def _water_depth(temperature: float) -> str:
    if temperature < 5:
        return "钓深水 3–5m，选择背风向阳的深水区"
    if temperature > 32:
        return "早晚钓 1.5–2m 浅滩，正午转 3m 以上深水"
    return "先钓 1.5–2m 浅滩，无口则转 3m 以上"


def _recommendation(
    band: str,
    rainstorm: bool,
    factors: list[FactorOut],
) -> str:
    if rainstorm:
        return "雷雨/暴雨天气存在安全风险，恶劣天气一票否决，今天不建议出钓。"
    if band == "劝退":
        worst = sorted(factors, key=lambda item: (item.score / item.max_score, item.code))[:2]
        names = "、".join(item.name for item in worst)
        return f"今天不建议出钓：{names}条件不佳。"
    if band == "极佳":
        return "强烈建议出钓，全天可钓，优先日出与日落窗口。"
    if band == "良好":
        return "适合出钓，建议优先日出前后窗口。"
    if band == "一般":
        return "有机会，建议挑时段，优先日出窗口。"
    return "不太理想，建议缩短行程或就近作钓。"


def compute_fish_activity(
    weather: WeatherSnapshot,
    now: datetime,
    species: str | None = None,
) -> FishActivityResult:
    local_now = ensure_shanghai(now)
    alerts: list[AlertOut] = []

    factors = [
        _score_f1(weather, alerts),
        _score_f2(weather),
        _score_f3(weather),
        _score_f4(weather, alerts),
        _score_f5(weather, alerts),
        _score_f6(weather, local_now),
        _score_f7(weather),
    ]
    alerts.sort(key=lambda item: _ALERT_ORDER[item.level])

    score = sum(item.score for item in factors)
    band = band_for_score(score)
    advice = ADVICE_BY_BAND[band]

    rainstorm = any(item.code == "RAINSTORM" for item in alerts)
    if rainstorm:
        band = "劝退"
        advice = ADVICE_BY_BAND["劝退"]

    top_factors = sorted(
        factors,
        key=lambda item: (-item.score / item.max_score, -item.score, item.code),
    )[:3]

    return FishActivityResult(
        score=score,
        band=band,
        advice=advice,
        recommendation=_recommendation(band, rainstorm, factors),
        factors=factors,
        top_factors=top_factors,
        best_windows=_best_windows(band, weather),
        water_depth=_water_depth(weather.temperature),
        suitable_species=_suitable_species(weather.temperature, species),
        alerts=alerts,
    )
