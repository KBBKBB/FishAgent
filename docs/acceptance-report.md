# FishAgent MVP 验收报告

> 版本：v1.2 ｜ 初版：2026-10-21 ｜ 更新：2026-10-22 ｜ 验收人：小项（项目协同）
> 结论：**通过（MVP，Mock 模式）**。无未关闭 P0/P1；P2 已关闭或转为已知限制。
> 依据：`docs/api-contract.md` v1.3、`docs/mvp-prd.md` v1.2、`docs/qa-plan.md` v1.3、`Spec/TechStack.md`。
> 补充（2026-10-22）：真实 Key 联调见第 9 节，结论为**通过**；契约升至 v1.3。
> 补充（2026-10-22，P2 收口）：见第 10 节，97 passed、最终独立真实模式复跑 PASS（P0/P1/P2 = 0/0/0）；试点准入见 `docs/pilot-checklist.md`。
> 补充（2026-10-22，成都校准）：D1 改为成都及郊区；见第 11 节，P0 餐饮 POI 误判已修复复核，D11、Key、R10 已闭环，独立 QA 工程 PASS；**Conditional GO 已由人类接受（2026-10-22）**；D4 由人类确认已设置后，**S1 于 2026-10-22 放行、2026-10-23 启动**（见 §11.6）。

## 1. 验收目标与范围

交付一个可运行的 FishAgent MVP：

- FastAPI 后端：F1–F7 鱼情规则引擎、五档结论、最佳时段/水深/鱼种建议、强制安全提示。
- 钓位推荐：召回 → 禁钓过滤 → 去/回程车程 → 往返 ≤2 小时过滤 → 排序；入口坐标回退标注。
- 坐标转换：WGS84 → GCJ-02 单一入口，服务端完成。
- LangGraph 自然语言 Agent：意图识别 → 工具调用 → 回答编排；无 LLM Key 时确定性兜底。
- H5 演示界面：定位/手输坐标、评分卡、评分依据数据条、钓位列表、对话区；移动端可用。
- Mock 模式开箱可跑；附自动化测试、运行文档、QA 报告与本验收报告。

**不在本轮范围**：微信小程序、生成式 AI 备案/登记、UGC、真实数据商用授权、海钓/潮汐、权威禁钓矢量边界。详见 `Spec/Roadmap.md`。

## 2. 交付物

| 交付物 | 路径 | 状态 |
|---|---|---|
| 后端应用 | `backend/fishagent/` | 完成 |
| 自动化测试 | `backend/tests/`（89 用例） | 全绿 |
| H5 演示页 | `web/`（同源静态托管） | 完成 |
| API 契约 | `docs/api-contract.md` v1.2 | 完成 |
| MVP PRD | `docs/mvp-prd.md` v1.2 | 完成 |
| 演示场景 | `fixtures/demo_scenarios.json`（20 场景 / 54 步） | 完成 |
| 测试计划 / 报告 | `docs/qa-plan.md`、`docs/qa-report.md` | 完成 |
| 运行文档 | `README.md` | 完成 |
| 验收证据 | `docs/evidence/` | 完成 |

## 3. 验收结果

| 验收项 | 结果 | 证据 |
|---|---|---|
| 全量 pytest | **89 passed / 0 failed** | `docs/evidence/pytest-full.log` |
| 静态质量 | ruff All checks passed | `docs/evidence/ruff.log` |
| API + H5 独立验收 | **148/148 通过** | `docs/evidence/acceptance-log.txt`、`acceptance-summary.json` |
| 真实后端 H5 E2E | 375px/1280px 通过，无 console error、无第三方直连 | `docs/evidence/e2e-375.png`、`docs/evidence/e2e-1280.png` |
| P0 | 0 | QA 报告 |
| P1 | 0 未关闭（F-01 已修复复测；坐标测试数据已修正） | QA 报告 §8 |
| P2 | F-02/F-04 已关闭；F-03 转 M3 已知限制 | QA 报告 §8.5 |

### 3.1 功能验收要点

