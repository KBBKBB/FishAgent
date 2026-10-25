# FishAgent MVP 产品需求文档（PRD）

> 版本：v1.2 ｜ 编制：小产 ｜ 日期：2026-10-21 ｜ 状态：M1a 待评审（已对齐契约 v1.2）
> 上游依据：`项目立项文档.md` 2.4 / 第七、八章、`Spec/Mission.md`、`Spec/TechStack.md`、`docs/project-plan.md`、`docs/api-contract.md` v1.2
> 版本对齐：v1.1 已裁决 `alerts` 对象结构、`filtered` 不变式、时区、统一错误体、Mock `scenario` 与 F3/F4/F6 口径；v1.2 已裁决 F2/F5 口径、`best_windows` 数量、Agent 工具名与单程取整；AT-UI-06 明确评分依据数据条须带标题「评分依据（非天气预报）」，禁止多时段预报与天气播报式面板。本文均已对齐。
> 配套验收脚本：`fixtures/demo_scenarios.json`
> 适用范围：本轮 Mock 模式可运行 MVP。小程序端、生成式 AI 备案、真实 Key 实测、UGC、海钓均为范围外 Backlog。

---

## 0. 结论先行

本轮只交付一个能被真实点开的「出钓决策器」：用户给出位置，得到 **去不去（0–100 分 + 五档）、去哪（2 小时往返内钓位）、几点去（窗口）** 三个结论，并且每个结论都能解释、都带 AI 标识与免责声明。

验收只认三条硬线：

1. **零 Key 可跑**：Mock 模式下 `/health`、鱼情、钓位、对话四个入口全部可用，五档可通过固定种子复现。
2. **红线不可破**：单次周边搜索 `radius ≤ 50000m`；去/回程分别计算且合计 `≤ 7200s`；禁钓候选不返回；入口坐标优先、缺失回退并标注。
3. **劝退是产品能力**：鱼情差或恶劣天气时必须明确说「今天不建议出钓」，不得为了推荐而弱化。

---

## 1. 背景、目标与成功标准

### 1.1 用户问题

钓鱼人出发前真正要回答的是三个问题，而不是「今天气压多少」：

- 今天值不值得跑这一趟？
- 附近两小时车程内去哪？
- 几点到最好？

现有产品给数据、给列表，但不替用户做结论，也不敢劝退。FishAgent 的定位是**钓鱼辅助决策工具**：给参考建议，不承诺渔获。

### 1.2 本轮目标（MVP）

| 编号 | 目标 | 可验证结果 |
|---|---|---|
| G1 | 鱼情可解释 | 7 因子、0–100 分、五档、Top3 因子、最佳时段/水深/鱼种、强制提示 |
| G2 | 钓位可达可解释 | 2h 往返过滤、禁钓过滤、入口精度标记、排序与推荐理由、导航链接 |
| G3 | 对话闭环 | LangGraph 编排，3 类高频问句可正确调用工具并给出整合结论；无 Key 时确定性兜底 |
| G4 | H5 可演示 | 定位/手动坐标 → 评分卡 → 钓位列表 → 对话，全流程可完成 |
| G5 | 工程可交付 | Mock 开箱可跑、pytest 通过、Ruff 通过、README 可按步骤启动、无真实密钥 |

### 1.3 成功标准（本轮 DoD）

沿用 `docs/project-plan.md` 第四节，产品侧补充可执行口径：

1. 四个端点返回契约内响应，字段名不改。
2. 五档分数段边界 **40/55/70/85** 映射正确；暴雨/雷雨强制劝退；`alerts` 为对象数组，元素固定 `{code, level: danger|warning|info, message, forced}`，至少覆盖 `RAINSTORM`（danger）、`GALE`（danger）、`PRESSURE_PLUNGE`（warning，含 2–4h 窗口）。
3. `radius_km` 参数 1–150；服务端单次高德/Mock 周边请求 `radius ≤ 50000m`；>50km 覆盖必须分片且去重。
4. 去程 + 回程分别取值后求和过滤，禁止单程 ×2；`entr_location` 优先，缺失回退中心点并置 `entry_precision="center_fallback"`。
5. 禁钓候选在返回前排除；Mock 至少 1 个禁钓候选、2 个往返超时候选、1 个缺入口坐标但可推荐的候选。`filtered` 满足 `total_candidates = forbidden + over_two_hours + eligible` 与 `eligible = returned + truncated_by_limit`。
6. Agent 对 3 类问句至少各 1 条正确工具调用；无 Key 时 `mode="fallback"`；工具失败不返回 500。
7. H5 在 `http://127.0.0.1:8000/` 完成主流程，AI 标识与免责声明在结果页可见，375px 宽不横向滚动。
8. `pytest` 全绿、`ruff check` 通过；仓库与前端产物无真实 Key。
9. 时间语义统一：业务判定与展示用 `Asia/Shanghai`；`at` 不带时区按东八区解释；`generated_at` 为 UTC；鱼情响应含 `timezone="Asia/Shanghai"`。

### 1.4 非目标（本轮明确不做）

- 微信小程序、App、地图可视化底图、账号体系、收藏/分享。
- 生成式 AI 备案/算法登记、用户协议、投诉举报入口的正式上线。
- 高德/Open-Meteo/LLM 真实 Key 的配额与链路实测（适配器代码就绪即可）。
- UGC 钓点、禁钓权威矢量边界、机器学习模型、海钓/潮汐。
- 埋点与 A/B 实验（Roadmap M2 起）。

---

## 2. 用户与场景

### 2.1 目标用户

| 优先级 | 人群 | 关键诉求 | 本轮对应能力 |
|---|---|---|---|
| P0 | 野钓爱好者 | 「值不值得跑这一趟」 | 鱼情档位 + 2h 往返钓位 + 劝退 |
| P0 | 库钓玩家 | 「什么时候去最好」 | 最佳时段 + 对话追问 |
| P1 | 黑坑钓友 | 距离近、时段与鱼种策略 | 钓位排序 + 鱼种建议 |
| P2 | 竞技钓人群 | 要依据、不要黑箱 | Top3 因子 + 因子明细 |

### 2.2 关键决策时刻

1. **出发前一晚**：明天去不去？——看档位与劝退。
2. **当天早上**：几点出发、去哪？——看窗口与 2h 钓位列表。
3. **到水边后**：深浅怎么换？——看水深策略与对话追问（MVP 只给通用建议）。

### 2.3 用户故事

