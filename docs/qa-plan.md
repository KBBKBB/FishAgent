# FishAgent MVP 测试计划（QA Plan）

> 版本：v1.3 ｜ 编制：小测 ｜ 日期：2026-10-22
> 依据：`docs/api-contract.md` v1.3、`docs/project-plan.md`、`docs/mvp-prd.md`、`Spec/Mission.md`、`Spec/TechStack.md`、`项目立项文档.md` 第 2.4 节
> 适用版本：FishAgent MVP（Mock 模式默认开箱可跑；v1.3 增补真实模式最终复跑口径）
>
> v1.1 变更：按契约 v1.1 收敛 `alerts` 对象结构、`filtered` 不变式、Asia/Shanghai 时区、统一错误体、Mock `scenario` 五档触发、Provider 注入点，以及 F3/F4/F6 补全口径；关闭 A-02~A-05、A-07。
> v1.2 变更：按契约 v1.2 收敛 F2 兜底区间、F5 降水优先级、`best_windows` 按档位固定数量、Agent 工具名固定为 `get_fish_activity`/`recommend_spots`、单程分钟 `round_half_up`。
> v1.3 变更：按契约 v1.3 增补 `filtered` 的 `unavailable/evaluated/unevaluated` 三字段与三条不变式、真实模式多 typecode 水体召回、批量距离预筛与有界精算、P2-B 入口 `center_fallback` 方案 A、P2-C `unevaluated`/3s 慢加载提示验收；新增 SP-19~SP-22、AG-15、E2E-13~E2E-15；补充 97 个自动化用例映射。

## 1. 测试目标

用独立证据回答以下问题：

1. Mock 模式无需任何外部 Key，后端可启动，四个端点返回契约内响应。
2. F1–F7 规则引擎的因子、权重、总分、五档、Top3、强制提示符合契约与立项文档 2.4。
3. 钓位推荐满足四条红线：单次 `radius ≤ 50000m`、去/回程分别计算且合计 `≤ 7200s`、入口坐标优先/缺失标记、禁钓候选排除。
4. Agent 在无 `LLM_API_KEY` 时正确降级为确定性路由，覆盖“鱼情/气压、附近钓位、时段建议”三类问句。
5. H5 可完成“输入位置 → 评分与因子 → 钓位列表 → 对话”主流程，并展示 AI 标识、免责声明、Mock 提示。
6. 关键合规项无泄漏：前端无 Key、高危禁钓候选不出现、结论不承诺渔获、坐标不混用。
7. 真实模式（Open-Meteo / 高德 / DeepSeek）在杭州单点完成 50/100km 主链路：Top5 为自然水体、往返 ≤7200s、`filtered` v1.3 三条不变式成立、100km 目标 <30s（试点绝对上限 60s）。
8. P2-C 展示可用：`filtered.unevaluated > 0` 时 H5 显示「未评估 N（超出本轮预算）」；钓位请求 >3s 显示慢加载提示；375/1280 无横向溢出、无 console error。

## 2. 测试范围

### 2.1 范围内

| 域 | 覆盖内容 | 用例前缀 |
|---|---|---|
| 规则引擎 | F1–F7 评分、权重、总分、五档、Top3、impact、强制提示、AI 标识 | RE |
| 坐标 | WGS84→GCJ-02、反向转换、响应坐标系标注、天气使用 WGS84 | CO |
| 钓位 | 半径分片/硬校验、去/回程精算、往返过滤、入口坐标、禁钓过滤、排序、去重 | SP |
| API/运行时 | `/health`、OpenAPI、静态托管、错误格式、时间格式、密钥扫描 | API |
| Agent | 三类意图、fallback、参数校验、history、容错、延迟、合规话术、真实 LLM 输出 | AG |
| Web E2E | 定位/手动坐标、评分卡、钓位列表、对话、移动端、合规可见性、前端安全、P2-C 展示 | E2E |
| 真实模式 | 杭州单点 50/100km、水体召回、入口回退、`filtered` v1.3、耗时、真实三问、H5 E2E | SP-19~22、AG-15、E2E-15 |

### 2.2 范围外

- 真实链路仅覆盖杭州单点、单实例、50/100km；不做多城市、容量/配额压测、故障切换演练；真实配额与 P95 以试点监控为准。
- 微信小程序端、UGC、备案/算法登记、法务书面结论、生产部署与容量压测。
- 权威禁钓矢量边界的准确性；Mock 只验证过滤逻辑，不验证真实地理合规。
- 产品单元测试覆盖率指标。本角色的自动化测试以 **API 级黑盒 + 端到端** 为主；规则函数的定点断言仅作为边界补充证据，不替代 API/E2E 证据。
- 安全渗透、漏洞扫描、隐私合规审计。

### 2.3 角色边界

- 只修改 `backend/tests/` 与 QA 文档；不修改 `backend/fishagent/`、`web/`、`docs/mvp-prd.md`、`fixtures/` 等他人所有权内容。
- 不以修复缺陷为目标；缺陷附复现步骤、期望/实际、证据、影响与责任域，回报对应负责人并唤醒小项。
- 不执行 `git add` / `git commit` / `git push`，不创建 PR/MR。

## 3. 环境与前置条件

| 项 | 值 |
|---|---|
| 工作目录 | `D:\学习\GitHubCode\FishAgent` |
| Python | `C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe` |
| 安装 | `<python> -m pip install -e "backend[dev]"` |
| 启动 | `cd backend && <python> -m uvicorn fishagent.main:app --host 127.0.0.1 --port 8000` |
| 测试 | `<python> -m pytest backend/tests -q` |
| 静态检查 | `<python> -m ruff check backend` |
| 默认模式 | `FISHAGENT_MOCK_MODE=true`，`AMAP_WEB_KEY` / `LLM_API_KEY` 为空 |
| 真实模式 | `FISHAGENT_MOCK_MODE=false`；Key 仅写入本地 `backend/.env`，不进前端/文档/共享目录/证据/提交；独立 QA 使用临时端口，不重启 8018 |
| 真实限流 | `FISHAGENT_AMAP_CONCURRENCY=6`、`FISHAGENT_AMAP_QPS=2`；Agent 工具超时 `FISHAGENT_TOOL_TIMEOUT_SECONDS=45` |
| 浏览器 | 本机 Chrome/Edge，通过 `browser-harness` 以 CDP/Playwright 控制；视口至少覆盖 375×812、1280×900、1440×900 |
| 数据隔离 | 不写入生产库；Mock QA 不调用真实第三方；对话使用 `qa-` 前缀 session_id |

### 3.1 准入条件

1. `backend/` 与 `web/` 已交付，Mock 模式可启动。
2. `/health` 返回 200；三个业务端点可访问；`/` 返回 H5。
3. 小钱提供 Mock 场景触发方式（`at` 与场景映射，或内部开关）与 POI Mock 的确定性说明。
4. 小厚提供 Agent 无 Key 运行方式与 Web 启动方式。
5. 依赖安装成功，pytest 可收集测试。
6. 真实模式最终复跑：8018 已加载 P2-A 后端修复，或使用独立临时端口；Key 仅由本地 `.env` 注入，且与小钱/小厚的真实调用错峰，避免叠加高德配额。

未满足准入条件时，记录阻塞项与影响，不以“代码存在”替代运行证据。

## 4. 风险优先与执行顺序

