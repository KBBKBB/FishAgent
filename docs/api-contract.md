# FishAgent MVP 接口与工程契约 v1.8

> 本契约是并行开发的唯一字段依据。字段改名或语义变更必须先通知协调者（小项）并更新本文件。
>
> v1.1（2026-10-21）：澄清 `alerts` 结构、`filtered` 统计口径、时区规则、422 统一错误体、Mock 五档触发方式与测试注入点；补充 F3/F4/F6 边界口径。
> v1.2（2026-10-21）：裁决 F2 兜底区间外、F5 晴/雨口径、`best_windows` 数量、Agent 工具名、单程分钟取整。
> v1.3（2026-10-22）：真实模式钓位改为水体类型召回 + 回程批量预筛 + 最近候选分批精算；`filtered` 增补 `unavailable/evaluated/unevaluated`，新增有界并发与限速配置。
> v1.4（2026-10-23）：`GET /api/spots/recommend` 新增 `offset`（默认 0，0–20）用于“换一批”；评估目标改为 `offset+limit`（仍受 30 上限），返回 `eligible[offset:offset+limit]`；`eligible = returned + truncated_by_limit` 不变。商业 POI 过滤补充经营部/建材/商贸等后缀；评估批次改为 `max(limit, 10)`。
> v1.5（2026-10-25）：新增 `POST /api/spots/species`（推荐鱼种）与 `SpeciesProvider` 注入点；明确空结果、降级与缓存口径。
> v1.6（2026-10-25）：同步第二轮修复口径——降级必为全空、结构异常整体降级、负缓存 300s、缓存键归一化、`CancelledError` 上抛；补物种相关配置与注入点。
> v1.7（2026-10-26）：Phase 2 三阶段并发化 + 加深截止时间；页预算 6→12、LLM 调用 4→2；LLM 抽取计入每日配额并按 4.6 降级；未注册 API 路径的违规方法改为 404。
> v1.8（2026-10-27）：新增 `POST /api/agent/identify-fish`（图片识别鱼种，CR-05）；见 4.7 与 `cr05-fish-identification.md`。
> v1.9（2026-10-27）：`/api/spots/recommend` 增加 180s 结果缓存（按四舍五入坐标/半径/limit/物种/offset 分键）；单候选去程与回程合并为一次调用（真实高德 provider 忽略 `direction`），评估期调用数减半；冷启动 14.8s → 8.1s，热命中 <20ms。
> v2.0（2026-10-28）：4.7 错误码细分——新增 415 `IMAGE_EMPTY` / `IMAGE_CORRUPT`、503 `VISION_UNAVAILABLE`；`VisionUnavailable` 按失败原因（超时 / 上游错误 / 空回答 / 无法解析）给出不同文案，不再把服务中断说成「图片无法识别」或「不支持的格式」。同时接受 `MPO`（iPhone HDR / 人像照片的 JPEG 变体），此前会被误判为不支持的格式。
> v2.2（2026-10-28）：对话里的照片缩略图可点开全屏大图查看（1×–4× 缩放、双击/双指捏合、拖动、Esc 或点遮罩关闭、关闭后焦点回到缩略图）。纯前端交互，接口不变；图片地址现造、关闭即释放，仍不落盘。
> v2.3（2026-10-29）：4.6 `bing` Provider 改为**只搜地名**（原「{地名} 钓鱼」使 cn.bing 对每条查询都退化为字典页，召回率 0）；新增退化检测；新增 `source="typical"`——查过但没查到时按水域类型给参考值，文案与样式必须与「引用到具体来源」区分，`degraded` 与 `NullSpeciesProvider` 不给参考值。
> v2.4（2026-10-29）：4.6 修复前后端超时赛跑——抓页阶段补上截止时间（此前能让整批被外层取消），前端 `SPECIES_TIMEOUT_MS` 4500→7500，晚于后端预算 + 网络往返。
> v2.5（2026-10-29）：4.2 `water_depth` 改为由气温基准层 + F1/F2/F3/F4/F5/F7 修正推导，不再只看气温三分支（原实现使 5–32℃ 的每条请求返回同一句话）；`suitable_species` 与 `water_depth` 改读同一份决策计划，两者不再互相矛盾；劝退档不给水深策略、前端隐藏鱼种行。字段类型与位置不变。
> v2.6（2026-10-29）：新增 4.5b `GET /api/geo/search`、`GET /api/geo/nearby`（位置选择器）。Step 1 主路径改为「搜地名 / 看附近」，经纬度输入收进「高级」折叠区；新增 `PlaceCandidate` / `PlaceSearchResponse` schema。
> v2.6b（2026-10-29）：定位前检查 `isSecureContext`，非 https 时如实说明「不是权限问题」；定位成功后收起选择器列表并覆盖之前的选择。接口不变。
> v2.7（2026-10-30，已被 v2.7c 回退）：8018 曾改为 HTTPS 并新增 `serve-https.bat`。
> v2.7b（2026-10-30）：新增 `scripts/start-fishagent.vbs` 并装入 Windows 启动文件夹，登录后自动以隐藏方式拉起服务；仓库搬家需同步更新 `D:\FishAgent\repo-root.txt`。接口不变。
> v2.7c（2026-10-30）：8018 与开机自启改回**明文 HTTP**（`serve.bat`）。手机端因此没有定位与 Service Worker，页面如实提示；`serve-https.bat` 保留备用。接口不变。
> v2.8（2026-10-30）：新增 4.8 静态资源缓存与版本提示。shell 资源改 `no-cache`，`/health` 增加内容哈希 `build` 字段并注入 `index.html`，页面轮询发现新版本后提示、由用户自己点刷新。`/health` 响应新增 `build`（向后兼容的增量字段）。
> v2.9（2026-10-30）：钓位推荐不再总是「离你最近的几个」——评估池按方向扇区 × 距离环取样，分页前做间距交错，同名水体先去重；`meta` 增加 `selection_strategy` / `min_separation_m` / `separation_relaxed` 三个增量字段。
> v2.10（2026-10-30）：搜索半径改为**环带**。新增 `min_radius_km`（默认 0，旧调用行为不变），前端改为 0–10 / 10–50 / 50–100 / 100–150 四档；`filtered` 增加 `within_min_radius`，`meta` 增加 `min_radius_km`。
> v2.12（2026-10-31）：新增 4.9 `POST /api/agent/transcribe`（语音输入）。浏览器采集 16 kHz 单声道 PCM 上传，后端用 Vosk 离线识别；返回文本但**不自动发送**。失败分为 `SPEECH_EMPTY`/`SPEECH_FAILED`/`SPEECH_UNAVAILABLE`，不得把系统故障说成用户没说清。**不新增第三方调用**，前端仍零密钥。
> v2.11（2026-10-30）：4.4 新增 `bait` 意图（饵料/窝料/味型/钓法），由 `core/bait.py` 的确定性表作答，不依赖 LLM 与工具；查询中的鱼种改按全量 `KNOWN_SPECIES` 解析（原自带四鱼种表 + 鲫/鲤单字别名，使「白条用什么饵料」落到通用指南）。4.6 结果新增 `baits`，逐项与 `species` 对应。4.5b 约定定位成功后清空地名输入框。`baits` 为向后兼容的增量字段。
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
| `FISHAGENT_SPECIES_PROVIDER` | 空 | `mock` / `bing` / `none` / `disabled`；留空时 Mock 模式用 `mock`，真实模式用 `none`；`bing` 走 Bing 搜索（Phase 1，见 4.6）；未知值告警后按 `none` |
| `FISHAGENT_SPECIES_TIMEOUT_SECONDS` | `4.0` | 鱼种查询超时，范围 0 < x ≤ 30 |
| `FISHAGENT_SPECIES_CACHE_TTL_SECONDS` | `3600` | 鱼种结果缓存秒数，范围 0–86400；0 表示不读不写缓存 |
| `FISHAGENT_SPECIES_PAGE_FETCH` | `false` | 是否抓取搜索结果页正文（Phase 2）；无 LLM Key 时仅做白名单匹配 |