| ID | 优先级 | 用户故事 | 验收 |
|---|---|---|---|
| US-01 | P0 | 作为野钓爱好者，我输入位置后想看到今日鱼口评分、档位和 Top3 原因，从而决定去或不去。 | AT-FA-01~05、AT-UI-01 |
| US-02 | P0 | 作为库钓玩家，我想知道最佳出钓时段，并能问「明早几点去最好」。 | AT-FA-01/02/03、AT-CHAT-03 |
| US-03 | P0 | 作为没有固定钓点的钓友，我想看到 2 小时往返内、已排除禁钓区的钓位，并知道单程/往返耗时。 | AT-SPOT-01、AT-UI-01 |
| US-04 | P0 | 作为不想研究图表的用户，我想用一句口语问清鱼情、钓位或时段，并获得整合结论。 | AT-CHAT-01~03 |
| US-05 | P1 | 作为谨慎用户，我想知道结论是 AI 生成的、可能不准，并看到判断依据与免责说明。 | AT-CMP-01~03、AT-UI-02 |
| US-06 | P0 | 作为团队/评审，我希望无任何 Key 也能按固定步骤复现五档与主流程，完成验收。 | DEMO-ENV-01、DEMO-FA-01~05、DEMO-UI-01 |

---

## 3. 范围与优先级

### 3.1 本轮范围

| 模块 | P0（必须） | P1（应做，不阻塞验收） |
|---|---|---|
| 鱼情分析 | F1–F7、总分/五档、Top3、alerts、最佳时段、水深、鱼种、AI 标识 | 鱼种修正文案更细化 |
| 钓位推荐 | radius 硬校验、往返精算、禁钓过滤、入口回退、排序、理由、导航链接 | 展示「已过滤 N 个」摘要 |
| 对话 Agent | LangGraph、3 类问句、无 Key fallback、工具失败兜底 | 多轮上下文利用、fallback 标识 |
| H5 | 定位/手动坐标、评分卡、钓位列表、对话、AI 标识、免责、375px | 演示坐标快捷按钮、空态插画 |
| 工程 | Mock 可跑、pytest、Ruff、README | 请求耗时展示 |

### 3.2 关键假设

- A1：本轮验收以 Mock 数据为准；真实适配器只要求接口隔离与可注入，不要求实测。
- A2：H5 为无构建链静态页，由 FastAPI 同源托管。
- A3：业务判定与展示时区固定 `Asia/Shanghai`；`at` 不带时区按东八区解释；`generated_at` 始终 UTC（`Z` 结尾）。
- A4：Mock 天气通过 `/api/fish-activity?scenario=excellent|good|fair|poor|no_go` 确定性触发五档（仅 Mock 生效），固定 `at` 用于锁定时间窗口与演示复现（见 §5.1）。

---

## 4. 功能需求

### 4.1 鱼情分析（FR-FA）

#### FR-FA-01 输入与输出

输入：`lat`、`lon`（WGS84，必填）、`species`（可选，仅限 鲫鱼/鲤鱼/草鱼/鲢鳙；非法值 422 `INVALID_SPECIES`）、`at`（可选，ISO 8601；不带时区按 `Asia/Shanghai` 解释）、`location_name`（可选，展示用）、`scenario`（可选，仅 Mock 生效：`excellent|good|fair|poor|no_go`）。
输出严格按 `docs/api-contract.md` §4.2：`score`、`band`、`advice`、`recommendation`、`factors`（固定 7 项）、`top_factors`（3 项）、`best_windows`、`water_depth`、`suitable_species`、`alerts`（对象数组）、`weather_summary`、`data_sources`、`ai_disclosure`、`timezone="Asia/Shanghai"`、`generated_at`（UTC）。

#### FR-FA-02 五档与产品动作

总分为 7 项因子之和（0–100），分档与固定文案：

| 分数段 | `band` | `advice`（精确值） | 产品动作 | `best_windows` |
|---|---|---|---|---|
| 85–100 | 极佳 | 强烈建议出钓 | 给全天建议 + 2 个窗口 | 2 项（日出、日落） |
| 70–84 | 良好 | 适合出钓 | 给最佳时段 | 2 项（日出、日落） |
| 55–69 | 一般 | 有机会，建议挑时段 | 给 2 个候选窗口 | 2 项（日出、日落） |
| 40–54 | 偏差 | 不太理想，建议就近作钓 | 缩短行程 / 就近 | 1 项（日出） |
| 0–39 | 劝退 | 今天不建议出钓 | 明确理由，不鼓励出钓 | 0 项 |

规则：

- `advice` 必须与上表完全一致；`recommendation` 在 `advice` 基础上补具体窗口/原因，不得只复述天气。
- 暴雨/雷雨时 `band` 强制为「劝退」、`advice` 为「今天不建议出钓」，并在 `recommendation` 与 `alerts` 说明「恶劣天气一票否决」。**不因强制档位改写总分与因子和**；演示用劝退种子的原始总分须 <40（见 §5.1）。
- 劝退不等于降级兜底，必须给出至少 2 条可读原因（来自 Top3 因子或 alerts）。

#### FR-FA-03 七因子与权重

| 因子 | 上限 | 评分口径（MVP 验收口径） |
|---|---|---|
| F1 气压变化趋势 | 25 | 24h 变化量 Δ：稳定 `abs(Δ)≤2` → 18；缓降 `2<Δ≤8`（Δ 为负）→ 25；骤降 `Δ<-8` → 15 + 强制提示；缓升 `2<Δ≤8`（Δ 为正）→ 12；骤升 `Δ>8` → 5。2–3hPa 空档归入缓变。 |
| F2 气压绝对值 | 20 | 有近 30 天分布时按 30–70 百分位 20 / 15–30 或 70–85 百分位 12 / 极端 6；无分布时兜底：1005–1020hPa → 20；1000–1005 或 1020–1025hPa → 12；<1000 或 >1025hPa → 6（内层区间优先）。 |
| F3 气温与变温 | 15 | 日均温 15–28℃ 且 `abs(Δ24h)≤3` → 15；`3<abs(Δ)≤6` → 10；`6<abs(Δ)≤8` → 6；`abs(Δ)>8` → 3；日均温不在 15–28℃ 时基础分 −3，昼夜温差 >12℃ 再追加 −3（均下限 0）。 |
| F4 风力风向 | 15 | 2–3 级 → 15；0–1 级 → 9；4 级 → 8；5 级（8.0–10.7m/s）→ 3；≥6 级（≥10.8m/s）→ 0；≥5 级触发安全提示。下风口 +3 仅作用于钓位级 `fish_score`（Mock `downwind` 元数据），不改变通用 F4，两者上限均为 15。 |
| F5 降水与窗口 | 10 | 雷雨/暴雨（`is_thunderstorm` 或日降水 ≥50mm）→ 0 并强制劝退；大雨 25–50mm → 3；中雨 5–25mm → 7；小雨 0.1–5mm → 10；无雨（晴/阴）→ 8；雨后 0–6h → 7；连续晴热 >3 天 → 5（优先于无雨）。端点按左闭右开：5mm 记中雨、25mm 记大雨、50mm 记暴雨。 |
| F6 季节/时段 | 10 | 日出前后 1.5h、日落前 2h → 10（冬季窗口内同样优先给 10）；春秋其他时段 → 7；盛夏 11:00–15:00 且气温 >32℃ → 3；冬季以日均气温 <5℃ 作为水温代理 → 2；其余 → 5。 |
| F7 云量/光照 | 5 | 云量 30–70% → 5；>70% → 4；<30% → 3。 |

单项分不得超过上限，不得为负；总分必须等于 7 项之和。