| 层 | 内容 | 目的 | 对应用例 |
|---|---|---|---|
| L0 | 静态合规与密钥扫描 | 先排除 P0 合规风险 | API-06、E2E-07 |
| L1 | 启动与 API 冒烟 | 确认可测 | API-01/02/03 |
| L2 | 规则、坐标、钓位边界 | 验证核心红线 | RE、CO、SP |
| L3 | Agent fallback | 验证三类问句闭环 | AG |
| L4 | Web E2E 主流程 | 验证用户可见行为 | E2E-01~10 |
| L5 | 故障注入、延迟、兼容性 | 验证韧性与非功能 | AG-08/09/10、SP-15、E2E-08/11 |
| L6 | 真实模式最终复跑 | 验证真实 Provider 与 P2-C | SP-19~22、AG-15、E2E-13~15 |

执行原则：P0 用例全量执行；P1 用例在交付后执行；P2 视时间执行并披露未执行项。发现 P0 阻塞时，保留最小复现并立即回报，不继续堆叠无效用例。

## 5. 测试数据

### 5.1 固定坐标

| 名称 | WGS84 lat | WGS84 lon | 用途 |
|---|---|---|---|
| 杭州基准点 | 30.2741 | 120.1551 | 契约示例，主测试点 |
| 杭州偏移点 | 30.2800 | 120.1600 | 分片/去重/确定性 |
| 北京基准点 | 39.9042 | 116.4074 | 跨城市冒烟 |
| 远海点 | 0.0000 | 160.0000 | 空结果/容错 |
| 非法点 | 91 / -91 / 181 / -181 | — | 校验失败 |

已知坐标回归基准（契约示例）：WGS84 `(30.2741, 120.1551)` → GCJ-02 约 `(30.2756, 120.1598)`，允许误差 `±0.001°`；同时校验偏移量落在 50–500m 量级。

### 5.2 固定时刻

| `at` | 用途 |
|---|---|
| `2026-10-21T10:00:00Z` | 契约示例、确定性复跑 |
| `2026-03-15T04:00:00Z` | 春季（北京时间 12:00） |
| `2026-07-15T04:00:00Z` | 盛夏正午 |
| `2026-01-15T04:00:00Z` | 冬季 |
| `2026-10-22T21:30:00Z` | 日出窗口（北京时间 05:30 附近） |

时区口径（契约 v1.3，沿用 v1.2）：业务判定与展示固定 `Asia/Shanghai`；`at` 带时区按其转换，不带时区按东八区解释；`generated_at` 始终为 UTC（`Z`）。

### 5.3 五档触发数据

契约 v1.1 新增 `scenario=excellent|good|fair|poor|no_go`（仅 Mock 生效）作为五档主触发方式；v1.2 固定 `best_windows` 数量，v1.3 未变更。PRD §5.1 的 `at` 种子作为兼容回归；两者都应得到同一目标档位。

| `scenario` | 目标档位 | `at` 兼容种子（UTC） | 关键断言 |
|---|---|---|---|
| `excellent` | 极佳 | `2026-04-11T21:30:00Z` | 85–100；`advice="强烈建议出钓"`；`alerts=[]`；`best_windows` 恰 2 个 |
| `good` | 良好 | `2026-04-13T00:00:00Z` | 70–84；F1=18；`advice="适合出钓"`；`best_windows` 恰 2 个 |
| `fair` | 一般 | `2026-04-14T02:00:00Z` | 55–69；F1=12；`advice="有机会，建议挑时段"`；`best_windows` 恰 2 个 |
| `poor` | 偏差 | `2026-04-15T04:00:00Z` | 40–54；F1=5；`advice="不太理想，建议就近作钓"`；`best_windows` 恰 1 个 |
| `no_go` | 劝退 | `2026-06-20T06:00:00Z` | <40；`advice="今天不建议出钓"`；`best_windows=[]`；至少含 `RAINSTORM` 或 `GALE` 强制提示 |

### 5.4 真实模式固定数据（v1.3）

| 项 | 值 | 用途 |
|---|---|---|
| 起点 | 杭州西湖 WGS84 `30.2741 / 120.1551` | 唯一真实模式基准点 |
| 半径 | `50km`、`100km` | Top5、`filtered`、耗时对比 |
| Top5 参考 | 50/100km 均为古新河、西溪、东河、中河、希颜溪（以当次响应为准） | 自然水体率、去重、往返约束 |
| 水系特例 | 华家池 `190301\|120302\|190204`、华家池(上城区) `120302\|190204`、莫婆桥 `190307\|190204` | P2-A 多 typecode 保留 |
| 入口参考 | 50km 首屏 50 个自然水体仅 9 个有 `entr_location`；Top5 河流均无 | P2-B `center_fallback` 方案 A |
| 性能基线 | 100km 20.79–21.77s；50km 15.65s（历史实测，以复跑为准） | 目标 <30s、试点绝对上限 60s |

### 5.5 Mock 数据最低要求（契约 §5）

| 编号 | 要求 | 对应用例 |
|---|---|---|
| MD-01 | 天气 Mock 覆盖五档典型场景，通过 `scenario` 确定性触发；`at` 种子作为兼容回归 | RE-02、RE-21 |
| MD-02 | 包含气压 24h/3h/6h 变化、气温变温、风速、降水、云量、日出日落 | RE-06~13 |
| MD-03 | POI ≥8 个：2 个往返 ≤2h、1 个单程 >1h 但往返 ≤2h、2 个往返 >2h、1 个禁钓、1 个缺入口坐标 | SP-04~09 |
| MD-04 | 结果确定性可复现 | RE-18、SP-14 |
| MD-05 | `no_go` 至少包含暴雨/雷雨或 ≥5 级风，确保强制劝退 | RE-02、RE-14 |

## 6. 测试用例矩阵

### 6.1 规则引擎与合规（RE）