`.env.example` 只放占位符，严禁真实密钥入库。

## 4. 端点契约

### 4.1 `GET /health`

```json
{ "status": "ok", "version": "0.1.0", "build": "14c85f31a06a", "mock_mode": true }
```

- `version`：API 版本，人工维护，不随部署变化。
- `build`：**当前服务端 H5 资源的构建号**——对 `index.html` / `app.js` / `styles.css` / `sw.js` / `manifest.webmanifest` 内容做的 sha256 前 12 位（CRLF/LF 归一化，避免换行风格差异被当成新版本）。前端据此判断自己跑的是不是最新版。
- 响应头固定 `Cache-Control: no-store`：这个端点正是前端用来判断"我是不是旧版"的，缓存住的答案会让它永远轮询到那个旧答案。

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
  "water_depth": "先钓 2–2.5m 滩口，无口再试 2.5–3m 斜坡（有风增氧可钓浅）",
  "suitable_species": ["鲫鱼", "鲤鱼", "草鱼"],
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
- `water_depth` 生成规则（v2.5 起）——**没有任何真实水深数据参与，全是气温代理 + 天气因子推出的建议**，所以文案必须是「先钓 X，无口再试 Y」这种带退路的形状，不得写成确定的深度结论：
  - **基准层**由气温（水温代理）取格：`<5℃ → 4–5m`、`<12℃ → 3–4m`、`<20℃ → 2.5–3m`、`20–28℃ → 2–2.5m`、`28–32℃ → 1.5–2m`、`>32℃ → 1–1.5m`。
  - **修正**（各 ±1 格，净位移夹在 ±2 格内）：F5 雨后 ≤6h → 浅（鱼靠边觅食）；F1 气压缓降 −2~−8hPa → 浅（活跃上浮），24h 气压升 >8hPa → 深（压口沉底）；F2 气压 >1025hPa → 深，<1000hPa → 浅；F7 云量 >70% → 不变（仅记录），<30% 且气温 ≥20℃ → 深（强光避明）；F4 2–3 级风在暖水（≥12℃）→ 浅（增氧+遮蔽人影）、在冷水 → 深（风让浅层更冷），≤1 级风 → 深；F3 昼夜温差 >12℃ → 深；盛夏正午（6–8 月 11:00–15:00）且气温 >28℃ → 深；5–12℃ 且非阴天 → 浅（浅水升温快）。
  - **同一物理现象在不同水温下方向相反**：风在暖水指向浅、在冷水指向深；阳光在暖水指向深（避强光）、在冷水指向浅（升温）。不得复用单一季节的推理。
  - **原因标注**只在净位移非零时出现，取与净位移同向、且解释力最强的一项（排序：雨后 > 气压 > 高温 > 温差 > 浅水升温 > 冷水遇风 > 无风 > 强光 > 阴天 > 有风）。净位移为零时**不得**标注单因，否则会解释它并未造成的移动。
  - **劝退档不给水深策略**，固定返回「今日不建议出钓，无水深策略」。在同一个屏幕上说「今天别去」又告诉你钓多深是自相矛盾的，且推导出的原因还会与强制预警打架（雷雨天被算成「气压缓降鱼活跃上浮」）。
- `suitable_species` 生成规则（v2.5 起）——与 `water_depth` 读**同一个 `_depth_plan`**，两条建议不会再互相矛盾（此前各自只看气温，水深改用其他因子后会出现「钓 4–5m 深水」却推荐暖水鱼的情况）：
  - **浅水且气温 ≥22℃**（`plan.index ≤ 2`）→ 「草鱼、鲢鳙、鲤鱼」（活跃的暖水鱼领先）。
  - **中浅层且气温 ≥15℃**（`index ≤ 3`）→ 「鲫鱼、鲤鱼、草鱼」。
  - **其余（冷水 / 深水）** → 「鲫鱼、鲤鱼」（耐寒底层鱼）。
  - **请求的合法 `species` 永远排第一**，且不因与天气不符而被剔除——用户问的是他要钓的鱼，悄悄丢掉等于回答了另一个问题。
  - **劝退档**：列表仍保持非空（契约硬要求），返回请求鱼种或「鲫鱼」占位；前端**隐藏该行**，与隐藏水深策略同一理由——同一屏说「今天别去」又列出「适配鱼种」，会被读成「今天适合钓这个」。
- `best_windows` 数量按档位固定：极佳 / 良好 / 一般各 2 个（日出窗口、日落窗口），偏差 1 个（日出窗口），劝退 0 个。窗口使用 `Asia/Shanghai` 本地 `HH:MM`；日出窗口 = 日出前 1.5h 至日出后 1.5h，日落窗口 = 日落前 2h 至日落。