- **鱼情规则**：五档评分与 `best_windows` 数量 2/2/2/1/0 一致；`no_go` 返回 GALE / RAINSTORM / PRESSURE_PLUNGE 三条强制提示。
- **钓位推荐**：`filtered` 六字段满足两条不变式；往返 = 去程 + 回程且 ≤7200s；入口缺失回退 `center_fallback`；导航链接为高德 https。
- **坐标**：实现与 eviltransform 权威参考在杭州/北京/深圳三点 maxdiff < 1e-7；服务端为唯一转换入口。
- **Agent**：三类问句均命中固定工具 `get_fish_activity` / `recommend_spots`；回复 2–5 句；无承诺词；AI 标识齐全。
- **H5**：手输坐标更新、评分卡、评分依据数据条（标题「评分依据（非天气预报）」）、钓位 filtered 展示、对话、移动端均通过。
- **合规**：前端无 Key、无第三方直连；Mock 数据与免责声明可见；不承诺渔获。

## 4. 缺陷与处置

| 编号 | 级别 | 结论 | 处置 |
|---|---|---|---|
| F-01 Agent fallback 句数超限 | P1 | 已关闭 | 优先级装配 + 硬裁 5 句，强制安全提示保留；专项 24/24、回归 15 passed |
| F-02 承诺词护栏不完整 | P2 | 已关闭 | 补齐「百分百 / 100% / 绝不空军」，正常文本不误杀 |
| F-03「明早」未传 at | P2 | 已知限制 M3 | 当前按当前时刻评估；后续解析相对日期 |
| F-04 原始气象数据条 | P2 | 已关闭 | 保留数据条并加标题/副注，符合 AT-UI-06 |
| COORD 测试数据错误 | P1（测试） | 已关闭 | 杭州期望值与偏移上限按三点复核定稿；仅改测试数据 |

## 5. 已知限制与残留风险

1. **真实链路未验证**：未配置 Open-Meteo / 高德 / LLM Key；全部证据来自 Mock/fallback。上线前需完成真实 Key 联调、配额与限流验证。
2. **真实路况未接入**：车程为基线估计，非实时导航；页面已标注「预估」。
3. **F5 降水口径为临时规则**，待真实数据校准（Backlog）。
4. **「明早」语义**：未解析目标日期并传 `at`，属 M3 改进项。
5. **QA 运行器故障**：小测的运行器三次报 `CONVERSATION_RUNTIME_CLEANUP_PENDING`，本轮运行时验收由小项代执行；建议恢复后由小测独立复跑，恢复 QA 签字（不影响本轮产品结论）。
6. **无 Git 提交**：当前改动为工作区文件，未提交；发布前需按仓库规范处理。

## 6. 复现步骤（已验证）

```bash
# 安装（仓库根目录）
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -e "backend[dev]"

# 启动（Mock 模式，无需 .env；8000 被占用时可换 8031）
cd backend
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn fishagent.main:app --host 127.0.0.1 --port 8031

# 打开 http://127.0.0.1:8031/ ，定位或手输坐标，查看鱼情/钓位/对话

# 测试
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests -q
```

演示问句：`今天气压适合钓鱼吗？`、`附近哪里野钓好？`、`明早几点去最好？`。
Mock 五档：`/api/fish-activity?lat=30.2741&lon=120.1551&scenario=excellent|good|fair|poor|no_go`。

## 7. 角色与签署

| 角色 | 成员 | 交付 | 状态 |
|---|---|---|---|
| 项目协同 / 验收 | 小项 | 计划、契约、README、验收报告、代执行运行验收 | 完成 |
| 后端实现 | 小钱 | 后端核心、Provider、服务与 API、自测与坐标复核 | 完成 |
| Agent / H5 | 小厚 | LangGraph Agent、H5、P1/P2 修复与 E2E 证据 | 完成 |
| 产品 / 验收数据 | 小产 | PRD v1.2、fixtures 20 场景/54 步 | 完成 |
| QA | 小测 | 测试计划 v1.2、静态审查、缺陷发现；运行器故障未执行运行时 | 计划/审查完成；运行时由小项代执行 |

## 8. 结论

FishAgent MVP 在 Mock 模式下可启动、可演示、可测试，满足本轮验收标准；建议按第 5 节完成真实 Key 联调与独立 QA 复跑后进入试点。

## 9. 真实 Key 补充验收（2026-10-22）

> 验收人：小项（项目协同）｜ 依据：`docs/api-contract.md` v1.3、QA 报告 §9、`docs/evidence/real-mode/`
> 结论：**通过（真实 Provider 链路）**。无未关闭 P0/P1；发现的问题均已修复或转为已知限制。Mock 模式仍为零配置默认路径。

### 9.1 验收结果

