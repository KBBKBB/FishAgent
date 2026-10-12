"""高德 Web 服务客户端 —— 对应红线 R3 (密钥不下发客户端 + IP 白名单 + sig 签名)。

所有 Web 服务调用必须经服务端中转, 本模块即「服务端唯一出口」的最小实现。
客户端 (小程序/H5) 只发一次业务请求, 不接触 Key。
"""

from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from .config import AMAP_BASE, Config
from .http import get_json


def _sign(params: dict[str, Any], secret: str) -> str:
    """高德数字签名: 参数按 key 升序拼接 k=v&... 后追加私钥, 取 md5。"""
    items = sorted((k, str(v)) for k, v in params.items() if k != "sig" and v is not None)
    query = "&".join(f"{k}={v}" for k, v in items)
    return hashlib.md5((query + secret).encode("utf-8")).hexdigest()


class AmapClient:
    """高德 Web 服务最小客户端。"""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()

    def call(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self.cfg.require_amap()
        data = dict(params)
        data["key"] = self.cfg.amap_key
        if self.cfg.amap_secret:
            data["sig"] = _sign(data, self.cfg.amap_secret)
        url = f"{AMAP_BASE}/{path.lstrip('/')}"
        return get_json(url, data, timeout=self.cfg.timeout)

    # —— 具体接口封装 ——

    def place_around(self, location: str, radius: int, **kw: Any) -> dict[str, Any]:
        """周边搜索 v3/place/around。radius 硬校验在 poi.py 完成 (R2)。"""
        params = {"location": location, "radius": radius, **kw}
        return self.call("v3/place/around", params)

    def place_text(self, keywords: str, **kw: Any) -> dict[str, Any]:
        """关键字搜索 v3/place/text (双路召回之一)。"""
        return self.call("v3/place/text", {"keywords": keywords, **kw})

    def place_polygon(self, polygon: str, **kw: Any) -> dict[str, Any]:
        """多边形搜索 v3/place/polygon (突破半径上限的分片方案)。"""
        return self.call("v3/place/polygon", {"polygon": polygon, **kw})

    def distance(
        self,
        origins: str,
        destination: str,
        distance_type: int = 1,
    ) -> dict[str, Any]:
        """距离测量 v3/distance。注意: 1 个终点 × 最多 100 个起点 (R4)。

        type=1 为驾车模式 (是否计实时路况需 M1-T04 实测确认)。
        """
        return self.call(
            "v3/distance",
            {"origins": origins, "destination": destination, "type": distance_type},
        )

    def driving(self, origin: str, destination: str, **kw: Any) -> dict[str, Any]:
        """驾车路径规划 v5/direction/driving (v3/distance 不可用时的替代)。"""
        return self.call("v5/direction/driving", {"origin": origin, "destination": destination, **kw})

    def convert_amap(self, locations: str, coordsys: str = "gps") -> dict[str, Any]:
        """官方坐标转换 v3/assistant/coordinate/convert —— 仅用于与本地算法交叉校验。"""
        return self.call("v3/assistant/coordinate/convert", {"locations": locations, "coordsys": coordsys})


def is_amap_ok(resp: dict[str, Any]) -> bool:
    """高德成功响应 status == '1' (字符串)。"""
    return str(resp.get("status")) == "1"


def amap_error(resp: dict[str, Any]) -> str:
    return f"status={resp.get('status')} infocode={resp.get('infocode')} info={resp.get('info')}"