### 4.3 `GET /api/spots/recommend`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `lat` | float | 是 | WGS84 |
| `lon` | float | 是 | WGS84 |
| `species` | string | 否 | 目标鱼种 |
| `radius_km` | float | 否 | 外圈半径，默认 100，范围 1–150 |
| `min_radius_km` | float | 否 | 内圈半径，默认 0，范围 0–150。与 `radius_km` 构成**环带**，见下 |
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
- **搜索范围是环带，不是上限**（2026-10-30）：`min_radius_km`~`radius_km` 表示**只**返回落在这个区间内的钓位，内圈同样排除。`min_radius_km` 默认 0，因此不传时行为与旧版「半径上限」完全一致。**不做内圈排除的话，用户想看"远一点"时，返回的还是那几个最近的**——而最近的往往正是分数最高的，区间就白设了。
  - 违例（`min_radius_km >= radius_km`，或越界）返回 422 `INVALID_RADIUS_RANGE`。空环带（如 50~50）视为笔误而非查询。
  - 内圈排除**发生在禁钓过滤与取样之前**，因此 `filtered.forbidden` 等计数描述的都是环带内的情况，不会把用户按距离排除掉的候选算进禁钓数。
  - 缓存键包含 `min_radius_km`：`10~50` 与 `0~50` 是两次不同搜索，共用一个键会让其中一次静默失效。
  - **可能返回空**：环带内若不存在 2 小时内可往返的水域，结果就是空列表。这是「往返 ≤ 2 小时」这条硬规则的结果，不是搜索失败。实测成都 20km 以外没有任何水域满足该条件，因此 50–100、100–150 两档在成都稳定为空；前端文案会说明是「这段距离的水域往返都超过 2 小时」，不写成「换个位置试试」。
- 排序：`total_score` 降序；同分按往返时长升序。`drive_seconds_out/back/round_trip` 均为整数秒；`drive_minutes_one_way = round_half_up(drive_seconds_out / 60)`（四舍五入到整数分钟）。
- 往返均超过 2h 的候选不得出现在 `spots`，仅计入 `filtered.over_two_hours`。
- **真实模式召回口径**：高德 around 使用 `types=190204|190205`（自然地名-河流/湖泊）、`sortrule=distance`、`extensions=all`；只保留 `typecode` 为 190204/190205 的水体，`110202` 仅在名称含湖/河/江/溪等水体词时保留。餐饮、住宅、学校、商场、KTV、道路以及经营部/商行/公司/工厂/建材/沙石/五金/超市/商店/门市/批发/经销/商贸等商业 POI 一律排除。
- **同名水体先去重**（2026-10-30）：高德把一条河拆成多个 POI（`府河`、`府河(锦江)`、`锦江`），若不去重，一页会出现三张都叫「府河」的卡片，等于没有选择。去重在**评估之前**对候选池做，比较时剥掉括号与空格；这样既不会把配额浪费在同一个水域上，也不会出现"测了三条同名河、只剩一条能进页面"。实测成都 50km 首屏原本 5 张里有 3 张同名。
- **真实模式评估口径**：候选先按直线距离排序；对最近 ≤100 个候选调用一次高德 `/v3/distance`（单终点、最多 100 起点）按回程时长重排；随后按批次（默认 `max(limit, 10)`，评估上限 30 个候选）对入围候选做去/回程分别路径精算，凑够 `offset+limit` 个合格候选即停（`offset+limit ≤ 30`）。批量距离仅用于排序，不替代去/回程精算；回程/去程值在基线路况下可能相同，但始终各调用一次。`unavailable` 表示路径规划失败，保守排除。
- **评估池不只看最近的**（2026-10-30）：若直接取距离最近的一批来评估，远一点但更好的钓位永远没被测量过，页面只会反映用户脚下那一小圈。因此评估池会按**方向扇区 × 距离环**取样（`_sector_balanced_pool` / `_interleave_sectors`），下限 30 个、按评估批量向上取整。注意只按扇区平衡**不够**：每个扇区取到的仍是"该方向最近的几个"，而城市周边最近的点天然围成一圈——实测按扇区平衡后 150km 搜出 1246 个候选，评价完的 28 个仍全在 11km 内。距离环必须一起轮转。
- **散布与成本的取舍（实测记录）**：把评估池放大到 40、按距离环铺满 150km，在成都实测要 **3 倍**路径调用（10 → 30 次）却只返回 8 个钓位（因为远环大量超 2 小时），属于"花三倍代价拿更少结果"，已放弃。当前策略保持池深 30 与旧版一致，仅改变**取谁**：默认 50km 首屏的散布从 1.1–5.5km 提升到 1.1–10.8km，评估次数不变。150km 档因为要够到远处会用到 30 次上限。
- **分页口径**：先对**全部**合格候选按间距规则交错排序（`_interleave_by_spacing`），再切片 `[offset:offset+limit]`。交错只决定"谁进这一页"，页内仍按 `total_score` 降序，卡片顺序仍承诺"最好的在前"。若先切页再散布，页大小之外没有可选余地，且第 2 页可能重复第 1 页的钓位。每次请求重新召回、评估并排序，不做缓存；因此两次请求之间若路况/天气变化，批次内容可能变化，仅保证单次响应内无重复。
- **散布字段**：`meta.selection_strategy`（当前固定 `sector_greedy_spacing`）、`meta.min_separation_m`（这一页**实际达成**的最小两两间距，不是目标值）、`meta.separation_relaxed`（目标间距达不到、已逐步放宽）。目标间距随搜索半径缩放，夹在 3–25km。
- `truncated_by_limit = eligible - returned` 涵盖 `offset` 前被跳过的合格候选与窗口外剩余候选；`eligible = returned + truncated_by_limit` 不变式继续成立。`forbidden=0` 仅为未命中规则的事实字段，不代表“均可钓”。
- **有界并发与限速**：召回分片与路径规划共享并发信号量（`FISHAGENT_AMAP_CONCURRENCY`，默认 6）与请求起间隔（`FISHAGENT_AMAP_QPS`，默认 2）；Mock 不受影响。**QPS=2 是高德账号的硬限制**，实测调高会返回 `CUQPS_HAS_EXCEEDED_THE_LIMIT`，因此提高并发数对总耗时无效（实测 6/12/20 并发均为 14s 量级）。
- **去程/回程只算一次**：真实 `AMapGeoProvider.estimate_drive_seconds` 忽略 `direction` 参数，去程与回程是对同一 origin/destination 的完全相同请求。服务层因此只发一次（`direction_affects_result=False`），往返时间按 2 倍展示。Mock 区分去/回程（`_TRAVEL_FACTORS`），故保留两次调用。
- **结果缓存**：`GET /api/spots/recommend` 按 (坐标四舍五入 3 位、radius_km、limit、species、offset) 缓存 180s（`_CACHE_TTL_SECONDS`），LRU 上限 256 条。车程是基线估算，几分钟内变化在噪声范围内。实测冷启动 14.8s → 8.1s，热命中 <20ms。
- `filtered` 口径（固定顺序）：`total_candidates` = 召回总数（进入任何过滤前的基数）；先按内圈半径排除，再禁钓过滤，再对评估窗口做往返过滤，最后排序截断。保持不变式：
  `total_candidates = within_min_radius + forbidden + evaluated + unevaluated`；
  `evaluated = unavailable + over_two_hours + eligible`；
  `eligible = returned + truncated_by_limit`；
  `returned = len(spots)`。
  `unevaluated` 含被省略的去重候选：它们被召回了但没有任何车程估算，正是"未评估"的含义。
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
- 无 `LLM_API_KEY` 或 LLM 调用失败时，必须自动降级为确定性路由（`mode="fallback"`），至少正确识别四类意图：鱼情/气压、附近钓位、时段建议、饵料/钓法，并调用相应工具。
- **饵料意图不依赖工具，也不依赖 LLM**（v2.11）：`bait` 意图从 `core/bait.py` 的确定性表作答，`tool_calls` 可为空。理由与鱼种接口相同——关掉 LLM 时仍要能回答；同一种鱼每次必须得到同一套方案。饵料与鱼情同时被问到时，两者都要出现在回复里，总句数仍受 5 句上限约束。
- **查询里的鱼种必须按全量 `KNOWN_SPECIES` 解析**（v2.11，实故障）：原实现自带的鱼种表只有鲫/鲤/草/鲢鳙四种，且别名字段只有「鲫」「鲤」，于是「鲫鱼用什么饵料」靠单字别名**碰巧**命中，「白条用什么饵料」「翘嘴用什么饵料」「罗非鱼用什么饵料」则一个都匹配不到，直接落到「我可以帮你分析……」。现在与 `/api/spots/species` 共用 `core/species.py` 的同一张表。误匹配由「最长优先」保证：「鲤鱼」先于「鲤」。
- **鱼种超出鱼情模型范围时不得传参**（v2.11）：`/api/fish-activity` 只接受鲫/鲤/草/鲢鳙，传别的会 422。「白条今天适合钓吗」应改为查询**通用**鱼情并照常回答，而不是让工具调用失败——`tool_calls[].args` 中不应出现该物种。
- 工具失败时给出可读兜底话术，不得返回 500 堆栈；`tool_calls[].status` 标记 `ok|error`。
- 回复禁止「必上鱼/保证爆护」等承诺；不得原样播报天气预报。
- 延迟目标：Mock 模式 P95 ≤ 3s（不含真实 LLM）。

