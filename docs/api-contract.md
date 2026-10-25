# FishAgent MVP 接口与工程契约 v1.6

> 本契约是并行开发的唯一字段依据。字段改名或语义变更必须先通知协调者（小项）并更新本文件。
>
> v1.1（2026-10-21）：澄清 `alerts` 结构、`filtered` 统计口径、时区规则、422 统一错误体、Mock 五档触发方式与测试注入点；补充 F3/F4/F6 边界口径。
> v1.2（2026-10-21）：裁决 F2 兜底区间外、F5 晴/雨口径、`best_windows` 数量、Agent 工具名、单程分钟取整。
> v1.3（2026-10-22）：真实模式钓位改为水体类型召回 + 回程批量预筛 + 最近候选分批精算；`filtered` 增补 `unavailable/evaluated/unevaluated`，新增有界并发与限速配置。
> v1.4（2026-10-23）：`GET /api/spots/recommend` 新增 `offset`（默认 0，0–20）用于“换一批”；评估目标改为 `offset+limit`（仍受 30 上限），返回 `eligible[offset:offset+limit]`；`eligible = returned + truncated_by_limit` 不变。商业 POI 过滤补充经营部/建材/商贸等后缀；评估批次改为 `max(limit, 10)`。
> v1.5（2026-10-25）：新增 `POST /api/spots/species`（推荐鱼种）与 `SpeciesProvider` 注入点；明确空结果、降级与缓存口径。
> v1.6（2026-10-25）：同步第二轮修复口径——降级必为全空、结构异常整体降级、负缓存 300s、缓存键归一化、`CancelledError` 上抛；补物种相关配置与注入点。
> 上游依据：`Spec/Mission.md`、`Spec/TechStack.md`、`项目立项文档.md` 第 2.4 节。

## 1. 目录与所有权

```
backend/                          # 小钱（agent/ 目录归小厚）
  pyproject.toml                  # 依赖与工具配置
  fishagent/
    __init__.py
    main.py                       # FastAPI 实例、CORS、路由挂载、web 静态托管
    config.py                     # pydantic-settings 配置
    schemas.py                    # 对外 API 的 Pydantic 模型（本契约）
    core/coords.py                # wgs84_to_gcj02 / gcj02_to_wgs84（唯一转换入口）
    core/rules.py                 # F1–F7 评分、分档、Top3
    core/forbidden.py             # 禁钓过滤（保守排除）
    core/species.py               # 鱼种白名单、别名归一、去重与截断
    providers/base.py             # WeatherProvider / GeoProvider / SpeciesProvider 协议
    providers/open_meteo.py       # 真实气象适配器
    providers/weather_mock.py     # 确定性 Mock
    providers/amap.py             # 高德 POI/距离适配器
    providers/amap_mock.py        # 确定性 Mock
    providers/species_mock.py     # 鱼种 Mock Provider
    providers/species_none.py     # 不伪造社区数据的空 Provider
    services/fish_activity.py     # 聚合天气 + 规则引擎
    services/spots.py             # 召回 → 入口坐标 → 往返精算 → 过滤 → 排序
    services/species.py           # 批量鱼种查询 + 进程内缓存 + 降级
    api/fish_activity.py          # GET /api/fish-activity
    api/spots.py                  # GET /api/spots/recommend
    api/species.py                # POST /api/spots/species
    api/meta.py                   # GET /health, GET /api/demo/config
    agent/                        # 小厚
      graph.py                    # LangGraph 状态图
      tools.py                    # 工具：鱼情 / 钓位
      llm.py                      # OpenAI 兼容 LLM 适配 + 无 Key 兜底
      router.py                   # POST /api/agent/chat
backend/tests/                    # 小测
web/                              # 小厚：index.html / app.js / styles.css
docs/                             # 小产（mvp-prd.md）、小项（计划/契约/验收）
fixtures/                         # 小产：演示场景
```

**挂载约定**：`main.py` 必须挂载 `api.fish_activity.router`、`api.spots.router`、`api.species.router`、`api.meta.router`、`agent.router.router`；`agent/router.py` 由小厚提供，至少导出 `router`。`web/` 通过 `StaticFiles(html=True)` 挂到 `/`，API 优先匹配。

## 2. 通用约定