| ID | P | 来源 | 步骤/输入 | 期望结果 | 证据 |
|---|---|---|---|---|---|
| RE-01 | P0 | 契约 §4.2 | `GET /api/fish-activity?lat=30.2741&lon=120.1551&at=2026-10-21T10:00:00Z` | `factors` 恰为 F1–F7 七项；`max_score` 依次为 25/20/15/15/10/10/5；每项 `0 ≤ score ≤ max_score`；`score` 总和等于 `score` 字段，且 0–100 | JSON |
| RE-02 | P0 | 契约 §4.2/§5、PRD §6.1.2 | 以 `scenario=excellent/good/fair/poor/no_go` 依次请求；再用 PRD §5.1 对应 `at` 种子回归 | 档位与区间一致：`≥85 极佳`、`70–84 良好`、`55–69 一般`、`40–54 偏差`、`<40 劝退`；`advice` 与五档固定文案一致；`best_windows` 数量分别为 2/2/2/1/0；`no_go` 的 `advice` 恰为「今天不建议出钓」且 `best_windows=[]` | 10 组 JSON |
| RE-03 | P1 | 契约 §4.2、PRD §6.1.1 | 对 85/84、70/69、55/54、40/39 构造总分（调用 `compute_fish_activity` 等价可测入口） | 边界分别落入极佳/良好、良好/一般、一般/偏差、偏差/劝退；0 与 100 极值不崩溃 | 规则函数输出 + 代码位置 |
| RE-04 | P0 | 契约 §4.2 | 任一正常场景 | `top_factors` 长度为 3；按 `score/max_score` 降序、再按 `score` 降序；每项与 `factors` 中同 code 项完全一致；无重复 code | JSON |
| RE-05 | P0 | 契约 §4.2 | 遍历 `factors` | `ratio ≥ 0.8 → positive`；`ratio ≤ 0.5 → negative`；其余 `neutral`；边界 0.8/0.5 取值正确 | JSON 断言 |
| RE-06 | P0 | 立项 2.4.2 F1、PRD §4.1 | 固定气象样本：-4.2/-0.5/-3/+5/+9 hPa（24h） | 分别得 25/18/25/12/5（2–3hPa 归缓变）；骤降 -9 时 `alerts` 含 `PRESSURE_PLUNGE` 与「有效窗口仅 2–4 小时」；F1 明细可见未来 24h 与 3h/6h 变化 | JSON + 注入样本 |
| RE-07 | P1 | 立项 2.4.2 F2、契约 §4.2 | 无 30 天分布，`pressure_msl` 分别取 1005–1020、1000–1005、1020–1025、<1000、>1025 | 分别得 20/12/12/6/6；`detail` 明示兜底口径 | JSON |
| RE-08 | P1 | 契约 §4.2 F3 | 日均温 15–28℃ 且 24h 变温 ≤3/3–6/6–8/>8；日均温不在 15–28℃；昼夜温差 >12 | 分别 15/10/6/3；基础分 -3、昼夜温差再 -3，均下限 0 | JSON |
| RE-09 | P1 | 契约 §4.2 F4 | 风力 0–1/2–3/4/5/≥6 级 | 分别 9/15/8/3/0；≥5 级 `alerts` 含 `GALE` danger；`/api/fish-activity` 通用 F4 不计算下风口 +3（下风口仅用于钓位级 `fish_score`） | JSON |
| RE-10 | P1 | 立项 2.4.2 F5、契约 §4.2 | 雷雨/暴雨（`is_thunderstorm=true` 或日降水 ≥50mm）；大雨 25–50mm；中雨 5–25mm；小雨 0.1–5mm；无雨；雨后 0–6h；连续晴热 >3 天 | 分别 0（并强制劝退）/3/7/10/8/7/5；连续晴热优先于无雨；暴雨/雷雨强制劝退并提示 | JSON |
| RE-11 | P1 | 契约 §4.2 F6 | 日出前后 1.5h、日落前 2h、春秋其他时段、盛夏正午 >32℃、冬季日均气温 <5℃、其余 | 分别 10/10/7/3/2/5；窗口内优先 10；冬季以日均气温 <5℃ 代理水温，窗口判定与 `sunrise`/`sunset` 自洽 | JSON |
| RE-12 | P1 | 立项 2.4.2 F7 | 云量 30–70%、>70%、<30% | 分别 5/4/3 | JSON |
| RE-13 | P0 | 契约 §4.2 | 暴雨/雷雨、≥5 级风、24h 骤降 >8hPa 三类场景 | `alerts` 为对象数组，每项含 `code/level/message/forced`；至少覆盖 `RAINSTORM` danger、`GALE` danger、`PRESSURE_PLUNGE` warning；强制项 `forced=true`；骤降提示含 2–4h 窗口 | JSON |
| RE-14 | P0 | 契约 §4.2、Mission P1 | 暴雨/雷雨场景 | `band` 必须为「劝退」，`advice` 为「今天不建议出钓」，`recommendation` 含明确理由 | JSON |
| RE-15 | P0 | 契约 §2/§4.2、TechStack R6 | 任一业务响应与 Agent 响应 | `ai_disclosure` 存在且含 AI 与“仅供参考/不承诺渔获”；`advice`/`reply` 不含「必上鱼」「保证爆护」「100%」等承诺词 | JSON + 正则 |
| RE-16 | P1 | 契约 §4.2 | `species` 取鲫鱼/鲤鱼/草鱼/鲢鳙；缺省；未知值「鲨鱼」 | 合法值与缺省均 200；`suitable_species` 非空且为字符串数组；未知值 422 且 `code=INVALID_SPECIES` | JSON |
| RE-17 | P0 | 契约 §4.2 | `lat=-91/91`、`lon=-181/181`、缺失、非数字 | 422；无 500；错误体可解析 | JSON |
| RE-18 | P1 | 契约 §4.2 | 同一输入连续请求 2 次 | 两次 `score`、`band`、`factors`、`top_factors` 完全相同；`generated_at` 可不同 | 2 组 JSON |
| RE-19 | P1 | 契约 §4.2、立项 2.4.4 | 正常场景 | `best_windows` 非空，时间为 `HH:MM`，start < end；`water_depth`、`suitable_species` 非空 | JSON |
| RE-20 | P1 | 契约 §2/§4.2 | 正常场景 | `data_sources` 含 Mock 标识；`generated_at` 为 ISO 8601 UTC（以 `Z` 结尾）；`timezone="Asia/Shanghai"` | JSON |
| RE-21 | P1 | 契约 §4.2/§5 | `scenario=bogus`；真实模式传 `scenario` | 非法枚举 422 `VALIDATION_ERROR`；真实模式忽略 `scenario` 而非改变规则结果 | JSON |
| RE-22 | P1 | 契约 §2 | 同一时刻分别传 `at=2026-10-21T18:00:00`（无时区，按东八区）与 `at=2026-10-21T10:00:00Z` | 两次 `score`、`band`、`factors`、`best_windows` 一致（证明时区换算正确） | 2 组 JSON |
| RE-23 | P1 | 契约 v1.2 §4.2 | 五档各取一场景，读取 `weather_summary.sunrise/sunset` 与 `best_windows` | 窗口数量按档位 2/2/2/1/0；时间为 `HH:MM` 且 `start < end`；日出窗口约等于日出前 1.5h 至日出后 1.5h，日落窗口约等于日落前 2h 至日落（允许分钟级取整） | JSON + 时间算术 |

### 6.2 坐标（CO）

| ID | P | 来源 | 步骤/输入 | 期望结果 | 证据 |
|---|---|---|---|---|---|
| CO-01 | P0 | TechStack R1、契约 §4.3 | `GET /api/spots/recommend?lat=30.2741&lon=120.1551` | `user_location.wgs84` 等于输入；`gcj02` ≈ `(30.2756, 120.1598)`，误差 ≤0.001°；WGS 与 GCJ 偏移在 50–500m 量级 | JSON + 计算脚本 |
| CO-02 | P1 | TechStack R1 | 直接调用 `gcj02_to_wgs84(wgs84_to_gcj02(p))`（或已知点对照） | 回环误差 ≤5m；转换入口唯一，业务代码不手写裸转换 | 脚本输出 + 代码检索 |
| CO-03 | P1 | 契约 §4.3 | 正常钓位响应 | 用户与钓位坐标均明确标注坐标系；钓位使用 `location_gcj02` / `entry_location_gcj02`；不得把 WGS 值塞入 GCJ 字段 | JSON |
| CO-04 | P1 | TechStack R1、契约 §4.2 | 注入天气 Provider spy | 天气调用使用 WGS84 原始坐标；地图调用使用 GCJ-02；两者不混用 | spy 日志 |
| CO-05 | P2 | 契约 §4.2 | 中国境外坐标（0,160） | 不失衡崩溃；转换策略不产生明显错误偏移；仅记录，不作强断言 | JSON |

### 6.3 钓位推荐与过滤（SP）