| 验收项 | 结果 | 证据 |
|---|---|---|
| AMap / Open-Meteo / DeepSeek 连通 | 均连通，服务端 Key 生效 | `real-mode/fish-activity.json`、`amap-measure.log`、`agent-chat-final.json` |
| 真实鱼情 | 杭州西湖 81 分 / 良好；F1–F7 合计 = 81；Open-Meteo；时区正确 | `fish-activity.json` |
| 真实钓位 100km | 20.79–21.77s；644 候选；Top5 古新河/西溪/东河/中河/希颜溪，全为河流；往返 ≤7200s | `spots-perf-final.json`、`h5-e2e.log` |
| 真实钓位 50km | 15.65s；47 候选；Top5 与 100km 同名同类型 | `spots-perf-final.json` |
| 契约 v1.3 不变式 | 三条全部通过 | `h5-e2e.log`、`spots-perf-final.json` |
| LangGraph LLM | 三问均 `mode=llm`；3–4 句；无承诺词；工具 ok | `agent-chat-final.json` |
| H5 真实模式 E2E | 0 失败 / 0 告警；牌标“在线数据”/“LLM”；375/1280 无横向滚动、无 console error | `h5-e2e.log`、`web-real-375.png`、`web-real-1280.png` |
| 自动化 | 96 passed / 0 failed（3.82s，当时基线）；ruff All checks passed | `pytest-full.log`、`ruff.log`；P2 收口后 97 passed，见第 10 节 |

### 9.2 真实模式关键指标

| 指标 | 数值 |
|---|---|
| 100km 钓位接口耗时 | 20.79–21.77s（优化前 >240s） |
| 100km filtered | total 644 / forbidden 9 / unavailable 0 / >2h 0 / eligible 10 / returned 5 / truncated 5 / evaluated 10 / unevaluated 625 |
| 50km filtered | total 47 / forbidden 9 / unavailable 0 / >2h 0 / eligible 10 / returned 5 / truncated 5 / evaluated 10 / unevaluated 28 |
| Agent 三问耗时 | 4.67s / 42.44s / 2.38s（另一样本 7.76s / 51.21s / 2.88s） |
| 真实 LLM 回答 | 3–4 句，无承诺词，无 Markdown 标记 |

### 9.3 本轮交付变更

- **Provider/服务**：自然水体类型召回、业务 POI 过滤、`/v3/distance` 批量预筛、最近 30 精算上限、并发 6 / QPS 2；契约 v1.3 新增 `unavailable/evaluated/unevaluated`。
- **Agent**：工具超时从 8s 改为可配置 45s（`FISHAGENT_TOOL_TIMEOUT_SECONDS`）；`ANSWER_SYSTEM_PROMPT` 增加纯文本约束。
- **配置**：`FISHAGENT_AMAP_CONCURRENCY` / `FISHAGENT_AMAP_QPS`；修复 httpx 对 `NO_PROXY` 中 `[::1]` 的解析崩溃。
- **测试**：新增 7 个用例（水体召回 3、性能/截断/unavailable/Mock 回归 4），全量 96 passed。
- **文档**：契约 v1.3、README 真实模式说明、QA 报告 §9、本补充验收。

### 9.4 新增/关闭缺陷

| 编号 | 级别 | 结论 | 处置 |
|---|---|---|---|
| R-01 100km 真实链路 >240s | P1 | 已关闭 | 类型召回 + 批量预筛 + 精算上限 + 并发/QPS，降至约 21s |
| R-02 真实 POI 混入餐饮/小区 | P1 | 已关闭 | `types=190204\|190205` + 名称/类型过滤，Top5 全为自然水体 |
| R-03 Agent 工具 8s 超时 | P1 | 已关闭 | 可配置 45s + `asyncio.wait_for`，钓位对话恢复 LLM |
| R-04 Markdown 星号 | P2 | 已关闭 | Prompt 纯文本约束；H5 与三问复跑无标记 |
| R-05 NO_PROXY IPv6 崩溃 | P2 | 已关闭 | 启动时规范化 NO_PROXY |
| R-06 `unevaluated` 未展示 | P2 | 待办 | 字段已提供，H5 后续补充 |

### 9.5 已知限制与残留风险

