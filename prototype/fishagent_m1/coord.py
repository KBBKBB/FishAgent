"""坐标转换 —— 对应实现红线 R1 (TechStack.md §5).

R1【强制】: 手机 GPS / Open-Meteo 用 WGS84, 高德所有 Web 服务 API 只接受 GCJ-02。
境内偏差 50~500 米, 可直接导致「推荐钓位落到对岸」。

本模块提供 wgs84_to_gcj02() / gcj02_to_wgs84() 作为【唯一转换入口】。
采用纯算法本地转换 (不消耗高德配额, 对应调用量预算中「坐标转换 → 降为 0」),
高德 v3/assistant/coordinate/convert 仅作为交叉校验之用 (见 amap.convert_amap)。

参考: GCJ-02 偏移算法为公开逆向工程实现, 精度与高德官方 API 一致 (米级)。
"""

from __future__ import annotations

import math

# Krasovsky 1940 椭球参数
_A = 6378245.0
_EE = 0.00669342162296594323

OUT_OF_CHINA_LNG = (73.66, 135.05)
OUT_OF_CHINA_LAT = (3.86, 53.55)


def out_of_china(lat: float, lng: float) -> bool:
    """境外不做偏移 (GCJ-02 仅在中国境内生效)。"""
    return not (
        OUT_OF_CHINA_LNG[0] < lng < OUT_OF_CHINA_LNG[1]
        and OUT_OF_CHINA_LAT[0] < lat < OUT_OF_CHINA_LAT[1]
    )


def _transform_lat(x: float, y: float) -> float:
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    """WGS84 -> GCJ-02 (火星坐标)。返回 (lat, lng)。"""
    if out_of_china(lat, lng):
        return lat, lng
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lat + dlat, lng + dlng


def gcj02_to_wgs84(lat: float, lng: float) -> tuple[float, float]:
    """GCJ-02 -> WGS84。用迭代法逼近, 收敛到 1e-9 度 (约 0.1mm)。"""
    if out_of_china(lat, lng):
        return lat, lng
    wlat, wlng = lat, lng
    for _ in range(30):
        glat, glng = wgs84_to_gcj02(wlat, wlng)
        dlat = glat - lat
        dlng = glng - lng
        if abs(dlat) < 1e-11 and abs(dlng) < 1e-11:
            break
        wlat -= dlat
        wlng -= dlng
    return wlat, wlng


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点球面距离 (米), 用于度量坐标偏移幅度。"""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def offset_meters(lat: float, lng: float) -> float:
    """给定 WGS84 点, 返回转 GCJ-02 后的水平偏移 (米)。"""
    glat, glng = wgs84_to_gcj02(lat, lng)
    return haversine_m(lat, lng, glat, glng)
