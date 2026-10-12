"""M2-B01 持久化层 —— SQLite 起步，预留 PostGIS 迁移。

设计约束：
  · **R7 位置隐私**：不落库精确坐标；需要位置维度时只存**粗化网格**（coarsen）。
  · 生产计划迁移到 PostgreSQL + PostGIS（矢量边界/空间索引）；本层接口保持稳定，
    换实现不影响上层（services / analytics）。

当前落库对象：埋点事件（M2-B13）；UGC 钓点（M4）将复用同一连接。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    props   TEXT,
    user_id TEXT,
    ts      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
"""


def coarsen(value: float, precision: int = 2) -> float:
    """R7：位置粗化到网格（默认 0.01°≈1km），用于落库，禁止存精确坐标。"""
    return round(value, precision)


class Database:
    """极简 SQLite 封装（线程安全写入）。"""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def insert_event(self, name: str, props: dict | None = None, *, user_id: str | None = None, ts: str | None = None) -> int:
        import datetime as dt
        ts = ts or dt.datetime.now().isoformat(timespec="seconds")
        payload = json.dumps(_coarsen_props(props or {}), ensure_ascii=False)
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO events (name, props, user_id, ts) VALUES (?, ?, ?, ?)",
                (name, payload, user_id, ts),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def events_by_name(self) -> dict[str, int]:
        with self._lock:
            rows = self.conn.execute("SELECT name, COUNT(*) AS n FROM events GROUP BY name").fetchall()
        return {r["name"]: r["n"] for r in rows}

    def count_events(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"])

    def close(self) -> None:
        with self._lock:
            self.conn.close()


def _coarsen_props(props: dict) -> dict:
    """R7：对 props 中的经纬度做粗化（键名含 lat/lng 时）。"""
    out = {}
    for k, v in props.items():
        if isinstance(v, (int, float)) and ("lat" in k.lower() or "lng" in k.lower()):
            out[k] = coarsen(float(v))
        else:
            out[k] = v
    return out