1. **回程方向近似**：Provider 忽略 `direction`，去/回均按用户→钓位方向估算；两次调用独立但回程非真实返程路况。
2. **入口坐标缺失**：真实 Top5 全部 `center_fallback`，导航终点为水体中心，页面已提示精度较低。
3. **多 typecode 漏召回**：精确匹配 typecode 会排除 `190301|120302|190204` 一类水域 POI。
4. **覆盖有限**：仅杭州起点；共享配额未做真实模式 P95/限流压测；未覆盖多城市、多时段。
5. **真实延迟波动**：钓位问句 21–51s；H5 仅有“输入中”状态，建议后续加进度提示/流式输出。
6. **H5 字段缺口**：`unevaluated` 未展示（P2）。
7. **QA 独立性**：本轮真实模式补充验证由小项执行，独立 QA 复跑仍建议在运行器恢复后进行。

### 9.6 密钥与发布

- Key 仅存于 `backend/.env`，已被 `.gitignore:153` 忽略；无 `.env` 被 Git 跟踪。
- 对仓库、共享目录、前端与证据的扫描未发现精确 AMap/LLM Key 或 `sk-` 模式命中。
- Key 曾在群聊明文提供，**联调结束后应立即轮换**。
- 当前改动未做 Git 提交，按约定由项目统一处理。

### 9.7 角色与签署（补充）

| 角色 | 成员 | 补充交付 | 状态 |
|---|---|---|---|
| 项目协同 / 验收 | 小项 | 真实模式复核、H5 E2E、报告与证据 | 完成 |
| 后端 / Provider | 小钱 | 钓位性能与召回质量修复、契约 v1.3、96 测试 | 完成 |
| Agent / H5 | 小厚 | 工具超时、Markdown 约束、修复验证 | 完成 |
| QA | 小测 | Mock 阶段测试计划与静态审查 | 真实模式独立复跑已完成（2026-10-22，见第 10 节） |

### 9.8 补充结论

真实 Key 链路已达到可试点标准：Provider 连通、真实鱼情与钓位可用、LangGraph LLM 回答合规、H5 端到端可用。进入试点前应完成 Key 轮换、独立 QA 复跑，并按优先级处理 `unevaluated` 展示、入口坐标与多 typecode 召回等 P2 项。

> 上述前置项已于 2026-10-22 P2 收口中完成，独立 QA 复跑通过；详见第 10 节与 `docs/pilot-checklist.md`。Key 轮换与试点范围/阈值仍待人类确认。

---

## 10. P2 收口与最终独立复跑（2026-10-22）

### 10.1 结论

- P2-A/P2-B/P2-C 已处置：P2-A、P2-C 关闭；P2-B 采用方案 A（保留 `center_fallback` + 显著提示），方案 C 作为试点反馈后的备选。
- 全量自动化 **97 passed / 0 failed**，ruff 通过；最终独立真实模式复跑 **PASS**，新增 P0/P1/P2 = **0/0/0**，仅 1 项建议级观察 O-01。
- 工程侧已达可试点状态；试点邀请仍需人类完成 R1 Key 轮换、R5/R7/R8/R9/R10 确认，详见 `docs/pilot-checklist.md`。

### 10.2 P2 处置结果

| 编号 | 问题 | 处置 | 状态 |
|---|---|---|---|
| P2-A | 多 typecode 水域 POI 漏召回 | `providers/amap.py` 按 `|` 拆分 typecode 逐项判断；新增 `test_around_search_keeps_multi_typecode_water_pois`；真实 Top5 全为自然水体 | 关闭 |
| P2-B | 入口坐标稀疏，导航终点回退水体中心 | 抽样 50 个 50km 自然水体 POI，仅 9 个含 `entr_location`（18%），Top5 为 0/5；采用方案 A：保留 `center_fallback` 并逐条提示“端点精度较低”；方案 C（懒加载入口查询 + 缓存）待试点反馈 | 本轮采纳 A |
| P2-C | H5 未展示 `unevaluated`、无慢加载提示 | `web/app.js`：>0 时显示“未评估 N（超出本轮预算）”，为 0 隐藏；请求 >3s 显示“正在规划车程，真实模式约需 20 秒”；真实 100km 验证通过 | 关闭 |

### 10.3 最终独立复跑（QA：小测）

