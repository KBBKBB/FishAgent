# FishAgent MVP QA 报告

> 版本：v1.8 ｜ 编制：小测 ｜ 日期：2026-10-24
> 状态：**CR-03 M3 阶段 2 独立复验完成**。M1b 集成 **26/26 PASS**；P2 复测 **11/11 PASS**（O-CR03-01、O-CR03-02 关闭）；阶段 1 A **47/47**、B **42/45**（3 项失败已随 P2 修复关闭）；真机 + HTTPS 仍**待托管验证**。本轮新增 P0/P1/P2 = 0/0/0。
> 历史：v1.0 由小项在 QA 运行器故障期间代执行（第 8 节）；真实 Key 联调见第 9 节；杭州最终独立复跑见第 10 节；成都起点独立复验见第 11 节；D11 + Key 独立增量复验见第 12 节；CR-01 独立复验见第 13 节；CR-02 独立复验见第 14 节；CR-03 M3 阶段 1 见第 15 节，阶段 2 复验见 15.13。
> 依据：`docs/api-contract.md` v1.3、`docs/qa-plan.md` v1.3、`docs/mvp-prd.md`、`Spec/TechStack.md`、`docs/pilot-checklist.md` v0.3。

## 1. 本轮范围与结论

| 项 | 结果 |
|---|---|
| 静态审查范围 | `backend/fishagent/agent/`（graph/router/tools/llm）、`web/`（index.html/app.js/styles.css） |
| 静态审查方式 | 只读代码审查 + 契约字段核对 + 纯函数复现（不启动服务、不改实现） |
| P0 | 0 项 |
| P1 | 0 项未关闭（F-01 已修复并复测通过） |
| P2 | 3 项已处置（F-02/F-04 已关闭；F-03 转已知限制 M3） |
| pytest | 89 passed / 0 failed（`docs/evidence/pytest-full.log`） |
| API 红线 + H5 E2E | 148/148 通过（`docs/evidence/acceptance-log.txt`、`acceptance-summary.json`） |
| 最终结论 | **通过（Mock 模式）**；真实 Key 链路未验证，见第 8 节残留风险 |

## 2. P1 缺陷

### F-01 Agent fallback 鱼情/时段回复超过 PRD 的 2–5 句上限

- **严重级别**：P1（用户可见验收失败；不阻断启动）
- **责任人**：小厚（`backend/fishagent/agent/llm.py`）
- **来源**：PRD §6.2「统一断言：`reply` 2–5 句」；qa-plan AG-14
- **复现步骤**：
  1. 不启动后端，直接调用纯函数 `compose_fallback_reply`。
  2. 使用典型鱼情 payload：含 1 条 positive、1 条 negative 因子、1 个最佳窗口、`water_depth`。
  3. 分别以 `intents=["fish"]` 与 `intents=["time"]` 调用，按中文句号切分句数。