- 编码 UTF-8；时间统一 ISO 8601 UTC（`2026-10-21T10:00:00Z`）。
- 经纬度参数：WGS84 输入（`lat`, `lon`）；高德调用前统一经 `wgs84_to_gcj02()` 转换；返回给前端的坐标标注坐标系。
- 错误格式：**所有** 4xx/5xx 统一为 `{"detail": {"code": "INVALID_RADIUS", "message": "..."}}`，通过 FastAPI 异常处理器实现。
- 参数校验失败（422）同样使用统一结构：`{"detail": {"code": "VALIDATION_ERROR", "message": "参数校验失败", "fields": [{"field": "lat", "message": "..."}]}}`；`fields` 为可选数组。
- 时区：业务判定与展示时区固定为 `Asia/Shanghai`。`at` 带时区时按其转换；不带时区时按东八区本地时间解释；`generated_at` 始终为 UTC（`Z` 结尾）。响应含 `"timezone": "Asia/Shanghai"`。
- 所有面向用户的结论必须包含 AI 标识与「不承诺渔获」免责；不得原样播报天气预报（P5/R8）。
- Mock 模式为默认（`FISHAGENT_MOCK_MODE=true`），无任何 Key 可完整运行。

## 3. 配置项（环境变量 / `.env`）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `FISHAGENT_MOCK_MODE` | `true` | true 时使用 Mock 天气/POI/LLM 兜底 |
| `FISHAGENT_HOST` | `127.0.0.1` | 监听地址 |
| `FISHAGENT_PORT` | `8000` | 端口 |
| `AMAP_WEB_KEY` | 空 | 高德 Web 服务 Key（仅服务端） |
| `OPEN_METEO_BASE_URL` | `https://api.open-meteo.com/v1` | 气象数据源 |
| `LLM_API_KEY` | 空 | OpenAI 兼容 Key；为空走 fallback |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM 网关 |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名 |
| `LLM_TIMEOUT_SECONDS` | `30` | LLM 超时 |
| `FISHAGENT_AMAP_CONCURRENCY` | `6` | 真实模式召回与路径规划并发上限 |
| `FISHAGENT_AMAP_QPS` | `2` | 真实模式请求起间隔（秒） |
| `FISHAGENT_SPECIES_PROVIDER` | 空 | `mock` / `none` / `disabled`；留空时 Mock 模式用 `mock`，真实模式用 `none`；未知值告警后按 `none` |
| `FISHAGENT_SPECIES_TIMEOUT_SECONDS` | `4.0` | 鱼种查询超时，范围 0 < x ≤ 30 |
| `FISHAGENT_SPECIES_CACHE_TTL_SECONDS` | `3600` | 鱼种结果缓存秒数，范围 0–86400；0 表示不读不写缓存 |

`.env.example` 只放占位符，严禁真实密钥入库。

## 4. 端点契约

### 4.1 `GET /health`

```json
{ "status": "ok", "version": "0.1.0", "mock_mode": true }
```

### 4.2 `GET /api/fish-activity`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `lat` | float | 是 | -90~90（WGS84） |
| `lon` | float | 是 | -180~180（WGS84） |
| `species` | string | 否 | 鲫鱼/鲤鱼/草鱼/鲢鳙；缺省给通用分 |
| `at` | datetime | 否 | 评估时刻（ISO），缺省当前时刻；不带时区按 `Asia/Shanghai` 解释 |
| `location_name` | string | 否 | 展示用地点名 |
| `scenario` | string | 否 | 仅 Mock 模式生效：`excellent/good/fair/poor/no_go`，用于确定性触发五档；真实模式忽略 |

响应 `FishActivityResponse`：