#### FR-FA-04 Top3 与 impact

- `top_factors` 取贡献比 `score/max_score` 降序，比值相同按 `score` 降序，仍相同按因子编号升序，取前 3。
- `impact`：比值 ≥0.8 → `positive`；≤0.5 → `negative`；其余 → `neutral`。
- `top_factors` 必须是 `factors` 的子集，字段值与 `factors` 中对应项一致。

#### FR-FA-05 强制提示（alerts）

`alerts` 固定为对象数组，元素结构 `{code, level, message, forced}`：

| 触发条件 | `code` | `level` | `forced` | `message` 必须包含 | 其他影响 |
|---|---|---|---|---|---|
| 暴雨 / 雷雨（`is_thunderstorm=true` 或等效暴雨标记） | `RAINSTORM` | `danger` | `true` | 「雷雨」或「暴雨」+ 不建议出钓 | `band=劝退`，`advice` 固定 |
| `wind_level ≥ 5`（`wind_speed_ms ≥ 8.0`） | `GALE` | `danger` | `true` | 「≥5级」或「大风」及安全提醒 | F4 得 0–3 |
| `pressure_change_24h < -8` | `PRESSURE_PLUNGE` | `warning` | `true` | 「骤降」及「有效窗口仅 2–4 小时」 | F1 得 15 |

- `level` 仅允许 `danger|warning|info`；`forced=true` 表示规则强制触发，不得省略或降级。
- UI 必须逐条可见并按 `level` 区分危险程度；验收按 `code`、`level`、`forced` 与 `message` 关键词断言。
- 允许出现其他 `code` 的补充提示（如 `HEAT`），但不得替换上述三类强制提示。

#### FR-FA-06 建议内容

- `best_windows` 项含 `start`、`end`（HH:MM，`Asia/Shanghai` 本地时间）与 `label`（「日出窗口」「日落窗口」）；`start < end`。
- 数量按档位固定：极佳/良好/一般各 2 项（日出、日落），偏差 1 项（日出），劝退 0 项。
- 窗口定义：日出窗口 = 日出前 1.5h 至日出后 1.5h；日落窗口 = 日落前 2h 至日落。
- `water_depth` 非空，给可执行策略（如「先钓 1.5–2m 浅滩，无口则转 3m 以上」）。
- `suitable_species` 非空；传入合法 `species` 时应考虑该鱼种，不改变 7 因子结构。
- 劝退时不得输出「值得去」「强烈建议」等鼓励性文案。

#### FR-FA-07 可复现与时间

- 同一 `(lat, lon, at, scenario)` 连续 3 次调用，除 `generated_at` 外结果一致。
- `at` 缺省取当前时刻；`at` 带时区时按其转换，不带时区时按 `Asia/Shanghai` 解释；F6 与日出日落按 `Asia/Shanghai` 计算。
- `generated_at` 始终为 UTC ISO 8601（`Z`）；响应含 `"timezone": "Asia/Shanghai"`。
- 同一时刻的 `at=2026-04-11T21:30:00Z` 与 `at=2026-04-12T05:30:00`（无时区）必须给出相同业务结果。

### 4.2 钓位推荐（FR-SPOT）

#### FR-SPOT-01 处理链路

召回水域候选 → WGS84→GCJ02 → 入口坐标选择 → 去/回程分别精算 → 往返过滤 → 禁钓过滤 → 综合评分排序 → 截断 `limit`。

#### FR-SPOT-02 半径与分片

- API `radius_km` 默认 100，范围 1–150；越界返回 422。
- 服务端每次周边搜索 `radius ≤ 50000m`；`radius_km > 50` 时按网格/同心环分片，结果按 POI id 去重。
- 任何情况下不得把 >50000 的值传入 Provider；Mock 适配器同样要保留该校验与去重逻辑。
- 召回量异常下限（Mock：≥8 个候选）用于发现「静默降级」。

#### FR-SPOT-03 入口坐标

- 有 `entr_location` 时必须用入口坐标做精算与导航；`entry_precision="entr_location"`。
- 缺失时回退 POI 中心点，`entry_precision="center_fallback"`，UI 标注「端点精度较低」。
- Mock 必须至少有 1 个「缺入口坐标、但往返 ≤2h 且非禁钓」的候选进入结果，保证回退标记可见。

#### FR-SPOT-04 往返车程

- 去程与回程分别取时长，过滤条件 `drive_seconds_out + drive_seconds_back ≤ 7200`；禁止单程 ×2。
- `drive_seconds_round_trip` 必须等于两者之和；`drive_minutes_one_way = round_half_up(drive_seconds_out / 60)`，四舍五入到整数分钟（89s→1、90s→2），不得向下取整或单程 ×2。
- 往返 >7200s 的候选不得出现在 `spots`，只计入 `filtered.over_two_hours`。
- `traffic_basis` 在 Mock 模式为 `baseline_estimate`，UI 标注「预估车程，实际以导航为准」。

#### FR-SPOT-05 禁钓过滤

- 在返回前排除：名称含「一级保护区」「饮用水源」「禁钓」「养殖场」「承包塘」等黑名单词，或落入示例禁钓圆区。
- 边界不明时保守排除。被排除数量计入 `filtered.forbidden`，不得出现在 `spots`。
- Mock 至少 1 个禁钓候选，用于验证过滤。

#### FR-SPOT-06 评分与排序

- `total_score` 0–100（1 位小数），必须综合鱼情、水域类型/鱼种适配、往返车程；`fish_score` 0–100。
- 钓位处于下风口/迎风岸（Mock `downwind` 元数据）时，`fish_score` 中 F4 部分 +3，上限仍为 15；该修正仅作用于钓位级 `fish_score`，不改变 `/api/fish-activity` 的通用 F4。
- 排序：`total_score` 降序；同分按 `drive_seconds_round_trip` 升序。
- 每个结果 `reasons` 2–4 条，至少 1 条与鱼情/因子相关、1 条与车程相关；不得使用「保证有鱼」等承诺。
- `navigation_url` 使用入口坐标（GCJ02，`lon,lat` 顺序），包含 `position` 与 `name`。

#### FR-SPOT-07 过滤统计与空态

- `filtered` 固定含 `total_candidates`、`forbidden`、`over_two_hours`、`eligible`、`returned`、`truncated_by_limit`，均为非负整数。
- 口径与顺序：`total_candidates` = 召回并去重后、过滤前总数；随后依次执行禁钓过滤 → 往返时长过滤 → 排序截断。
- 不变式：`total_candidates = forbidden + over_two_hours + eligible`；`eligible = returned + truncated_by_limit`；`returned = len(spots)`。
- 同时命中禁钓与超时的候选只计入 `forbidden`。
- 无符合条件候选时返回 200 + `spots: []`，不得 500；UI 展示空态与「扩大范围/更换位置」建议。

#### FR-SPOT-08 坐标