- **实际**：`fish` 与 `time` 均为 **6 句**；`fish` 回复还会继续追加 `alerts`，可能更长。
- **期望**：2–5 句；超限时应压缩因子理由、窗口或水深建议，保留档位/建议/至少 1 条理由/时间窗口。
- **代码位置**：`backend/fishagent/agent/llm.py:341-387`（`_fish_summary` 逐句 append，无长度上限）。
- **证据**：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261021-185300\evidence\static-review\fallback-sentence-count.json`（`fish: 6, time: 6`）。
- **回归用例**：`backend/tests/test_agent_chat.py::test_reply_is_two_to_five_sentences`（已加入，后端交付后执行）。
- **备注**：不改实现；请小厚确认修复后在相同路径复测。

## 3. P2 观察项

### F-02 LLM 承诺词护栏不完整

- **位置**：`backend/fishagent/agent/llm.py:119-123`
- **现象**：`PROMISE_PATTERN` 仅覆盖「必上鱼/保证爆护/保证上鱼/包爆护/必爆护/百分百上鱼」，未覆盖 PRD 明令禁止的「百分百」「100%」「绝不空军」。
- **影响**：仅在真实 LLM Key 模式可能漏出承诺性表述；Mock fallback 不会生成这些词。
- **建议**：补齐正则并对 LLM 输出做同口径检查；若小项裁定 LLM 非 MVP 门禁，可保留为 P2。

### F-03 「明早」时段意图未传递目标时刻

- **位置**：`backend/fishagent/agent/graph.py:61-71`、`backend/fishagent/agent/tools.py:20-32`
- **现象**：`time` 意图调用 `get_fish_activity` 时只传 `lat/lon/species/location_name`，未传 `at`；「明早几点去最好」实际按当前时刻评估，窗口语义可能不是次日早晨。
- **影响**：PRD AT-CHAT-03 只断言回复含 `HH:MM` 与理由，当前实现可能通过；但用户问题语义未被严格满足。
- **建议**：从提问解析「明早/明天/今天」并传 `at`，或明确产品口径为「基于当前天气的时段建议」。

### F-04 鱼情卡展示原始气象指标，可能触碰 AT-UI-06

- **位置**：`web/app.js:455-497`
- **现象**：页面渲染气压、24h 变压、风力、气温、降水、云量、日出日落等原始 `weather_summary` 指标。
- **影响**：PRD §6.5 AT-UI-06 要求「无原始天气预报面板」；当前是紧凑指标条而非预报面板，是否违规需小产/小项裁定。
- **建议**：保留与因子解释直接相关的指标，或改为「因子依据」文案；不阻塞发布前先记录。

## 4. 静态合规核对（通过项）

| 检查 | 结果 |
|---|---|
| Agent AI 标识 | `AI_DISCLOSURE = "本内容由 AI 生成，仅供参考，不承诺渔获。"`，与契约一致 |
| Agent 三类意图 | 气压/鱼情、附近钓位、时段均可命中；未知意图返回引导 |
| 工具名 | `get_fish_activity` / `recommend_spots`，与 v1.2 固定值一致 |
| 工具失败 | `call_tools` 捕获异常并置 `status="error"`；`compose_answer` 有兜底话术，不返回 500 堆栈 |
| species 归一化 | `normalize_species` 将自由文本映射到四类合法鱼种，未透传 |
| 历史裁剪 | 服务端仅使用最近 10 条 `history` |
| Web alerts | 按对象渲染 `code/level/message/forced`，危险项样式区分 |
| Web filtered | 六字段（total/forbidden/over_two_hours/eligible/returned/truncated_by_limit）均展示 |
| Web 时区 | 鱼情卡展示 `timezone`；钓位生成时间按 `Asia/Shanghai` 展示 |
| Web 密钥/直连 | `web/` 无 `AMAP_WEB_KEY`/`LLM_API_KEY`/`sk-`；仅同源 `/api/*`；无 `restapi.amap.com`/`api.open-meteo.com`/`api.openai.com` |
| AI 标识与免责 | 首页常驻「AI 生成 · 仅供参考」、免责声明、不承诺渔获、遵守禁钓规定 |
| XSS | 动态文本使用 `textContent`，未发现 `innerHTML` 注入 |
| `.env.example` | 仅占位符，无真实 Key |

## 5. 运行时待验证（Q-02/Q-03）

1. `backend/tests/` 全量 pytest（当前 89 个用例可收集；后端交付后执行）。
2. `/health`、四个端点、统一 422/503、`scenario` 五档、F2/F5/best_windows/单程取整。
3. `filtered` 不变式、入口回退、禁钓排除、`radius ≤ 50000` 注入 spy。
4. Agent 三类 fallback、工具失败注入、500 字边界、回复句数。
5. 启动 uvicorn，用 browser-harness 执行 H5 主流程、375px 响应式、Network 无第三方直连。
6. 将原始 JSON/日志/截图存入外部 `evidence/`，按 P0/P1/P2 更新本报告。

## 6. 风险与阻塞

- **阻塞**：`backend/fishagent/main.py`、`services/`、`api/` 未交付，无法启动与执行 API 测试。
- **未验证**：真实 Open-Meteo/高德/LLM 链路（无 Key，仅 Mock）；真实路况与生产 P95。
- **文档差异**：PRD 与契约在 F3/F6/F4、Agent 回复长度上仍有口径差；测试以契约 v1.2 为准并记录差异。
- **测试数据**：`center_fallback`、禁钓、超时候选依赖小钱 Mock 数据设计；若不满足，按 Mock 缺陷记 P1。

## 7. 变更记录

| 版本 | 日期 | 变更 | 作者 |
|---|---|---|---|
| v0.1-draft | 2026-10-21 | 静态审查 agent/ 与 web/；记录 F-01~F-04；运行时待后端交付 | 小测 |
| v1.0 | 2026-10-21 | 补齐运行时执行结果（pytest 89 passed、验收 148/148）、缺陷关闭与已知限制 | 小项 |
| v1.1 | 2026-10-22 | 真实 Key 联调补充（第 9 节）：96 passed、真实 50/100km 与 LLM 三问 | 小项 |
| v1.2 | 2026-10-22 | P2-A/B/C 收口后最终独立真实模式复跑（第 10 节）：97 passed、H5 18/18、新增缺陷 0 | 小测 |
| v1.3 | 2026-10-22 | 成都起点最终独立复验（第 11 节）：98 passed、API 50/100km、H5 27/27、Agent 2/2；工程 PASS，整体 NO-GO（D11、Key 轮换） | 小测 |
| v1.4 | 2026-10-22 | D11 + Key 独立增量复验（第 12 节）：126 passed、D11 API 50/100km、H5 34/34、Key 抽验与泄漏扫描；P0/P1/P2=0/0/0；D11 工程与 Key 可关闭，不判 GO | 小测 |
| v1.5 | 2026-10-23 | CR-01 独立复验（第 13 节）：154 passed、ruff clean、真实 API limit=10/offset=5、H5 49/49；P0/P1/P2=0/0/0；O-02 为同名不同 POI；CR-01 可签收，S1 整体准入不变 | 小测 |
| v1.6 | 2026-10-23 | CR-02 独立复验（第 14 节）：UA 矩阵 + 真实 8018 共 58/58；scheme/坐标/名称/回退通过；真机调起待人类确认；P0/P1/P2=0/0/0；O-CR02-01 观察 | 小测 |
| v1.7 | 2026-10-24 | CR-03 M3 阶段 1 独立 QA（第 15 节）：M1 PWA 47/47；M2 本地安全 42/45；新增 P2 ×2（登录错误响应头、访问日志含客户端 IP）；M1b 与真机/HTTPS 待后续 | 小测 |
| v1.8 | 2026-10-24 | CR-03 M3 阶段 2 独立复验（15.13）：M1b 集成 26/26；P2 复测 11/11，O-CR03-01/O-CR03-02 关闭；新增 P0/P1/P2=0/0/0；真机/HTTPS 待托管 | 小测 |

## 8. 最终执行结果（v1.0）

### 8.1 执行说明

小测的 QA 运行在 11:07、11:12、11:13 三次唤醒均因平台运行器错误 `RUNNER_EXECUTION_FAILED: CONVERSATION_RUNTIME_CLEANUP_PENDING` 失败，未能产出运行时结果。为不中断交付，由小项以集成负责人身份代执行 Q-02/Q-03，并保留小钱（实现方）与小厚的独立证据交叉核对；**建议运行器恢复后由小测复跑一次，恢复独立 QA 签字**。这不影响本轮产品结论。

### 8.2 自动化测试

| 项 | 结果 | 证据 |
|---|---|---|
| 全量 pytest | **89 passed / 0 failed**（2.91s） | `docs/evidence/pytest-full.log` |
| ruff | All checks passed | `docs/evidence/ruff.log` |
| 测试数据修正 | `test_coords.py` 杭州期望值与偏移上限两处修正；实现未改 | 小钱 eviltransform 三点复核；小项复算 maxdiff < 1e-7 |

修正说明：原用例杭州期望 `(30.2756, 120.1598)` 与 50–500m 偏移上限错误。按 eviltransform 权威参考：杭州 `(30.271771, 120.159794)`、偏移 519.9m；北京偏移 555.0m；深圳偏移 605.9m。用例改为 `(30.271771, 120.159794)`、偏移上限 700m；其余断言未放宽。

### 8.3 API 红线验收（并入 148 项总检查，全过）

- 五档 `scenario`：极佳/良好/一般/偏差/劝退，分档与 `best_windows` 数量 2/2/2/1/0；`no_go` 三条强制提示（GALE/RAINSTORM/PRESSURE_PLUNGE）。
- `filtered` 不变式：`total_candidates = forbidden + over_two_hours + eligible`；`eligible = returned + truncated_by_limit`。
- 往返：`drive_seconds_round_trip = out + back`，全部 ≤7200s；单程 `round_half_up` 核对通过。
- 入口坐标：缺失回退 `center_fallback`，与契约一致。
- 坐标：用户位置同时返回 `wgs84` 与 `gcj02`；钓位返回 `location_gcj02` / `entry_location_gcj02`。
- 错误体：`radius_km=151`、`limit=11`、`species=鲈鱼`、非法 chat 入参均返回 422，`INVALID_SPECIES`/`VALIDATION_ERROR` 正确；`radius_km=51` 按契约 1–150 合法，每个上游 Provider 单次搜索半径由服务层硬限 ≤50000m（`services/spots.py:30,63`，`providers/amap.py:67`）。
- 合规：`web/` 无 Key、无第三方直连；AI 标识与免责文案存在；三类对话 2–5 句且无承诺词。

### 8.4 H5 E2E（真实后端，端口 8031，未使用 `?mock=1`）

- 手输坐标 30.2800/120.1600 更新成功，页面分数/档位与 API 一致。
- 评分卡：评分依据数据条标题「评分依据（非天气预报）」、副注「仅当前因子数据」、数据源、生成时间、时区（Asia/Shanghai）。
- 钓位：5 个候选、`filtered` 字段、单程/往返、入口精度提示、高德 https 导航链接。
- 对话三连问：均 2–5 句、无承诺词、AI 标识可见；无 `undefined`/`NaN`。
- 响应式：375px 与 1280px 均无横向滚动；无 console error、无失败请求、无第三方请求。
- 截图：`docs/evidence/e2e-375.png`、`docs/evidence/e2e-1280.png`。

### 8.5 缺陷状态

| 编号 | 级别 | 状态 | 证据 |
|---|---|---|---|
| F-01 回复句数超限 | P1 | 已关闭 | 小厚优先级装配 + 硬裁 5 句；专项 24/24；`test_agent_chat.py` 15 passed |
| F-02 承诺词护栏 | P2 | 已关闭 | 5 个承诺词命中、正常文本不误杀 |
| F-03「明早」未传 at | P2 | 已知限制（M3） | 按当前时刻评估，PRD 允许；后续解析相对日期 |
| F-04 评分依据数据条 | P2 | 已关闭 | 标题/副注已加；E2E 断言通过 |
| COORD 测试数据 | P1（测试） | 已关闭 | 见 8.2 |

### 8.6 残留风险

1. 真实 Open-Meteo / 高德 / LLM 链路未配置 Key，未验证；全部证据来自 Mock/fallback。
2. 真实路况、生产 P95、限流与配额未验证。
3. F5 降水口径为临时规则，待真实数据校准。
4. 「明早」未解析目标日期，属已知语义限制（M3）。
5. QA 运行器故障导致本轮独立 QA 签字缺失，建议恢复后由小测复跑（非产品缺陷）。

## 9. 真实 Key 联调补充（2026-10-22，v1.1）

> 本节覆盖第 8 节的 Mock 结论，记录真实 AMap / Open-Meteo / DeepSeek Key 接入后的补充验证。密钥仅存放在 `backend/.env`（`.gitignore:153`），未进入仓库、前端、证据或共享目录。补充验证由小项执行，并交叉核对小钱（钓位/Provider）与小厚（Agent/H5）的实现证据；独立 QA 复跑仍建议在运行器恢复后进行。

### 9.1 补充结论

| 项 | 结果 | 证据 |
|---|---|---|
| 真实 Provider 连通 | Open-Meteo、高德 Web 服务、DeepSeek 均连通 | `docs/evidence/real-mode/fish-activity.json`、`amap-measure.log`、`agent-chat-final.json` |
| 真实鱼情 | 杭州西湖 81 分 / 良好；F1–F7 合计 = 81；数据源 Open-Meteo；时区 Asia/Shanghai | 同上 |
| 真实钓位 100km | 20.79–21.77s；644 候选；Top5 全为自然水体；往返均 ≤7200s | `spots-perf-final.json`、`h5-e2e.log` |
| 真实钓位 50km | 15.65s；47 候选；Top5 与 100km 同名同类型 | `spots-perf-final.json` |
| LangGraph LLM | 三问均 `mode=llm`；3–4 句；无承诺词；工具状态 ok | `agent-chat-final.json` |
| H5 真实模式 E2E | 0 失败 / 0 告警；375px、1280px 均无横向滚动；无 console error | `h5-e2e.log`、`web-real-375.png`、`web-real-1280.png` |
| 自动化 | **96 passed / 0 failed（3.82s）**；ruff All checks passed | `pytest-full.log`、`ruff.log` |

### 9.2 契约 v1.3 与真实数据

| 半径 | 耗时 | total | forbidden | unavailable | >2h | eligible | returned | truncated | evaluated | unevaluated |
|---|---|---|---|---|---|---|---|---|---|---|
| 100km | 20.79–21.77s | 644 | 9 | 0 | 0 | 10 | 5 | 5 | 10 | 625 |
| 50km | 15.65s | 47 | 9 | 0 | 0 | 10 | 5 | 5 | 10 | 28 |

- 三条不变式均通过：`total = forbidden + evaluated + unevaluated`；`evaluated = unavailable + over_two_hours + eligible`；`eligible = returned + truncated_by_limit`。§8.3 的三字段公式为 v1.2 口径，真实模式按 v1.3 补充字段验证。
- 召回改为自然水体类型 `types=190204|190205` + `sortrule=distance`；桃酥店、海鲜馆、小区、社区等业务 POI 已剔除；西湖等景区水体仅在名称含水系词时保留。
- 预筛仅用 `/v3/distance`（最近 ≤100 个候选、单目的地）按回程时长重排，不替代逐点精算；精算按距离分批、每批 `max(2×limit,10)`、总上限 30，达到 limit 提前停止。
- 去/回各调用一次；100km Top5 与 50km 古新河 `522+516` 说明两次调用独立。Provider 当前忽略 `direction`，回程仍按用户→钓位方向估算（见 9.5）。

### 9.3 Agent 真实回答

| 问句 | 模式 | 工具 | 句数 | API 耗时 | H5 耗时 | Markdown |
|---|---|---|---|---|---|---|
| 今天气压适合钓鱼吗？ | llm | get_fish_activity · ok | 4 | 4.67s | 2.58s | 无 |
| 附近哪里野钓好？ | llm | recommend_spots · ok | 4 | 42.44s | 21.02s | 无 |
| 明早几点去最好？ | llm | get_fish_activity · ok | 3 | 2.38s | 2.40s | 无 |

- 另一样本：鱼情 7.76s、钓位 51.21s、时段 2.88s，钓位问句真实耗时区间 21–51s（高德 100km 约 21s + DeepSeek 编排波动）。
- PRD 的 P95 ≤3s 仅约束 Mock 模式，真实模式不适用；但钓位问句等待较长，H5 仅显示“输入中”，后续应增加进度提示或流式输出（Backlog）。
- Markdown P2：时间类回答曾输出 `**04:35–07:35 的日出窗口**`，H5 的 `textContent` 会显示星号。小厚在 `ANSWER_SYSTEM_PROMPT` 增加纯文本约束后，H5 复跑与三问采样均无 `**`/`#`/列表标记。

### 9.4 H5 真实模式 E2E

- 后端 `mock_mode=false`，页面徽标为“在线数据”；三问均显示 `LLM` 徽标与工具“完成”徽标。
- 评分卡、评分依据数据条、数据源、生成时间、时区、Top3 因子、最佳窗口、AI 标识均正常；钓位 `filtered` 字段、单程/往返、入口精度提示、高德 https 导航链接均正常。
- 375×812 与 1280×800 均无横向滚动；无 `undefined`/`NaN`；无 console error；无第三方直连。
- 证据：`docs/evidence/real-mode/h5-e2e.log`、`web-real-375.png`、`web-real-1280.png`。

### 9.5 本轮修复与缺陷

| 编号 | 级别 | 问题 | 处置 | 状态 |
|---|---|---|---|---|
| R-01 | P1 | 100km 真实召回 + 精算 >240s | 自然水体召回、批量预筛、精算上限 30、并发 6 / QPS 2 | 已关闭（20.79–21.77s） |
| R-02 | P1 | 真实 POI 混入餐饮/小区，35 个仅 1 个水体 | 类型召回 + 名称/类型过滤 | 已关闭（Top5 全为自然水体） |
| R-03 | P1 | Agent 工具 8s 超时导致钓位对话降级 | 超时改为可配置 45s，`asyncio.wait_for` 兜底 | 已关闭（钓位对话 mode=llm） |
| R-04 | P2 | LLM 回复含 Markdown 星号 | Prompt 增加纯文本约束 | 已关闭（复跑无标记） |
| R-05 | P2 | httpx 0.28.1 因 NO_PROXY 含 `[::1]` 崩溃 | 启动时规范化 NO_PROXY | 已关闭 |
| R-06 | P2 | H5 未展示 `unevaluated` | 契约字段已提供 | 待办（P2） |

### 9.6 残留风险

1. **回程方向近似**：`estimate_drive_seconds` 忽略 `direction`，去/回均为用户→钓位方向；两次调用独立但回程并非真实返程路况。
2. **入口坐标缺失**：真实 Top5 全部 `center_fallback`，导航终点为水体中心，页面已提示“端点精度较低”。
3. **多 typecode 漏召回**：如华家池 `190301|120302|190204` 因精确匹配 typecode 被排除；P2 召回完整性待补。
4. **覆盖不足**：仅验证杭州起点；共享配额下未做真实模式 P95/限流压测；未覆盖多城市、多时段。
5. **真实延迟波动**：钓位对话 21–51s；H5 无阶段进度提示。
6. **H5 字段缺口**：`unevaluated` 未展示（P2）。
7. **密钥轮换**：Key 曾在群聊明文提供，联调完成后应立即轮换；当前仓库/共享目录/证据扫描无精确 Key 或 `sk-` 命中。
8. **无 Git 提交**：当前改动仍在工作区，按约定未提交。

> 上述第 3、6 项已由 P2 收口关闭：多 typecode 召回由 `test_amap_recall.py` 回归覆盖；`unevaluated` 展示与 3s 慢加载提示已在第 10 节真实 100km H5 验证。第 1、2、4、5、7、8 项仍作为残留风险保留。

## 10. 最终独立真实模式复跑（2026-10-22，v1.2）

> 本节由小测独立执行，不引用小项/小钱/小厚的复跑数字。服务为 8018（`/health` 返回 `mock_mode=false`），**未重启、未改代码、未改运行配置、未提交 Git**。Key 仅由本地 `backend/.env` 注入，本节与全部证据不含 Key。

### 10.1 结论

| 项 | 结果 |
|---|---|
| 自动化 | **97 passed / 0 failed（3.29s）**；ruff All checks passed |
| 真实 100km | **22.60s**；650 候选；Top5 全为河流；往返 942–1776s；三条不变式通过 |
| 真实 50km | **14.37s**；50 候选；Top5 全为河流；往返 958–1756s；三条不变式通过 |
| 真实鱼情 | 88 分 / 极佳；F1–F7 合计 88；Open-Meteo；1.29s；2 个窗口 |
| H5 真实模式 | **18/18**；慢提示 3.06s；未评估 631 与 API 一致；375/1280 无溢出；三问均 llm、4/4/4 句、无 Markdown/承诺词；console 0 error；请求全同源 |
| 新增缺陷 | **P0 0 / P1 0 / P2 0** |
| 最终结论 | **通过**。P2-A/B/C 收口后真实模式主链路、P2-C 展示与 97 例基线均成立，可进入试点准入收口。 |

### 10.2 自动化独立复跑

- 命令：`cd backend && <python> -m pytest tests -q --junitxml=...`
- 结果：**97 passed in 3.29s**；JUnit 记录 `tests=97 errors=0 failures=0 skipped=0 time=3.294`。
- 命令：`cd backend && <python> -m ruff check fishagent tests`
- 结果：`All checks passed!`
- 证据：
  - `D:\学习\GitHubCode\qa-outputs\FishAgent\20261022-133142\evidence\real-mode-final\pytest-final.log`
  - `D:\学习\GitHubCode\qa-outputs\FishAgent\20261022-133142\evidence\real-mode-final\pytest-final.xml`
  - `D:\学习\GitHubCode\qa-outputs\FishAgent\20261022-133142\evidence\real-mode-final\ruff-final.log`

### 10.3 真实钓位 API（8018）

| 半径 | 耗时 | total | forbidden | unavailable | >2h | eligible | returned | truncated | evaluated | unevaluated | 三条不变式 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 100km | 22.60s | 650 | 9 | 0 | 0 | 10 | 5 | 5 | 10 | 631 | 通过 |
| 50km | 14.37s | 50 | 9 | 0 | 0 | 10 | 5 | 5 | 10 | 31 | 通过 |

- `total_candidates = forbidden + evaluated + unevaluated`：100km `650=9+10+631`；50km `50=9+10+31`。
- `evaluated = unavailable + over_two_hours + eligible`：两档均 `10=0+0+10`。
- `eligible = returned + truncated_by_limit`：两档均 `10=5+5`；`returned = len(spots)=5`。
- 九个字段均为非负整数；两次请求均首次成功，`attempts=1`，无 5xx、无重试。
- 真实鱼情：88 分 / 极佳；F1–F7 = 25/12/15/15/10/7/4（合计 88）；数据源 Open-Meteo；窗口 04:35–07:35、15:22–17:22；耗时 1.29s。
- 证据：
  - `...\real-mode-final\spots-100km.json`
  - `...\real-mode-final\spots-50km.json`
  - `...\real-mode-final\fish-activity-real.json`
  - `...\real-mode-final\real-mode-api-summary.json`
  - `...\real-mode-final\real-mode-api-check.log`

### 10.4 Top5 与入口精度

| # | 100km 钓位 | 类型 | entry_precision | 去/回/往返（s） | 单程分钟 |
|---:|---|---|---|---:|---:|
| 1 | 古新河 | 河流 | center_fallback | 471 / 471 / 942 | 8 |
| 2 | 西溪 | 河流 | center_fallback | 600 / 600 / 1200 | 10 |
| 3 | 东河 | 河流 | center_fallback | 741 / 741 / 1482 | 12 |
| 4 | 中河 | 河流 | center_fallback | 868 / 868 / 1736 | 14 |
| 5 | 希颜溪 | 河流 | center_fallback | 888 / 888 / 1776 | 15 |

- 50km Top5 同名同类型，往返分别为 958 / 1164 / 1478 / 1736 / 1756s，全部 ≤7200s。
- 两档均满足 `drive_seconds_round_trip = out + back`、单程分钟 `round_half_up`、导航 URL 前缀 `https://uri.amap.com/marker`。
- Top5 全部 `center_fallback`（方案 A，数据稀疏），H5 对 5 条均展示“该钓位缺少入口坐标，已回退至中心点，端点精度较低”。

### 10.5 50km `unevaluated=31` 判定

**契约内预期，不是展示缺陷。**

- 50km 可评估候选 = `total 50 - forbidden 9 = 41`；首批 `max(2×limit,10)=10` 个完成精算后得到 10 个 eligible，已达到 `limit=5`，循环提前停止（`services/spots.py:335-367`）。
- 剩余 `41-10=31` 个未进入评估窗口，按契约计入 `unevaluated`；不属于 `evaluated/eligible`，三条不变式仍成立。
- H5 展示“未评估 31（超出本轮预算）”与 P2-C 已验收口径一致，未把未评估候选误显示为可达钓位。
- 非缺陷观察 O-01（建议级，不计 P2）：文案未区分“已满足限额提前停止”与“达到 30 个精算上限”，对 50km 场景可能让用户误以为预算不够；如后续优化，可在文案或 tooltip 中区分两种原因，不影响本轮结论。

### 10.6 H5 真实模式 E2E（18/18）

| 检查组 | 结果 | 关键证据 |
|---|---|---|
| 慢加载提示 | PASS | 1.5s 时仍为“正在筛选附近钓位…”；3.06s 变为“正在规划车程，真实模式约需 20 秒”；加载完成后占位清除 |
| 未评估展示 | PASS | API `unevaluated=631`，页面显示“未评估 631（超出本轮预算）”，数值一致 |
| Top5/入口 | PASS | 5 个钓位均为河流；5/5 显示 center_fallback 精度提示 |
| 布局与溢出 | PASS | 1280 与 375 均 `scrollWidth = clientWidth`；对话后 375 仍无横向溢出 |
| 三问 | PASS | `mode` 均 `llm`；工具依次 `get_fish_activity`/`recommend_spots`/`get_fish_activity`，均 ok；回复 4/4/4 句；无 Markdown、无承诺词；DOM 与 API 文本一致；徽标含 LLM 与工具“完成” |
| 合规/运行时 | PASS | 页面无 Key 形态命中；console error 0；HTTP 请求全同源；真实模式徽标为“在线数据” |

- 截图：
  - `...\real-mode-final\h5-real-1280.png`
  - `...\real-mode-final\h5-real-375.png`
  - `...\real-mode-final\h5-real-slow-hint-1280.png`
  - `...\real-mode-final\h5-real-chat-1280.png`
- 全量检查：`...\real-mode-final\real-mode-h5-summary.json`（18/18）；日志：`...\real-mode-final\real-mode-h5-check.log`。

### 10.7 缺陷清单

| 级别 | 新增 | 明细 |
|---|---|---|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 0 | — |
| 观察 O-01 | — | 50km `unevaluated` 文案未区分“提前满足限额”与“预算耗尽”；建议级，不判缺陷 |

- 已关闭复核：P2-C（`unevaluated` 展示 + 3s 慢提示）经真实 100km H5 验证；P2-A 多 typecode 由 97 例中的 `test_amap_recall.py`（4 例）覆盖；P2-B 方案 A 在 Top5 5/5 `center_fallback` 场景下按约定标记并提示。

### 10.8 残留风险

1. **入口坐标稀疏**：Top5 仍 5/5 `center_fallback`，导航终点为水体中心；湖泊/水库可能落在水中或对岸，需试点观察导航落点。
2. **回程方向近似**：Provider 忽略 `direction`，回程仍按“用户→钓位”方向估算，不是真实返程路况。
3. **F-03 已知限制**：「明早」意图未解析并传 `at`，时段建议按当前时刻评估；登记 M3，不阻塞。
4. **覆盖范围**：仅杭州单点、单实例；未做多城市、真实 P95/配额压测与故障切换。
5. **延迟**：钓位 14–23s、Agent 钓位问句历史 21–51s；3s 慢提示已缓解等待焦虑，但无流式/阶段进度。
6. **50km 语义**：`unevaluated=31` 来自提前停止，展示口径已验收；建议后续细化文案（O-01）。
7. **Key 轮换**：仍由人类执行并验证；本次复跑未读取或输出 Key。
8. **无 Git 提交**：按约定当前改动仍在工作区。

### 10.9 合规声明与输出归档

- 未修改任何业务代码、测试代码、CI/运行配置；未重启 8018；未执行 `git add/commit/push`，未创建 PR/MR。
- 未调用高德/Open-Meteo/DeepSeek 之外的第三方；浏览器请求全部同源；证据中无 Key、无 `sk-`/32 位高德 Key 形态。
- 本次复跑输出根目录：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261022-133142\`
  - 证据：`evidence\real-mode-final\`
  - 报告：`reports\qa-report-v1.2.md`（本文件副本）

## 11. 成都起点最终独立复验（2026-10-22，v1.3）

> 执行人：小测；对象：8018 真实模式（`/health` 返回 `mock_mode=false`）。独立执行，不引用小项结果；未重启 8018、未改代码/测试/CI、未提交 Git。

### 11.1 结论

| 项 | 结果 |
|---|---|
| 自动化 | **98 passed / 0 failed**（3.74s；首次独立执行 4.38s）；`ruff check fishagent tests` All checks passed |
| 真实鱼情 | 85 分 / 极佳；F1–F7 = 25/20/10/9/10/7/4，合计 85；Open-Meteo；2.15s |
| 真实钓位 50km | 23.32s；Top5 全自然水体；三条不变式成立；`returned=5` |
| 真实钓位 100km | 20.98s；Top5 全自然水体；三条不变式成立；`returned=5` |
| H5 真实模式 | **27/27**；成都默认、50km 默认、100km 切换、慢提示、未评估一致、375/1280 无横向溢出、console error 0 |
| H5 Mock 回归 | 杭州默认、`Mock 演示` 标注、未评估隐藏、无慢提示、5 个钓位、console error 0 |
| Agent 真实两问 | 鱼情 3.62s / 钓点 44.16s；均 `mode=llm`、工具 `ok`、4 句、无 Markdown/承诺词 |
| Key 扫描 | 仓库 + 共享目录（排除 `backend/.env`）严格 Key 形态命中 **0** |
| 新增 P0/P1/P2 | **0 / 0 / 0** |
| 工程结论 | **PASS**（成都起点真实链路与 H5 回归通过） |
| 试点准入 | **NO-GO**；阻塞 D11 成都禁钓/水体清单、Key 轮换（R1/D4）。工程 PASS 不等于 GO |

### 11.2 自动化独立复跑

| 项 | 结果 | 证据 |
|---|---|---|
| 全量 pytest | 98 passed / 0 failed（3.74s；首次 4.38s） | `evidence\chengdu-final\pytest-chengdu.log`、`pytest-chengdu.xml` |
| ruff | All checks passed | `evidence\chengdu-final\ruff.log` |

### 11.3 真实钓位 API（成都天府广场 30.657, 104.066）

| 半径 | 耗时 | total | forbidden | unavailable | >2h | eligible | returned | truncated | evaluated | unevaluated |
|---|---|---|---|---|---|---|---|---|---|---|
| 50km | 23.32s | 49 | 0 | 0 | 0 | 10 | 5 | 5 | 10 | 39 |
| 100km | 20.98s | 649 | 0 | 0 | 0 | 10 | 5 | 5 | 10 | 639 |

- 三条不变式均成立：`total = forbidden + evaluated + unevaluated`；`evaluated = unavailable + over_two_hours + eligible`；`eligible = returned + truncated_by_limit`。
- `returned == len(spots) == 5`；5 个 id 唯一；导航链接均为 `https://uri.amap.com/marker`；`round_trip = out + back` 且均 ≤7200s；单程分钟按 half-up 核对通过。

| 50km 排名 | 100km 排名 | 名称 | 类型 | 50km 往返(s) | 100km 往返(s) | 入口精度 |
|---|---|---|---|---|---|---|
| 1 | 1 | 锦江 | 河流 | 1116 | 1116 | center_fallback |
| 2 | 2 | 府河 | 河流 | 1228 | 1204 | center_fallback |
| 3 | 3 | 锦江 | 河流 | 1840 | 1847 | center_fallback |
| 4 | 5 | 西郊河 | 河流 | 2038 | 2034 | center_fallback |
| 5 | 4 | 东湖 | 湖泊 | 2060 | 2038 | center_fallback |

- Top5 全为自然水体，未命中餐饮/小区/商店经营名称；P0 原问题名称“碗山河·西南风味菜…”在 50km 与 100km 两档均未出现。
- **`forbidden=0` 仅记录事实，不判合规 PASS**：D11 成都禁钓/水体清单尚未配置，页面“禁钓排除 0”不能对外表述为“已完成禁钓合规检查”。
- 两次独立真实调用间往返秒数有轻微波动（如 50km/100km 第 4、5 名），属实时路况/估算差异；不变式与上限均满足。
- 观察 O-02：Top5 出现两条“锦江”，id 不同、属不同河段，不判缺陷；但用户侧名称区分度偏低，建议后续补充河段名（P2 建议，不阻塞）。

### 11.4 H5 真实模式与 Mock 回归（27/27）

| 检查组 | 结果 | 关键证据 |
|---|---|---|
| 成都默认值 | PASS | 纬度 `30.6570`、经度 `104.0660`、位置摘要“成都天府广场”；默认半径 50km |
| 真实首屏 | PASS | 请求 `radius_km=50`；5 个钓位；评分 85/极佳；数据条标题“评分依据（非天气预报）” |
| 3s 慢提示 | PASS | 1.5s 仍为“正在筛选附近钓位…”；2.96s 变为“正在规划车程，真实模式约需 20 秒”；完成后占位清除 |
| 未评估一致 | PASS | 50km API `unevaluated=39`，页面“未评估 39（超出本轮预算）”；100km API 639，页面一致 |
| 100km 切换 | PASS | 选择 100km 后发出 `radius_km=100` 请求，24.01s 完成；5 个钓位、自然水体、无经营名称 |
| 布局 | PASS | 1280 与 375 均 `scrollWidth = clientWidth`；100km 375px 仍无横向溢出 |
| 合规/运行时 | PASS | 真实模式徽标“在线数据”；console error 0；HTTP 请求全同源；页面无 Key 形态 |
| Mock 回归 | PASS | 默认杭州 `30.2741/120.1551`；徽标“Mock 演示”；无“未评估”；无慢提示；5 个钓位；375px 无溢出；console error 0 |

- 证据截图：
  - `evidence\chengdu-final\h5-chengdu-50km-1280.png`
  - `evidence\chengdu-final\h5-chengdu-100km-1280.png`
  - `evidence\chengdu-final\h5-chengdu-100km-375.png`
  - `evidence\chengdu-final\h5-chengdu-slow-hint-1280.png`
  - `evidence\chengdu-final\h5-chengdu-mock-1280.png`
  - `evidence\chengdu-final\h5-chengdu-mock-375.png`
- 汇总：`evidence\chengdu-final\chengdu-h5-summary.json`（27/27）；日志：`chengdu-h5-run.log`。

### 11.5 Agent 真实对话（API 直连）

| 问句 | 耗时 | mode | 工具 | 句数 | Markdown/承诺词 |
|---|---|---|---|---|---|
| 今天气压适合钓鱼吗？ | 3.62s | llm | get_fish_activity · ok | 4 | 无 |
| 成都附近哪里野钓好？ | 44.16s | llm | recommend_spots · ok | 4 | 无 |

- `ai_disclosure` 与契约一致；工具状态均 `ok`；无 `**`/标题/列表标记；无“必上鱼/保证爆护/百分百/100%/绝不空军”等承诺词。
- 钓点问句 44.16s 属真实高德召回与 LLM 编排耗时；本轮未验证 H5 聊天窗口内的阶段进度，仅确认卡片区 3s 慢提示，聊天等待体验仍为残留风险。
- 证据：`evidence\chengdu-final\chengdu-agent-summary.json`、`agent-fish.json`、`agent-spots.json`。

### 11.6 Key 扫描

- 范围：仓库 `D:\学习\GitHubCode\FishAgent`、共享目录 `...\conv_01m5f11s2b8as0qr3fky3sp7vf\shared`，并对本次 QA 输出目录复核；排除 `backend\.env`（未读取）。
- 严格 Key 形态（`AMAP_WEB_KEY` 为 32 位十六进制、`LLM_API_KEY` 以 `sk-` 开头、URL 参数 `key` 为 32 位十六进制）命中 **0**。
- 原始宽松正则命中 7 处，逐条脱敏核验均为 md5 摘要、空赋值或占位符（`AMAP_WEB_KEY` 与 `LLM_API_KEY` 均未赋值），不是真实 Key；扫描报告不写入任何匹配值。
- 证据：`evidence\chengdu-final\key-scan.json`、`key-scan.log`。

### 11.7 缺陷与阻塞

| 编号 | 级别 | 项 | 状态 |
|---|---|---|---|
| — | P0 | 新发现 P0 | 0 |
| — | P1 | 新发现 P1 | 0 |
| — | P2 | 新发现 P2 | 0 |
| O-02 | 观察 | Top5 两条“锦江”同名不同 id | 建议补河段名；不阻塞 |
| B-01 | 准入阻塞 | D11：成都禁钓/水体清单未配置，`forbidden=0`，不能承诺禁钓合规 | **OPEN（人类/产品）** |
| B-02 | 准入阻塞 | Key 轮换（R1/D4）仍待人类执行并验证 | **OPEN（人类）** |

> 注：B-01/B-02 的增量复验结果与关闭判断见第 12 节（v1.4）；本节保留 v1.3 时点状态。

- 本轮工程 E2E（API、H5、Agent、pytest/ruff）通过；**试点准入结论保持 NO-GO**，直至 B-01、B-02 闭环。杭州既有 PASS 不覆盖成都。

### 11.8 残留风险

1. **D11 合规缺口**：成都无本地禁钓清单/保守白名单；`forbidden=0` 不能作为合规证据，页面“禁钓排除 0”需在对外文案中谨慎处理。
2. **入口坐标稀疏**：Top5 5/5 `center_fallback`，导航终点为水体中心，可能落在水中或对岸。
3. **同名钓位**：Top5 有两条“锦江”，id 唯一但用户区分度不足（O-02）。
4. **真实延迟**：钓位 API 13–23s，Agent 钓点问句 44s；H5 卡片有 3s 慢提示，聊天窗口仍只有“输入中”。
5. **回程方向近似**：Provider 忽略 `direction`，回程按用户→钓位方向估算，不是真实返程路况（既有已知限制）。
6. **覆盖范围**：仅成都天府广场单点、单实例；未做多城市、多时段、真实 P95/配额/限流压测。
7. **Key 轮换**：B-02 未闭环；本轮未读取、回显或记录任何真实 Key。
8. **无 Git 提交**：按约定改动仍在工作区，未执行 `git add/commit/push`。

### 11.9 合规声明与输出归档

- 仅做验证与文档：未修改业务代码、产品测试、CI/运行配置；未重启 8018；未创建 PR/MR。
- 浏览器请求全部同源；未调用高德/Open-Meteo/DeepSeek 之外的第三方；所有产物不含 Key。
- 本次复验根目录：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261022-155000\`
  - 报告副本：`reports\qa-report-v1.3.md`
  - 证据：`evidence\chengdu-final\`
  - 发布记录：`publish-log\20261022-chengdu-final.md`

## 12. D11 + Key 独立增量复验（2026-10-22，v1.4）

> 触发：小项 seq=214。本节数据均由小测本轮独立执行，不引用小项/小钱/小厚结果；未读取 `backend/.env`，未重启 8018，未修改代码/CI/运行配置，未提交 Git。

### 12.1 结论总表

| 项 | 结果 | 说明 |
|---|---|---|
| 自动化 | PASS | 126 passed / 0 failed（3.84s）；ruff 全通过；新增 28 条 `test_forbidden`，原 98 条无回归 |
| Key 服务级抽验 | PASS | `/health` real、鱼情 1x、50km 钓位 1x、chat 1x 均 200；未读取 `.env` |
| D11 真实 API | PASS（工程） | 50km 14.65s、100km 26.15s；`returned=len(spots)=5`、id 唯一、往返 ≤7200s、导航 URL 存在；Top5 无保护地/禁用关键词/商业名 |
| H5 真实 + Mock | PASS | 34/34；375/1280 无横向溢出；合规文案可见且与要求逐字一致；console error 0 |
| Key 泄漏扫描 | PASS | 严格形态 0、LLM Key 前缀 0；宽松命中 13 处经脱敏核验为 md5/session_id/哈希片段/占位赋值 |
| P0/P1/P2 | 0 / 0 / 0 | 无新增缺陷 |
| D11 是否可关闭 | **可关闭（工程）** | 规则实现、测试、真实 API、H5 均有本轮证据；名称启发式边界与免责声明仍需保留 |
| Key 是否可关闭 | **可关闭（服务级）** | 独立抽验证明真实链路可用；控制台轮换与 `.env` 未由本角色读取 |
| 总体准入 | **不判 GO** | 只给工程与合规事实；由小项汇总、人类决策 |

### 12.2 自动化与 D11 覆盖

- `pytest tests -q`：**126 passed, 0 failed, 0 errors, 3.84s**（JUnit 126）。
- `ruff check fishagent tests`：**All checks passed**。
- 模块分布（JUnit）：test_agent_chat 15、test_amap_recall 5、test_api_contract 8、test_compliance 11、test_coords 6、test_fish_activity 28、test_forbidden 28、test_spots 21、test_spots_performance 4。
- `test_forbidden.py` 共 28 条：9 条保护地/国家公园等正向排除、11 条水源地/军事/养殖等既有关键词回归、6 条普通水域放行、2 条配置圆区/空名称。与 D11“名称命中才排除、其余默认放行”一致。
- 原 98 条（126 − 28）全部通过，未发现回归。
- 证据：`evidence\d11-key-final\pytest-d11.log`、`pytest-d11.xml`、`ruff-d11.log`。

### 12.3 Key 独立抽验（服务级）

| 检查 | 结果 | 耗时 | 关键字段 |
|---|---|---|---|
| `GET /health` | 200 | 0.031s | `status=ok`、`version=0.1.0`、`mock_mode=false` |
| 鱼情 1x | 200 | 1.392s | 94 分 / 极佳；F1–F7 = 25/20/10/15/10/10/4；来源 Open-Meteo、规则引擎 v1 |
| 钓位 50km 1x | 200 | 14.652s | 5 条；非 Mock |
| 聊天 1x | 200 | 3.486s | `mode=llm`、`get_fish_activity` ok、4 句、无 Markdown/承诺词 |

- 聊天回复包含 AI 披露与“以实时导航为准/遵守当地规定”类边界，未出现“必上鱼/保证爆护”等承诺。
- 本轮未读取 `backend/.env`，未回显或记录任何 Key 值；仅通过服务行为判断真实模式。
- 证据：`evidence\d11-key-final\d11-key-summary.json`、`fish-key-check.json`、`spots-50km.json`、`agent-key-check.json`。

### 12.4 D11 真实 API（成都天府广场）

| 半径 | 耗时 | filtered 九字段 | Top5 水体（类型） | 往返秒 | 入口精度 |
|---|---|---|---|---|---|
| 50km | 14.652s | 49 / 0 / 0 / 0 / 10 / 5 / 5 / 10 / 39 | 锦江（河）、府河（河）、府河(锦江)（河）、西郊河（河）、东湖（湖） | 1417 / 1464 / 2200 / 2203 / 2282 | 5/5 `center_fallback` |
| 100km | 26.150s | 649 / 0 / 0 / 0 / 10 / 5 / 5 / 10 / 639 | 锦江（河）、府河（河）、锦江（河）、西郊河（河）、府河(锦江)（河） | 1390 / 1464 / 2170 / 2218 / 2222 | 5/5 `center_fallback` |

- filtered 顺序：`total_candidates / forbidden / unavailable / over_two_hours / eligible / returned / truncated_by_limit / evaluated / unevaluated`。
- 三条不变式均成立：`total = forbidden + evaluated + unevaluated`；`evaluated = unavailable + over_two_hours + eligible`；`eligible = returned + truncated_by_limit`；且 `returned = len(spots) = 5`。
- 5 个 id 互不重复；全部往返 ≤7200s；每条均有导航 URL。
- Top5 均为自然水体；名称未命中 20 个 D11 禁用关键词（保护地/水源/军事/养殖/承包等），未出现商业名；v1.3 中的“碗山河·西南风味菜…”未再出现。
- **口径**：`forbidden=0` 仅是本轮召回结果的事实，**不是**合规 PASS；名称未命中规则不等于“均可钓”，页面“以当地公告为准”免责声明必须保留。

证据：`evidence\d11-key-final\spots-50km.json`、`spots-100km.json`、`d11-key-run.log`。

### 12.5 H5 真实 + Mock（375/1280）

- 真实模式：默认成都天府广场 30.6570/104.0660、默认 50km；初始请求 `lat=30.657&lon=104.066&radius_km=50&limit=5`。
- 3s 慢提示：2.91s 出现“正在规划车程，真实模式约需 20 秒”，3s 前不出现。
- 卡片数量与当次 API 一致（DOM=API=5）；徽标“在线数据”；`center_fallback` 精度提示 5/5 对应；50km `unevaluated=39`、100km `unevaluated=639` 与后端一致。
- 100km 切换：`radius_km=100`，Top5 更新为 锦江/府河/府河(锦江)/东湖/西郊河。
- 合规文案：真实 50km、100km、Mock，以及 375 窄屏下均可见；文本逐字为：
  `禁钓提示：国家公园、自然保护区、饮用水水源保护区等保护地禁止垂钓；其他水域是否可钓以当地公告为准。`
  该节点 `children=0`（纯文本），未引入第三方资源。
- 布局：1280 与 375 均无横向溢出（scrollWidth = clientWidth）；console error 0；网络请求全部同源；页面无 Key 形态字符串。
- Mock：默认杭州西湖 30.2741/120.1551，徽标“Mock 演示”；不显示 `unevaluated`、不出现慢提示；5 条卡片；合规文案同上且为纯文本节点；375 无溢出；console error 0；同源。
- 汇总：**34/34 通过**（真实 23 项 + Mock 11 项）。
- 证据：`d11-h5-summary.json`、`d11-h5-run.log` 及 `d11-slow-hint-1280.png`、`d11-real-50km-1280.png`、`d11-real-100km-1280.png`、`d11-real-100km-375.png`、`d11-mock-1280.png`、`d11-mock-375.png`。

### 12.6 Key 泄漏扫描

- 范围：仓库 `D:\学习\GitHubCode\FishAgent`、`qa-outputs\FishAgent` 全量、共享目录 `...\conv_01m5f11s2b8as0qr3fky3sp7vf\shared`；排除 `backend\.env`（未读取）。
- 严格形态（`AMAP_WEB_KEY` 赋值 32 位十六进制、LLM Key 赋值、URL `key=` 32 位十六进制）命中 **0**；LLM Key 前缀 token 命中 **0**。
- 宽松正则命中 13 处（8 个文件），逐条脱敏核验为：`.env.example` 空/占位赋值、md5 摘要、v1.3 SHA-256 的 32 位片段、Mock `session_id`、既有基线报告中的占位赋值；**未发现真实 Key**。扫描产物只记录路径与计数，不记录匹配值。
- 本轮新增报告、证据、JSON 均不含 Key；H5 页面文本扫描 0 命中。
- 证据：`key-leak-scan.json`、`key-leak-scan.log`。

### 12.7 缺陷、观察项与关闭判断

| 编号 | 级别 | 项 | 状态 |
|---|---|---|---|
| — | P0 | 新发现 P0 | 0 |
| — | P1 | 新发现 P1 | 0 |
| — | P2 | 新发现 P2 | 0 |
| O-02 | 观察 | Top5 出现同名“锦江”/“府河(锦江)” | 保留；id 唯一，建议补河段名，不阻塞 |

- **D11：可关闭（工程）**。规则实现 `backend/fishagent/core/forbidden.py`、28 条测试、真实 API 与 H5 均有本轮独立证据；不修改代码。
- **Key：可关闭（服务级）**。真实模式 health/鱼情/钓位/聊天全链路 200，证明 Key 链路可用；控制台轮换动作与 `.env` 内容未由本角色读取或验证。
- **总体准入：不判 GO**。D11 名称启发式无法覆盖未标注保护地，`forbidden=0` 不能写成“禁钓已排除”；最终由小项汇总、人类决策。

### 12.8 残留风险

1. **名称启发式**：仅按名称关键词与示例圆区排除；未标注保护地、边界变化、地方临时禁钓可能漏判，必须保留“以当地公告为准”。
2. **入口精度**：成都 Top5 5/5 `center_fallback`，导航终点可能落在水体中心或对岸。
3. **同名/近名**：50/100km 均出现“锦江”“府河(锦江)”，用户区分度不足（O-02）。
4. **延迟尾部**：50km 14.65s、100km 26.15s，仅单次串行采样，未测 P95/配额/限流；聊天无阶段进度。
5. **覆盖范围**：仅成都天府广场单点、单实例、单时段；未做多城市、多时段、弱网与并发验证。
6. **合规口径**：`forbidden=0` 是事实字段，不是禁钓合规结论；对外文案不得承诺“全部可钓”。
7. **无 Git 提交**：按约定未执行 `git add/commit/push`；改动留在工作区，由开发/协调角色处理。

### 12.9 产物与合规声明

- 仅验证与文档：未改业务代码、产品测试、CI/运行配置；未重启 8018；未创建 PR/MR；未读取 `.env`；未回显 Key。
- 浏览器请求全部同源；未引入第三方资源；所有产物不含 Key。
- 本轮根目录：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261022-165000\`
  - 报告归档：`reports\qa-report-v1.4.md`
  - 证据：`evidence\d11-key-final\`
  - 发布记录：`publish-log\20261022-d11-key-final.md`

## 13. CR-01 独立复验（2026-10-23，v1.5）

> 触发：小项 seq=325。本节数据均由小测本轮独立执行，不引用小项/小厚结果；未读取 `backend/.env`，未重启 8018，未修改代码/CI/运行配置，未提交 Git；真实调用串行执行。

### 13.1 结论总表

| 项 | 结果 | 说明 |
|---|---|---|
| 自动化 | PASS | 154 passed / 0 failed / 0 errors（4.26s）；ruff 全通过；新增 16 条商业 POI 用例与 `limit=10` 用例均通过 |
| 真实 API `limit=10` | PASS | 200，12.855s，10/10 条自然水体；id 唯一；无商业名；三条不变式成立 |
| 真实 API `offset=5&limit=5` | PASS（能力保留） | 200，13.104s，5 条；不变式成立；H5 不使用该参数 |
| H5 真实 8018 | PASS | 首次请求 `limit=10`、无 `offset`；首屏 5 条；换批 0.044s 无新请求；回卷文案逐字一致；375/1280 无溢出；console 0 |
| H5 Mock 回归 | PASS | 5→1 换批、100km 重置回第 1 批、回卷文案一致、375 无溢出、console 0 |
| O-02 同名“锦江” | 已澄清 | `B0HRD7XB54` 锦江区 1052m 与 `BY0001NRKN` 成华区 2707m，id/坐标/距离均不同，是两个 POI；**不记 P1** |
| P0/P1/P2 | 0 / 0 / 0 | 无新增缺陷 |
| CR-01 是否可签收 | **可签收（QA 工程）** | 自动化、真实 API、H5 真实/Mock 均有本轮独立证据；名称启发式与延迟风险保留 |
| S1 整体准入 | **不改变** | 本节只给 CR-01 工程事实；S1 准入仍由小项汇总、人类决策 |

### 13.2 自动化与用例核对

- `pytest tests -q`：**154 passed, 0 failed, 0 errors, 4.26s**（JUnit 154 节点）。
- `ruff check fishagent tests`：**All checks passed**。
- 模块分布（JUnit）：test_agent_chat 15、test_amap_recall 21、test_api_contract 8、test_compliance 11、test_coords 6、test_fish_activity 28、test_forbidden 28、test_spots 28、test_spots_performance 9。
- 商业 POI 过滤：本轮新增 16 条（15 个商业后缀参数化 + 1 条“水泥河沙经营部”排除且保留锦江/府河/西郊河/沙河），全部通过；`test_amap_recall` 由 5 条增至 21 条。含既有 2 条商业 POI 用例，商业相关共 18 个节点通过。
- `limit=10`：`test_limit_ten_evaluates_one_ten_candidate_batch` 通过，断言 `evaluated=10`、`returned=10`、`unevaluated=110`、`drive_calls=20`，证明单批按 10 个评估而非旧的最小 5。
- offset：共 12 个用例节点（11 个唯一用例名，`test_offset_beyond_eligible_returns_empty_page` 在 `test_spots.py` 与 `test_spots_performance.py` 各有一份），全部通过，未发现回归。
- 证据：`evidence\cr01\pytest-cr01.log`、`pytest-cr01.xml`、`pytest-cr01-summary.json`、`ruff-cr01.log`。

### 13.3 真实 API（成都天府广场，串行）

| 请求 | 状态 | 耗时 | 返回 | filtered 九字段 |
|---|---|---|---|---|
| `/health` | 200 | 0.006s | `mock_mode=false` | — |
| `limit=10`（50km） | 200 | 12.855s | 10 条 | 48 / 0 / 0 / 0 / 10 / 10 / 0 / 10 / 38 |
| `offset=5&limit=5`（50km） | 200 | 13.104s | 5 条 | 48 / 0 / 0 / 0 / 10 / 5 / 5 / 10 / 38 |

- filtered 顺序：`total_candidates / forbidden / unavailable / over_two_hours / eligible / returned / truncated_by_limit / evaluated / unevaluated`。
- 两次请求三条不变式均成立：`total = forbidden + evaluated + unevaluated`；`evaluated = unavailable + over_two_hours + eligible`；`eligible = returned + truncated_by_limit`；且 `returned = len(spots)`。
- `limit=10` 水体：锦江、府河、西郊河、磨底河、浣花溪、府河(锦江)、东湖、锦江、小沙河、清水河；10 个 id 唯一；无“经营部/商行/公司/建材/砂石”等商业名；全部为河流/湖泊；往返 1266–4099s，均 ≤7200s；导航 URL 10/10 存在；入口精度 9 条 `center_fallback`、1 条 `entr_location`。
- `offset=5&limit=5` 水体：摸底河、东湖、锦江、小沙河、清水河；5 个 id 唯一；无商业名；往返 3012–4072s。
- **口径**：`forbidden=0` 只是本轮召回事实，不是禁钓合规结论；名称未命中不等于“均可钓”。
- 证据：`evidence\cr01\cr01-api-limit10.json`、`cr01-api-offset5.json`、`cr01-api-summary.json`。

### 13.4 O-02 同名判定

| 名称 | id | 行政区 | 距离 | 坐标 |
|---|---|---|---|---|
| 锦江 | `B0HRD7XB54` | 锦江区 | 1052m | 30.646826, 104.062212 |
| 锦江 | `BY0001NRKN` | 成华区 | 2707m | 30.669603, 104.090780 |

- 两条记录 id、行政区、距离、坐标均不同，是**两个不同的 POI**，不是同一钓位重复；不记 P1。
- H5 首屏第 1 条与第 2 批第 3 条同名“锦江”，但卡片同时展示行政区与距离（“河流 · 锦江区 / 1.1 km” vs “河流 · 成华区 / 2.7 km”），可区分；首屏与第 2 批 id 集合无交集。
- O-02 保留为观察项：同名水体在列表中的辨识度仍有限，建议后续补充河段名。
- **附注**：`limit=10` 与 `offset=5` 是两次独立请求，召回/排序并非跨请求稳定——`offset=5` 出现“摸底河”（`B0LRFN6G2X`，金牛区 3466m），而 `limit=10` 第 6–10 条为“府河(锦江)、东湖、锦江、小沙河、清水河”；两者仅 4 个 id 重合。H5 使用单次响应的本地切片，不受该现象影响；若未来把 `offset` 作为稳定分页契约对外，需要产品/后端另行定义。

### 13.5 H5 真实 + Mock（375/1280）

**真实 8018（默认成都天府广场、50km）**

- 首次且唯一一次钓位请求：`/api/spots/recommend?lat=30.657&lon=104.066&radius_km=50&limit=10`，**无 `offset`**；全程 `request_count=1`。
- 首屏 5 条：锦江、府河、西郊河、磨底河、浣花溪，与响应前 5 条逐项一致。
- 点击“换一批”：5 条（府河(锦江)、东湖、锦江、小沙河、清水河），**0.044s**，请求数 1→1（无新请求），状态“已换到下一批钓位。”。
- 再点“换一批”：回到第 1 批 5 条，**0.043s**，无新请求，提示逐字为 **“已展示全部推荐，已回到第 1 批。”**。
- 按钮：文案“换一批”，加载中禁用、加载完成启用；3s 后出现“正在规划车程，真实模式约需 20 秒”。
- 布局：1280 与 375 均无横向溢出（scrollWidth = clientWidth = bodyScrollWidth = innerWidth）；console error 0、page error 0；请求全部同源、无外部资源；页面无 Key 形态字符串；徽标“在线数据”。
- 合规：禁钓提示 1 处、可见、纯文本（children=0），逐字为
  `禁钓提示：国家公园、自然保护区、饮用水水源保护区等保护地禁止垂钓；其他水域是否可钓以当地公告为准。`
  对话说明逐字为 `对话由 AI 生成，仅供参考，不承诺渔获；请遵守当地禁钓规定。`

**Mock 回归（`?mock=1`，杭州默认）**

- 首屏 5 条（青山水库、镜湖湿地野塘、苕溪河湾、白鹭湖、九龙湖）；换批 1 条（湘湖），状态“已换到下一批钓位。”；再点回卷第 1 批并提示“已展示全部推荐，已回到第 1 批。”。
- 切 100km：回到第 1 批 5 条，来源行含“搜索半径 100 km”“Mock 数据”；为控制高德 QPS（O-04），本轮**未对真实 100km 发起请求**，仅用 Mock 验证重置逻辑。
- 不展示 `unevaluated`；无 3s 慢提示；375 无横向溢出；合规/对话文案同上；console error 0、page error 0；同源；徽标“Mock 演示”。
- 汇总：**49/49 通过**（真实 32 项 + Mock 17 项）。证据：`cr01-h5-summary.json`、`cr01-h5-run.log`、`cr01_h5_check.py` 及 `cr01-real-first-1280.png`、`cr01-real-second-1280.png`、`cr01-real-rollover-1280.png`、`cr01-real-slow-hint-1280.png`、`cr01-real-375.png`、`cr01-mock-first-1280.png`、`cr01-mock-second-1280.png`、`cr01-mock-375.png`。

### 13.6 缺陷与观察项

| 编号 | 级别 | 项 | 状态 |
|---|---|---|---|
| — | P0 | 新发现 P0 | 0 |
| — | P1 | 新发现 P1 | 0 |
| — | P2 | 新发现 P2 | 0 |
| O-02 | 观察 | 两批出现同名“锦江” | 已核验为不同 POI；保留辨识度建议，不阻塞 |
| O-CR01-01 | 观察 | `offset` 跨请求结果不稳定（摸底河/府河(锦江) 差异） | H5 不使用 offset；若未来作为分页契约需另行定义，不记 P2 |

- **CR-01：可从 QA 工程角度签收（PASS）**。商业 POI 过滤、`limit=10` 单批评估、H5 预取 10 + 本地换批、回卷/重置、合规文案均有本轮独立证据。
- **S1 整体准入：不改变**。本节不判 GO；由小项汇总 CR-01 状态并向人类汇报。

### 13.7 残留风险

1. **商业名启发式**：仅覆盖后缀/店招/关键词；未收录的商业命名仍可能漏过，本轮“无商业名”只代表成都 50km 单次样本。
2. **首屏延迟**：`limit=10` 单次 12.855s，H5 依赖 3s 慢提示缓解；未测 P95、弱网与并发，真实高德 QPS 压力仍受 O-04 约束。
3. **100km 真实未复跑**：本轮仅 Mock 验证 100km 重置，真实 100km 的召回/延迟沿用 v1.4 数据，未新增样本。
4. **offset 语义**：跨请求不稳定且 H5 不使用；对外 API 若承诺稳定分页需补充契约与测试。
5. **覆盖范围**：成都单点、单时段、单实例；未做多城市、多时段、并发与配额验证。
6. **入口精度**：10 条中 9 条 `center_fallback`，导航终点可能落在水体中心或对岸（既有风险）。
7. **同名辨识**：O-02 仍建议补河段名；当前依赖行政区+距离区分。
8. **无 Git 提交**：按约定未执行 `git add/commit/push`；改动留在工作区，由开发/协调角色处理。

### 13.8 产物与合规声明

- 仅验证与文档：未改业务代码、产品测试、CI/运行配置；未重启 8018；未创建 PR/MR；未读取 `.env`；未回显 Key。
- 真实调用串行：`/health` → `limit=10` → `offset=5&limit=5` → H5 单次真实加载，无并发加压。
- 浏览器请求全部同源；未引入第三方资源；所有产物不含 Key。
- 本轮根目录：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261023-1746\`
  - 报告归档：`reports\qa-report-v1.5.md`
  - 证据：`evidence\cr01\`
  - 发布记录：`publish-log\20261023-cr01.md`
  - 共享副本：`C:\Users\koubinbin\.qoderwake-cn\data\cloud-conversations\conv_01m5f11s2b8as0qr3fky3sp7vf\shared\qa-report.md`

## 14. CR-02 独立复验（2026-10-23，v1.6）

> 触发：小项 seq=344。本节数据均由小测本轮独立执行，不引用小厚/小项结论；未读取 `backend/.env`，未重启 8018（PID 70828 保持运行），未修改代码/CI/运行配置，未提交 Git；真实页面加载仅 1 次，未并发。

### 14.1 结论总表

| 项 | 结果 | 说明 |
|---|---|---|
| 代码核对 | PASS | scheme 本地固定构造；入口坐标回退；6 位小数；`dname` 编码；`safeHttpUrl` 仍只允许 http/https |
| Mock UA 矩阵 | PASS（34/34） | iPhone 375 / Android 375 / iPadOS 768 / 桌面 1280 全部通过；移动端回退可见且为 https；桌面无 App 回退 |
| 真实 8018 + iPhone UA | PASS（24/24，链接构造/回退） | 仅 1 次钓位请求 `limit=10` 无 `offset`；5/5 scheme/坐标/名称对齐；回退 5/5 为 https；CR-01 换批/回卷不回归 |
| 合计 | **58/58** | 真实 24 + Mock 34 |
| 真机调起 | **未验证（不判 PASS）** | 无头浏览器不能拉起高德 App；需人类在 iPhone 上点一次确认 |
| P0/P1/P2 | 0 / 0 / 0 | 无新增缺陷 |
| 观察项 | O-CR02-01 | 网页回退仍携带 `callnative=1`，可能再次尝试调起 App；不记 P1/P2 |
| CR-02 可签收范围 | **工程链接构造/回退可签收** | 真机调起待人类确认后再关闭 CR-02 |
| S1 整体准入 | **不改变** | 本节只给 CR-02 工程事实；S1 准入仍由小项汇总、人类决策 |

### 14.2 代码核对

| 位置 | 核对项 | 结论 |
|---|---|---|
| `web/app.js:93-102` | `safeHttpUrl` | 仅 `http:`/`https:` 返回，其他协议返回 null；全文件仅 `renderSpot` 1 处调用；未发现 `javascript:`/`data:`/`file:` |
| `web/app.js:104-108` | Apple 移动端判定 | iPhone/iPad/iPod；iPadOS 桌面 UA 用 `Macintosh` + `maxTouchPoints > 1` |
| `web/app.js:110-112` | Android 判定 | `/Android/i` |
| `web/app.js:114-128` | `amapAppUrl` | 取 `entry_location_gcj02`，缺失回退 `location_gcj02`；`Number` 有限性校验；`toFixed(6)`；`encodeURIComponent(name)`；`sourceApplication=FishAgent&dev=0&t=0`；iOS/Android scheme 均在本地固定拼接，未读取 API 返回的 scheme |
| `web/app.js:721-740` | `renderSpot` 链接 | 移动端主链接为 App scheme，另有“未安装高德？使用网页版”https 回退（`target=_blank`、`rel=noopener noreferrer`）；桌面端仅 https、`target=_blank`，无 App 回退 |
| `backend/fishagent/services/spots.py:146-152` | `navigation_url` | 仍为 https `uri.amap.com/marker`，带 `coordinate=gaode&callnative=1`；本轮未改后端 |

- `node --check web/app.js` 通过；QA 脚本 `py_compile` 通过。
- 证据：`evidence\cr02\cr02-static-review.log`、`cr02-node-check.log`、`cr02-pycompile.log`。

### 14.3 UA 矩阵（Mock，无上游调用）

| 场景 | 视口 | 断言 | 结果 |
|---|---|---|---|
| iPhone | 375×812 | `iosamap://path`；5/5 `sourceApplication=FishAgent`、`dev=0&t=0`、`dlat/dlon` 6 位小数与入口坐标一致、`dname` 解码等于钓位名；回退 https + 指定文案；无溢出；console 0 | 8/8 |
| Android | 375×812 | `amapuri://route/plan/`；其余同上 | 8/8 |
| iPadOS | 768×1024 | Macintosh UA + `maxTouchPoints=5`；识别为 iOS scheme `iosamap://path`；其余同上 | 9/9 |
| 桌面 | 1280×900 | https `uri.amap.com`；`target=_blank`；无 App scheme；无移动端回退；无溢出；console 0 | 9/9 |

- Mock 首屏 5 条：青山水库、镜湖湿地野塘、苕溪河湾、白鹭湖、九龙湖；白鹭湖 `entry_location_gcj02=null`，链接正确使用中心坐标 `30.220000/119.980000`。
- 移动端回退文案逐字为“未安装高德？使用网页版”，5/5 可见且为 https；桌面端回退数量 0。
- 所有场景请求均同源、无外部资源；合规文案逐字一致且为纯文本。
- 截图：`cr02-mock-iphone-375.png`、`cr02-mock-android-375.png`、`cr02-mock-ipados-768.png`、`cr02-mock-desktop-1280.png`。

### 14.4 真实 8018 + iPhone UA（串行一次）

- `/health`：200，0.049s，`mock_mode=false`；PID 70828 仍在运行，未重启。
- 钓位请求仅 **1 次**：`http://127.0.0.1:8018/api/spots/recommend?lat=30.657&lon=104.066&radius_km=50&limit=10`，无 `offset`。
- API 返回 10 条、id 唯一；首屏 5 条：锦江、府河、摸底河、清水河、磨底河；第 2 批 5 条：西郊河、浣花溪、府河(锦江)、锦江、小沙河（与当次 API 第 6–10 条逐项一致）。
- App 链接 5/5 通过：`iosamap://path?`；`dlat/dlon` 与 API `entry_location_gcj02`（缺失回退 `location_gcj02`）6 位小数一致；`dname` 解码等于 API 名称；`sourceApplication=FishAgent`、`dev=0&t=0`。
- 回退链接 5/5 与 API `navigation_url` 语义一致、均为 https、`target=_blank`、文案逐字“未安装高德？使用网页版”；5/5 均携带 `callnative=1`（见 14.5）。
- CR-01 不回归：第 2 批 5 条、点击 **0.329s**、无新钓位请求；再点回卷第 1 批、**0.280s**、无新请求，提示逐字“已展示全部推荐，已回到第 1 批。”。
- 375 无横向溢出（scrollWidth = clientWidth = bodyScrollWidth = innerWidth = 375）；console error 0、page error 0；请求全部同源；禁钓提示逐字一致、纯文本、可见。
- 说明：本次真实 API 排序与第 13 节 CR-01 单次样本不同（如首屏出现“摸底河”），属于跨请求召回/排序波动；CR-02 只要求“当次响应内 5/5 对齐”，已满足，不记缺陷。
- 证据：`cr02-h5-summary.json`、`cr02-key-facts.json`、`cr02-health.json`、`cr02-h5-run.log`、`cr02-real-iphone-375.png`、`cr02-real-iphone-375-second.png`。

### 14.5 O-CR02-01：网页回退仍带 `callnative=1`

- 真实 5/5 回退 URL 形如：
  `https://uri.amap.com/marker?position=104.062212,30.646826&name=%E9%94%A6%E6%B1%9F&coordinate=gaode&callnative=1`
- 高德 URI API 文档对 `callnative` 的定义：`0` 表示不调起，`1` 表示尝试调起高德地图 App；该参数仅在移动端有效（参考：`https://lbs.amap.com/api/uri-api/guide/mobile-web/point/`）。
- 因此，“未安装高德？使用网页版”在 App 未安装/浏览器不支持 scheme 时，仍可能先尝试唤起客户端，再停留或回到网页；无头浏览器无法证明真机最终停在网页还是出现额外提示。
- **口径**：不记 P1/P2，记录为 O-CR02-01；建议产品确认是否将移动端回退 URL 的 `callnative` 改为 `0`（或使用纯网页 marker 链接），确保“网页版”语义纯粹。该调整不影响本轮主链接 scheme 结论。
- 本轮未修改后端；该 URL 由既有 `_navigation_url` 生成。

### 14.6 缺陷与观察项

| 编号 | 级别 | 项 | 状态 |
|---|---|---|---|
| — | P0 | 新发现 P0 | 0 |
| — | P1 | 新发现 P1 | 0 |
| — | P2 | 新发现 P2 | 0 |
| O-CR02-01 | 观察 | 网页回退携带 `callnative=1`，可能再次尝试调起 App | 记录口径，建议产品确认；不阻塞主链接 |
| — | 边界 | 真机实际拉起高德 App | **未验证**；无头浏览器只能验证 href 构造与回退存在 |

- **CR-02 工程侧可签收**：scheme、坐标、名称、参数、移动端回退、桌面 https、CR-01 不回归均有本轮独立证据。
- **真机不计 PASS**：需人类在 iPhone 上实际点击“打开高德导航”，确认高德 App 被拉起；如需覆盖 Android，再补一次 Android 真机。
- **S1 整体准入不改变**。

### 14.7 残留风险

1. **真机调起未验证**：iOS/Android 自定义 scheme 的实际拉起、系统提示、App 内终点识别均依赖真机；无头浏览器不能替代。
2. **未安装场景**：回退链接带 `callnative=1`，App 未安装时是否出现额外唤起提示/是否稳定停留网页版未验证（O-CR02-01）。
3. **浏览器容器差异**：微信/QQ 等内置浏览器可能拦截自定义 scheme；本轮仅模拟标准 Safari/Chrome UA，未覆盖内置浏览器。
4. **入口精度**：真实 5 条中仍有 `center_fallback` 条目，App 终点可能落在水体中心或对岸（既有风险）。
5. **单次样本**：真实仅 1 次 iPhone UA 页面加载、单时段；未测 Android 真机、弱网、并发与 P95。
6. **无 Git 提交**：按约定未执行 `git add/commit/push`；改动留在工作区，由开发/协调角色处理。

### 14.8 产物与合规声明

- 仅验证与文档：未改业务代码、产品测试、CI/运行配置；未重启 8018；未创建 PR/MR；未读取 `.env`；未回显 Key。
- 真实调用串行：health 1 次、真实 H5 页面加载 1 次（仅 1 次钓位请求）；Mock UA 矩阵无上游调用。
- 浏览器请求全部同源；未引入第三方资源；所有产物不含 Key。
- 本轮根目录：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261023-1927\`
  - 报告归档：`reports\qa-report-v1.6.md`
  - 证据：`evidence\cr02\`
  - 发布记录：`publish-log\20261023-cr02.md`
  - 共享副本：`C:\Users\koubinbin\.qoderwake-cn\data\cloud-conversations\conv_01m5f11s2b8as0qr3fky3sp7vf\shared\qa-report.md`

## 15. CR-03 M3 阶段 1+2 独立 QA（2026-10-24，v1.8）

> 触发：小项 seq=393。M1（小厚）与 M2 本地（小钱）已交付，M1b 正在补。阶段 1 先做不受 M1b 影响的检查：A（M1 PWA 壳）与 B（M2 本地安全）；C（M1b 集成）与 P2 复测于阶段 2（v1.8，见 15.13）完成；D（真机 + HTTPS）只产出清单，状态“待托管验证”。
> 约束：未改业务代码/产品测试/CI/运行配置；未重启 8018；未在 8018 开启访问控制；未做端口映射或公网发布；未读取 `.env`；未回显任何 Key。真实上游调用约束见 15.9 的执行偏差声明。

### 15.1 结论总表

| 项 | 结果 | 说明 |
|---|---|---|
| A. M1 PWA 壳 | **PASS（47/47）** | 安装契约、SW 缓存、离线诚实性、安装入口、响应式、CR-01/CR-02 回归全部通过 |
| B. M2 本地安全 | **42/45** | 3 项失败对应 2 个 P2 发现（O-CR03-01、O-CR03-02），均已复测关闭；其余鉴权/CORS/限流/配额/失败即关闭全部通过 |
| C. M1b 集成 | **PASS（26/26）** | 401 跳转/next 回跳/无循环、非契约 401 不误跳、429 提示与不自动重试、正常路径与 CR-01/CR-02/合规回归全部通过（15.7、15.13） |
| D. 真机 + HTTPS | **未执行（待托管验证）** | 已产出 41 项真机/HTTPS 清单，全部标注“待托管验证” |
| 新增 P0/P1/P2 | **0 / 0 / 0** | O-CR03-01、O-CR03-02 已复测关闭 |
| CR-03 签收口径 | **阶段 1+2 工程侧可签收** | A + B + C 完成、P2 关闭；D（真机 + HTTPS）完成后才能讨论 CR-03 整体关闭 |
| S1 整体准入 | **不改变** | 本节只给 CR-03 阶段 1+2 QA 事实，由小项汇总、人类决策 |

### 15.2 测试环境与隔离

| 实例 | 端口 | 模式 | 关键配置 | 用途 |
|---|---|---|---|---|
| PWA Mock | 8033 | Mock（`?mock=1`） | 无访问控制 | A 组 47 项；无上游调用 |
| 安全 Mock | 8022 | Mock + 访问控制 | `FISHAGENT_PUBLIC_ACCESS_ENABLED=true`；测试邀请码/密钥；CORS 白名单 `http://allowed.example`；限流 IP 8 / token 4 / login 3；`TRUST_PROXY_HEADERS=true` 仅用于按合成 XFF 隔离限流桶 | B01–B21、B28–B30、B32–B35 |
| 配额实例 | 8034 | 非 Mock（假 Key） | 三类日配额均为 0；上游 URL 指向本地 guard `127.0.0.1:8099` | B22–B27、B31；**未发出任何真实上游请求** |
| 8018 | 8018 | 真实（既有） | 未重启、未改配置、未开访问控制 | B32/B33 只读复查 |

- 浏览器：系统 Chrome，Playwright headless；PWA 安装性检查使用持久化上下文（默认隐身上下文会返回 `in-incognito`）。
- 移动端 UA 矩阵：iPhone 375×812、Android 375×812、iPadOS 768×1024（Macintosh UA + `maxTouchPoints>1`）、桌面 1280×900。
- 所有测试实例均为本轮临时启动，测试后停止；不使用 8023/8024/8025（已被其他进程占用）。

### 15.3 A. M1 PWA 壳（47/47 PASS）

| 分组 | 检查 | 结果 |
|---|---|---|
| Manifest | `application/manifest+json` MIME；`id/name/short_name/start_url/scope/display/display_override/lang/colors/prefer_related_applications` 与契约一致；4 条 icon 声明（192/512 any + 192/512 maskable） | 5/5 |
| 图标实体 | 请求 5 个图标资源（192/512 any、192/512 maskable、apple-touch 180），均 200、`image/png`、实际像素与声明一致 | PASS |
| iOS/壳 meta | `apple-mobile-web-app-capable`、status bar、`apple-mobile-web-app-title`、`mobile-web-app-capable`、`theme-color`、icon/manifest 链接 | 3/3 |
| SW 注册 | `./sw.js` 注册成功，scope `/`，`active` 且 `controller` 已接管 | PASS |
| 预缓存 | `fishagent-v1-static` 单缓存，10 个壳资源全部命中，无缺失 | PASS |
| API 不缓存 | 访问前后 Cache Storage 均无 `/api/*`；仅静态缓存存在 | 2/2 |
| 版本清理 | 注入旧缓存 `fishagent-v0-legacy` + 重新注册后，旧缓存与旧条目被删除，仅保留 `fishagent-v1-static` | PASS |
| 安装性 | Chrome `Page.getInstallabilityErrors` = `[]`，manifest 无错误 | PASS |
| 安装入口 | 合成 `beforeinstallprompt` 后 Android 安装按钮由隐藏变可见；iOS 显示“分享 → 添加到主屏幕”引导；standalone 模拟下安装按钮与 iOS 引导均隐藏；关闭引导后 sessionStorage 持久 | 5/5 |
| 离线 | `/api/*` 离线返回 503 JSON；离线下壳可打开、显示离线横幅、钓位卡片 0、无缓存/伪造数据；恢复网络后横幅消失并自动刷新 | 6/6 |
| 控制台 | 桌面/iPhone/Android/iPadOS 正常路径 console error 0、pageerror 0；离线阶段的 503 为预期项 | 5/5 |
| 响应式 | 375 / 768 / 1280 均无横向溢出（scrollWidth = clientWidth = innerWidth） | 4/4 |
| CR-01 回归 | 首屏 5 + 本地换批 5→1→5 无新钓位请求；真实请求 `limit=10` 且无 `offset`；半径变更触发重新请求 | 4/4 |
| CR-02 回归 | iPhone `iosamap://path`、Android `amapuri://route/plan/`；5/5 参数与 6 位坐标；网页回退 https + `_blank` + `noopener noreferrer` | 4/4 |
| 合规文案 | 禁钓提示逐字一致且纯文本；AI 标识与免责声明存在 | 2/2 |

- 截图：`cr03-pwa-desktop-1280.png`、`cr03-pwa-persistent-1280.png`、`cr03-pwa-offline-1280.png`、`cr03-pwa-iphone-375.png`、`cr03-pwa-android-375.png`、`cr03-pwa-ipados-768.png`。
- 说明：`display-mode` 的 CDP 模拟未能改变 `matchMedia`，standalone 场景通过 init script 覆盖 `matchMedia('(display-mode: standalone)')` 与 `navigator.standalone` 验证应用逻辑；**真实主屏启动仍属 D 组待验证项**。
- 说明：离线横幅与 `online` 事件在 CDP 离线模拟下不会自动翻转 `navigator.onLine`，因此分别用 init script（`onLine=false`）和显式 `online` 事件验证应用逻辑；真实网络切换仍属 D 组。

### 15.4 B. M2 本地安全（42/45）

| 分组 | 检查 | 结果 |
|---|---|---|
| 登录页 | 200；`X-Frame-Options: DENY`；`Cache-Control: no-store`；CSP 含 `default-src 'none'`、`frame-ancestors 'none'`、`form-action 'self'`；页面无外链资源 | 3/3 |
| 公开面 | `/`、`/manifest.webmanifest`、`/sw.js`、`/health`、`/api/demo/config` 均 200 | 5/5 |
| 受保护面 | 无凭证访问 `/api/fish-activity`、`/api/pilot/usage`、`/openapi.json`、`/docs` 均 401 `UNAUTHORIZED`，带 `WWW-Authenticate: Bearer realm="fishagent-pilot"` 与 `no-store` | 4/4 |
| 令牌语义 | 格式错误 → `INVALID_TOKEN`；篡改 → `INVALID_TOKEN`；过期 → `TOKEN_EXPIRED`（带 `WWW-Authenticate` + `no-store`） | 3/3 |
| 登录/会话 | 正确邀请码 200 且响应体不含令牌；Cookie `HttpOnly; Secure; SameSite=lax; Path=/; Max-Age=43200`；`/api/pilot/session` 登录/匿名状态正确；注销清除 Cookie | 4/4 |
| 错误邀请码 | 401 `INVALID_INVITE_CODE`；但缺 `Cache-Control: no-store` 与 `WWW-Authenticate`（B09b/B09c，见 O-CR03-01） | 1/3 |
| 限流 | 登录 3 次/IP/分钟：第 4 次 429 + `Retry-After: 60`；令牌 4 次/分钟：第 5 次 429；IP 8 次/分钟：第 9 次 429；均返回 `RATE_LIMITED` | 3/3 |
| CORS | 白名单 Origin 预检 200，`ACAO` 精确回显、`ACAC: true`、`Retry-After` 暴露；非白名单预检 400 且无 `ACAO`；实际响应非白名单不加 `ACAO` | 4/4 |
| 每日配额 | 非 Mock 实例 + 假 Key + 配额 0：鱼情（Open-Meteo）、钓位（高德）、Agent（LLM）均 429 `QUOTA_EXCEEDED`，`Retry-After=37040` 与本地零点一致；`/api/pilot/usage` 三项 `exhausted=true`；guard 日志 0 次 CONNECT | 6/6 |
| 日志 | 应用日志不含邀请码、密钥、令牌、假 Key；访问日志含客户端 IP（B29，见 O-CR03-02）；配额实例日志不含密钥 | 2/3 |
| 8018 | PID 70828 仍在监听；`/pilot/login`、`/api/pilot/session`、`/api/pilot/usage` 均 404；`/openapi.json`、`/docs` 无需鉴权 200 | 2/2 |
| 失败即关闭 | 缺邀请码/密钥启动失败（RuntimeError）；`CORS=*` 启动失败 | 2/2 |
| 合计 | **42/45** | 3 项失败：B09b、B09c、B29 |

### 15.5 新增发现

#### O-CR03-01（P2）：错误邀请码的 401 缺少 `Cache-Control: no-store` 与 `WWW-Authenticate`

- **复现**：`POST /api/pilot/login`，body `{"code":"wrong-code"}`，带任意 XFF；观察响应头。
- **预期**：按 `docs/cr03-deployment-plan.md` §4.2“所有 401 均带 `WWW-Authenticate: Bearer realm="fishagent-pilot"`”“所有鉴权错误响应 `Cache-Control: no-store`”，应同时具备两个头。
- **实际**：HTTP 401，body `detail.code=INVALID_INVITE_CODE`；响应头既无 `Cache-Control` 也无 `WWW-Authenticate`。其余 401（`UNAUTHORIZED`/`INVALID_TOKEN`/`TOKEN_EXPIRED`）均正确。
- **影响**：低。错误邀请码响应可能被中间缓存（虽为 POST，通常不缓存）；客户端无法对所有 401 采用统一的 Bearer 处理。**不构成鉴权绕过**，邀请码校验本身正确。
- **置信度**：高（B09b/B09c 两项直接证据，稳定复现）。
- **建议**：在 `pilot/router.py` 的登录错误路径或 `ApiError` 处理器统一补齐 `Cache-Control: no-store` 与 `WWW-Authenticate`。本轮不改代码。
- **v1.8 复测**：**已关闭**。开发者将 401 头统一到 `errors.py` 的 `AUTH_CHALLENGE`/`error_headers`，middleware 复用同一常量。本轮独立复测四类 401（`UNAUTHORIZED`/`INVALID_TOKEN`/`TOKEN_EXPIRED`/`INVALID_INVITE_CODE`）均同时具备 `Cache-Control: no-store` 与 `WWW-Authenticate: Bearer realm="fishagent-pilot"`，共 8/8；登录与业务请求仍 200。

#### O-CR03-02（P2）：uvicorn 访问日志包含客户端 IP

- **复现**：8022 带 `X-Forwarded-For: 10.0.0.20` 请求；8034 带 `10.0.1.11` 请求；查看实例日志。
- **预期**：小项要求“日志不得包含 IP/token/invite code/key”。
- **实际**：应用日志（logger 输出）不含 IP/令牌/邀请码/Key；但 **uvicorn 默认访问日志**记录 `10.0.0.x`/`10.0.1.x` 客户端 IP（无 XFF 时记录 socket peer `127.0.0.1`）。这是 uvicorn 默认 `ProxyHeadersMiddleware` 信任本机回源并写访问日志的行为，不是应用代码打印。
- **影响**：中低。若部署侧保留默认访问日志，会留存客户端 IP，与“日志不含 IP”的要求字面不符；不涉及令牌/邀请码/Key 泄漏。
- **置信度**：高（日志原文：`INFO: 10.0.1.11:0 - "GET /api/fish-activity..." 429`）。
- **建议**：部署时使用 `--no-access-log`，或自定义日志过滤器移除 `client_addr`；若确需访问日志，明确保留期限与访问权限。本轮不改运行配置。
- **v1.8 复测**：**已关闭（部署侧方案可执行）**。部署计划启动命令统一为 `uvicorn fishagent.main:app --host 127.0.0.1 --port 8020 --workers 1 --no-access-log`，新增 §3.1 访问日志策略（方案 A）；本轮以独立实例 8037 实测：`/health` + 4 次 401 + 登录 + 2 次业务共 8 次请求后，日志仅 4 行启动信息、`HTTP/1.1` 访问行 0；功能请求状态 200/401 均正常。反向代理自身访问日志仍需部署时按 §3.1 关闭或脱敏。

### 15.6 8018 复查

- PID **70828** 仍在 `0.0.0.0:8018` 监听；未重启、未改配置。
- `/pilot/login` → 404；`/api/pilot/session` → 404；`/api/pilot/usage` → 404。
- `/openapi.json` → 200、`/docs` → 200（无鉴权），证明访问控制开关未启用。
- 结论：**8018 未被本轮操作改变**。

### 15.7 C. M1b 集成（26/26 PASS，v1.8）

环境：8022（Mock + 访问控制，正常限流）、8036（Mock + 访问控制，token 限流 1）、8034（假 Key + 三类配额 0 + 本地 guard 8099）；Chrome headless，375×812 与 1280×900。

| 分组 | 检查 | 结果 |
|---|---|---|
| 401 三类码跳转 | `UNAUTHORIZED`/`INVALID_TOKEN`/`TOKEN_EXPIRED` 均跳转 `/pilot/login?next=%2F%3Ffrom%3Dqa%26x%3D1`，`next` 解码为 `/?from=qa&x=1` 完整保留，登录页导航次数 1 | 9/9 |
| 登录回跳 | 登录成功后落回 `/?from=qa&x=1`；钓位卡片 4 张；API 状态序列 `[401,401,200,200,200]` | PASS |
| `/pilot/` 无循环 | 已在 `/pilot/probe` 下时 401 不再跳登录页，路径保持 `/pilot/probe` | PASS |
| 非契约 401 不误跳 | 注入 `INVALID_INVITE_CODE` 后页面保持 `/`，仅显示“邀请码不正确”错误文案，无登录跳转 | PASS |
| RATE_LIMITED | 429 共 1 次，`Retry-After: 60`；提示“请求过于频繁，请 60 秒后重试。”；2.1 秒观察窗内后续请求 0 | 3/3 |
| QUOTA_EXCEEDED | 429 共 2 次，`Retry-After: 36330`（与 Asia/Shanghai 零点一致）；提示“今日额度已用完，请 36330 秒后重试。”；2.1 秒观察窗内后续请求 0 | 3/3 |
| CR-01 回归 | 首屏 5 → 换批 1 → 回到 5；状态文案“已换到下一批钓位。”“已展示全部推荐，已回到第 1 批。”逐字一致；换批期间钓位请求 0 | PASS |
| CR-02 回归 | iPhone/Android 均 5 张卡片；`iosamap://`/`amapuri://` 调起判定与网页回退可用；无横向溢出；console/pageerror 0 | 4/4 |
| 正常路径 | 桌面 1280 无横向溢出，console/pageerror 0 | PASS |
| 合规文案 | 禁钓提示逐字存在；AI 标识与免责声明存在 | PASS |
| 上游调用 | 复跑（守卫增强版）0 次 CONNECT，未触达任何真实上游 | PASS |

- 截图：`cr03c-c01-401-login-375.png`、`cr03c-c02-normal-1280.png`、`cr03c-c05-rate-limit-375.png`、`cr03c-c06-quota-375.png`。
- C09 首次运行的 1 次孤立连接调查见 15.13.4；不涉及外部真实接口。
- 真机登录页 401 跳转仍属 D 组待验证项。

### 15.8 D. 真机 + HTTPS（全部待托管验证）

- 清单：`plans/cr03-real-device-https-checklist.md`（41 项，覆盖安装入口/主屏安装/standalone 启动/定位授权/登录 401/429/高德拉起/离线恢复/更新清理/Cookie/响应式/可访问性/合规文案）。
- 当前阻塞：无公网 HTTPS 入口、无试点邀请码、无真机执行环境。
- **结论**：全部标注“待托管验证”，不纳入本轮 PASS 统计，不构成 CR-03 签收依据。

### 15.9 执行偏差声明（必须披露）

- 在 B 组开始前，为确认 8018 是否开启访问控制，本轮**误对 8018 发起了 2 次数据接口探测**：`GET /api/fish-activity`（返回 200）与 `GET /api/spots/recommend`（超时）。
- 这两个接口在真实模式下会调用真实上游（高德/Open-Meteo），因此**违反了“不调用真实 Key”的约束**；可能消耗少量真实额度，具体量无法从本机确认。
- 发现后立即停止：后续 8018 复查仅使用 `/openapi.json`、`/docs`、`/pilot/login`、`/api/pilot/session`、`/api/pilot/usage` 等非数据端点；未再调用任何真实数据接口。
- 未读取、未回显任何 Key；未修改 8018；未重启 8018。

### 15.10 缺陷与观察项汇总

| 编号 | 级别 | 项 | 状态 |
|---|---|---|---|
| — | P0 | 新发现 P0 | 0 |
| — | P1 | 新发现 P1 | 0 |
| O-CR03-01 | **P2** | 错误邀请码 401 缺 `no-store`/`WWW-Authenticate` | **已关闭（v1.8）**；四类 401 头 8/8 通过 |
| O-CR03-02 | **P2** | uvicorn 访问日志含客户端 IP | **已关闭（v1.8）**；`--no-access-log` 实测 0 访问行，§3.1 已定稿 |
| — | 边界 | 真机安装/主屏启动/定位/高德拉起 | 待托管验证 |
| — | 边界 | M1b 401/429 集成 | **已完成，26/26 PASS（v1.8）** |

### 15.11 残留风险

1. **真实设备未验证**：安装、standalone、定位授权、高德 App 拉起、iOS 存储清理均无法由无头浏览器证明。
2. **HTTPS/反向代理未验证**：TLS、SW 同源、`/sw.js`/manifest 不被改写、代理头与 IP 限流在真实拓扑下的行为未验证。
3. **配额计数为进程内存**：重启清零、多 worker 各自计数；试点必须单 worker。
4. **配额与上游账单口径可能不一致**：本轮仅用 0 配额验证 429 路径，未验证真实额度下的计数精度。
5. **限流桶隔离依赖测试用 XFF**：真实部署若代理头配置错误，IP 限流可能被伪造绕过（设计文档已列为风险）。
6. **离线模拟局限**：`navigator.onLine` 与 `online` 事件由脚本模拟，真实网络切换行为待 D 组验证。
7. **访问日志 IP**：uvicorn 默认访问日志已通过 `--no-access-log` 关闭并实测 0 访问行（O-CR03-02 关闭）；反向代理自身访问日志仍需部署时关闭或脱敏（部署计划 §3.1）。
8. **无 Git 提交**：按约定未执行 `git add/commit/push`；本轮仅改 QA 文档与证据。

### 15.12 产物与合规声明

- 仅验证与文档：未改业务代码、产品测试、CI/运行配置；未重启 8018；未在 8018 开启访问控制；未做端口映射/公网发布；未创建 PR/MR；未读取 `.env`；未回显 Key。
- 真实上游调用：A 组全部 Mock；B 组配额实例为假 Key + 0 配额 + 本地 guard，guard 日志 0 次 CONNECT；8018 的 2 次误探测见 15.9。
- 本轮规范根目录（仓库外）：`D:\学习\GitHubCode\qa-outputs\FishAgent\20261024-1335\`
  - 报告归档：`reports\qa-report-v1.7.md`（阶段 1）、`reports\qa-report-v1.8.md`（阶段 1+2）
  - 证据：`evidence\cr03\`（A/B/C 脚本、日志、JSON 汇总、截图、P2 复测产物）
  - 计划：`plans\cr03-real-device-https-checklist.md`
  - 发布记录：`publish-log\20261024-cr03.md`
- 仓库内证据副本（按小项要求）：`docs\evidence\real-mode\cr03\`
- 共享副本：`C:\Users\koubinbin\.qoderwake-cn\data\cloud-conversations\conv_01m5f11s2b8as0qr3fky3sp7vf\shared\qa-report.md`
- SHA-256：三份报告副本的一致性哈希记录在 `publish-log\20261024-cr03.md`。

### 15.13 CR-03 M3 阶段 2 复验（2026-10-24，v1.8）

#### 15.13.1 范围与约束

- 触发：小项 seq=405（C 组复验 + P2 复测）；小厚 seq=402 交付 M1b，小钱 seq=411 交付 P2 修复。
- 约束执行：未改业务代码/产品测试/CI/运行配置；未重启 8018；未在 8018 开启访问控制；未做端口映射/公网发布；未读取/回显任何 Key；未调用任何真实数据接口；临时实例用后停止。

#### 15.13.2 C 组执行环境

| 实例 | 端口 | 模式 | 关键配置 | 用途 |
|---|---|---|---|---|
| C 正常 | 8022 | Mock + 访问控制 | 正常限流；Cookie 非 Secure 仅用于 HTTP 本地测试 | 401 跳转、登录回跳、`/pilot/` 无循环、CR-01/CR-02/合规回归 |
| C 限流 | 8036 | Mock + 访问控制 | `FISHAGENT_PILOT_RATE_LIMIT_TOKEN_PER_MINUTE=1`，IP 限流放宽 | `RATE_LIMITED` 与不自动重试 |
| C 配额 | 8034 | 非 Mock（假 Key） | 三类日配额 0；上游 URL 指向本地 guard `127.0.0.1:8099` | `QUOTA_EXCEEDED` 与不自动重试 |
| P2 日志 | 8037 | Mock + 访问控制 | 启动参数含 `--no-access-log` | O-CR03-02 独立实证 |
| 守卫 | 8099 | 本地 guard | 记录连接与脱敏请求行（丢弃 query） | 证明无上游调用 |

#### 15.13.3 C 组结果：26/26 PASS

| 检查组 | 结果 |
|---|---|
| C01A/B/C：三类 401 跳转 + code + 无循环 | 9/9 |
| C02：登录回跳 + 合规文案 + CR-01 换批 + 桌面 console/溢出 | 4/4 |
| C03：`/pilot/` 下不循环 | 1/1 |
| C04：非契约 401 不误跳 | 1/1 |
| C05：`RATE_LIMITED` 响应/文案/无自动重试 | 3/3 |
| C06：`QUOTA_EXCEEDED` 响应/文案/无自动重试 | 3/3 |
| C07/C08：iPhone/Android CR-02 + console | 4/4 |
| C09：无上游连接 | 1/1（复跑） |

关键证据：401 跳转 URL `http://127.0.0.1:8022/pilot/login?next=%2F%3Ffrom%3Dqa%26x%3D1`，`next` 解码 `/?from=qa&x=1`，登录页导航 1 次；登录后落回 `/?from=qa&x=1`，API 序列 `[401,401,200,200,200]`；限流 429 `Retry-After: 60`、配额 429 `Retry-After: 36330`，2.1 秒窗口内 0 次后续请求；iPhone/Android 均 5 张卡片、调起与回退可用、无溢出、console 0。

#### 15.13.4 P2 复测：11/11 PASS（独立于开发自测）

| 项 | 检查 | 结果 |
|---|---|---|
| O-CR03-01 | 8022 上四类 401 均含 `Cache-Control: no-store` 与 `WWW-Authenticate: Bearer realm="fishagent-pilot"` | 4/4 |
| O-CR03-01 | 8037（`--no-access-log`）四类 401 同样具备两项头 | PASS |
| O-CR03-02 | 8037 启动命令含 `--no-access-log` 且 `--workers 1`；部署计划 §3.1 含 XFF 说明 | 2/2 |
| O-CR03-02 | 8 次请求（health + 4×401 + 登录 + 2×业务）后日志仅 4 行启动信息，`HTTP/1.1` 访问行 0 | PASS |
| 功能 | 登录 200 + Cookie，鱼情/钓位业务 200 | PASS |
| 8018 | 仅 `/health` 只读，200、`mock_mode=false`、PID 70828 未变 | PASS |

- 开发自测与本轮独立复测一致：四类 401 头统一、访问日志 0 行、180 passed/ruff clean（开发侧声明，本轮只验证行为，不重复运行单测）。
- 部署计划启动命令与 §3.1 已同步定稿；本轮未修改运行配置。

#### 15.13.5 上游调用与一次孤立连接

- 第一次 C 组全量运行时，C09 记录到 1 次 CONNECT（05:54:10 UTC，发生在仅 8022 Mock 实例活动期间）；该次运行 C09 FAIL。
- 定位：8034 配额实例隔离复测 0 次 CONNECT；8022/8036 均为 Mock。守卫增强记录对端端口与脱敏请求行后复跑，26/26 且 0 次 CONNECT。
- 判定：一次性、不可复现；连接目标仅为本地 `127.0.0.1:8099` 守卫，**未触达任何外部真实接口**，不涉及真实 Key。两次守卫日志均保留。
- 与阶段 1 的 2 次真实数据接口误探测不同，本轮**未对 8018 发起任何数据接口请求**。

#### 15.13.6 8018 与实例清理

- 8018：PID 70828 仍在 `0.0.0.0:8018`；仅 `GET /health` 只读复查（200，`mock_mode=false`）；未重启、未改配置、未开访问控制。
- 临时实例 8022、8034、8036、8037、8099 均在交付前停止；未触碰 8023/8024/8025。

#### 15.13.7 结论

- C（M1b 集成）**PASS**；O-CR03-01、O-CR03-02 **关闭**；阶段 2 新增 P0/P1/P2 = 0/0/0。
- CR-03 工程侧（A+B+C）具备签收条件；**D（真机 + HTTPS）仍待托管验证**，CR-03 整体不判 GO，S1 整体准入不变，由小项汇总、人类决策。