```json
{
  "score": 68,
  "band": "一般",
  "advice": "有机会，建议挑时段",
  "recommendation": "有机会，建议挑时段，优先日出窗口",
  "factors": [
    {
      "code": "F1",
      "name": "气压变化趋势",
      "score": 25,
      "max_score": 25,
      "impact": "positive",
      "detail": "未来24h气压缓降 4.2hPa，鱼口活跃信号"
    }
  ],
  "top_factors": [ { "code": "F1", "name": "气压变化趋势", "score": 25, "max_score": 25, "impact": "positive", "detail": "..." } ],
  "best_windows": [ { "start": "05:30", "end": "08:00", "label": "日出窗口" } ],
  "water_depth": "先钓 1.5–2m 浅滩，无口则转 3m 以上",
  "suitable_species": ["鲫鱼", "鲤鱼"],
  "alerts": [
    {
      "code": "PRESSURE_PLUNGE",
      "level": "warning",
      "message": "气压 24h 骤降 9.0hPa，有效窗口仅 2–4 小时",
      "forced": true
    }
  ],
  "weather_summary": {
    "pressure_msl": 1012.0,
    "pressure_change_24h": -4.2,
    "pressure_change_3h": -0.8,
    "pressure_change_6h": -1.5,
    "temperature": 22.0,
    "temperature_change_24h": 7.0,
    "diurnal_range": 9.0,
    "wind_speed_ms": 4.5,
    "wind_level": 3,
    "wind_direction": "东南风",
    "precipitation_mm": 0.0,
    "cloud_cover_pct": 55,
    "sunrise": "06:12",
    "sunset": "17:48",
    "is_thunderstorm": false
  },
  "data_sources": ["Open-Meteo（Mock）", "FishAgent 规则引擎 v1"],
  "ai_disclosure": "本结论由 AI 辅助生成，仅供参考，不承诺渔获。",
  "timezone": "Asia/Shanghai",
  "generated_at": "2026-10-21T10:00:00Z"
}
```

约束：

- `factors` 固定 7 项（F1–F7），`score ≤ max_score`，权重上限 25/20/15/15/10/10/5。
- 总分 = 7 项得分之和（0–100），分档：`>=85 极佳`、`>=70 良好`、`>=55 一般`、`>=40 偏差`、`<40 劝退`。
- `top_factors` 取对总分贡献（score/max_score 降序，再按 score 降序）前 3 项。
- `impact`：`score/max_score >= 0.8` → `positive`；`<= 0.5` → `negative`；其余 `neutral`。
- `alerts` 元素结构固定为：
  `{"code": "RAINSTORM|GALE|PRESSURE_PLUNGE|...", "level": "danger|warning|info", "message": "中文提示", "forced": true}`
  `forced=true` 表示由规则强制触发、不得省略。强制提示至少覆盖：暴雨/雷雨（`RAINSTORM`，`level=danger`）、≥5 级风（`GALE`，`level=danger`，安全提示）、骤降 >8hPa/24h（`PRESSURE_PLUNGE`，`level=warning`，提示有效窗口 2–4h）。暴雨/雷雨时 `band` 必须为「劝退」。
- `species` 可选；合法值仅 `鲫鱼/鲤鱼/草鱼/鲢鳙`，未知值返回 422 `INVALID_SPECIES`；缺省给通用分。Agent 内部需先归一化，避免把自由文本直接透传。
- 劝退档 `advice` 必须为「今天不建议出钓」。
- F2 无 30 天分布时使用兜底：1005–1020hPa → 20 分；1000–1005 或 1020–1025hPa → 12 分；<1000 或 >1025hPa → 6 分。
- F5 降水口径补全（临时口径，待校准）：雷雨/暴雨（`is_thunderstorm=true` 或日降水 ≥50mm）→ 0 分并强制劝退；大雨 25–50mm → 3 分；中雨 5–25mm → 7 分；小雨 0.1–5mm → 10 分；无雨（晴/阴）→ 8 分；雨后 0–6 小时 → 7 分；连续晴热 >3 天 → 5 分（优先于无雨）。
- F3 区间补全（临时口径，待校准）：24h 变温 ≤3℃ 且日均温 15–28℃ → 15；3–6℃ → 10；6–8℃ → 6；>8℃ → 3；日均温不在 15–28℃ 时基础分 −3（下限 0）；昼夜温差 >12℃ 再 −3（下限 0）。
- F4 下风口/迎风岸 +3 修正**仅用于钓位级 `fish_score`**（Mock 钓点提供 `downwind` 元数据），不改变 `/api/fish-activity` 的通用 F4 得分；两者上限均为 15。≥5 级时得分 8–10.7m/s→3、≥10.8m/s→0。
- F6 冬季判定在 MVP 使用**日均气温 <5℃ 作为水温代理**（水温数据源为 M5），PRD 与测试按此口径；窗口内仍优先给 10 分。
- `best_windows` 数量按档位固定：极佳 / 良好 / 一般各 2 个（日出窗口、日落窗口），偏差 1 个（日出窗口），劝退 0 个。窗口使用 `Asia/Shanghai` 本地 `HH:MM`；日出窗口 = 日出前 1.5h 至日出后 1.5h，日落窗口 = 日落前 2h 至日落。