- 入参 `lat/lon` 为 WGS84；返回 `user_location` 同时含 WGS84 与 GCJ02；钓位坐标为 GCJ02。
- 坐标转换只允许走 `core/coords.py` 唯一入口；天气查询继续使用 WGS84。
- 已知点回归：`wgs84_to_gcj02(39.915, 116.404)` 与标准值 `(39.916404, 116.410244)` 误差 ≤1e-4°；往返转换误差 ≤1e-5°。

### 4.3 自然对话 Agent（FR-CHAT）

#### FR-CHAT-01 契约

请求/响应按 `docs/api-contract.md` §4.4。`message` 1–500 字；`location` 必填；`history` 最多保留最近 10 条；`session_id` 可选，缺省由服务端生成并在响应回显。
`mode` 取 `llm` 或 `fallback`；`tool_calls[].status` 取 `ok` 或 `error`；`ai_disclosure` 固定文案。

#### FR-CHAT-02 三类问句（本轮验收）

| ID | 问句 | 意图 | 必调工具 | 回复必须包含 | 禁止 |
|---|---|---|---|---|---|
| CHAT-01 | 今天这气压适合钓鱼吗？ | 鱼情 | `get_fish_activity` | 档位/行动建议、至少 1 条因子理由、时间窗口 | 原样播报天气预报；承诺渔获 |
| CHAT-02 | 附近哪里野钓好？ | 钓位 | `recommend_spots` | 至少 1 个钓位名、往返耗时（标「预估」）、选择理由 | 承诺渔获；保证合法 |
| CHAT-03 | 明早几点去最好？ | 时段 | `get_fish_activity`（可含 `recommend_spots`） | 至少 1 个 `HH:MM` 时段、给出理由 | 只回「看天气」；播报天气 |

工具名按契约 v1.2 固定：鱼情 `get_fish_activity`、钓位 `recommend_spots`；`tool_calls[].name` 必须精确等于这两个值，不接受语义等价别名。
Agent 调用工具前必须归一化 `species`（仅 鲫鱼/鲤鱼/草鱼/鲢鳙），不得把用户自由文本直接透传；无法归一化时按通用分处理，不返回 422。

#### FR-CHAT-03 无 Key 兜底

- `LLM_API_KEY` 为空或 LLM 调用失败时，`mode="fallback"`，必须仍正确识别三类意图并调用相应工具。
- 意图关键词：鱼情（气压/鱼情/鱼口/适合钓鱼/活跃度）、钓位（附近/钓位/钓点/哪里/野钓/水库/黑坑）、时段（几点/时段/明早/窗口/什么时候）。
- 同时命中多类时，以问句核心诉求为主；无法识别时返回 200，说明可回答的三类问题并请用户补充位置或目标，不得空响应或 500。

#### FR-CHAT-04 工具失败与超时

- 工具失败时返回 200，`tool_calls[].status="error"`，`reply` 给可读兜底（说明暂时无法获取及可重试），不得返回 500 堆栈。
- 部分成功时保留可用结果（如鱼情可用、钓位失败），并在回复中说明缺口。
- LLM 超时 30s 内降级 fallback；Mock 模式 P95 ≤3s。

#### FR-CHAT-05 回复风格

- 结论先行，2–5 句中文口语；先给「去/不去/去哪/几点」，再给 1–2 条理由。
- 不原样播报天气（P5/R8）；只解释与鱼情有关的因子。
- 全部回复由 UI 展示 `ai_disclosure`；不得出现「必上鱼」「保证爆护」「百分百」等表述。

### 4.4 H5 演示界面（FR-UI）

#### FR-UI-01 页面结构

单页从上到下：位置区 → 鱼情卡 → 钓位列表 → 对话区 → 免责声明。
位置区：浏览器定位按钮、手动经纬度输入、「开始分析」；定位失败时提示改用手动输入。
鱼情卡：总分/100、档位、`advice`、Top3 因子（含 impact 标识）、最佳时段、水深、鱼种、alerts（危险项高亮）。
钓位列表：名称、水域类型、入口精度标记、单程/往返时间（带「预估」）、推荐理由、导航链接。
对话区：3 个示例问题快捷按钮、输入框、发送、消息列表。

#### FR-UI-02 状态

- 加载中：按钮禁用 + 明确进度提示。
- 参数错误：展示可读错误（如「经度需在 -180~180」），不白屏。
- 无钓位：展示空态与调整建议。
- 对话 fallback：展示「当前为规则兜底回答」（P1，不阻塞）。
- 网络/服务失败：展示重试入口。

#### FR-UI-03 合规与标注

- 顶部或评分卡固定展示 `AI 生成 · 仅供参考`。
- Mock 模式展示 `Mock 演示模式 · 天气与钓位为模拟数据`。
- 结果页可见免责声明全文（非仅弹窗）；页脚常驻。
- `entry_precision="center_fallback"` 的钓位显示「端点精度较低」。
- 所有车程显示「预估」；不展示原样天气预报面板。评分依据数据条（`weather_summary`）必须展示，标题为「评分依据（非天气预报）」，仅展示当前时刻影响评分的因子数据，不得出现多时段预报或天气播报式面板；数据源与生成时间保持可见。
- 前端不得出现任何 Key，不得直连高德/Open-Meteo/LLM。

#### FR-UI-04 兼容与响应式

- 最新版 Chrome/Edge/Safari；375px 宽起不横向滚动。
- 导航链接新窗口打开。
- 页面可直接由 `http://127.0.0.1:8000/` 访问，无需构建。

### 4.5 合规文案（FR-CMP）

#### FR-CMP-01 AI 标识（精确文案）

| 位置 | 文案 |
|---|---|
| 页面常驻标识 | `AI 生成 · 仅供参考` |
| 鱼情接口 `ai_disclosure` | `本结论由 AI 辅助生成，仅供参考，不承诺渔获。` |
| 对话接口 `ai_disclosure` | `本内容由 AI 生成，仅供参考，不承诺渔获。` |

#### FR-CMP-02 免责声明（页面全文）

> FishAgent 仅提供基于公开数据的参考性建议，不保证渔获结果。请遵守当地渔业法规与禁钓规定，自行确认垂钓合法性；注意涉水安全，恶劣天气请勿出钓，建议结伴出行。本演示仅将定位用于本次推荐，不做长期保存。

#### FR-CMP-03 其他标注

| 场景 | 文案 |
|---|---|
| Mock 模式 | `Mock 演示模式 · 天气与钓位为模拟数据` |
| 端点回退 | `端点精度较低` |
| 车程 | `预估车程，实际以导航为准` |
| 规则兜底 | `当前为规则兜底回答` |

#### FR-CMP-04 禁止表述

不得出现：`必上鱼`、`保证爆护`、`百分百上鱼`、`绝不空军`、`稳了`。不得承诺渔获、不得保证钓位合法、不得替代用户确认禁钓规定。

#### FR-CMP-05 数据与隐私

- 展示 `data_sources`（如 `Open-Meteo（Mock）`、`FishAgent 规则引擎 v1`）。
- 不长期存储精确位置；本演示无数据库写入，日志不得打印完整经纬度。
- 前端产物与仓库不得含真实 Key；`.env.example` 仅占位符。