| 项 | 结果 |
|---|---|
| pytest / ruff | 97 passed / 0 failed（3.29s）；JUnit tests=97 errors=0 failures=0；All checks passed |
| 真实 100km spots | 22.60s；filtered 650 / 9 / 0 / 0 / 10 / 5 / 5 / evaluated 10 / unevaluated 631 |
| 真实 50km spots | 14.37s；filtered 50 / 9 / 0 / 0 / 10 / 5 / 5 / evaluated 10 / unevaluated 31 |
| 不变式 | 三条均成立；`returned = len(spots) = 5`；两档首次成功、无 5xx/重试 |
| Top5 | 古新河/西溪/东河/中河/希颜溪，全为河流；100km 往返 942–1776s，50km 958–1756s，均 ≤7200s；5/5 `center_fallback` |
| 真实鱼情 | 88 分 / 极佳；F1–F7 合计 88；Open-Meteo；1.29s；窗口 04:35–07:35、15:22–17:22 |
| H5 真实模式 | 18/18：3.06s 慢提示、未评估 631、375/1280 无溢出、三问 LLM、工具 ok、无 Markdown/承诺词、console error 0、请求全同源 |
| 缺陷 | P0 0 / P1 0 / P2 0；O-01：50km `unevaluated` 文案未区分“提前满足限额”与“预算耗尽”（建议级） |

### 10.4 50km `unevaluated=31` 口径

契约内预期，不是展示缺陷：可评估候选 41（50 − 禁钓 9），首批 10 个精算后得到 10 个 eligible，达到 `limit=5` 后提前停止；剩余 31 个未进入评估窗口，计入 `unevaluated`。三条不变式仍成立。H5 未把未评估候选显示为可达钓位。

### 10.5 证据索引

- QA 报告第 10 节：`docs/qa-report.md`；归档 `qa-outputs/FishAgent/20261022-133142/reports/qa-report-v1.2.md`。
- 本报告自检证据：`docs/evidence/real-mode/`（`summary.json`、`pytest-full-p2.log`、`ruff-p2.log`、`spots-perf-p2.json`、`h5-e2e.log`、`agent-chat-final.json`、`web-real-375.png`、`web-real-1280.png`）。
- QA 独立复跑证据：`qa-outputs/FishAgent/20261022-133142/evidence/real-mode-final/`（pytest、ruff、spots JSON、H5 JSON、4 张截图、复跑脚本）。
- P2-C 专项证据：`docs/evidence/real-mode/web-p2c-slow-hint-375.png`、`web-p2c-unevaluated-375.png`、`web-p2c-unevaluated-1280.png`、`web-p2c-mock-375.png`、`p2c-h5-check.log`。
- P2-B 探针：`docs/evidence/real-mode/entry-location-probe.log`、`route-endpoint-probe.log`；P2-A 探针：`multi-typecode-probe.log`。

### 10.6 残留风险（更新）

1. 入口坐标稀疏：Top5 5/5 `center_fallback`，导航终点为水体中心；已逐条提示，试点需观察导航落点。
2. 回程方向近似：Provider 忽略 `direction`，回程不是真实返程路况。
3. F-03「明早」未解析并传 `at`，时段建议按当前时刻评估；登记 M3，不阻塞。
4. 仅杭州单点、单实例；未做多城市、真实 P95 压测、配额耗尽与故障切换演练。
5. 钓位 14–23s、Agent 钓位问句历史 21–51s；3s 慢提示已缓解，但无流式/阶段进度。
6. 50km `unevaluated` 文案精度（O-01），后续可区分提前停止与预算耗尽。
7. Key 曾明文出现在群聊，**轮换仍待人类执行并验证**。
8. 当前改动未做 Git 提交，按约定由项目统一处理。

### 10.7 试点准入建议

**Conditional GO（工程侧就绪，人类决策未闭环）**：在 R1 Key 轮换、R5 入口方案签署、R7 隐私合规复核、R8 试点范围/规模/周期/配额、R9 阈值与停止条件、R10 回滚演练完成前，不邀请真实用户。决策项与责任人见 `docs/pilot-checklist.md` §B。

> 后续状态（2026-10-22）：上述工程项均已闭环，人类已接受 Conditional GO；当前仅剩外部邀请前 4 项条件，见 §11.6 与 `docs/pilot-checklist.md` §H。

### 10.8 签署

