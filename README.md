# FishAgent（垂钓智行）

为钓鱼爱好者提供「今天去哪里钓、几点去、值不值得去」的**决策型智能体**。基于气象数据、地理信息与钓鱼经验规则，输出鱼口活跃度评分、可解释因子与 2 小时往返车程内的钓位推荐，并支持自然语言对话。

> 产品定位：钓鱼辅助决策工具，输出仅供参考，**不承诺渔获**。鱼情差时会明确劝退——「省下一趟」也是产品价值。

## 功能

- **鱼情分析**：F1–F7 七因子规则引擎，0–100 评分、五档结论、Top 3 因子解释、最佳时段 / 水深 / 鱼种建议；暴雨、雷雨、大风等场景强制提示。
- **钓位推荐**：水域 POI 双路召回思路 + 入口坐标 + 去/回程分别精算，按往返 ≤ 2 小时过滤；禁钓区保守排除；按鱼情、水域类型、鱼种适配度与车程综合排序。
- **推荐鱼种**：每个钓位卡异步展示小红书网友分享的鱼种；查不到时明确提示「暂无相关鱼种推荐」。来源与「仅供参考」标识随结果展示。
- **自然对话 Agent**：基于 LangGraph 的意图识别 → 工具调用 → 回答编排；未配置 LLM Key 时自动降级为确定性路由，三类典型问句可直接使用。
- **H5 演示界面**：定位或手动坐标输入、评分卡与因子明细、钓位列表、对话区；移动端可用。
- **Mock 模式**：无需任何外部 Key 即可启动与演示；真实数据源通过 Provider 隔离，配置 Key 后切换。

## 架构

```
H5（web/，由 FastAPI 同源托管）
        │  /api/fish-activity · /api/spots/recommend · /api/agent/chat
        ▼
FastAPI 服务端（backend/fishagent/）
  ├─ 坐标转换 wgs84_to_gcj02（唯一入口）
  ├─ 鱼情规则引擎 F1–F7
  ├─ 钓位召回 → 入口坐标 → 往返精算 → 禁钓过滤 → 排序
  ├─ LangGraph Agent（工具调用 + 无 Key 兜底）
  └─ Provider：Open-Meteo / 高德 / Mock
```

客户端不持有任何 Web 服务 Key；所有第三方调用经服务端中转。

## 快速开始（Mock 模式）

要求：Python 3.11+（本机验证使用 3.12）。

```bash
# 1. 安装（在仓库根目录执行）
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -e "backend[dev]"

# 2. 启动
cd backend
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn fishagent.main:app --host 127.0.0.1 --port 8000

# 3. 打开
# 浏览器访问 http://127.0.0.1:8000/
```

无需 `.env`：默认 `FISHAGENT_MOCK_MODE=true`，天气、POI 与 LLM 均使用确定性 Mock/兜底数据。

## 接入真实数据（可选）

复制 `.env.example` 为 `.env`（位于 `backend/` 或仓库根目录，按实现读取），填入：

| 变量 | 说明 |
|---|---|
| `FISHAGENT_MOCK_MODE=false` | 关闭 Mock |
| `AMAP_WEB_KEY` | 高德 Web 服务 Key（仅服务端） |
| `FISHAGENT_AMAP_CONCURRENCY` | 真实模式并发上限，默认 6 |
| `FISHAGENT_AMAP_QPS` | 真实模式请求起间隔上限，默认 2（按高德配额调整） |
| `OPEN_METEO_BASE_URL` | 默认 `https://api.open-meteo.com/v1` |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | OpenAI 兼容 LLM 配置；DeepSeek 示例：`https://api.deepseek.com/v1` + `deepseek-chat`；缺省走兜底路由 |
| `FISHAGENT_SPECIES_PROVIDER` | `mock` / `bing` / `none` / `disabled`；留空时 Mock 模式用 `mock`，真实模式用 `none`（不伪造社区数据）；`bing` 用 Bing 搜索结果匹配鱼种（Phase 1） |
| `FISHAGENT_SPECIES_TIMEOUT_SECONDS` | 鱼种查询超时，默认 4 秒；超时只降级该行展示 |
| `FISHAGENT_SPECIES_CACHE_TTL_SECONDS` | 鱼种结果缓存秒数，默认 3600 |

真实 Key 不随仓库分发；前端产物中不得出现任何 Key。