### 4.5 `GET /api/demo/config`（可选，用于前端）

返回 Mock 模式、默认演示坐标（杭州 30.2741/120.1551）、免责与 AI 标识文案，字段由小钱/小厚约定即可。

### 4.5b `GET /api/geo/search`、`GET /api/geo/nearby`（位置选择器）

Step 1 的定位入口。经纬度对普通用户没有意义——钓鱼的人记得住「青龙湖」，记不住 30.6570——所以主路径改成「搜地名」和「看看附近」，坐标输入收进「高级」折叠区。

**`GET /api/geo/search?q=<关键词>&limit=8`**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `q` | string | 是 | 1–60 字符，允许中文 |
| `limit` | int | 否 | 默认 8，范围 1–20 |

**`GET /api/geo/nearby?lat=&lon=&radius_km=30&limit=8`**：`lat`/`lon` 必填（WGS84），`radius_km` 范围 1–50。

两者共用响应结构 `PlaceSearchResponse`：

```json
{
  "results": [
    {"name": "三岔湖景区", "address": "望湖北街178号", "lat": 30.2794, "lon": 104.2669, "kind": "湖泊", "distance_m": null}
  ],
  "query": "三岔湖",
  "resolved": true
}
```

约束：

- **坐标一律 WGS84**。高德只有 GCJ-02，转换只在 provider 边界发生（`core/coords.py`），上层看到的只有一种基准；泄漏会让用户静默偏出几百米。
- **`resolved` 必须区分「查过了没有」和「这个源不会查」**。`resolved=false` 表示 provider 不支持该方法或上游失败，前端据此引导到手动坐标，而不是告诉用户「没有这个地方」——把服务故障说成用户输入错误是我们在别处已经修过一次的同类错误。
- **失败降级为 200 + 空列表**，不返回 5xx：手动坐标表单仍然可用，选择器挂掉不该让整页失败。
- **搜索结果水域优先**：`/v3/place/text` 返回的是**大类前缀**（`110200` 风景名胜、`110203` 水库、`110000` 景区），不是 `around` 搜索的叶子码（`190204` 河流、`190205` 湖泊）。写成叶子码匹配时线上**一条都匹配不上**，排序会静默失效。判定用前缀 + 名称水体词，并排除桥/码头/收费站/闸/堤这类「通向水域但不是钓点」的地名。
- `kind`：水域结果填具体类型（湖泊/河流/水库/野塘），文字搜索结果若判定为水域也填类型，否则填 `place`。
- 结果经过名称非空与坐标范围校验；排序稳定，同组内保留高德的原始相关度顺序。
- **前端定位需要 HTTPS**（2026-10-29 实故障）：`navigator.geolocation` 只在安全上下文可用，而**非安全上下文下浏览器把「根本不提供定位」也报成 `PERMISSION_DENIED`（code 1）**，与用户真的点了拒绝完全无法区分。前端必须**先检查 `window.isSecureContext`**，为 false 时直接说明「http 地址不支持定位，不是权限问题」，不得沿用「权限被拒绝」的文案——否则用户会去找一个永远改不好的开关。
- **部署（2026-10-30 最终）**：8018 日常走**明文 HTTP**，用仓库根的 `serve.bat` 启动，开机自启同此。因此在手机访问 `http://<LAN-IP>:8018` 时**定位按钮不可用**（只有地名搜索、附近水域、手动坐标可用），Service Worker 也不注册——这是权衡后接受的代价，见 `docs/cr03-lan-https-runbook.md` §5。需要定位与 PWA 时改用 `serve-https.bat`（mkcert IP SAN 证书，SAN 覆盖 `localhost`/`127.0.0.1`/`192.168.31.68`，有效期至 2029-01-24；证书按 IP 签发，主机 IP 变了要重签）。
- 界面对上述限制必须**如实说明**：明文时提示「改用 https / 地名搜索」，不得暗示是权限问题。
- 定位成功时优先级最高，直接覆盖此前的搜索/点选结果，并收起选择器列表。
- **定位成功后必须清空地名输入框**（v2.11）：输入框是「待搜索的关键词」，不是「当前地点」——当前地点由 Step 1 的摘要行负责显示。位置已经换成定位点而输入框还留着上一个地名，界面就自相矛盾了。清空只针对定位按钮这条路：用户主动搜索、从列表点选时输入框正是他正在操作的对象，抹掉只会让人重新输入。

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
      "note": "来自小红书网友分享，仅供参考",
      "baits": [
        {
          "species": "鲤鱼",
          "main": "甜香谷物味商品饵，或嫩玉米、红薯块",
          "nest": "老玉米、麦粒提前做窝，窝量宜大",
          "tip": "鲤鱼谨慎，钓点保持安静，中鱼后迅速带离窝点",
          "generic": false
        }
      ]
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
- **四种结果必须互相可分辨**，`source` 是唯一判据，调用方不得靠文案或码值猜测：
  | 情况 | `species` | `has_recommendation` | `source` | `note` |
  |---|---|---|---|---|
  | 引用到具体来源 | 非空 | true | `xiaohongshu` / `bing` | 来自该来源 |
  | 查过但没查到，按水域类型给参考 | 非空 | true | `typical` | 「未查到该水域的具体鱼种，以下为同类水域常见鱼种，仅供参考」 |
  | 查过且该水域类型未知 | `[]` | false | `none` | 「暂无相关鱼种推荐」 |
  | 降级（上游失败） | `[]` | false | `none` | 不变 |

  `typical` **不是引用来源**：它是「同类水域常见鱼种」，不是这个水域的实测或网友报告。前端必须用不同措辞呈现（`参考：同类水域常见鱼种`），弱化样式，不得让它看起来像查到了具体依据。