---

## 5. Mock 数据与演示种子

### 5.1 五档天气种子（B-03 必须支持）

为实现五档可复现演示，天气 Mock 必须支持通过 `at` 命中以下场景；同一 `(lat, lon, at)` 连续 3 次结果一致。种子只约束档位与关键天气条件，精确分数可在目标区间内调参。

| 场景 | `scenario` | `at`（UTC） | 本地时间（Asia/Shanghai） | 关键天气画像 | 目标档位 |
|---|---|---|---|---|---|
| 极佳 | `excellent` | `2026-04-11T21:30:00Z` | 04-12 05:30 | 气压缓降约 5hPa/24h、1012hPa、气温 20℃、24h 变温 1℃、2–3 级风、多云无雨、日出窗口 | 85–100 极佳 |
| 良好 | `good` | `2026-04-12T22:30:00Z` | 04-13 06:30 | 气压稳定约 ±1hPa、1010hPa、气温 22℃、变温 4℃、4 级风、多云无雨、日出窗口 | 70–84 良好 |
| 一般 | `fair` | `2026-04-14T02:00:00Z` | 04-14 10:00 | 气压缓升约 4hPa/24h、1008hPa、气温 26℃、变温 5℃、4 级风、无雨、春秋非窗口 | 55–69 一般 |
| 偏差 | `poor` | `2026-04-15T04:00:00Z` | 04-15 12:00 | 气压骤升约 10hPa/24h、1018hPa、气温 30℃、变温 9℃、1 级风、连续晴热、晴 | 40–54 偏差 |
| 劝退 | `no_go` | `2026-06-20T06:00:00Z` | 06-20 14:00 | 雷雨、1002hPa、骤降约 12hPa/24h、变温 -9℃、6 级风、云量 >70%、气温 >32℃ | <40 劝退 |

> 五档优先通过 `scenario` 参数触发（仅 Mock 生效）；`at` 用于锁定时间窗口并保证演示复现。未提供 `scenario` 时按种子默认场景生成。
> 目标分数拆解见附录 B，仅作实现对齐，不作为精确断言；验收断言以 `band`、`advice`、`alerts` 与数量约束为准。劝退种子必须同时满足：原始总分 <40、`RAINSTORM`+`GALE`+`PRESSURE_PLUNGE` 三条强制提示齐备，避免「45 分劝退」的演示观感。

### 5.2 水域 POI Mock

- 围绕用户坐标生成 ≥8 个候选，覆盖水库/湖泊/河流/野塘，确定性可复现。
- 至少 2 个往返 ≤2h；1 个单程 >1h 但往返 ≤2h；2 个往返 >2h；1 个禁钓；1 个缺 `entr_location` 但往返 ≤2h 且非禁钓。
- 名称与地址为演示虚构数据；禁钓候选名称含「一级保护区」或落入示例禁钓圆区。
- 同一请求重复执行，钓位 id、距离、时长、排序一致。

### 5.3 确定性

- Mock 天气以 `(lat, lon, date, at)` 为种子，`scenario` 显式覆盖种子画像；Mock POI 以 `(lat, lon, radius)` 为种子。
- 无 `at` 参数的接口（钓位推荐、对话）在 Mock 下按小时取整种子，保证 60 秒内重复请求结果一致。
- 除 `generated_at` 外，同一输入连续 3 次响应一致。
- 不得依赖外网；无 Key 时不得尝试真实 Provider。

---

## 6. 验收用例

> 可执行版本见 `fixtures/demo_scenarios.json`；本节定义口径与优先级。P0 全过才可交付，P1 缺陷记录不阻塞（除合规项）。

### 6.1 五档评分验收

#### 6.1.1 分档边界（规则级，P0）

| 输入总分 | 期望 `band` | 期望 `advice` |
|---|---|---|
| 39 | 劝退 | 今天不建议出钓 |
| 40 | 偏差 | 不太理想，建议就近作钓 |
| 54 | 偏差 | 不太理想，建议就近作钓 |
| 55 | 一般 | 有机会，建议挑时段 |
| 69 | 一般 | 有机会，建议挑时段 |
| 70 | 良好 | 适合出钓 |
| 84 | 良好 | 适合出钓 |
| 85 | 极佳 | 强烈建议出钓 |

同时验证 0 与 100 极值不崩溃；分档函数必须可被单元测试直接调用（或提供等价可测试入口）。

#### 6.1.2 五档端到端（Mock 种子，P0）

| ID | 种子场景 | 关键断言 |
|---|---|---|
| AT-FA-01 | `scenario=excellent` + 极佳 `at` | `band="极佳"`；85≤`score`≤100；`factors` 7 项且和为 `score`；F1=25；`alerts=[]`；`best_windows` 恰 2 项（日出、日落）；`advice="强烈建议出钓"`；`timezone="Asia/Shanghai"` |
| AT-FA-02 | `scenario=good` + 良好 `at` | `band="良好"`；70≤`score`≤84；F1=18；F4=8；`advice="适合出钓"`；`best_windows` 恰 2 项（日出、日落） |
| AT-FA-03 | `scenario=fair` + 一般 `at` | `band="一般"`；55≤`score`≤69；F1=12；`advice="有机会，建议挑时段"`；`best_windows` 恰 2 项（日出、日落） |
| AT-FA-04 | `scenario=poor` + 偏差 `at` | `band="偏差"`；40≤`score`≤54；F1=5；F3=0（变温 9℃ 得 3，日均温 30℃ 再 −3）；F5=5（连续晴热）；`advice="不太理想，建议就近作钓"`；`best_windows` 恰 1 项（日出） |
| AT-FA-05 | `scenario=no_go` + 劝退 `at` | `band="劝退"`；`score`<40；`advice="今天不建议出钓"`；`best_windows=[]`；F2=12（1002hPa 落在 1000–1005 兜底档）；F5=0；`alerts` 含 `RAINSTORM`(danger,forced)、`GALE`(danger,forced)、`PRESSURE_PLUNGE`(warning,forced)；`recommendation` 含原因 |

五档用例统一断言：`factors` 顺序 F1–F7、权重上限 25/20/15/15/10/10/5、`top_factors` 3 项且与 `factors` 一致、`alerts` 元素均含 `code/level/message/forced`、`ai_disclosure` 精确文案、`data_sources` 含 Mock 标识、`timezone="Asia/Shanghai"`、`generated_at` 为 UTC；`best_windows` 每项的 `start`/`end` 为 `Asia/Shanghai` 本地 `HH:MM` 且 `start < end`，数量按 2/2/2/1/0 固定。

#### 6.1.3 因子一致性（P0）

- `top_factors` 按贡献比降序；比值相同按分数降序。
- `impact` 阈值 0.8 / 0.5 正确；边界 0.8 → positive，0.5 → negative。
- 任一因子 `0 ≤ score ≤ max_score`；总分等于 7 项和。
- 骤降种子（劝退）F1=15 且 `PRESSURE_PLUNGE.message` 含「2–4 小时」；≥5 级风 F4≤3 且 `GALE` 出现；雷雨时 `RAINSTORM.level="danger"` 且 `band="劝退"`。
- `alerts` 不得出现字符串元素；`forced=true` 的强制提示不得被过滤或降级。

