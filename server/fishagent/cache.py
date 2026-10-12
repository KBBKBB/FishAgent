"""M2-B14 轻量 TTL 缓存（进程内，零依赖）。

用途（对应 Roadmap M2-B14）：
  · 气象 30~60min（同网格复用）；
  · POI 网格级缓存（同片同半径复用）；
  · 精算基准口径缓存（实时口径不缓存）。

⚠️ 进程内实现仅供 M2 内测；生产应替换为 Redis/多实例共享缓存。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TTLCache:
    """带 TTL 的线程安全缓存，附命中统计。"""

    def __init__(self, default_ttl: float = 600.0, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.default_ttl = default_ttl
        self._clock = clock
        self._data: dict[str, tuple[float | None, Any]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            expires, value = item
            if expires is not None and self._clock() >= expires:
                del self._data[key]
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        ttl = self.default_ttl if ttl is None else ttl
        expires = None if ttl is None or ttl <= 0 else self._clock() + ttl
        with self._lock:
            self._data[key] = (expires, value)

    def get_or_set(self, key: str, factory: Callable[[], Any], ttl: float | None = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value, ttl)
        return value

    def stats(self) -> dict[str, int]:
        with self._lock:
            size = len(self._data)
        return {"size": size, "hits": self.hits, "misses": self.misses}


def grid_key(prefix: str, lat: float, lng: float, *, precision: int = 2) -> str:
    """按网格取缓存键（默认 0.01°≈1km，气象按此复用足够）。"""
    return f"{prefix}:{round(lat, precision)}:{round(lng, precision)}"