- **哪些情况不给参考值**：`degraded=true`（上游本身失败，给什么都等于宣称我们查过）、以及 `resolves_empty=False` 的 provider（如 `NullSpeciesProvider`——功能被主动关闭，空结果不是「没查到」）。这两种情况一律 `species=[]`。`water_type` 为空或不属于已知类型时也不推导，宁可什么都不说。
- **未知 API 路径的方法语义**：`/api/*` 兜底路由对所有方法生效。路径未注册返回 404 `NOT_FOUND`（`接口不存在：…`）；路径已注册但方法不匹配返回 405 `METHOD_NOT_ALLOWED`（`接口不支持该请求方法：…`）。禁止让未匹配请求落到静态目录挂载上，那会返回 Starlette 默认英文 `Method Not Allowed`，掩盖真实原因。
- **降级语义**：Provider 超时、抛异常（含配额异常）、返回结构异常时，一律返回 200 + **全部空结果** + `degraded=true`；不得返回 5xx。结构异常包括：外层非 list、行数与本次实际查询数（缓存未命中项数）不符、单行不是 list/tuple。降级响应不得混入缓存中的非空结果。
- **取消传播**：`asyncio.CancelledError` 必须向上传播，不得被降级逻辑吞掉。
- **缓存**：进程内按归一化 `(name, water_type)` 元组缓存，重启清空、多 worker 不共享；成功非空结果 TTL 为 `FISHAGENT_SPECIES_CACHE_TTL_SECONDS`（默认 3600），空结果与降级结果 TTL 为 `min(TTL, 300)`；降级结果同样写入负缓存，避免上游故障时逐请求重打；TTL=0 时不读不写；缓存条目上限 2000，超限先清过期再全清。
- `FISHAGENT_SPECIES_PROVIDER`：`mock` / `bing` / `none` / `disabled`。留空时 Mock 模式用 `mock`，真实模式用 `none`；未知值告警后按 `none`。
- **`bing` Provider（Phase 1）**：以**水域名本身**查询 cn.bing（不带「钓鱼」等第二词），只解析结果页的标题与摘要，用 `core/species.py` 的白名单与别名做匹配；不抓取目标页正文、不调用 LLM、不使用 Cookie。命中则返回鱼种，未命中或遭遇验证码/非 200/网络异常时返回空列表（`has_recommendation=false`）。`source_label` 为「Bing 搜索」。
  - **查询式必须只用地名（2026-10-29 实故障，勿回退）**：原实现用「{水域名} 钓鱼」。实测 cn.bing 只要追加任何第二个中文词，就不再匹配水体，而是退化为对首字返回字典词条——「三岔湖 钓鱼」返回「三（拼音：sān）是汉语一级通用汉字」，「三岔湖 鱼 / 渔获 / 钓鱼攻略 / "三岔湖 钓鱼" / 三岔湖 钓鱼 -汉字」全部返回同一个字典页。只搜「三岔湖」才返回景区页、湖泊官网与本地文章，而这些页面正文里确实有鱼种。旧查询式让**每一条**查询都命中最坏路径，召回率为 0。
  - **退化可识别**：用结果**标题**判定（摘要段落只有 2–4/16 命中且每次浮动，不足以设阈值）。退化时 8/10 条标题是字典词条，正常时 0 条；判定为退化则记 `warning` 并返回空列表，避免把「Bing 没匹配上地名」误当成「这个水域没有鱼」。
  - 已知限制：cn.bing 对长查询和多词查询会退化（如上）；`site:xiaohongshu.com` 在 cn.bing 上无效且小红书内容几乎无收录。真实小红书检索需官方或授权数据源。
  - **实测召回率（2026-10-29，成都周边）**：只搜地名 + 抓 4 个结果页正文，三岔湖→`翘嘴`、黑龙滩水库→`鲫鱼`、升钟湖→空。约 2/3 命中，每次 1 个鱼种——远低于原设计预期，这也是引入 `typical` 参考值的原因。
  - **已排除的替代数据源（实测，勿重复尝试）**：360 搜索（so.com）头几次命中 5/5，随后返回「访问异常页面」要求验证码，数分钟内即封；百度有反爬，标题解析不出；DuckDuckGo 本机连接超时；高德 POI 对自然水体无评分无评论，垂钓园 POI 的 `featured_reviews` 全空；LLM 直接按地名作答时，五个不同湖泊返回**完全相同**的「鲫鲤草鲢」且自报 `certain:true`（仅青海湖裸鲤这类著名水域准确），不可作为事实来源。
  - **Phase 2（`FISHAGENT_SPECIES_PAGE_FETCH=true`）**：当摘要命中不足 2 个鱼种时，抓取前若干个结果页正文，先做白名单匹配，再（若配置了 `LLM_API_KEY`）由 LLM 抽取。预算按**请求**而非钓位计算：每请求最多抓 12 页、最多 2 次 LLM 调用，单页正文最多取 4000 字符送模型。抓取受 SSRF 防护约束：仅允许 http(s)、仅允许解析到公网地址、拒绝 localhost/私网/链路本地/保留地址，单页最多 512KB。百科、问答、搜索引擎自身等噪声域名跳过。任一页面失败只影响该页，不影响整批。
  - **并发与时间预算**：搜索结果检索、页面抓取、逐钓位加深三个阶段对钓位并行（单个钓点内部仍串行，且同一请求最多一个 LLM 调用在飞）；每请求预算在并发前按钓位分配（先补满单个钓点的 `_PAGE_CONCURRENCY` 上限，再轮到下一个）。加深阶段带截止时间：`FISHAGENT_SPECIES_TIMEOUT_SECONDS` 减去 0.35s 留白，届时未开始的抓页/抽取直接放弃并保留已得的摘要命中，避免被 `asyncio.wait_for` 整体取消而丢掉全部结果。单次 LLM 调用亦受剩余时间约束。
  - **抓页阶段本身也受截止时间约束（2026-10-29 实故障，勿回退）**：此前只有「未开始的抓页」会被放弃，**进行中**的抓页用的是 httpx 客户端超时（等于整个 provider 预算），可以活得比整批还久。实测一个 `tieba.baidu.com` 页面把该阶段撑到 10.9s、远超 4s 预算，外层 `asyncio.wait_for` 于是取消整批，连已经拿到的摘要命中一起丢掉。修复：整段抓页用 `asyncio.wait_for` 包住，超时则保留摘要命中返回。给多少预算都一样永不结束的批，现在会准时收口。
  - **前后端超时必须错开**：前端 `SPECIES_TIMEOUT_MS`（7.5s）必须晚于后端 `FISHAGENT_SPECIES_TIMEOUT_SECONDS`（4.0s）加上网络往返。原为 4.5s，只留 0.5s——手机网络上一个几百毫秒的往返就能让前端先掐断，用户看到「请求超时」，而后端日志里那一条其实是 `200 OK`，白丢一次已经查到的结果。后端自己会在预算用完时返回 `degraded`，前端不需要抢在它前面。
  - **LLM 配额**：抽取调用计入 CR-03 的每日 LLM 配额（`FISHAGENT_LLM_DAILY_QUOTA`，与 Agent 共用同一账本，跨进程重启重置）。配额耗尽时抽取返回空列表并保留摘要/正文白名单命中，不抛 429——遵循本节「配额异常降级为 200」的裁决；`/api/pilot/usage` 的 `llm` 项会显示 `exhausted=true`。
  - 合规：仅读取公开搜索结果页；展示时必须保留来源标识与「仅供参考」。