| 角色 | 成员 | 本轮交付 | 状态 |
|---|---|---|---|
| 项目协同 / 验收 | 小项 | 8018 重启、全量测试、H5 E2E、证据与验收收口 | 完成 |
| 后端 / Provider | 小钱 | P2-A 多 typecode 修复 + 单测；P2-B 探针与方案 | 完成 |
| Agent / H5 | 小厚 | P2-C unevaluated 展示与慢加载提示；真实验证 | 完成 |
| QA | 小测 | 最终独立真实模式复跑；qa-plan v1.3；qa-report 第 10 节 | 完成 |
| 产品 | 小产 | 试点提案 v0.1（范围、指标、停止条件、准入） | 完成 |
| 人类 / Owner | kbbisgentleman | Key 轮换、试点范围与阈值批准、go/no-go | **待确认** |

### 10.9 密钥与合规

- 仓库与共享目录全量扫描：精确 AMap/LLM Key 与 `sk-` 模式命中 **0**（排除 `backend/.env`，该文件已 gitignore）。
- 本轮未输出、未复制 Key；证据与报告不含 Key。
- 未执行 Git 提交；未对外发布。

---

## 11. 成都试点校准抽检（2026-10-22）

### 11.1 背景与结论

人类于 2026-10-22 将试点城市 D1 由杭州改为**成都及郊区**，D2–D10 按建议确认。此前真实验收均以杭州为起点，不能直接外推到成都。本轮以成都天府广场（30.6570, 104.0660）为起点做真实抽检，结论：**成都暂不满足试点准入（NO-GO）**，需先修复 P0 并补齐禁钓清单；上述阻塞已于同日闭环，最终建议见 §11.6。

### 11.2 抽检结果

| 项 | 结果 |
|---|---|
| 真实鱼情 | 85 分 / 极佳；1.38s；窗口 05:39–08:39、16:26–18:26；Open-Meteo |
| 50km 钓位（修复前） | 16.45s；filtered 50 / 禁钓 0 / evaluated 10 / unevaluated 40；Top5 锦江、府河、碗山河（餐饮）、锦江、东湖 |
| 100km 钓位（修复前） | 19.35s 与 33.33s 两次样本（尾部超 30s Gate）；filtered 650 / 禁钓 0 / evaluated 10 / unevaluated 640 |
| 50km 钓位（P0 修复后） | **13.92s**；filtered 49 / 禁钓 0 / evaluated 10 / unevaluated 39；Top5 锦江、府河、锦江、西郊河、东湖，全为自然水体 |
| 100km 钓位（P0 修复后） | **18.71s**；filtered 649 / 禁钓 0 / evaluated 10 / unevaluated 639；Top5 同 50km，全为自然水体 |
| 车程 | 修复后 50/100km Top5 往返均 ≤7200s |
| 入口精度 | 5/5 `center_fallback`，与杭州一致 |
| Agent 对话 | 真实 LLM；`get_fish_activity` + `recommend_spots` 均 ok；37.88s |
| 独立 QA（小测） | **98 passed** / ruff clean；50km **23.32s**、100km **20.98s**；Top5 全自然水体、不变式成立；H5 **27/27**；Agent 2/2；新增 P0/P1/P2 = 0/0/0；O-02 同名锦江 |
| D11 + Key 增量独立 QA（小测） | **126 passed** / ruff clean；50km **14.65s**、100km **26.15s**；Top5 全自然水体、无保护地/商业名；H5 **34/34**；Key 服务级抽验通过；P0/P1/P2 = 0/0/0 |
| 证据 | `docs/evidence/real-mode/chengdu-probe.json`（修复前）、`chengdu-final-e2e.json` / `.log`（修复后，37/37 PASS）、`chengdu-h5-check.log`（42/42 PASS）、`key-rotation-verify.json`、`d11-h5-check.log`、`rollback-drill.json` / `.log`、`docs/qa-report.md` §11–§12 + `qa-outputs/FishAgent/20261022-155000/`、`20261022-165000/` |

### 11.3 新增缺陷与缺口

