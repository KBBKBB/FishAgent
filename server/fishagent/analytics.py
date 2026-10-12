"""M2-B13 埋点接口 —— 门禁 K04（关键埋点 100% 覆盖）。

K04 要求：T01/T02/T09/T10 所依赖的埋点必须 100% 覆盖，否则指标不可信。
本模块定义**关键事件枚举**并在记录时强校验，未注册事件直接报错，避免「漏埋」。

依赖事件（对应立项文档 §8.3 口径）：
  · recommendation_shown   展示的推荐条数（T02 分母）
  · spot_navigated         导航跳转（T02 分子之一）
  · spot_favorited         收藏（T02 分子之一）
  · prediction_feedback    抽样回访的预测认可（T01 分子/分母）
  · went_fishing           是否出钓（T01 分母、O02）
  · skipped_fishing        未出钓（O02）
  · skip_reason            未出钓原因（假设 A6）
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

K04_EVENTS: frozenset[str] = frozenset({
    "recommendation_shown",
    "spot_navigated",
    "spot_favorited",
    "prediction_feedback",
    "went_fishing",
    "skipped_fishing",
    "skip_reason",
})


class AnalyticsSink:
    """内存 + 可选 JSONL 落盘的埋点接收器。"""

    def __init__(self, path: str | Path | None = None, store=None) -> None:
        self.path = Path(path) if path else None
        self.store = store  # 可选：storage.Database（M2-B01 持久化）
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def record(self, name: str, props: dict | None = None, *, user_id: str | None = None) -> dict:
        if name not in K04_EVENTS:
            raise ValueError(f"未注册的埋点事件: {name}（K04 要求关键埋点全覆盖，禁止漏埋）")
        event = {
            "name": name,
            "props": props or {},
            "user_id": user_id,
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self._events.append(event)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        if self.store is not None:
            self.store.insert_event(name, event["props"], user_id=user_id, ts=event["ts"])
        return event

    def summary(self) -> dict:
        counts: dict[str, int] = {e: 0 for e in K04_EVENTS}
        with self._lock:
            for ev in self._events:
                counts[ev["name"]] = counts.get(ev["name"], 0) + 1
        return {"total": sum(counts.values()), "by_event": counts}

    def coverage(self) -> dict:
        """K04：关键事件覆盖情况（出现次数 > 0 视为已覆盖）。"""
        counts = self.summary()["by_event"]
        missing = [e for e in K04_EVENTS if counts.get(e, 0) == 0]
        return {"events": len(K04_EVENTS), "covered": len(K04_EVENTS) - len(missing), "missing": sorted(missing)}