- **配额异常口径（2026-10-25 裁决）**：Provider 配额耗尽按本节降级为 200（不返回 429）；`providers/base.py` 中「配额异常应返回 429」的通用注释不适用于本端点。
- 前端必须标注来源与“仅供参考”，不得承诺渔获；`degraded=true` 时文案必须与「暂无相关鱼种推荐」区分（如「鱼种信息暂不可用，仅供参考」）。
- **`baits` 由 `species` 派生，不单独查询**（v2.11）：逐项与 `species` 同序对应，每个鱼种一项，`species` 为 `[]` 或 `degraded=true` 时 `baits` 必为 `[]`。这样卡片上不可能出现「推荐饵料」里的鱼种是「推荐鱼种」那一行没提到的。
  - 数据来自 `core/bait.py` 的确定性表，不是模型输出：同一条水域每次问到的饵料必须一致，且关掉 LLM（mock 模式）时仍然可用。
  - `generic=true` 表示该鱼种没有专属条目、返回的是通用方案，前端必须显式标注（「（通用）」）。当前 `KNOWN_SPECIES` 全部有专属条目，该分支仅在未来新增鱼种时可达，测试用 monkeypatch 覆盖。
  - `typical` 来源（同类水域参考值）同样带 `baits`——卡片显示了哪些鱼种，就给出这些鱼种的饵料。

### 4.7 `POST /api/agent/identify-fish`（CR-05，图片识别鱼种）

上传或拍摄一张照片识别鱼种，返回置信度、简要知识、习性、钓饵推荐与注意事项。完整规格见 [`cr05-fish-identification.md`](cr05-fish-identification.md)，本节只记录与主契约相关的硬约束。

- 请求：`multipart/form-data`，`image`（file，必填）+ `note`（text，可选，≤100 字符）。图片大小上限 `FISHAGENT_IDENTIFY_MAX_UPLOAD_BYTES`（默认 8 MiB）。
- 图片处理：流式读取并截断、Pillow 真实解码（不信任 `Content-Type`/扩展名）、最长边缩放至 `FISHAGENT_IDENTIFY_MAX_SIDE`（默认 1280）、重编码 JPEG quality=85、**丢弃 EXIF（含手机 GPS）**。全程在内存中，不落盘、不缓存、不记日志。
- 接受格式：JPEG / **MPO** / PNG / WEBP / GIF / HEIF / AVIF。`MPO` 是 iPhone HDR、人像、实况照片的 JPEG 变体（Pillow 报 `format="MPO"`，但解码路径与 JPEG 相同，只取第一帧）；漏掉它会把 iPhone 默认拍出的照片判成不支持的格式。
- 模型：`LLM_VISION_MODEL`，留空回落 `LLM_MODEL`。所配模型必须接受图像输入。`content` 为空一律视为失败，不得把 `reasoning_content` 当答案。
- `identified=false` 时 `species` 与 `raw_species` 必须为 `null`——模型会把「无法识别」等占位词填进 `species`，不得透传给前端。
- 文本字段命中 `violates_guardrails`（承诺渔获）时，整体降级为未识别，不得输出半清洗的结果。
- 错误：413 `PAYLOAD_TOO_LARGE` / `IMAGE_TOO_LARGE`、415 `IMAGE_EMPTY` / `UNSUPPORTED_MEDIA_TYPE` / `IMAGE_CORRUPT`、422 `VALIDATION_ERROR`、429 `QUOTA_EXCEEDED`、503 `PROVIDER_NOT_CONFIGURED` / `VISION_UNAVAILABLE`，均用统一错误体。
- **如实报告**：视觉调用本身失败（超时 / 上游报错 / 空回答 / 回答无法解析）返回 503 `VISION_UNAVAILABLE`，文案按失败原因区分，且明确不归咎于照片；`identified=false`（200）只表示「模型看过了，照片里没有鱼」。两者**不可合并**。415 的三种来源（空文件 / 不是图片 / 文件损坏）各有独立 `code` 与文案，前端必须透传，不得统一改写成「不支持的图片格式」。
- **配额**：真实模式每次视觉调用在 `api/identify.py` 内 `ledger.consume("llm")` 扣 1 单位；耗尽抛 `UpstreamQuotaExceeded` 由已有 handler 转 429 + `Retry-After`。与 4.6 不同：本端点无部分结果可降级，故返回 429 而非 200。

### 4.8 静态资源缓存与版本提示（CR-05）

目标：用户不用手动清缓存，也不必猜自己是不是旧版；有新版本时看得见、且由自己决定何时刷新。

**缓存策略**

