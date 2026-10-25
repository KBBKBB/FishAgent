"""Deterministic community-species mock.

Each water body maps to a stable species list from a water-type pool. Roughly
one in five names deliberately yields no recommendation so the "暂无相关鱼种
推荐" path is exercised without special-casing individual spots.
"""

from __future__ import annotations

import hashlib

from fishagent.schemas import SpotSpeciesQuery

_POOLS: dict[str, tuple[str, ...]] = {
    "水库": ("鲫鱼", "鲤鱼", "草鱼", "鲢鳙", "青鱼"),
    "河流": ("鲫鱼", "鲤鱼", "白条", "马口", "翘嘴"),
    "湖泊": ("鲫鱼", "鲤鱼", "鳊鱼", "鲢鳙", "翘嘴"),
    "野塘": ("鲫鱼", "黑鱼", "黄颡鱼", "鲶鱼"),
}
_DEFAULT_POOL = ("鲫鱼", "鲤鱼", "草鱼")

_NO_RECOMMENDATION_BUCKET = 5


class MockSpeciesProvider:
    name = "mock"
    source_label = "小红书（Mock）"

    async def find_species(
        self,
        spots: list[SpotSpeciesQuery],
    ) -> list[list[str]]:
        return [self._for_spot(spot) for spot in spots]

    def _for_spot(self, spot: SpotSpeciesQuery) -> list[str]:
        seed = f"{spot.name}|{spot.water_type}".encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        if digest[0] % _NO_RECOMMENDATION_BUCKET == 0:
            return []
        pool = _POOLS.get(spot.water_type.strip(), _DEFAULT_POOL)
        count = 1 + digest[1] % min(3, len(pool))
        start = digest[2] % len(pool)
        return [pool[(start + offset) % len(pool)] for offset in range(count)]