| 编号 | 级别 | 问题 | 处置 |
|---|---|---|---|
| C-01 | P0 | Top5 含餐饮 POI“碗山河·西南风味菜·现炒浇头面(水璟唐店)”；高德将其标为 `190204（自然地名;河流）`，同坐标另有 `050000` 餐饮 POI | **已关闭（小项复核）**：`_has_business_name()` 保守经营词排除 + 回归测试；全量 98 passed、ruff clean；修复后 50/100km Top5 均无餐饮 POI |
| C-02 | P1/合规 | 成都 50/100km `forbidden=0`；示例禁钓圆区仅覆盖杭州西湖，成都无本地边界/清单 | **已关闭（工程）**：人类授权 D11“默认允许、保护地除外”；后端新增 8 个保护地关键词 + 28 条测试，H5 常驻“以当地公告为准”提示；小测独立复验 126 passed、Top5 无保护地/商业名。名称过滤仍为启发式，不承诺禁钓完整性 |
| C-03 | P1/体验 | H5 默认位置仍为杭州、默认半径 100km；D1/D10 未落地 | **已关闭**：小厚改为真实模式默认成都天府广场、默认 50km 可选 100km；Mock 保留杭州示例；成都 H5 33/33 PASS |
| O-02 | 观察 | “锦江”在 Top5 出现两次（不同 POI/河段），当前仅按 POI id 去重 | 暂不判缺陷；试点观察是否需要按名称合并 |
| O-03 | 观察 | 100km 修复后样本 34.26s / 30.13s / 18.71s，尾部仍可能超过提案 Gate 30s | 支持 D10 默认 50km；100km 作为可选项并继续观测 |

### 11.4 与杭州结论的关系

- 杭州的 97 passed、独立 QA PASS、H5 18/18 仍是有效历史基线，但**不覆盖成都**。
- 成都 P0 已修复并由小项复核：全量 **98 passed**、ruff clean；8018 重启后最终 E2E API **37/37**、H5 **33/33**，50/100km Top5 全为自然水体，不变式与往返上限成立。
- 小测已按成都起点完成独立复验：**98 passed**、API 50/100km、H5 **27/27**、Agent 2/2，新增 P0/P1/P2 = **0/0/0**；工程侧通过。
- 召回质量与独立 QA 已闭环；禁钓合规（D11）与 Key 轮换（D4/R1）仍待人类，不因工程 PASS 判 GO。
- 性能口径备注：小测 50km 单次 **23.32s** 高于提案 §4.2 的 20s Gate 线；该 Gate 定义为 **P95**，当前仅单次样本，不能据此判定 Gate 通过或失败，S1 期需统计 P95。100km 历史 30–34s 尾部风险仍在，默认 50km。

### 11.5 当前准入状态（2026-10-22 收口前）

**成都 NO-GO（已解除）**，原阻塞项：D11（成都禁钓策略）、D4/R1（Key 轮换）。C-01、C-03 已关闭，独立成都 QA 已通过；D1–D10 已由人类确认，D1 成都、D10 默认 50km 已在 H5 落地。收口结果见 §11.6。详见 `docs/pilot-checklist.md` §A、§B、§E。

### 11.6 D11 + Key + R10 收口与准入建议（2026-10-22）

| 项 | 结果 | 证据 |
|---|---|---|
| Key 轮换（R1/D4） | **已关闭（服务级）**：8018 重启后真实模式；鱼情 / 50km 钓位 / chat 均 200；仓库+qa-outputs+共享精确 Key 0、`sk-` 0 | `docs/evidence/real-mode/key-rotation-verify.json`；`docs/qa-report.md` §12.3、§12.6 |
| D11 后端策略 | **已关闭（工程）**：默认允许、保护地/水源/军事/禁渔等名称或圆区除外；新增 8 个保护地关键词 + 28 条测试；126 passed、ruff clean | `backend/fishagent/core/forbidden.py`、`backend/tests/test_forbidden.py`；`chengdu-final-e2e.json`；qa-report §12.2、§12.4 |
| D11 H5 提示 | **已关闭（工程）**：真实/Mock 常驻“禁钓提示…以当地公告为准”，逐字一致；375/1280 无溢出、console 0；D1/D10 不回归 | `d11-h5-check.log`、`chengdu-h5-check.log`（42/42）、`web-cd-compliance-375.png`；qa-report §12.5 |
| R10 回滚演练 | **已关闭**：停服 0.51s 且不可访问；Mock 启动 4.33s、`mock_mode=true`、H5 徽标“Mock 模式”；Mock 停服 0.50s；随后恢复真实模式 | `rollback-drill.json` / `.log`、`rollback-mock-375.png` |
| 独立复验 | PASS：126 passed；D11 API 50/100km 14.65s / 26.15s；H5 34/34；P0/P1/P2 = 0/0/0 | `docs/qa-report.md` v1.4 §12，SHA-256 `c89de6cf28972870abfec551bc22d5deab0aa0a0a38874dac046fe9fb87c0aef` |
| 人类签署 | **已接受（2026-10-22）**：人类回复“接受”，确认接受残余风险与 Conditional GO；条件⑤闭环 | 群消息 seq=233；`docs/pilot-checklist.md` §H |
| 人类按建议确认 | **已确认（2026-10-22）**：D4 建议配额、R7 文案、R8 支持值班、天气覆盖方案；R7 关闭、R8 桌面演练 PASS | 群消息 seq=242；`docs/pilot-checklist.md` §H；`docs/evidence/s1-readiness/r8-tabletop-drill.json` |
| D4 配额完成 | **已关闭（人类确认）**：人类 2026-10-22 回复“已按D4设置好”；小项随后复验真实链路正常：鱼情 200/1.45s、50km 钓位 200/14.34s；控制台截图未提供，可后补 | 群消息 seq=251；`docs/pilot-checklist.md` v0.10 §B/§H |
| S1 启动 | **已启动（2026-10-23 08:53，UTC+8）**：真实模式、H5 200；鱼情 200/1.331s/91 分；成都 50km 钓位 200/12.722s，Top5 全自然水体；今日降雨日 1/1；暂未邀请用户（待建群） | `docs/evidence/s1-launch/kickoff-2026-10-23.json`；`docs/s1-run-log.md` |
| S1 内网访问 | **已开通（人类选择 B）**：监听 `0.0.0.0:8018`，内网 `http://192.168.31.68:8018/`；经内网 IP 复验 health/H5 200、鱼情 200/1.570s、50km 钓位 200/14.785s；仅限可信内网、无鉴权 | `docs/evidence/s1-launch/lan-access-2026-10-23.json`；`docs/s1-run-log.md` §7 |
| 新增缺陷 | 0 P0 / 0 P1 / 0 P2；O-02 同名锦江、府河(锦江) 保留为观察项 | qa-report §12.7 |