| 资源 | 响应头 | 理由 |
|---|---|---|
| `index.html`、`app.js`、`styles.css`、`sw.js`、`manifest.webmanifest` | `Cache-Control: no-cache` | 允许存但每次必须回源校验。ETag 是内容哈希，命中即 `304` 无响应体，局域网内代价可忽略 |
| `icons/*` | `Cache-Control: public, max-age=86400` | 不含任何行为，SW 里本就是 cache-first，没必要每次校验 |
| `/health` | `Cache-Control: no-store` | 它本身就是"我是不是旧版"的判据，缓存答案等于永远不自知 |

**为什么必须是 `no-cache` 而不是 `no-store`**：`no-store` 会连离线回退一起丢掉。`no-cache` 只要求校验，离线时仍能取回缓存副本。

**为什么之前是坏的**：静态响应只带 `ETag` + `Last-Modified`，没有 `Cache-Control`，浏览器因此按启发式新鲜度自行决定（通行做法是文件年龄的 10%）。一个一天前的 `app.js` 可能几小时都不回源，**连刷新都不解决**——刷新同样被缓存答复。

**版本号**

- 服务端启动时算出 `build`（见 4.1），并在响应 `index.html` 时把同一值注入 `<meta name="fishagent-build">`。
- 构建号由内容算出，**不手工维护**。`__version__` 保持为 API 版本，不承担构建标识的职责——要求每次部署手动改常量，迟早会忘。
- 构建号按文件签名（mtime + size）失效重算：静态目录是每次请求读盘的，只改 `web/` 而不重启服务时，若构建号被缓存住，就会一边发新文件一边报旧版本，提示条永远不触发。

**前端行为**

- 页面每 60 秒、以及从后台切回时，拉一次 `/health`，把 `build` 与自身 meta 比较。
- 不一致时显示可关闭的提示条「FishAgent 有新版本可用 / 立即更新」。
- **刷新只由用户点击触发，绝不自动 reload**：表单输入、已选鱼获照片、对话记录都只在内存中（照片明确不落盘），静默刷新会直接吞掉这些。
- 「稍后再说」按 build 记住，同一个新版本不再弹；用户下次刷新后自然拿到新版。
- meta 里仍是占位符 `__FISHAGENT_BUILD__`（说明这份 HTML 不是本应用发的，例如 `file://` 或陈旧代理）时，视为未知版本并完全关闭检测，否则每次轮询都会误报有更新。

**与 Service Worker 的关系**：SW 侧仍是 shell 资源 network-first + `skipWaiting` + `clients.claim`。但**手机上目前不注册 SW**（明文 http 非安全上下文，见 4.5b），所以上述 HTTP 缓存策略是手机端唯一的实际保障，不能指望 SW。

### 4.9 `POST /api/agent/transcribe`（CR-06，语音输入）

把一段说话转成文字。`Content-Type: multipart/form-data`。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `audio` | file | 是 | 16 kHz 单声道 16-bit 小端 PCM；时长 ≤ `FISHAGENT_SPEECH_MAX_SECONDS`（默认 60s） |
| `sample_rate` | text | 否 | 默认 16000，且**必须**是 16000 |

成功 200：

```json
{
  "text": "鲫鱼用什么饵料",
  "provider": "vosk",
  "ai_disclosure": "本内容由 AI 生成，仅供参考，不承诺渔获。",
  "generated_at": "2026-10-31T10:00:00Z"
}
```

**返回文本，不返回对话轮次**：调用方把 `text` 填进输入框，由用户确认后自己发送。识别错误（尤其本地模型对钓鱼术语）直接发送会把一次听错变成一条用户没问过的回答。

口径：

- **音频只在内存**：流式读取并计数上限（不信 `Content-Length`），不落盘、不缓存、不写日志——含不把 PCM、base64 或识别出的文本写进日志。与 4.7 图片同一条约束。
- **采样率必须 16000**：浏览器用 `AudioContext({sampleRate:16000})` 直接产出该格式，实测可用；因此**不需要 ffmpeg** 转码。
- **空结果与失败必须分开**，都是 422 但 code 不同：
  | 情况 | HTTP | code | 能否让用户改进 |
  |---|---|---|---|
  | 引擎跑了，没听到声音 | 422 | `SPEECH_EMPTY` | 能（「靠近麦克风再说一次」） |
  | 引擎报错 | 422 | `SPEECH_FAILED` | 不能（重试或改用文字） |
  | 引擎不可用（未装/无模型） | 501 | `SPEECH_UNAVAILABLE` | 不能（功能未启用） |
  | 提供方意外异常 | 503 | `SPEECH_UNAVAILABLE` | 不能 |
  | 采样率不符 | 415 | `AUDIO_INVALID` | — |
  | 音频为空 | 415 | `AUDIO_INVALID` | — |
  | 超时长 | 413 | `AUDIO_TOO_LARGE` | 能（说短一点） |

  区分 `SPEECH_EMPTY` 与 `SPEECH_FAILED` 的理由，与 4.7 区分超时和格式错误相同：把系统故障说成用户没说清楚是要用户去修一个不是他造成的问题。