| ID | P | 来源 | 步骤/输入 | 期望结果 | 证据 |
|---|---|---|---|---|---|
| SP-01 | P0 | 契约 §4.3 | 仅传 `lat/lon` | 200；`meta.radius_km=100`、`round_trip_limit_seconds=7200`、`traffic_basis="baseline_estimate"`；`len(spots) ≤ 5` | JSON |
| SP-02 | P0 | 契约 §4.3 | `radius_km=1/100/150`；`radius_km=0/-1/150.1`；`limit=1/10/0/11` | 合法值 200；非法值 422 且统一错误体；radius 不得静默降级或 500 | JSON |
| SP-03 | P0 | TechStack R2、契约 §4.3 | 注入 POI Provider spy，分别请求 `radius_km=50/100/150` | 每次 around 调用 `radius ≤ 50000`；>50km 走分片/同心环（Mock 可简化但必须有调用与去重逻辑）；结果无重复 id | spy 日志 + JSON |
| SP-04 | P0 | TechStack R4、契约 §4.3 | 默认坐标请求 | 每个返回钓位满足 `drive_seconds_out + drive_seconds_back ≤ 7200` 且 `round_trip = out + back`；返回列表无超时项；`filtered.over_two_hours ≥ 2` | JSON + 算术断言 |
| SP-05 | P0 | TechStack R4 | 检查“单程 >1h 但往返 ≤2h”候选 | 该候选可被保留（证明未用单程×2 误杀）；其 `out > 3600` 且 `out+back ≤ 7200` | JSON |
| SP-06 | P0 | TechStack R4 | 构造 out=3500、back=3800（合计 7300）候选 | 必须被过滤，只计入 `filtered.over_two_hours`；不得因 `2×3500=7000` 而保留 | 注入数据 + JSON |
| SP-07 | P0 | TechStack R4、契约 v1.3 §4.3、PRD §4.2 | 默认结果与缺入口候选 | 有 `entr_location` 时 `entry_precision="entr_location"`；缺失时回退中心点、`entry_precision="center_fallback"` 且入口坐标与中心点一致；Mock 默认结果至少 1 个 fallback；真实模式允许 Top5 全部 `center_fallback`（方案 A，数据稀疏），但必须标记且 H5 提示精度较低，不单独判失败 | JSON + DOM 文本 |
| SP-08 | P0 | TechStack R5、契约 §4.3 | 默认结果 | 名称含「一级保护区」或落入示例禁钓圆区的候选不出现在 `spots`；`filtered.forbidden ≥ 1`；导航链接中也不得出现该候选 | JSON |
| SP-09 | P0 | 契约 v1.3 §4.3 | 默认请求（Mock 与真实各一次） | 精确满足三条不变式：`total_candidates = forbidden + evaluated + unevaluated`、`evaluated = unavailable + over_two_hours + eligible`、`eligible = returned + truncated_by_limit`；`returned = len(spots)`；九个字段均为非负整数；同时命中禁钓与超时只计 `forbidden`；Mock `total_candidates ≥ 8` | JSON + 算术断言 |
| SP-10 | P0 | 契约 §4.3 | 默认请求；`limit=1` | `total_score` 非增序；同分时往返秒数升序；`len(spots) ≤ limit`；`limit=1` 返回全局第一 | JSON |
| SP-11 | P0 | 契约 §4.3 | 默认请求 | `navigation_url` 以 `https://uri.amap.com/marker` 开头；`position=lon,lat` 与入口 GCJ 坐标一致（误差 ≤1e-4）；有入口时不得用中心点 | JSON 字符串解析 |
| SP-12 | P2 | 契约 §4.3 | 默认请求 | `distance_m > 0`；`reasons` 非空且包含往返时间/水域类型/鱼种适配等可读理由；`fish_score/total_score` 在 0–100 | JSON |
| SP-13 | P1 | 契约 §4.3 | `radius_km=1` 或远海坐标 | 200；`spots=[]`；`filtered` 与 `meta` 完整；不得 500 | JSON |
| SP-14 | P1 | 契约 §4.3 | 同一请求连续 2 次 | 钓位 id、顺序、分数、时长一致；`generated_at` 可不同 | 2 组 JSON |
| SP-15 | P1 | project-plan DoD | 预热后连续 10 次默认请求 | P95 ≤3s（本地 Mock，记录原始耗时） | 计时日志 |
| SP-16 | P1 | 契约 §4.3 | `radius_km=150` | 结果 id 唯一；分片边界的重复候选被去重；`meta.radius_km` 回显请求值 | JSON |
| SP-17 | P2 | 契约 §4.3 | 传入 `species=鲫鱼` | 200；若实现鱼种适配，`reasons` 或 `total_score` 应体现；不得 500 | JSON |
| SP-18 | P1 | 契约 v1.2 §4.3 | 检查每条 `spots` 的 `drive_seconds_out` 与 `drive_minutes_one_way` | `drive_minutes_one_way = round_half_up(drive_seconds_out / 60)`（四舍五入到整数分钟），与往返秒数分别独立；不得用单程×2 作为往返 | JSON + 算术断言 |
| SP-19 | P0 | 契约 v1.3 §4.3、P2-A | 高德召回单测：`190204\|190205` 主类型；含 `190301\|120302\|190204`、`120302\|190204`、`190307\|190204` 的混合 typecode；名称似水但 typecode 非水的餐饮/小区 | 按 `\|` 拆分后任一 code 命中 190204/190205 即保留；`_water_type` 选水体 code（河流/湖泊）；110202 仍需名称含水体系词；餐饮/小区/社区仍被过滤；返回 `water_type` 正确 | 单测 + 注入 POI JSON |
| SP-20 | P1 | 契约 v1.3 §4.3、P2-A/B | 真实模式 50/100km；批量距离 `origins≤100`、`destination` 单点；最近 100 预筛；每批 `max(2×limit,10)`、总精算上限 30、达到 limit 提前停止；并发 6/QPS 2 | 批量距离仅用于排序、不替代精算；去/回分别精算；100km Top5 自然水体且耗时 <30s（试点上限 60s）；0 次 CUQPS 超限；Mock 仍全量评估 | 单测 + 真实 JSON/日志 |
| SP-21 | P1 | 契约 v1.3 §4.3 | 注入单条路径规划失败（`ProviderError`） | 该候选计入 `unavailable`，不进入 `eligible`；其余候选正常返回；三条不变式仍成立；接口不 500 | 单测 + JSON |
| SP-22 | P1 | 契约 v1.3 §4.3、P2-C | 构造 `unevaluated > 0` 与 `unevaluated = 0` 两种响应；H5 查看筛选摘要 | `unevaluated` 仅表示超出本轮精算预算的候选，不计入 `evaluated/eligible`；>0 时显示「未评估 N（超出本轮预算）」；=0/缺失时不显示；375px 不溢出 | JSON + DOM 文本 + 截图 |

### 6.4 API 与运行时（API）

| ID | P | 来源 | 步骤/输入 | 期望结果 | 证据 |
|---|---|---|---|---|---|
| API-01 | P0 | 契约 §4.1 | `GET /health` | 200；`status="ok"`、`version="0.1.0"`、`mock_mode=true` | JSON |
| API-02 | P1 | 契约 §1、§4 | `GET /openapi.json` | 200；包含 `/health`、`/api/fish-activity`、`/api/spots/recommend`、`/api/agent/chat` | JSON 路径列表 |
| API-03 | P0 | 契约 §1、§6 | `GET /`、`/app.js`、`/styles.css`、`/api/fish-activity` | `/` 返回 HTML；静态资源 200；API 路由仍返回 JSON（未被静态托管吞掉） | HTTP 状态 + 响应片段 |
| API-04 | P1 | 契约 §2 | 触发非法 radius、非法 lat、缺 location 的 chat、未知路由 | 所有 4xx/5xx 统一 `{"detail":{"code","message"}}`；参数校验为 422 `VALIDATION_ERROR`，可带 `fields` 数组；不得出现 FastAPI 默认数组/HTML 错误页 | JSON |
| API-05 | P1 | 契约 §2/§4.2 | 正常鱼情响应 | `generated_at` 可被 ISO 8601 解析且为 UTC（`Z`）；`timezone="Asia/Shanghai"`；`at` 按契约时区解释 | JSON |
| API-10 | P1 | PRD §6.5 AT-CMP-03 | 检查运行日志与响应 | 日志不含完整经纬度明文；无数据库写入；`.env.example` 仅占位符 | 日志抽样 |
| API-06 | P0 | TechStack R3、契约 §3 | 扫描响应体、`web/` 静态文件、浏览器网络请求 | 不含真实 `AMAP_WEB_KEY`/`LLM_API_KEY`；不出现 `sk-` 或 32 位高德 Key 形态；`.env.example` 仅占位符 | 扫描日志 |
| API-07 | P2 | 契约 §1 | `GET /api/unknown`；`POST /api/fish-activity` | 404/405 JSON；不得 500；不得回退为 HTML 200 | HTTP 状态 |
| API-08 | P2 | 契约 §4.5 | `GET /api/demo/config` | 若实现：含 mock 模式、默认杭州坐标、AI 标识/免责文案；若未实现：记录为可选未交付 | JSON |
| API-09 | P2 | 契约 §2 | 10 个并发健康检查与规则请求 | 无 500、无连接重置；响应可解析 | 并发日志 |