### 4.3 `GET /api/spots/recommend`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `lat` | float | 是 | WGS84 |
| `lon` | float | 是 | WGS84 |
| `species` | string | 否 | 目标鱼种 |
| `radius_km` | float | 否 | 默认 100，范围 1–150 |
| `limit` | int | 否 | 默认 5，范围 1–10 |
| `offset` | int | 否 | 默认 0，范围 0–20；在排序后的合格候选中跳过前 `offset` 个，用于“换一批” |

响应 `SpotRecommendationResponse`：

```json
{
  "user_location": {
    "wgs84": { "lat": 30.2741, "lon": 120.1551 },
    "gcj02": { "lat": 30.2756, "lon": 120.1598 }
  },
  "spots": [
    {
      "id": "mock_spot_001",
      "name": "青山水库",
      "water_type": "水库",
      "address": "示例地址",
      "location_gcj02": { "lat": 30.35, "lon": 120.02 },
      "entry_location_gcj02": { "lat": 30.349, "lon": 120.021 },
      "entry_precision": "entr_location",
      "distance_m": 42300,
      "drive_seconds_out": 2700,
      "drive_seconds_back": 3000,
      "drive_seconds_round_trip": 5700,
      "drive_minutes_one_way": 45,
      "fish_score": 72,
      "total_score": 81.5,
      "reasons": ["气压缓降，鱼口活跃", "往返约 95 分钟", "水库适配鲫鱼"],
      "navigation_url": "https://uri.amap.com/marker?position=120.021,30.349&name=青山水库"
    }
  ],
  "filtered": {
    "total_candidates": 9,
    "forbidden": 1,
    "unavailable": 0,
    "over_two_hours": 2,
    "eligible": 6,
    "returned": 5,
    "truncated_by_limit": 1,
    "evaluated": 8,
    "unevaluated": 0
  },
  "meta": {
    "mock_mode": true,
    "radius_km": 100,
    "round_trip_limit_seconds": 7200,
    "traffic_basis": "baseline_estimate",
    "generated_at": "2026-10-21T10:00:00Z"
  }
}
```

约束（对应 TechStack R2/R4/R5）：

- 单次高德周边搜索 `radius` 必须 ≤ 50000；负值/超限在代码层拒绝，不得静默降级；>50km 的覆盖由网格/同心环分片完成（Mock 可简化，但校验逻辑与去重逻辑必须存在）。
- 去程与回程分别取时长，过滤条件 `drive_seconds_out + drive_seconds_back <= 7200`；禁止用单程×2。
- 有 `entr_location` 时必须用入口坐标；缺失回退中心点并置 `entry_precision="center_fallback"`，UI 标注「端点精度较低」。
- 禁钓候选在返回前排除（Mock：名称黑名单 + 示例禁钓圆区；边界不明时保守排除）。
- 排序：`total_score` 降序；同分按往返时长升序。`drive_seconds_out/back/round_trip` 均为整数秒；`drive_minutes_one_way = round_half_up(drive_seconds_out / 60)`（四舍五入到整数分钟）。
- 往返均超过 2h 的候选不得出现在 `spots`，仅计入 `filtered.over_two_hours`。
- **真实模式召回口径**：高德 around 使用 `types=190204|190205`（自然地名-河流/湖泊）、`sortrule=distance`、`extensions=all`；只保留 `typecode` 为 190204/190205 的水体，`110202` 仅在名称含湖/河/江/溪等水体词时保留。餐饮、住宅、学校、商场、KTV、道路以及经营部/商行/公司/工厂/建材/沙石/五金/超市/商店/门市/批发/经销/商贸等商业 POI 一律排除。
- **真实模式评估口径**：候选先按直线距离排序；对最近 ≤100 个候选调用一次高德 `/v3/distance`（单终点、最多 100 起点）按回程时长重排；随后按批次（默认 `max(limit, 10)`，评估上限 30 个候选）对入围候选做去/回程分别路径精算，凑够 `offset+limit` 个合格候选即停（`offset+limit ≤ 30`）。批量距离仅用于排序，不替代去/回程精算；回程/去程值在基线路况下可能相同，但始终各调用一次。`unavailable` 表示路径规划失败，保守排除。
- **分页口径**：按 `total_score` 降序（同分按往返时长升序）排序后返回 `eligible[offset:offset+limit]`；`offset=0` 与旧版首屏一致。每次请求重新召回、评估并排序，不做缓存；因此两次请求之间若路况/天气变化，批次内容可能变化，仅保证单次响应内无重复。
- `truncated_by_limit = eligible - returned` 涵盖 `offset` 前被跳过的合格候选与窗口外剩余候选；`eligible = returned + truncated_by_limit` 不变式继续成立。`forbidden=0` 仅为未命中规则的事实字段，不代表“均可钓”。
- **有界并发与限速**：召回分片与路径规划共享并发信号量（`FISHAGENT_AMAP_CONCURRENCY`，默认 6）与请求起间隔（`FISHAGENT_AMAP_QPS`，默认 2）；Mock 不受影响。
- `filtered` 口径（固定顺序）：`total_candidates` = 召回并去重后的候选总数（进入过滤前的基数）；先禁钓过滤，再对评估窗口做往返过滤，最后排序截断。保持不变式：
  `total_candidates = forbidden + evaluated + unevaluated`；
  `evaluated = unavailable + over_two_hours + eligible`；
  `eligible = returned + truncated_by_limit`；
  `returned = len(spots)`。
  同时命中禁钓与超时的候选只计入 `forbidden`。`unevaluated` 为未进入评估窗口的候选；Mock 全量评估，因此 `unevaluated=0`，上述不变式退化为 `total_candidates = forbidden + over_two_hours + eligible`。

