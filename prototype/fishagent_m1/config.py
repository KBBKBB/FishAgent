"""配置 —— 密钥仅从环境变量读取 (对应红线 R3: 密钥不下发客户端、不入库)。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

AMAP_BASE = "https://restapi.amap.com"
OPEN_METEO_BASE = "https://api.open-meteo.com"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com"


@dataclass
class Config:
    # —— 高德 (服务端持有) ——
    amap_key: str | None = field(default_factory=lambda: os.getenv("AMAP_KEY") or None)
    # 数字签名用私钥 (高德「数字签名」开启后才有), 对应 R3 的 sig
    amap_secret: str | None = field(default_factory=lambda: os.getenv("AMAP_SECRET") or None)
    timeout: float = field(default_factory=lambda: float(os.getenv("FA_HTTP_TIMEOUT", "8")))

    @property
    def amap_ready(self) -> bool:
        return bool(self.amap_key)

    def require_amap(self) -> None:
        if not self.amap_key:
            raise RuntimeError(
                "缺少高德 Key: 请设置环境变量 AMAP_KEY (服务端持有, 严禁下发客户端)。"
                " M1 离线演示可加 --mock 参数使用 fixtures。"
            )


# 高德周边搜索半径硬上限 (R2): 超过 50000 会静默降级为默认 3000 米且不报错
AMAP_AROUND_MAX_RADIUS = 50000
AMAP_AROUND_DEFAULT_RADIUS = 3000  # 超限后被静默应用的默认值

# 距离测量 API 批量上限: 1 个终点 × 最多 100 个起点 (R4)
AMAP_DISTANCE_MAX_ORIGINS = 100

# 往返车程阈值 (R4): 去程 + 回程 <= 7200 秒
ROUND_TRIP_MAX_SECONDS = 7200

# 水域 POI 关键词 (双路召回之一, 见立项文档 4.2)
WATER_KEYWORDS = ["水库", "湖", "河", "塘", "野钓"]