### 6.5 Agent 对话（AG）

| ID | P | 来源 | 步骤/输入 | 期望结果 | 证据 |
|---|---|---|---|---|---|
| AG-01 | P0 | 契约 §4.4、project-plan DoD 4 | `POST /api/agent/chat`，message=「今天这气压适合钓鱼吗？」，location=杭州，无 LLM Key | 200；`mode="fallback"`；`tool_calls` 含 `get_fish_activity` 且 status=ok；`fish_activity` 非空；reply 有鱼情结论与时段建议 | JSON |
| AG-02 | P0 | 契约 §4.4、PRD §4.3 | message=「附近哪里野钓好？」 | 200；`mode="fallback"`；`tool_calls[].name="recommend_spots"` 且 status=ok；`spots` 非空；reply 含至少 1 个钓位名、往返耗时（标「预估」）与理由 | JSON |
| AG-03 | P0 | 契约 §4.4、project-plan DoD 4 | message=「明早几点去最好？」 | 200；`mode="fallback"`；调用 `get_fish_activity`；reply 含具体时段（`HH:MM` 或“窗口”），`best_windows` 非空 | JSON |
| AG-04 | P0 | 契约 §4.4 | 检查三类响应 | `tool_calls[].status ∈ {ok,error}`；`tool_calls[].name` 仅 `get_fish_activity`/`recommend_spots` 且与意图匹配；不得空数组冒充成功 | 3 组 JSON |
| AG-05 | P0 | 契约 §4.4、PRD §6.4 | 缺 `location`；空 message；501 字 message；缺 message；恰 500 字 message | 前四类 422 且提示定位/长度；500 字 200 不崩溃；均不得 500 | JSON |
| AG-06 | P1 | 契约 §4.4、PRD §4.3 | 传 12 条 history；带 `session_id="qa-session-1"`；不传 session_id | 200；传入时回显，缺省时服务端生成并回显；不因超长 history 报错；仅保留最近 10 条（不可外部确认时记录实现口径） | JSON |
| AG-07 | P0 | TechStack R6、契约 §4.4 | 检查回复与响应 | `ai_disclosure` 存在；reply 不含「必上鱼/保证爆护/100%」；不得原样播报天气预报式长列表 | JSON + 正则 |
| AG-08 | P1 | 契约 §4.4 | 注入工具异常（monkeypatch 或故障 Provider） | 200；reply 为可读兜底话术；对应 `tool_calls[].status="error"`；无 500/堆栈 | 注入日志 + JSON |
| AG-09 | P1 | 契约 §4.4 | 设置无效 `LLM_API_KEY`、不可达 `LLM_BASE_URL`、`LLM_TIMEOUT_SECONDS=2` | 自动降级 `mode="fallback"`；请求在可控时间内返回；无 500 | 启动日志 + JSON |
| AG-10 | P1 | 契约 §4.4 | 预热后连续 20 次 fallback 对话 | P95 ≤3s（本地 Mock，记录原始耗时） | 计时日志 |
| AG-11 | P0 | 契约 §4.4 | 三类响应中的 `fish_activity`/`spots` | 若非 null，字段符合 §4.2/§4.3；`fish_activity.factors` 为 7 项；`spots` 每项满足往返 ≤7200s | JSON |
| AG-12 | P2 | TechStack R8 | 人工阅读 reply | 只给鱼情结论/因子解释/建议，不出现“明日天气播报”式原文；必要时标注数据来源 | 人工记录 |
| AG-13 | P1 | PRD §6.2 AT-CHAT-04 | message=「帮我写首诗」 | 200；reply 非空并引导至鱼情/钓位/时段三类问题；不得编造鱼情、不得 500 | JSON |
| AG-14 | P1 | PRD §6.2 统一断言 | 三类问句各请求一次 | `reply` 为 2–5 句（按中文句号/问号/叹号切分）；不得只回「看天气」；不得原样播报天气长列表 | JSON + 句数统计 |
| AG-15 | P1 | 契约 v1.3 §4.4、P2-C | 真实 Key 三问：气压/钓位/时段；`FISHAGENT_TOOL_TIMEOUT_SECONDS=45` | 三问均 200；`mode="llm"`；工具名与状态正确（钓位为 `recommend_spots`，其余 `get_fish_activity`，均 `ok`）；2–5 句；无 Markdown 标记（`**`、`#`、列表符号）；无承诺词；钓位问句 ≤45s，超时按 200 + `status="error"` 兜底 | JSON + 计时 + 正则 |

### 6.6 Web E2E（E2E）

