# FishAgent M2 — MVP 服务端

> 阶段：**M2 MVP**（`Spec/Roadmap.md` 第三章）。目标：打通「鱼情分析 + 钓位推荐」核心闭环，交付可内测版本。
> 工程取向：**零依赖 Python**（沿用 M1 原型风格），标准库实现 HTTP 服务，预留 FastAPI 迁移位。

## 目录结构

```
server/
├── app.py                 # 服务入口（--offline 可无 Key 运行）
├── fishagent/
│   ├── config.py          # 配置（R3：密钥仅从环境变量读取）
│   ├── coord.py           # R1 坐标唯一入口 wgs84→gcj02
│   ├── amap.py / http.py  # 高德服务端出口（R3）
│   ├── poi.py             # 双路召回（type 码 + 关键词）+ R2 半径硬校验
│   ├── sharding.py        # 网格分片（突破 50km 上限）
│   ├── route.py           # 往返车程精算（R4）
│   ├── weather.py         # Open-Meteo 接入（pressure_msl + 30 天分布）
│   ├── factors.py         # 鱼情规则引擎 F1–F7 + 可解释输出（R6/R8）
│   ├── services.py        # 服务编排：两个核心用例
│   ├── cache.py           # M2-B14 进程内 TTL 缓存（气象/POI 网格）
│   ├── analytics.py       # M2-B13 埋点（K04 关键事件强校验 + JSONL 落盘）
│   ├── boundary.py        # M2-B11 禁钓权威矢量边界（GeoJSON + 射线法，R5）
│   ├── api.py             # HTTP 路由（标准库 http.server）
│   └── mock.py            # 离线 mock（演示/单测）
├── fixtures/              # 演示与测试数据
└── tests/                 # 单元测试（标准库 unittest）
```

## 快速开始

```bash
cd server
python3 app.py --offline --port 8000     # 无需任何 Key（mock 高德 + 合成气象）
# 或真实链路：
export AMAP_KEY=xxxx && python3 app.py

# 可选：加载权威禁钓矢量边界（R5，GeoJSON）
export FA_BAN_ZONES=fixtures/ban_zones.sample.geojson
```

### 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/fish-activity?lat=&lng=` | 鱼情活跃度（评分/分档/Top3 因子/可解释文本） |
| GET | `/api/v1/spots?lat=&lng=&limit=` | 钓位推荐（往返 ≤2h，含单程预估与端点精度标注） |
| POST | `/api/v1/events` | 记录关键埋点（K04 强校验；`{"name":...,"props":{...}}`） |
| GET | `/api/v1/analytics/summary` | 埋点计数汇总 |
| GET | `/api/v1/analytics/coverage` | K04 关键事件覆盖情况 |

```bash
curl 'http://127.0.0.1:8000/api/v1/fish-activity?lat=30.657&lng=104.066'
curl 'http://127.0.0.1:8000/api/v1/spots?lat=30.657&lng=104.066&limit=5'
```

## 测试

```bash
cd server && python3 -m unittest discover -s tests -t . -v
```

## 对应 Roadmap 任务

| 编号 | 落地位置 |
|---|---|
| M2-B03/B04/B05 气象+规则+可解释 | `weather.py` / `factors.py` / `services.analyze_fish_activity` |
| M2-B06/B07 双路召回+分片 | `poi.py` / `sharding.py` / `services.recommend_spots` |
| M2-B08/B09 往返精算+过滤 | `route.py` |
| M2-B10 综合排序 | `services.recommend_spots`（当前按往返时长排序；后续叠加鱼情/鱼种权重） |
| M2-B11 禁钓过滤（R5） | `boundary.py`（GeoJSON 矢量边界 + 射线法 + 保守排除）+ `services.is_banned` 关键词兜底 |
| M2-B13 埋点（门禁 K04） | `analytics.py` + `POST /api/v1/events`（事件强校验，禁止漏埋） |
| M2-B14 缓存层 | `cache.py`（气象 30min / 归档 6h，TTL + 命中统计） |
| M2-B12 服务端 Key 管理（R3） | `config.py` / `amap.py`（**IP 白名单与 sig 待接入网关**） |
| M2-B01 脚手架 | 本目录 |

## 尚未完成（M2 待办）

- [ ] 数据库 / PostGIS 初始化与持久化（M2-B01）
- [ ] 接入**官方**禁钓矢量数据（M2-B11 机制已就绪，当前用样例 GeoJSON）
- [ ] 小程序前端（M2-F01..F06）
- [ ] FastAPI 迁移（依赖可安装后）
- [x] 埋点接口（M2-B13）／缓存层（M2-B14）／禁钓矢量过滤机制（M2-B11）