- **不得出现"不清晰/格式/文件损坏"等归因于用户的措辞**（测试锁定）。
- 文本截断到 500 字，与 `POST /api/agent/chat` 的 `message` 上限一致。
- `FISHAGENT_SPEECH_PROVIDER`：`vosk` / `none`。留空视为 `none`；未知值告警后按 `none`。`vosk` 需要 `FISHAGENT_SPEECH_MODEL_PATH` 指向已解压的模型目录。
- 引擎是同步且 CPU 密集的，**必须放到线程里跑**（`asyncio.to_thread`），否则会阻塞事件循环整个时长。
- 前端能力判断**不得**依赖「`webkitSpeechRecognition` 是否存在」：实测该构造器在非安全上下文下**同样存在**，而 `navigator.mediaDevices` 才真正消失。正确顺序是先判 `isSecureContext`，再判 `mediaDevices`。

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
| v1.7 | 2026-10-26 | Phase 2 串行改并发（检索/抓页/加深三阶段）、每请求页预算 6→12、LLM 调用 4→2、加深阶段截止时间与单次调用限时；LLM 抽取计入每日配额并按 4.6 降级；明确未知 API 路径 404/405 语义 | 5 钓位批量冷启动 4.1s 撞 4s 超时导致整批降级；未注册路径的 POST 误报英文 405 |
| v1.8 | 2026-10-27 | 新增图片识别鱼种端点（multipart 上传、图片内存内规范化与 EXIF 丢弃、视觉模型抽取、占位词与承诺性表述防护、配额返 429） | CR-05：Agent 板块支持拍照/上传识别鱼种 |
| v1.9 | 2026-10-27 | `/api/spots/recommend` 结果缓存 180s + 去/回程调用合并；冷启动 14.8s→8.1s，热命中 <20ms | 手机端「附近钓位」需等 14s 才出结果，被用户当成服务不可用 |
| v2.0 | 2026-10-28 | 识别端点错误码细分：415 `IMAGE_EMPTY`/`IMAGE_CORRUPT`、503 `VISION_UNAVAILABLE`（按超时/上游错误/空回答/无法解析分文案）；前端透传 `detail.message` 不再自行概括；接受 `MPO` | 识别失败一律回「不支持的图片格式，请换一张」，把服务超时与文件损坏都说成格式问题，误导用户 |
| v2.1 | 2026-10-28 | 接受 `MPO` 格式（iPhone HDR/人像照片）；识别期间不再禁用上传/拍照入口，重新选图即取消上一张，预览气泡提供取消按钮 | iPhone 默认拍摄的照片被 415 判成「不支持的格式」；选错照片后按钮被禁用且无取消入口，用户回不到选择界面 |
| v2.2 | 2026-10-28 | 对话里的照片缩略图可点开全屏大图（1×–4× 缩放、双击/捏合、拖动、Esc/点遮罩关闭、焦点回到缩略图）；图片地址按需现造、关闭即释放 | 168px 缩略图看不清鱼的特征，用户无法回看自己上传的照片 |
| v2.3 | 2026-10-29 | `bing` Provider 只搜地名 + 退化检测；新增 `source="typical"`（按水域类型的参考值，与引用来源在文案/样式上区分；`degraded` 与 `NullSpeciesProvider` 不给） | 「{地名} 钓鱼」使 cn.bing 对每条查询都返回首字字典词条，鱼种推荐召回率为 0；360/百度/DDG/高德 POI/LLM 直接作答均实测不可用 |
| v2.4 | 2026-10-29 | 抓页阶段加截止时间；前端鱼种超时 4500→7500ms | 手机上「推荐鱼种」报「请求超时」，后端日志却是 200 OK：一个慢页面使抓页阶段超出预算、整批被外层 `wait_for` 取消，且前端 4.5s 闹钟只比后端 4.0s 预算晚 0.5s，移动网络往返就足以先掐断 |
| v2.5 | 2026-10-29 | `water_depth` 由气温基准层 + F1/F2/F3/F4/F5/F7 修正推导，输出「先钓 X，无口再试 Y（原因）」；`suitable_species` 与之共用 `_depth_plan`；劝退档不给策略且前端隐藏鱼种行 | 原实现只看气温三分支，5–32℃ 之间每条请求都返回同一句话，卡片没有信息量；且雷雨劝退时仍给出「钓浅」并被标注成「气压缓降鱼活跃」，与预警自相矛盾；水深改用多因子后还会出现「钓 4–5m 深水」却推荐暖水鱼的组合 |
| v2.6 | 2026-10-29 | 新增 `/api/geo/search` 与 `/api/geo/nearby`；Step 1 改为地名搜索 + 附近水域，坐标输入折叠进「高级」 | Step 1 唯一的手动入口是一对经纬度输入框，普通用户记不住也读不懂；钓鱼的人知道「三岔湖」但不知道 30.2794/104.2669 |
| v2.6b | 2026-10-29 | 定位前检查 `isSecureContext`；非 https 时明确说明「不是权限问题」；定位成功后收起选择器列表 | 真机用 http 访问局域网 IP 时，浏览器把「不提供定位」报成 `PERMISSION_DENIED`，前端统一提示「定位权限被拒绝」，把地址协议问题误导成权限问题 |
| v2.7 | 2026-10-30 | ~~8018 直接改为 HTTPS~~（已于 v2.7c 回退） | 明文 8018 在真机上永久失去定位与 Service Worker；独立 8020 实例多一个要维护的进程 |
| v2.7b | 2026-10-30 | 新增 `scripts/start-fishagent.vbs` 并放入启动文件夹（无窗口、重复启动自动跳过、日志落 `D:\FishAgent\logs`） | 主机重启后手工起服务会退回明文访问或干脆没起，定位与 PWA 又失效；`.bat` 放启动项会常驻命令行窗口 |
| v2.7c | 2026-10-30 | **回退 v2.7**：8018 与开机自启改回明文 HTTP（新增 `serve.bat`，VBS 用 `Const BAT_NAME` 切换）。接受手机端无定位、无 SW；`serve-https.bat` 保留备用。接口不变 | 真机装 mkcert CA 的门槛、以及证书按 IP 签发导致换地址就要重签，比换回来的定位与 PWA 更麻烦；页面已能如实说明限制，不再把协议问题说成权限问题 |
| v2.8 | 2026-10-30 | shell 资源加 `Cache-Control: no-cache`；`/health` 增加内容哈希 `build` 并注入 `index.html`；页面轮询发现新版后显示提示条，由用户点「立即更新」 | 静态响应原本不带 `Cache-Control`，浏览器按启发式新鲜度自行缓存，旧 `app.js` 可能几小时不回源，**刷新也拿不到新版**；手机端没有 SW 兜底，只能靠 HTTP 缓存策略 |
| v2.9 | 2026-10-30 | 钓位推荐改为「扇区 × 距离环」取样评估池 + 间距交错分页 + 同名水体去重；`meta` 新增 `selection_strategy` / `min_separation_m` / `separation_relaxed` | 实测成都 80km 搜出 448 个候选，返回的 5 个全在 7.7km 内、鱼情分全是 81（排序实际等价于「最近的几个」）；另有一页 5 张卡片里 3 张同名「府河」，用户无从区分 |
| v2.10 | 2026-10-30 | 搜索半径改为**环带**：新增 `min_radius_km`（默认 0，兼容旧调用），前端下拉改为 0–10 / 10–50 / 50–100 / 100–150 四档；`filtered` 新增 `within_min_radius`，`meta` 新增 `min_radius_km` | 用户要看「远一点的地方」，而单一半径只能收窄外圈，返回的仍是那几个最近的；环带才能真正把近处的排除掉 |
| v2.11 | 2026-10-30 | 4.4 新增 `bait` 意图（确定性表，不依赖 LLM/工具）；鱼种解析改为共用 `core/species.py` 全量清单 + 最长优先匹配；超出鱼情模型的物种不再传给 `/api/fish-activity`。4.6 结果新增 `baits`（由 `species` 派生）。4.5b 约定定位成功后清空地名输入框 | 问「白条/翘嘴/罗非鱼用什么饵料」返回「我可以帮你分析……」，只有「鲫鱼」能答：饵料类问题不匹配任何意图，且 agent 自带的鱼种表只有四种、别名字段只有「鲫」「鲤」，鲫鱼是靠单字别名碰巧命中的；Step 3 卡片只给鱼种不给饵料；定位后地名框仍留着旧关键词，界面自相矛盾 |