| ID | P | 来源 | 步骤/输入 | 期望结果 | 证据 |
|---|---|---|---|---|---|
| E2E-01 | P0 | 契约 §6 | 打开 `http://127.0.0.1:8000/` | 页面加载成功；控制台无 error；可见「AI 生成 · 仅供参考」、免责声明（不承诺渔获/遵守禁钓规定）、Mock 模式提示 | 截图 + console 日志 |
| E2E-02 | P0 | 契约 §6、project-plan DoD 5 | 手动输入 30.2741/120.1551 → 查询 | 展示总分、档位、Top3 因子、最佳时段、风险提示；请求返回契约字段；无整页刷新 | 截图 + 网络 JSON |
| E2E-03 | P1 | 契约 §6 | 点击定位按钮，浏览器授权模拟坐标 | 使用授权坐标发起请求；页面展示位置；授权拒绝时（E2E-04）有可读提示 | 截图 + 网络请求 |
| E2E-04 | P1 | 契约 §6 | 拒绝定位授权 | 提示无法获取定位并使用手动坐标；页面不崩溃；手动输入仍可用 | 截图 |
| E2E-05 | P0 | 契约 §6、TechStack R4 | 查看钓位列表 | 每项显示名称、类型、单程/往返时间、理由、导航链接；`center_fallback` 候选显示「端点精度较低」；列表项往返 ≤2h；导航链接指向高德 URI（不实际跳转） | 截图 + DOM 文本 |
| E2E-06 | P0 | 契约 §6、project-plan DoD 4/5 | 依次点击/输入三类示例问题 | 三类均有回复；fallback 模式可见（或等效提示）；reply 展示；无 JS 错误 | 截图 ×3 + console |
| E2E-07 | P0 | TechStack R3、契约 §6 | 打开 DevTools Network，完成一轮主流程 | 无 `restapi.amap.com`、`api.open-meteo.com`、`api.openai.com` 请求；无 Key 出现在页面源码/请求；仅同源 API | HAR/网络日志 + 扫描 |
| E2E-08 | P1 | 契约 §6、responsive-design | 375×812、390×844、1440×900 视口 | 375px 起无横向滚动；卡片/列表/对话可用；文字不重叠 | 3 张截图 + `scrollWidth <= clientWidth` |
| E2E-09 | P1 | 契约 §2、§6 | 输入空值/非法经纬度并提交 | 显示可读错误；不发送无效请求或正确处理 422；页面不崩溃 | 截图 + console |
| E2E-10 | P1 | 契约 §6 | 桌面与移动端完整主流程 | 两端均能完成“位置 → 评分 → 钓位 → 对话”；无控制台 error | 截图 + 日志 |
| E2E-11 | P2 | accessibility-audit（补充） | 键盘 Tab、表单标签、按钮可访问名、对比度 | 输入有 label；按钮有可访问名；焦点可见；状态不仅靠颜色；不阻塞发布 | 审计记录 |
| E2E-12 | P1 | 契约 §4.2/§4.3、PRD §6.5 | 触发 `no_go` 并查看鱼情卡；查看钓位统计与时间 | `alerts` 逐条渲染且危险项高亮；页面展示 `Asia/Shanghai` 语义的时段；`filtered` 统计与 API 一致（若 UI 展示）；对话 fallback 标识可见；页面无「必上鱼/保证爆护/百分百/绝不空军」 | 截图 + DOM 文本 |
| E2E-13 | P1 | 契约 v1.3 §4.3、P2-C | 真实 100km 返回 `unevaluated=625`；Mock 返回 `unevaluated=0`；观察钓位筛选摘要 | >0 时显示「未评估 625（超出本轮预算）」且与 API 一致；=0/缺失不显示；375px 不溢出；不误显示为可达钓位 | 截图 + DOM 文本 + API JSON |
| E2E-14 | P1 | 契约 v1.3 §4.3、P2-C | 将钓位响应延迟 4.2s；观察 3s 前后占位文案；请求完成/失败/新一轮请求 | 3s 前为「正在筛选附近钓位…」；>3s 改为「正在规划车程，真实模式约需 20 秒」；请求结束立即恢复/消失；无轮询；旧请求不得清掉新请求定时器 | 截图 + 计时 + DOM |
| E2E-15 | P1 | 契约 v1.3 §4.3/§4.4、P2-A/B/C | 真实模式 8018（或独立真实端口）100km 全流程：位置→鱼情→钓位→三问 | `mock_mode=false`；候选/返回数与 API 一致；Top5 自然水体、往返 ≤7200s；`center_fallback` 提示可见；375/1280 无横向滚动、console 0 error、请求同源；三问均 LLM、2–5 句、无 Markdown/承诺词；慢加载提示按实际耗时出现 | 截图 + 网络 JSON + console + 计时 |

### 6.7 自动化用例映射（97 例）

采集命令：`cd backend && <python> -m pytest tests --collect-only -q`；2026-10-22 当前工作树收集 **97 个**，全量运行 97 passed。参数化用例按实际收集数量计。

| 测试文件 | 收集数 | 主要映射 |
|---|---:|---|
| `test_agent_chat.py` | 15 | AG-01~07、AG-11、AG-13、AG-14 |
| `test_amap_recall.py` | 4 | SP-19、SP-20 |
| `test_api_contract.py` | 8 | API-01~05、API-07 |
| `test_compliance.py` | 11 | API-06、RE-15、AG-07、E2E-01/07/12 |
| `test_coords.py` | 6 | CO-01、CO-02 |
| `test_fish_activity.py` | 28 | RE-01~05、RE-13~23 |
| `test_spots.py` | 21 | SP-01~02、SP-04~11、SP-13~14、SP-16~17、SP-21~22 |
| `test_spots_performance.py` | 4 | SP-20~22 |
| **合计** | **97** | — |

明细（括号内为参数化收集数）：

- `test_agent_chat.py`（15）：`pressure_question_uses_fish_activity_tool`→AG-01/04；`nearby_spots_question_uses_spots_tool`→AG-02/04；`best_time_question_returns_window`→AG-03/04；`three_intents_have_ok_tool_calls_and_full_payload`→AG-04/11；`missing_location_rejected`→AG-05；`invalid_location_rejected`→AG-05；`empty_message_rejected`（2）→AG-05；`message_length_boundary`→AG-05；`history_is_truncated_not_rejected`→AG-06；`session_id_is_generated_when_absent`→AG-06；`session_id_is_echoed`→AG-06；`unknown_intent_returns_guidance`→AG-13；`reply_is_two_to_five_sentences`→AG-14；`ai_disclosure_and_no_promises`→AG-07。
- `test_amap_recall.py`（4）：`around_search_uses_water_types_and_filters_business_pois`→SP-19；`batch_distance_uses_single_destination_and_parses_results`→SP-20；`around_search_rejects_water_like_names_without_water_typecode`→SP-19；`around_search_keeps_multi_typecode_water_pois`→SP-19。
- `test_api_contract.py`（8）：`health`→API-01；`required_routes_are_registered`→API-02；`static_index_is_served`→API-03；`static_assets_are_served`→API-03；`api_route_is_not_shadowed_by_static_mount`→API-03；`validation_error_uses_unified_shape`→API-04；`unknown_api_route_uses_unified_shape`→API-04/API-07；`generated_at_is_utc`→API-05。
- `test_compliance.py`（11）：`web_sources_contain_no_key_or_direct_provider_calls`→API-06/E2E-07；`web_only_calls_same_origin_api`→E2E-07；`env_example_has_placeholders_only`→API-06；`homepage_has_required_disclosures`→E2E-01；`homepage_has_no_promise_or_raw_weather_panel`→RE-15/E2E-12；`fish_activity_response_compliance`（5）→RE-15/E2E-12；`chat_response_compliance`→AG-07。
- `test_coords.py`（6）：`wgs84_to_gcj02_known_points`（2）→CO-01；`gcj02_to_wgs84_round_trip`（3）→CO-02；`domestic_offset_is_in_expected_range`→CO-01。
- `test_fish_activity.py`（28）：`scenario_maps_to_band`（5）→RE-02；`prd_at_seeds_compatibility`（5）→RE-02；`factor_invariants_and_top3`→RE-01/04/05；`no_go_alerts_schema_and_forced_content`→RE-13/14；`weather_summary_is_complete`→RE-19；`best_windows_format`→RE-19/23；`valid_species`→RE-16；`invalid_species_rejected`→RE-16；`invalid_coordinates_rejected`（6）→RE-17；`invalid_scenario_rejected`→RE-21；`naive_at_is_interpreted_as_shanghai_time`→RE-22；`response_timezone_and_generated_at`→RE-20/API-05；`data_sources_and_ai_disclosure`→RE-15/20；`no_catch_promises_in_text`→RE-15；`deterministic_for_same_input`→RE-18。
- `test_spots.py`（21）：`default_recommendation_contract`→SP-01；`filtered_counters_and_invariants`→SP-09/21/22；`round_trip_filter_uses_both_directions`→SP-04~06；`entry_location_precision_and_fallback`→SP-07；`forbidden_candidates_are_excluded`→SP-08；`sorting_and_limit`→SP-10；`radius_and_limit_validation`（10）→SP-02；`radius_150_uses_unique_candidates`→SP-16；`radius_1_does_not_fail`→SP-13；`navigation_url_uses_entry_coordinates`→SP-11；`valid_species_accepted`→SP-17；`deterministic_for_same_input`→SP-14。
- `test_spots_performance.py`（4）：`stops_after_nearest_batch_meets_limit`→SP-20；`expands_evaluation_batches_until_limit_is_met`→SP-20；`unavailable_drives_are_counted_separately`→SP-21；`mock_mode_still_evaluates_every_candidate`→SP-20/22。

