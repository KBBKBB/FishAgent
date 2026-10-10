# M1-T06 各接口独立配额实测 / M1-T08 气象数据源可用性

> 对应假设 **A3**（个人 Key 日配额 ≥3 万次）与 TechStack §4.1。
> 状态：T08 `[x]` 已验证；T06 `[ ]` 模板就绪（需真实 Key）。

---

## Part A — M1-T08 气象数据源可用性验证 `[x]`

### A.1 实测结论（本环境已跑通）

| 项 | 结果 |
|---|---|
| 数据源 | **Open-Meteo**（免 Key） |
| 预报接口 | `api.open-meteo.com/v1/forecast` ✅ 返回 200 |
| 实测返回 | **96 小时**逐时序列（past_days=2 + forecast_days=2），时区 `Asia/Shanghai` |
| 变量 | `pressure_msl, temperature_2m, relative_humidity_2m, precipitation, wind_speed_10m, wind_direction_10m, cloud_cover` |
| 日级变量 | `sunrise, sunset, temperature_2m_max, temperature_2m_min` |
| 历史接口 | `archive-api.open-meteo.com/v1/archive` ✅ 30 天 `pressure_msl` 返回 **744 个样本**（区间 1003.1~1026.6 hPa） |
| 取值约定 | 统一用 **`pressure_msl`**（海平面气压），天气查询用 **WGS84** 原始坐标 |

### A.2 因子取值设计（TechStack §4.1 强制）

- **F1**：24h 变化量 + 3h/6h 短时变化率；**优先使用未来 24h 预报变化量**（「即将骤降」决策价值更高）。
- **F2**：相对**当地近 30 天 `pressure_msl` 分布**做归一化（百分位），不用全国统一阈值；
  实测近 30 天分布跨度 ~23 hPa，证明固定阈值会造成季节性误判，**归一化必要**。

### A.3 授权提示

Open-Meteo 免费层为 **Non-Commercial（CC BY 4.0）**；商用需购买 Key（`customer-` 前缀域名）。
详见 `data-source-authorization.md`。备源：和风天气 / 心知天气（需确认商用授权）。

### A.4 复现

```bash
cd prototype && python3 - <<'PY'
from fishagent_m1.weather import fetch_forecast, fetch_archive_pressure
s = fetch_forecast(30.657, 104.066)
print(len(s.times), s.timezone, list(s.variables))
a = fetch_archive_pressure(30.657, 104.066, 30)
print(len(a), min(a), max(a))
PY
```

---

## Part B — M1-T06 各接口独立配额实测 `[ ]`

### B.1 为什么必须「按接口分别测」

高德 **POI 搜索与路径规划/距离测量通常分属不同配额池**，且个人认证 Key 与
企业认证 Key 额度差异大。只测总量会误判瓶颈。

### B.2 实测记录表（待填）

| 接口 | 端点 | 配额池 | 个人 Key 日配额 | 实测日期 | 结论 |
|---|---|---|---|---|---|
| 周边搜索 | `v3/place/around` | POI 搜索 | ⏳ | — | — |
| 关键字搜索 | `v3/place/text` | POI 搜索 | ⏳ | — | — |
| 多边形搜索 | `v3/place/polygon` | POI 搜索 | ⏳ | — | — |
| 距离测量 | `v3/distance` | 路径规划 | ⏳ | — | — |
| 驾车路径规划 | `v5/direction/driving` | 路径规划 | ⏳ | — | — |
| 坐标转换 | `v3/assistant/coordinate/convert` | 基础 | ⏳（本地算法可降为 0） | — | — |

### B.3 「配额 → 可支撑用户量」对照（模板）

以立项文档 4.5 的调用量模型（日活 1000、人均 3 次推荐）为基准：

| 接口 | 单用户日调用 | 日活 1,000 用量 | 日活 3,000 | 日活 10,000 | 免费额度 70% 上限 |
|---|---|---|---|---|---|
| POI 搜索（分片） | 3~9 | ~15,000 | ⏳ | ⏳ | ⏳ |
| 距离/路径精算 | 见下 | ~6,000（**待修正**） | ⏳ | ⏳ | ⏳ |

> ⚠️ **精算用量待修正**：`route-measurement.md` 发现去程不可批量，真实量级可能
> 放大至 ~50 倍。**T06 必须在此修正后重估**，否则「配额 → 用户量」对照失真。

### B.4 A3 判定

**A3：个人 Key 日配额 ≥ 3 万次。** 待实测；若不足则需提前企业认证（影响成本与工期）。