### 4.4 `POST /api/agent/chat`

请求：

```json
{
  "message": "今天这气压适合钓鱼吗？",
  "location": { "lat": 30.2741, "lon": 120.1551, "name": "杭州西湖" },
  "session_id": "demo-session-1",
  "history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

`message` 必填（1–500 字）；`location` 必填（MVP 不做地理编码，缺失返回 422 并提示前端获取定位）；`history` 最多保留最近 10 条。

响应 `ChatResponse`：

```json
{
  "reply": "……口语化结论，含推荐时段与理由……",
  "session_id": "demo-session-1",
  "mode": "llm",
  "tool_calls": [
    { "name": "get_fish_activity", "args": { "lat": 30.2741, "lon": 120.1551 }, "status": "ok" }
  ],
  "fish_activity": { "...": "同 4.2 响应，可为 null" },
  "spots": { "...": "同 4.3 响应，可为 null" },
  "ai_disclosure": "本内容由 AI 生成，仅供参考，不承诺渔获。"
}
```

约束：

- Agent 必须基于 **LangGraph** 构建状态图（意图识别 → 工具调用 → 组织回答）；LLM 通过 OpenAI 兼容接口调用。工具名固定为 `get_fish_activity` 与 `recommend_spots`，`tool_calls[].name` 必须使用这两个值。
- 无 `LLM_API_KEY` 或 LLM 调用失败时，必须自动降级为确定性路由（`mode="fallback"`），至少正确识别三类意图：鱼情/气压、附近钓位、时段建议，并调用相应工具。
- 工具失败时给出可读兜底话术，不得返回 500 堆栈；`tool_calls[].status` 标记 `ok|error`。
- 回复禁止「必上鱼/保证爆护」等承诺；不得原样播报天气预报。
- 延迟目标：Mock 模式 P95 ≤ 3s（不含真实 LLM）。

### 4.5 `GET /api/demo/config`（可选，用于前端）

返回 Mock 模式、默认演示坐标（杭州 30.2741/120.1551）、免责与 AI 标识文案，字段由小钱/小厚约定即可。

### 4.6 `POST /api/spots/species`（CR-04，推荐鱼种）

按钓位批量查询社区（小红书）网友分享的鱼种。**独立于钓位接口异步调用**：钓位列表先返回，本接口失败或超时只影响“推荐鱼种”一行，不影响钓位主流程。

请求：

```json
{
  "spots": [
    { "spot_id": "mock_spot_001", "name": "青山水库", "water_type": "水库", "address": "示例地址" }
  ]
}
```

约束：`spots` 1–10 项；`name` 1–120 字符且去空格后不得为空；`spot_id`/`water_type`/`address` 可为空。

响应 `SpeciesRecommendationResponse`：

```json
{
  "results": [
    {
      "spot_id": "mock_spot_001",
      "spot_name": "青山水库",
      "species": ["草鱼", "鲤鱼"],
      "has_recommendation": true,
      "source": "xiaohongshu",
      "source_label": "小红书（Mock）",
      "note": "来自小红书网友分享，仅供参考"
    }
  ],
  "provider": "mock",
  "degraded": false,
  "source_disclosure": "鱼种信息来自小红书网友分享，仅供参考，不承诺渔获；请出发前自行核实。",
  "generated_at": "2026-10-25T10:00:00Z"
}
```

口径：

- 结果顺序与请求顺序一一对应；同一 `name|water_type` 的重复项只查询一次（按 strip 后的 `(name, water_type)` 元组归一）。
- 请求字段上限：`spot_id` ≤ 64、`name` 1–120、`water_type` ≤ 40、`address` ≤ 200；`name` 去空格后不得为空。
- 鱼种经过别名归一、去重、白名单过滤，单钓位最多 4 个，且只返回已知鱼种。
- 查不到时 `species=[]`、`has_recommendation=false`、`source="none"`、`note="暂无相关鱼种推荐"`。
- **降级语义**：Provider 超时、抛异常（含配额异常）、返回结构异常时，一律返回 200 + **全部空结果** + `degraded=true`；不得返回 5xx。结构异常包括：外层非 list、行数与本次实际查询数（缓存未命中项数）不符、单行不是 list/tuple。降级响应不得混入缓存中的非空结果。
- **取消传播**：`asyncio.CancelledError` 必须向上传播，不得被降级逻辑吞掉。
- **缓存**：进程内按归一化 `(name, water_type)` 元组缓存，重启清空、多 worker 不共享；成功非空结果 TTL 为 `FISHAGENT_SPECIES_CACHE_TTL_SECONDS`（默认 3600），空结果与降级结果 TTL 为 `min(TTL, 300)`；降级结果同样写入负缓存，避免上游故障时逐请求重打；TTL=0 时不读不写；缓存条目上限 2000，超限先清过期再全清。
- `FISHAGENT_SPECIES_PROVIDER`：`mock` / `none` / `disabled`。留空时 Mock 模式用 `mock`，真实模式用 `none`；未知值告警后按 `none`；真实小红书适配器实现 `SpeciesProvider` 后在此注册。
- **配额异常口径（2026-10-25 裁决）**：Provider 配额耗尽按本节降级为 200（不返回 429）；`providers/base.py` 中「配额异常应返回 429」的通用注释不适用于本端点。
- 前端必须标注来源与“仅供参考”，不得承诺渔获；`degraded=true` 时文案必须与「暂无相关鱼种推荐」区分（如「鱼种信息暂不可用，仅供参考」）。

## 5. Mock 数据要求

- **天气 Mock**：以 `(lat, lon, date, at)` 为种子确定性生成。五档通过查询参数 `scenario` 触发：`excellent`→极佳、`good`→良好、`fair`→一般、`poor`→偏差、`no_go`→劝退；未提供时按种子生成默认场景。必须包含气压 24h/3h/6h 变化、气温变温、风速、降水、云量、日出日落。`no_go` 场景至少包含暴雨/雷雨或 ≥5 级风，确保 `band=劝退`。
- **POI Mock**：围绕用户坐标生成 ≥ 8 个候选水域（水库/湖泊/河流/野塘），包含：2 个往返 ≤2h、1 个单程 >1h 但往返 ≤2h、2 个往返 >2h、1 个禁钓区（名称含「一级保护区」或落入示例禁钓圆区）、1 个缺入口坐标的候选；结果确定性可复现。
- **LLM 兜底**：不依赖外部网络；基于意图关键词与工具结果拼接中文回答。
- **鱼种 Mock**：以 `name|water_type` 为种子确定性生成 1–3 个鱼种；约 1/5 的水域返回空列表，用于覆盖“暂无相关鱼种推荐”路径；`source_label` 必须含 `Mock` 标识。

### 5.1 测试注入点（小测使用）

- Provider 通过 FastAPI 依赖函数获取：`get_weather_provider()`、`get_geo_provider()`（位于 `fishagent/deps.py` 或 `providers/__init__.py`，由小钱固定导出）。测试使用 `app.dependency_overrides[...]` 注入伪 Provider，用于 radius 上限 spy、往返时长构造、入口坐标缺失等场景。
- 规则引擎为纯函数：`compute_fish_activity(weather, now, species=None)`，测试可直接构造 `WeatherSnapshot`，不依赖 HTTP。
- 鱼种 Provider 通过 `get_species_provider()` 获取（`fishagent/deps.py`）；测试可用 `app.dependency_overrides[get_species_provider]` 注入伪 Provider，缓存可用 `reset_species_cache()` 清理。
- 钓位候选构造可使用 `fixtures/` 下场景文件；小产提供演示数据，小测可另建测试专用 fixture，不修改他人文件。

## 6. UI 契约（小厚）

- 页面 `/`：位置区（浏览器定位按钮 + 手动经纬度输入）→ 鱼情卡（总分、档位、Top3 因子、最佳时段、风险提示）→ 钓位列表（名称、类型、单程/往返时间、理由、推荐鱼种、导航链接）→ 对话区（示例问题快捷按钮：今天气压适合钓鱼吗 / 附近哪里野钓好 / 明早几点去最好）。
- 钓位卡在理由下方显示“推荐鱼种：…”并标注来源与“仅供参考”；无结果显示“暂无相关鱼种推荐”。鱼种异步加载，不得阻塞钓位渲染。
- 必须可见：`AI 生成 · 仅供参考` 标识、免责声明（不承诺渔获、遵守当地禁钓规定）、Mock 模式提示。
- 不得在前端出现任何 Key；不得直接调用高德 Web 服务。
- 移动端可用（宽度 375px 起不横向滚动）。

## 7. 运行与验证

```bash
# 安装（使用显式解释器路径）
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -e "backend[dev]"