说明：E2E-13/E2E-14 由浏览器冒烟脚本（Mock + 合成 `unevaluated`/延迟注入）覆盖，E2E-15 在真实模式最终复跑执行，均不计入 pytest 97；P2-C 的真实数据验收以 E2E-15 为准。

## 7. 执行与证据规范

1. **执行顺序**：L0 → L1 → L2 → L3 → L4 → L5 → L6；P0 先于 P1，Mock 基线先于真实模式。
2. **API 证据**：原始请求、HTTP 状态、响应 JSON 保存到 `evidence/api/`；命名 `TC-ID_场景.json`。
3. **pytest 证据**：完整 `pytest -q` 输出保存到 `evidence/pytest/pytest.log`；失败附 `--tb=long`。
4. **E2E 证据**：每步截图保存到 `evidence/e2e/`；网络日志/HAR 保存到 `evidence/network/`；控制台日志保存到 `evidence/logs/`。
5. **缺陷证据**：复现命令/步骤、期望/实际、截图/JSON、影响、责任域、发现时间。
6. **可复现性**：固定 `at`、固定坐标、固定 session_id；不确定性结果重跑 2 次并标注置信度。
7. **结果标记**：Pass / Fail / Blocked / Not Run；Blocked 必须写依赖与证据，不得用 Pass 掩盖。

## 8. 准入与准出

### 8.1 准入

- 后端 Mock 模式启动成功，`/health` 200。
- `/`、三个业务端点可访问。
- 测试依赖安装完成，`pytest --collect-only` 无导入错误。
- Mock 场景触发方式与固定数据可复现。

### 8.2 准出

- 本轮范围内 P0、P1 用例已执行；P0 缺陷清零；P1 缺陷有明确处置（修复验证或经小项确认接受并记录残余风险）。
- P2 缺陷与未执行项在 `docs/qa-report.md` 中列明。
- 自动化测试命令可复跑，结果可复现；当前基线为 **97 passed**。
- E2E 主流程有截图/网络证据；P2-C 的 `unevaluated` 与慢加载提示在真实 100km 下有验证记录（E2E-13/14/15）。
- 真实模式 50/100km 有 Top5、`filtered` 三条不变式、往返约束与耗时证据；100km 目标 <30s，超过 60s 需在报告中标注阻塞并请小项裁决。
- 合规项（前端无 Key、AI 标识/免责、禁钓过滤、往返红线）有独立证据。
- 报告含测试范围、环境、通过/失败统计、缺陷分级、未覆盖项与结论。

## 9. 缺陷分级与流转

| 级别 | 判定 | 示例 | 处置 |
|---|---|---|---|
| P0 | 阻断主流程、合规/安全红线、数据正确性严重错误 | 服务无法启动；500 堆栈；禁钓候选漏出；前端出现 Key；radius >50000 进入请求；去/回程用单程×2；暴雨未劝退 | 立即回报责任人与小项，阻塞验收 |
| P1 | 契约字段/核心行为不符，但有绕过路径 | 三类意图之一 fallback 失败；入口回退未标记；Top3 排序错误；`filtered` 计数明显错误；错误格式不符 | 修复后回归，验收前清零或经小项确认 |
| P2 | 展示、文案、次要字段、边界体验 | reason 文案缺失；未知 species 处理不一致；可选 `/api/demo/config` 缺失；无障碍不足 | 记录并排期，不阻塞 MVP |

**流转**：小测提交缺陷（含复现与证据）→ 后端/规则/API 归小钱，Agent/H5 归小厚，PRD/Mock 场景口径归小产，契约歧义归小项 → 修复后由小测复测 → 更新报告。小测不直接改实现。

## 10. 追溯矩阵

| 来源 | 要求 | 用例 |
|---|---|---|
| 契约 §4.2 | 七因子、权重、总分、五档、Top3、impact、alerts 对象、scenario、AI 标识 | RE-01~RE-23 |
| 契约 §2 | 统一错误体、Asia/Shanghai 时区、generated_at UTC | API-04、API-05、RE-22 |
| 立项 2.4.2 | F1–F7 评分细则 | RE-06~RE-12 |
| 立项 2.4.3 / Mission P1 | 五档动作、劝退 | RE-02、RE-14 |
| TechStack R1 | WGS84/GCJ-02 唯一入口与回归 | CO-01~CO-04 |
| TechStack R2、契约 v1.3 §4.3 | 单次 radius ≤50000、分片、去重、批量预筛 | SP-02、SP-03、SP-16、SP-20 |
| TechStack R4、契约 §4.3 | 入口坐标、去/回程分别计算、合计 ≤7200、排序 | SP-04~SP-07、SP-10、SP-11 |
| TechStack R5、契约 §4.3 | 禁钓前置过滤、保守排除 | SP-08 |
| 契约 v1.3 §4.3 | `filtered` 九字段（新增 `unavailable/evaluated/unevaluated`）与三条不变式 | SP-09、SP-21、SP-22 |
| 契约 v1.3 §4.3 | 多 typecode 水体召回、批量距离预筛、有界精算、去/回独立精算 | SP-19、SP-20 |
| 契约 §4.3 Mock 数据 §5 | 8+ 候选、三类边界候选、确定性 | SP-04~SP-09、SP-14 |
| 契约 §5.1 | Provider 注入点、`compute_fish_activity` 纯函数 | RE-03、RE-06~RE-11、SP-03 |
| 契约 §4.4 | LangGraph、fallback 三类意图、容错、延迟、真实 LLM 输出 | AG-01~AG-15 |
| TechStack R6/R8、契约 §2 | AI 标识、免责、不承诺、不播报天气 | RE-15、AG-07、AG-12、E2E-01 |
| TechStack R3、契约 §6 | 前端无 Key、无直连第三方 | API-06、E2E-07 |
| 契约 §6、P2-C | H5 主流程、移动端、提示文案、`unevaluated`、慢加载 | E2E-01~E2E-15 |
| project-plan DoD | 启动、四端点、全流程、pytest、真实模式 | API-01、AG-01~03、E2E-02/05/06/15、Q-02 报告 |

## 11. 待确认问题与测试假设