#### 6.1.4 v1.1 规则补全回归（P0）

| 项 | 输入 | 期望 |
|---|---|---|
| F3 区间 | 日均温 20℃、`abs(Δ24h)=7℃` | 6 分 |
| F3 日均温修正 | 日均温 30℃、`abs(Δ24h)=1℃` | 15−3=12 分 |
| F3 双修正 | 日均温 30℃、`abs(Δ24h)=9℃`、昼夜温差 13℃ | 3−3−3=0（下限 0） |
| F4 风级 | 5 级（8.0m/s）→3；6 级（10.8m/s）→0 | 与契约一致 |
| F4 下风口 | 钓位 `downwind=true` | 仅钓位级 `fish_score` 的 F4 部分 +3（上限 15）；`/api/fish-activity` 通用 F4 不变 |
| F6 冬季 | 日均温 4℃、处于日出窗口 | 10 分（窗口优先） |
| F6 冬季非窗口 | 日均温 4℃、非窗口 | 2 分 |
| species | `species=黑鱼` | `/api/fish-activity` 返回 422 `INVALID_SPECIES`；Agent 内部归一化后按通用分，不 422 |
| 时区 | `at=2026-04-11T21:30:00Z` 与 `at=2026-04-12T05:30:00` | 业务结果一致（除 `generated_at`） |

#### 6.1.5 v1.2 口径回归（P0）

| 项 | 输入 | 期望 |
|---|---|---|
| F2 兜底内层 | 无 30 天分布，气压 1005 / 1012 / 1020hPa | 20 分（闭区间） |
| F2 兜底外层 | 气压 1000 / 1002 / 1025hPa | 12 分（闭区间） |
| F2 兜底异常 | 气压 999 / 1026hPa | 6 分 |
| F5 暴雨 | 日降水 50mm（或 `is_thunderstorm=true`） | 0 分且强制劝退，`RAINSTORM` 出现 |
| F5 大雨 | 日降水 25mm | 3 分（左闭右开：25 记大雨） |
| F5 中雨 | 日降水 5mm | 7 分（5 记中雨） |
| F5 小雨 | 日降水 0.1mm | 10 分 |
| F5 无雨 | 晴/阴、无雨 | 8 分 |
| F5 雨后 | 雨停 0–6h、当日无雨 | 7 分 |
| F5 晴热优先 | 连续晴热 >3 天 | 5 分（优先于无雨 8 分） |
| `best_windows` 数量 | 极佳 / 良好 / 一般 / 偏差 / 劝退 | 2 / 2 / 2 / 1 / 0 项；前四档分别含「日出窗口」「日落窗口」标签（偏差仅「日出窗口」） |
| 工具名 | 三类问句的 `tool_calls` | 仅 `get_fish_activity` / `recommend_spots`，无别名 |
| 单程取整 | `drive_seconds_out=89 / 90` | `drive_minutes_one_way=1 / 2`（half-up） |

> F5 优先级：雷雨/暴雨 > 大雨 > 中雨 > 小雨 > 雨后 0–6h > 连续晴热 >3 天 > 无雨；降水端点按左闭右开，50mm 记暴雨。F2 内层区间优先于外层。

### 6.2 三类问句验收（P0）

前置：`LLM_API_KEY` 为空，Mock 模式。

| ID | 请求 | 断言 |
|---|---|---|
| AT-CHAT-01 | `今天这气压适合钓鱼吗？` + 杭州坐标 | 200；`mode="fallback"`；`tool_calls` 含鱼情工具且 `status="ok"`；`fish_activity` 非空；`reply` 含档位/行动建议 + 至少 1 条理由 + 时间窗口；无天气播报式长句；`ai_disclosure` 精确 |
| AT-CHAT-02 | `附近哪里野钓好？` | 200；`tool_calls` 含钓位工具且 `status="ok"`；`spots` 非空且 `spots.spots` ≥1；`reply` 含至少 1 个钓位名 + 往返耗时 + 理由；不得出现「保证合法」 |
| AT-CHAT-03 | `明早几点去最好？` | 200；`fish_activity` 非空；`reply` 含至少 1 个 `HH:MM` 时段与理由；不得只回「看天气」 |
| AT-CHAT-04 | `帮我写首诗` | 200；`reply` 非空并引导至三类可回答问题；不得 500、不得编造鱼情 |

统一断言：`reply` 2–5 句、无「必上鱼/保证爆护/百分百」、不原样播报天气；`session_id` 回显；`tool_calls[].status` 仅 `ok|error`。

### 6.3 钓位、坐标与过滤验收（P0）

| ID | 检查 | 断言 |
|---|---|---|
| AT-SPOT-01 | 默认推荐 | 200；`spots` 1–5 条；每条往返=去+回且 ≤7200s；`drive_minutes_one_way == round_half_up(drive_seconds_out/60)`（89s→1、90s→2）；`total_score` 降序、同分往返升序；`reasons` 2–4 条含车程与鱼情依据；`navigation_url` 含入口坐标；`meta.generated_at` 为 UTC |
| AT-SPOT-02 | 禁钓过滤 | 返回结果名称不含「一级保护区/饮用水源/禁钓/养殖场/承包塘」；`filtered.forbidden` ≥1；同时命中禁钓与超时的候选只计入 `forbidden` |
| AT-SPOT-03 | 往返过滤 | 所有 `spots` 往返 ≤7200s；`filtered.over_two_hours` ≥2；不存在 `drive_seconds_round_trip > 7200` 的条目 |
| AT-SPOT-04 | 入口回退 | 至少 1 条 `entry_precision="center_fallback"`；其 `entry_location_gcj02` 等于中心点；UI 显示「端点精度较低」；其余为 `entr_location` |
| AT-SPOT-05 | 半径硬校验 | `radius_km=150` → 200；150.1/0/-1 → 422；单测证明所有 Provider 调用的 `radius ≤ 50000`，>50km 经分片且去重 |
| AT-SPOT-06 | 参数边界 | `limit=1` 与 `10` → 200；0/11 → 422；lat=91/lon=181 → 422；缺失 lat/lon → 422 |
| AT-SPOT-07 | 坐标回归 | `wgs84_to_gcj02(39.915, 116.404)` 误差 ≤1e-4°；往返误差 ≤1e-5°；杭州示例点与契约 §4.3 偏差 ≤1e-3°（约 110m） |
| AT-SPOT-08 | 确定性 | 同一请求连续 3 次，除 `generated_at` 外钓位 id、距离、时长、排序一致 |
| AT-SPOT-09 | 空态 | 无候选时 200 + `spots=[]`；`filtered` 计数非负；UI 显示空态建议（可用全过滤种子或单测覆盖） |
| AT-SPOT-10 | `filtered` 不变式 | `total_candidates = forbidden + over_two_hours + eligible`；`eligible = returned + truncated_by_limit`；`returned = len(spots)`；所有字段非负；`total_candidates` 为去重后、过滤前基数 |