**残余风险**

1. **名称启发式**：仅按名称关键词与已配置圆区排除，无法覆盖未标注保护地、边界变化或地方临时禁钓；`forbidden=0` 不是合规结论，页面与对外文案必须保留“以当地公告为准”。
2. **入口精度**：成都 Top5 5/5 `center_fallback`，导航终点可能落在水体中心或对岸。
3. **延迟尾部**：100km 单次 26.15s，历史 30–34s；未测 P95/限流/并发；默认 50km、100km 可选且不承诺固定耗时。
4. **覆盖范围**：仅成都天府广场单点、单实例、单时段；未做弱网、多时段、多城市验证。
5. **同名水体**：锦江/府河(锦江) 在 Top5 中区分度不足（O-02）。

**准入建议：GO —— S1 已放行（成都封闭内测，2026-10-22）**

- 工程/合规阻塞（P0、D11、Key、R10）均已关闭；**S1 已获放行**：成都及郊区、3–5 名定向邀请、默认 50km、100km 可选、不公开招募。
- 外部邀请前条件（全部闭环）：
  1. **D4 配额/费用上限**：**已关闭**（人类 2026-10-22 回复“已按D4设置好”；建议值：高德 2,000 次/日、DeepSeek 200 次/日、Open-Meteo 1,000 次/日、月度 ¥100；截图未提供，可后补）；变更后小项复验真实链路：鱼情 200/1.45s、50km 钓位 200/14.34s；
  2. **R7 合规文案终审**：**已关闭**（人类 2026-10-22 按建议确认 D11 提示、AI 披露、免责声明与邀请文案口径）；
  3. **R8 支持渠道与值班**：**安排已确认，桌面演练 PASS**；试点群实时消息测试在 S1 启动时执行（不阻塞邀请）；
  4. **天气过程覆盖**：方案已确认；S1 期间至少记录晴好与降雨/大风各一次，未覆盖不结束 S1；
  5. **接受残余风险**：**已关闭**（人类 2026-10-22 回复“接受”）。
- **S1 放行时间：2026-10-22；启动时间：2026-10-23 08:53**。开服核验 PASS（真实模式、H5 200、鱼情 91 分/1.331s、50km 钓位 12.722s），降雨日 1/1 已记录；内网访问已按选项 B 开通（`http://192.168.31.68:8018/`，仅限同一 Wi-Fi、无鉴权），经内网 IP 复验 health/H5/鱼情/50km 均 200；运行台账 `docs/s1-run-log.md`。当前待人类建立试点微信群并提供群名、发出首批 3–5 人定向邀请；建群后执行群内 P0/P1 实测，期间统计 P95 并补齐晴好天气样本。