| ID | 问题/假设 | 影响 | 处理 |
|---|---|---|---|
| A-01 | 契约 v1.1 已定义 `scenario` 五档；PRD §5.1 的 `at` 种子是否同时保留未明确 | RE-02 的兼容回归可能失败 | `scenario` 为主；`at` 种子作为 P1 兼容回归；若 `at` 不命中，记实现与 PRD 偏差，不判契约失败 |
| A-02 | 已关闭：`alerts` 为对象数组 `{code,level,message,forced}` | — | 按 v1.1 断言 |
| A-03 | 已关闭（v1.3）：`filtered` 九字段与三条不变式已固定；旧“六字段/两条不变式”口径不再作为验收依据 | 旧口径会误判 `unevaluated`/`unavailable` | 按 SP-09、SP-21、SP-22 精确断言 |
| A-04 | 已关闭：所有 4xx/5xx 统一 `detail{code,message}`；422 为 `VALIDATION_ERROR` | — | 按 API-04 断言 |
| A-05 | 已关闭：业务时区 `Asia/Shanghai`，`generated_at` UTC，响应含 `timezone` | — | 按 RE-22、API-05 断言 |
| A-06 | 已关闭（口径）：F2 兜底区间、F3 6–8℃、F4 5/≥6 级、F5 优先级、F6 冬季代理均已由契约 v1.2 明确；真实 30 天气压分布仍无数据 | 不影响 Mock 验收；真实分布未验证 | 按 v1.2 断言；真实分布列入残余风险 |
| A-07 | 已关闭：Provider 通过 `get_weather_provider()/get_geo_provider()` 获取，可 `dependency_overrides` 注入 | — | SP-03 用 spy Provider 断言 radius |
| A-08 | `center_fallback` 候选是否一定在默认结果中 | SP-07/E2E-05 依赖 Mock 数据设计 | 契约与 PRD 均要求出现；若不出现，记 Mock 数据缺陷（P1） |
| A-09 | `/api/demo/config` 为可选端点 | API-08 不应因缺失判失败 | 仅记录是否实现 |
| A-10 | PRD 与契约仍存差异：F3 6–8℃（PRD 5 / 契约 6）、F6 冬季（PRD ≤5℃ / 契约 <5℃）、F4 下风口（PRD 不计算 / 契约钓位级计算）；`alerts` 与 `best_windows` 数量已在 v1.2 对齐 | 可能误读验收口径 | 以 v1.3 契约为准（F3/F6/F4 口径沿用 v1.2）；请小产同步 PRD；报告注明差异 |
| A-11 | 已关闭：`best_windows` 数量由契约 v1.2 固定（2/2/2/1/0）；非劝退档 `advice` 精确文案仍来自 PRD | 文案差异可能只是产品口径差异 | 按 RE-02/RE-23 断言；仅文案不同且语义等价时记 P2 并请小项裁决 |
| A-12 | PRD §6.2 要求 `reply` 2–5 句，契约 §4.4 仅作为 LLM 提示词要求 | fallback 长回复可能违反 PRD 验收 | 按 PRD 作为 P1 断言（AG-14）；若小项裁定以契约为准，降为 P2 观察项 |
| A-13 | 契约 v1.3 的 `evaluated` 仅计做过精算的候选（含 `unavailable`），`unevaluated` 为超出本轮精算预算的候选；批量预筛不计入 `evaluated` | 若按旧“候选全集”口径断言会误判 | SP-09/21/22 用三条不变式；报告注明 v1.3 口径 |
| A-14 | P2-B 入口坐标：真实数据稀疏，Top5 可全部 `center_fallback` | 导航终点为水体中心，湖泊/水库可能落点不理想 | 本轮采用方案 A（零额外调用）；H5 必须提示精度较低；不单独判失败，试点观察导航落点 |
| A-15 | P2-C 慢加载提示阈值 3s 从钓位请求开始计；文案固定为「正在规划车程，真实模式约需 20 秒」 | 计时差异可能造成误判 | E2E-14 用 4.2s 延迟复现；真实模式记录实际耗时与提示出现时间 |
| A-16 | F-03 已知限制：「明早」意图未解析并传 `at`，仍按当前时刻评估 | 时段建议可能与用户语义有偏差 | 已登记 M3，不阻塞本轮；在 qa-report 披露，不按新缺陷重复计数 |
| A-17 | 自动化基线为 97（原 96）；新增 P2-A 华家池用例 | 计划/报告数量口径不一致 | 统一为 97；映射见 §6.7 |

## 12. 风险与残余风险

1. **真实链路边界**：已验证杭州单点 50/100km；但仅覆盖杭州、共享高德配额未做 P95/限流压测；100km 历史实测 20.79–21.77s，曾出现 57.96s 的预取耗时与一次瞬时 502（重试恢复）；DeepSeek 钓位问句 21–51s。单次 502 不判 P0，连续或可复现才升级。
2. **入口坐标数据稀疏**：50km 首屏 50 个自然水体仅 9 个有 `entr_location`，Top5 河流均无；本轮采用方案 A（`center_fallback`），导航终点为水体中心，湖泊/水库可能落在水中或对岸，需试点观察导航落点。
3. **多 typecode 覆盖**：P2-A 已按 `|` 拆分并保留混合 code 水体；真实样本中华家池等 3 个混合 POI 已验证保留，但其他别名/混合类型仍可能漏召回，需在试点中抽样。
4. **回程方向近似**：Provider 忽略 `direction`，去/回均按“用户→钓位”方向估算，回程为近似值；不得在报告/契约中表述为“方向独立精算”，需按实现口径披露。
5. **F-03 已知限制**：「明早」意图未解析并传 `at`，时段建议仍按当前时刻评估；已登记 M3，不阻塞本轮，但会影响语义准确性。
6. **P2-C 真实数据验证**：`unevaluated` 与慢加载提示已在 Mock/合成场景验证；真实 100km 的 `unevaluated=625` 与慢提示出现时机需在 E2E-15 最终复跑确认。
7. **规则边界可控性**：五档已由 `scenario` 控制；85/84 等精确边界依赖 `compute_fish_activity` 纯函数补充，报告需区分 API 证据与函数级证据。
8. **禁钓数据仅 Mock**：K01“高危禁钓漏出率=0”无法在 MVP 证明，只能证明过滤逻辑按示例黑名单执行。
9. **性能证据局限**：本地单机 Mock 与单次真实计时不代表生产 P95；真实模式仅验证“当前样本无明显阻塞”。
10. **Agent 语义覆盖**：只验证三类约定问句与 fallback；自由表达、多轮省略、同义改写未覆盖；真实 LLM 仍可能出现文案波动。
11. **浏览器兼容性**：以本机 Chrome 为主；未覆盖 Safari/Firefox/微信内置浏览器。
12. **无障碍非发布门禁**：仅做基础检查，不做 WCAG 全量审计。
13. **多用户并发/持久化**：MVP 无数据库与多租户要求，不做容量与隔离验证。
14. **PRD 与契约差异**：F3/F6/F4 与 Agent 回复长度仍存在文档口径分叉；测试以 v1.3 契约为准，PRD 同步前存在沟通成本。

## 13. 交付与证据保存

- 仓库内交付：`docs/qa-plan.md`（本文件）、`backend/tests/`、`docs/qa-report.md`。
- 仓库外归档（绝对路径）：
  - 当前根目录（v1.3 / 真实模式）：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261022-133142\`
  - 历史根目录（v1.1 / Mock 基线）：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261021-185300\`
  - `plans\`：测试计划副本（含 `qa-plan-v1.3.md`）
  - `cases\`：用例与追溯矩阵导出
  - `reports\`：测试报告（含 `qa-independent-baseline-20261022.md`、最终真实模式复跑报告）
  - `evidence\`：API JSON、pytest 日志与 JUnit、截图、浏览器摘要、网络日志
  - `publish-log\`：群内发布记录与阻塞说明
- 群内汇报格式：路径 + 命令 + 结果 + 风险；完成后唤醒小项。
- 不执行任何 Git 提交动作。

## 14. 变更记录

| 版本 | 日期 | 变更 | 作者 |
|---|---|---|---|
| v1.0 | 2026-10-21 | 初版：规则、坐标、钓位、API、Agent、E2E 用例矩阵与准出标准 | 小测 |
| v1.1 | 2026-10-21 | 按契约 v1.1 收敛 alerts、filtered 不变式、时区、统一错误体、scenario、Provider 注入与 F3/F4/F6；新增 RE-21/22、AG-13、E2E-12；关闭 A-02~A-05、A-07 | 小测 |
| v1.2 | 2026-10-21 | 按契约 v1.2 收敛 F2 兜底、F5 优先级、`best_windows` 数量、工具名与单程取整；新增 RE-23、SP-18、AG-14；更新 A-06/A-10/A-11，新增 A-12 | 小测 |
| v1.3 | 2026-10-22 | 按契约 v1.3 升级：`filtered` 九字段与三条不变式、多 typecode 召回、批量预筛/有界精算、P2-B 方案 A（`center_fallback`）、P2-C 未评估展示与 3s 慢加载提示；新增 SP-19~SP-22、AG-15、E2E-13~E2E-15、6.7 节 97 例映射；补充真实模式数据与风险，更新 A-03/A-13~A-17 | 小测 |