# 启动
cd backend
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn fishagent.main:app --host 127.0.0.1 --port 8000

# 测试
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m pytest backend/tests -q

# 代码检查
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m ruff check backend
```

依赖（`backend/pyproject.toml`）：`fastapi`、`uvicorn[standard]`、`httpx`、`pydantic>=2`、`pydantic-settings`、`langgraph>=1.0,<2`、`openai`；开发依赖：`pytest`、`pytest-asyncio`、`ruff`。

## 8. 完成定义（每个交付者自查）

- [ ] 改动仅限自己所有权目录，未提交真实密钥。
- [ ] 已按本契约字段实现/消费，未私自改名。
- [ ] 已运行相关测试或手工验证，并在群内报告「路径 + 命令 + 结果」。
- [ ] 有未决问题时明确写出「问题 / 影响 / 需要谁决策」，不静默跳过。

## 9. 变更记录

| 版本 | 日期 | 变更 | 原因 |
|---|---|---|---|
| v1.0 | 2026-10-21 | 初版契约，确定目录所有权、端点与字段 | 启动 MVP 并行开发 |
| v1.1 | 2026-10-21 | 明确 `alerts` 对象结构、`filtered` 统计不变式、统一 422、时区口径、Mock `scenario`、Provider 注入点；补全 F3/F4/F6 边界 | QA 计划 A-02~A-05 与实现确定性需要 |
| v1.2 | 2026-10-21 | 裁决 F2 兜底区间外、F5 降水口径、`best_windows` 数量、工具名、单程分钟取整 | PRD 残留待裁决项；保证 PRD、实现与测试同口径 |
| v1.3 | 2026-10-22 | 真实模式水体类型召回、回程批量预筛、分批精算、有界并发/限速；`filtered` 增补 `unavailable/evaluated/unevaluated` | 真实高德 100km 串行精算超时且关键词召回混入业务 POI |
| v1.5 | 2026-10-25 | 新增 `POST /api/spots/species`（推荐鱼种）与 `SpeciesProvider` 注入点；明确空结果、降级与缓存口径 | CR-04：钓位卡展示小红书网友推荐鱼种 |
| v1.6 | 2026-10-25 | 同步第二轮修复口径：降级必为全空、结构异常整体降级、负缓存 300s、缓存键归一化、`CancelledError` 上抛；配额异常裁决为降级 200；补物种相关配置与注入点 | CR-04 实现收敛 |