### 6.4 边界与异常验收

| ID | 场景 | 期望 |
|---|---|---|
| AT-ERR-01 | `lat/lon` 缺失或越界 | 422，`detail.code="VALIDATION_ERROR"`；不 500 |
| AT-ERR-02 | `radius_km` 越界 | 422，`detail.code="VALIDATION_ERROR"`；不静默降级 |
| AT-ERR-03 | `limit` 越界 | 422，`detail.code="VALIDATION_ERROR"` |
| AT-ERR-04 | 非法 `species` | 422，`detail.code="INVALID_SPECIES"`（v1.1 已裁决，不允许宽松降级） |
| AT-ERR-05 | `at` 非法 | 422，`detail.code="VALIDATION_ERROR"` |
| AT-ERR-06 | `message` 为空或 >500 字 | 422，`detail.code="VALIDATION_ERROR"` |
| AT-ERR-07 | `message` 恰 500 字 | 200，不 500 |
| AT-ERR-08 | 对话缺 `location` | 422，`detail` 提示前端获取定位 |
| AT-ERR-09 | `history` 12 条 | 200；服务端只使用最近 10 条 |
| AT-ERR-10 | 天气源失败 | 503，`detail` 含 `code`、`message`，不返回堆栈 |
| AT-ERR-11 | 钓位源失败 | 503，`detail` 含 `code`、`message`；若部分成功则说明缺口 |
| AT-ERR-12 | Agent 工具失败 | 200；`tool_calls[].status="error"`；`reply` 可读兜底 |
| AT-ERR-13 | LLM Key 存在但调用失败 | 200；`mode="fallback"`；三类意图仍可用 |
| AT-ERR-14 | 位置权限被拒 | H5 提示改用手动经纬度，不白屏 |
| AT-ERR-15 | 无符合条件钓位 | 200 + 空列表 + 空态文案；不推荐禁钓/超时项 |
| AT-ERR-16 | `at` 不带时区 | 按 `Asia/Shanghai` 解释；与同时刻 UTC 输入业务结果一致 |

### 6.5 H5 与合规验收

| ID | 检查 | 断言 |
|---|---|---|
| AT-UI-01 | 主流程 | 手动输入 30.2741/120.1551 → 评分卡（分数/档位/Top3/窗口/水深）→ 钓位列表（名称/类型/单程/往返/理由/导航）→ 3 类问句对话，全流程无报错 |
| AT-UI-02 | AI 标识与免责 | 页面常驻「AI 生成 · 仅供参考」；结果页可见免责全文；Mock 模式标识可见；对话兜底标识可见（P1） |
| AT-UI-03 | 精度、时区与过滤摘要 | center_fallback 卡片显示「端点精度较低」；车程带「预估」；导航新窗口；时段按 `Asia/Shanghai` 展示；如展示 `filtered`，数字须自洽（P1） |
| AT-UI-04 | 响应式 | 375px 宽无横向滚动；按钮/输入可用 |
| AT-UI-05 | 无 Key 泄露 | 页面源码与网络请求不含 `AMAP_WEB_KEY`、`LLM_API_KEY`、`sk-`；仅同源 `/api/*` |
| AT-UI-06 | 禁止表述与评分依据 | 页面无「必上鱼/保证爆护/百分百/绝不空军」；评分依据数据条（`weather_summary`）标题必须为「评分依据（非天气预报）」，仅含当前因子数据，无多时段预报/天气播报式面板；数据源与生成时间可见 |
| AT-CMP-01 | 鱼情标识 | `ai_disclosure` 精确；`data_sources` 含 Mock 与规则引擎标识 |
| AT-CMP-02 | 对话标识 | `ai_disclosure` 精确；回复无承诺性表述 |
| AT-CMP-03 | 数据来源与隐私 | 无数据库写入；日志不含完整经纬度；`.env.example` 仅占位符 |

### 6.6 追溯矩阵

| 目标 | 需求 | 用例 |
|---|---|---|
| G1 鱼情 | FR-FA-01~07 | AT-FA-01~05、§6.1.1（边界）、§6.1.4（v1.1 规则补全）、§6.1.5（v1.2 口径）、DEMO-FA-06 |
| G2 钓位 | FR-SPOT-01~08 | AT-SPOT-01~10、§6.1.5（单程取整） |
| G3 对话 | FR-CHAT-01~05 | AT-CHAT-01~04、AT-ERR-06~13、§6.1.5（工具名） |
| G4 H5 | FR-UI-01~04 | AT-UI-01~06 |
| G5 工程/合规 | FR-CMP-01~05 | AT-CMP-01~03、DEMO-ENG-01 |

---

## 7. 非功能需求

| 项 | 要求 |
|---|---|
| 性能 | Mock 模式下 `/api/spots/recommend`、`/api/agent/chat` P95 ≤3s；`/api/fish-activity` ≤3s |
| 可复现 | Mock 输入相同则输出相同（除 `generated_at`）；五档种子可命中 |
| 可用性 | 任一上游失败不返回 500 堆栈；对话必须给可读兜底 |
| 密钥 | 前端零 Key；仓库无真实 Key；服务端 Key 仅环境变量 |
| 隐私 | 不长期存储精确位置；日志不打印完整经纬度 |
| 时区 | 业务判定与展示 `Asia/Shanghai`；`at` 不带时区按东八区解释；`generated_at` 为 UTC；鱼情响应含 `timezone` |
| 兼容 | Python 3.12；现代桌面与移动浏览器；375px 起 |
| 代码质量 | `pytest` 全绿；`ruff check` 通过（允许记录明确的忽略项） |

---

## 8. 契约对齐与裁决记录

### 8.1 v1.1 已裁决（本文已对齐）

| 事项 | v1.1 结论 |
|---|---|
| `alerts` 结构 | 对象数组 `{code, level, message, forced}`，`level` 取 danger / warning / info；至少 `RAINSTORM`(danger)、`GALE`(danger)、`PRESSURE_PLUNGE`(warning，2–4h)；暴雨/雷雨强制劝退 |
| `filtered` 口径 | `total_candidates`=去重后过滤前；顺序禁钓→往返→排序截断；`total_candidates=forbidden+over_two_hours+eligible`；`eligible=returned+truncated_by_limit`；双命中只计 `forbidden` |
| 时区 | 业务与展示 `Asia/Shanghai`；`at` 无时区按东八区；`generated_at` UTC；响应含 `timezone` |
| 错误体 | 所有 4xx/5xx 统一 `detail{code,message}`；422 为 `VALIDATION_ERROR`，可带 `fields` |
| Mock 五档 | `scenario` 取 excellent / good / fair / poor / no_go（仅 Mock）；`no_go` 必须劝退 |
| 测试注入 | Provider 经 `get_weather_provider()` / `get_geo_provider()` 获取，支持 `dependency_overrides`；`compute_fish_activity` 为纯函数 |
| 规则补全 | F3 6–8℃ 记 6；F4 下风口 +3 仅钓位级 `fish_score`；F6 冬季以日均气温 <5℃ 代理；非法 `species` → 422 `INVALID_SPECIES` |