真实模式钓位只召回自然水体（高德 `types=190204|190205`），先按直线距离取最近候选、用批量距离接口按回程时长预筛，再对入围候选做去/回程分别精算；分片召回与路径规划均受 `FISHAGENT_AMAP_CONCURRENCY` / `FISHAGENT_AMAP_QPS` 约束。杭州 100km 实测约 22s。真实模式需服务端可访问 Open-Meteo、高德与 LLM 服务，客户端的网络请求只发往本服务。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查与 Mock 状态 |
| GET | `/api/fish-activity` | 鱼情评分、分档、因子明细、时段建议 |
| GET | `/api/spots/recommend` | 钓位推荐、往返车程、禁钓过滤、排序 |
| POST | `/api/spots/species` | 按钓位批量查询社区推荐鱼种（异步填充，不影响钓位主流程） |
| POST | `/api/agent/chat` | 自然语言对话（LangGraph Agent） |

完整字段与约束见 [`docs/api-contract.md`](docs/api-contract.md)。启动后可在 `/docs` 查看 OpenAPI。

### Mock 数据与触发方式（验收用）

- 五档场景：`GET /api/fish-activity?lat=30.2741&lon=120.1551&scenario=excellent|good|fair|poor|no_go`，仅 Mock 模式生效；`no_go` 必然返回劝退档。
- PRD 日期种子（未传 `scenario` 时按北京时间日期命中）：2026-04-12 极佳、04-13 良好、04-14 一般、04-15 偏差、06-20 劝退；可用 `at` 复现（如 `2026-04-11T21:30:00Z`）。
- 其他日期：按 `(lat, lon, date)` 的 SHA-256 种子在极佳/良好/一般/偏差中确定性选择，不产生 `no_go`。
- `at`：ISO 8601；带时区按其转换，不带时区按 `Asia/Shanghai` 解释；`generated_at` 恒为 UTC（`Z`）。
- POI Mock：围绕请求原点确定性生成 9 个候选：5 个往返 ≤2h（含 1 个单程 >1h、1 个缺入口坐标返回 `center_fallback`）、2 个往返 >2h、2 个禁钓（其中 1 个同时超时，只计入 forbidden）。单次 Provider 搜索半径恒 ≤50000m，`radius_km>50` 时使用 70km 网格分片并按 `id` 去重。
- 往返时长：去程/回程分别估算；`drive_minutes_one_way = round_half_up(drive_seconds_out / 60)`。
- Provider 注入：`fishagent.deps.get_weather_provider` / `get_geo_provider`，测试可用 `app.dependency_overrides` 替换为伪 Provider。

## 测试与质量

```bash
cd backend
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests -q
"C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe" -m ruff check .
```

测试覆盖：规则引擎边界（40/55/70/85）、坐标转换回归、radius 硬校验、往返过滤、入口坐标回退、禁钓排除、API 契约、Agent 三类兜底、推荐鱼种的 Mock/无结果/超时降级/缓存与合规文案。详见 [`docs/qa-plan.md`](docs/qa-plan.md) 与 `docs/qa-report.md`。

## 目录结构

```
backend/fishagent/        FastAPI 应用、规则引擎、Provider、Agent
backend/tests/            pytest 测试
web/                      H5 演示页（静态）
docs/                     交付计划、API 契约、PRD、测试与验收报告
fixtures/                 演示场景数据
Spec/                     产品使命、技术栈、路线图
项目立项文档.md            完整立项依据
```

## 范围与合规

- 当前交付为 **MVP**：Mock 模式可完整演示；真实高德/Open-Meteo/LLM 链路需配置 Key 后验证。
- 尚未包含：微信小程序端、生成式 AI 备案/登记、数据商用授权采购、UGC 社区、海钓/潮汐、权威禁钓矢量边界接入。参见 [`Spec/Roadmap.md`](Spec/Roadmap.md)。
- AI 生成结论必须展示「AI 生成 · 仅供参考」标识；不承诺渔获；不原样播报气象预报。
- 位置信息遵循最小必要、用完即弃；服务端日志需脱敏。

## 文档

- [项目交付计划](docs/project-plan.md)
- [API 与工程契约](docs/api-contract.md)
- [MVP PRD](docs/mvp-prd.md)
- [测试计划](docs/qa-plan.md)
- [测试报告](docs/qa-report.md)
- [验收报告](docs/acceptance-report.md)

## License

见 [LICENSE](LICENSE)。