### 8.2 v1.2 已裁决（本文已对齐）

| ID | 事项 | v1.2 结论 | 验收落点 |
|---|---|---|---|
| C-01 | F2 兜底分档 | 无 30 天分布时：1005–1020hPa → 20；1000–1005 或 1020–1025 → 12；<1000 或 >1025 → 6；内层区间优先 | §6.1.5、DEMO-FA-05 |
| C-02 | F5 降水口径 | 雷雨/暴雨（`is_thunderstorm` 或日降水 ≥50mm）→ 0 且强制劝退；大雨 25–50mm → 3；中雨 5–25mm → 7；小雨 0.1–5mm → 10；无雨 → 8；雨后 0–6h → 7；连续晴热 >3 天 → 5（优先于无雨） | §6.1.5、DEMO-FA-04/05 |
| C-03 | `best_windows` 数量 | 极佳 / 良好 / 一般各 2 项（日出、日落），偏差 1 项（日出），劝退 0 项；`Asia/Shanghai` 本地 `HH:MM` | §6.1.2、DEMO-FA-01~05 |
| C-04 | Agent 工具名 | 固定 `get_fish_activity` / `recommend_spots`，`tool_calls[].name` 精确匹配，不接受语义等价别名 | §6.1.5、DEMO-CHAT-01~03 |
| C-05 | 单程分钟取整 | `drive_minutes_one_way = round_half_up(drive_seconds_out / 60)`，89s→1、90s→2 | §6.1.5、AT-SPOT-01、DEMO-SPOT-01 |
| C-06 | 强制劝退与分数 | 不改写总分与因子和；劝退由 `band`/`advice`/`alerts` 表达，劝退种子原始分 <40 | AT-FA-05、DEMO-FA-05 |

> 约定：F5 优先级为雷雨/暴雨 > 大雨 > 中雨 > 小雨 > 雨后 0–6h > 连续晴热 >3 天 > 无雨；降水端点按左闭右开（5mm 记中雨、25mm 记大雨、50mm 记暴雨）。F5 为临时口径，待真实数据校准。

---

## 9. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| Mock 与真实数据源行为不一致 | 真实链路未验证 | 适配器接口隔离；README 标注「真实 Key 未实测」；Backlog 跟踪 |
| 规则口径与真实数据偏差（F2/F5 分档、边界端点） | 同一输入评分争议 | v1.1/v1.2 已裁决并写入 §4.1、§8.1、§8.2；F5 为临时口径，规则配置化，真实数据校准列 Backlog |
| 五档种子与实现耦合 | 演示失败 | 种子作为 B-03 验收项；小测按 `scenario` + `at` 回归；失败即缺陷 |
| 强制劝退与分数观感 | 用户困惑 | 劝退种子原始分 <40；alerts 明示一票否决 |
| 50km 分片仅在 Mock 验证 | 真实召回漏检 | 保留硬校验/去重单测；真实 Key 实测列 Backlog |
| fallback 意图误判 | 答非所问 | 关键词表 + 澄清兜底；三类问句纳入 P0 验收 |
| 禁钓数据仅为示例 | 合规风险 | UI 免责 + 自行确认合法性；权威矢量边界列 Backlog |
| 位置隐私 | 合规风险 | 无持久化；日志脱敏；前端不落盘 |

---

## 10. 演示与发布路径

1. 按 README 安装依赖（显式 Python 3.12 路径），`FISHAGENT_MOCK_MODE=true` 启动。
2. `GET /health` 确认 `mock_mode=true`。
3. 打开 `http://127.0.0.1:8000/`，手动输入 `30.2741 / 120.1551`，完成评分卡 → 钓位 → 对话。
4. 按 `fixtures/demo_scenarios.json` 的 `DEMO-FA-01~05` 依次以 `scenario=excellent|good|fair|poor|no_go` + 对应 `at` 请求，确认五档齐备且 `no_go` 含三条强制提示。
5. 按 `DEMO-CHAT-01~03` 验证三类问句；无 Key 时确认 `mode="fallback"`。
6. 执行 `pytest`、`ruff check`；记录结果与证据。
7. 本轮仅本地演示，不对外发布、不部署公网；真实 Key 实测列 Backlog。

---

## 附录 A：精确文案

```
AI 标识：AI 生成 · 仅供参考
鱼情免责：本结论由 AI 辅助生成，仅供参考，不承诺渔获。
对话免责：本内容由 AI 生成，仅供参考，不承诺渔获。
页面免责：FishAgent 仅提供基于公开数据的参考性建议，不保证渔获结果。请遵守当地渔业法规与禁钓规定，自行确认垂钓合法性；注意涉水安全，恶劣天气请勿出钓，建议结伴出行。本演示仅将定位用于本次推荐，不做长期保存。
Mock 标识：Mock 演示模式 · 天气与钓位为模拟数据
回退标注：端点精度较低
车程标注：预估车程，实际以导航为准
兜底标注：当前为规则兜底回答
劝退文案：今天不建议出钓
```

## 附录 B：五档种子目标分数拆解（实现对齐用，非精确断言）

| 因子 | 极佳 | 良好 | 一般 | 偏差 | 劝退 |
|---|---|---|---|---|---|
| F1（25） | 25（缓降 5） | 18（稳定 1） | 12（缓升 4） | 5（骤升 10） | 15（骤降 12，提示 2–4h） |
| F2（20） | 20（1012，兜底内层） | 20（1010，兜底内层） | 20（1008，兜底内层） | 20（1018，兜底内层） | 12（1002，兜底外层） |
| F3（15） | 15（20℃，变温 1） | 10（变温 4） | 10（变温 5） | 0（变温 9 → 3；日均 30℃ −3） | 0（变温 -9 → 3；日均 >32℃ −3） |
| F4（15） | 15（2–3 级） | 8（4 级） | 8（4 级） | 9（1 级） | 0（6 级，安全提示） |
| F5（10） | 8（无雨） | 8（无雨） | 8（无雨） | 5（连续晴热） | 0（雷雨，强制劝退） |
| F6（10） | 10（日出窗口） | 10（日出后 1.5h 内） | 7（春秋非窗口） | 7（春秋非窗口） | 3（盛夏正午高温） |
| F7（5） | 5（多云） | 5（多云） | 3（晴） | 3（晴） | 4（阴） |
| 目标总分 | 98 | 79 | 68 | 49 | 34 |

> 说明：F3 按 v1.1 口径（6–8℃ 记 6；日均温不在 15–28℃ 基础分 −3，下限 0）；F2 按 v1.2 兜底口径，1002hPa 落 1000–1005 外层档记 12。上表是 Mock 调参目标，允许 ± 少量偏差，但必须落在对应档位；劝退场景目标总分 34，且必须 <40。若实现选择其他拆解，以 §6.1.2 的档位与 alerts 断言为准。
