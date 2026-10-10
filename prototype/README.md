# M1 可行原型（prototype）

> 对应 `Spec/Roadmap.md` 产出物：**「可行原型 demo（POI 召回 + 车程精算 + 坐标转换可跑通）」**
> 与 M1 技术验证任务 **M1-T01 / T02 / T03 / T04 / T05 / T08**。

⚠️ **本原型只用于「验证假设」，不是业务代码。** 按 M1 定义，本阶段不写业务功能，
只把高风险技术点（坐标系、半径上限、批量口径、端点坐标）先跑通并暴露问题。

## 快速开始

```bash
# 离线演示：零依赖、无需任何 Key（使用合成 POI fixtures）
python3 demo.py --mock

# 真实链路：需服务端环境变量 AMAP_KEY（严禁下发客户端，见 R3）
AMAP_KEY=xxxx python3 demo.py --lat 30.657 --lng 104.066

# 单元测试
python3 -m pytest -q
```

## 目录结构

```
prototype/
├── demo.py                  # 端到端演示：坐标转换→分片→双路召回→车程精算→鱼情规则
├── fishagent_m1/
│   ├── coord.py             # WGS84↔GCJ-02 唯一转换入口（R1）
│   ├── config.py            # 密钥仅从环境变量读取（R3）；radius/批量/往返阈值常量
│   ├── http.py              # 标准库 HTTP（原型零依赖）
│   ├── amap.py              # 高德客户端：服务端中转 + sig 签名（R3）
│   ├── poi.py               # 双路召回 + radius 硬校验（R2）+ entr_location 回退（R4）
│   ├── sharding.py          # 网格/同心环分片，突破 radius 50km 上限（M1-T02）
│   ├── route.py             # 车程精算：1终点×≤100起点、去/回程分别计算（R4）
│   ├── weather.py           # Open-Meteo 接入，pressure_msl + 近30天分布（M1-T08）
│   ├── factors.py           # 鱼情规则引擎 F1–F7（立项文档 §2.4）
│   └── mock.py              # 离线合成高德客户端（仅演示/测试，不可作实测结论）
├── fixtures/water_pois.json # 合成水域 POI（含 entr_location 缺失样本）
└── tests/                   # pytest：坐标回归 / radius 硬校验 / 分片覆盖 / 往返口径 / 规则引擎
```

## 已验证的实现红线

| 红线 | 落地位置 | 说明 |
|---|---|---|
| **R1** 坐标系统一 | `coord.py` | `wgs84_to_gcj02()` 唯一入口，往返误差 <1mm；境内偏移 360~620m 实测 |
| **R2** 半径硬校验 | `poi.validate_radius()` | >50000 直接抛错，禁止静默降级进入请求 |
| **R3** 密钥不下发 | `amap.py` / `config.py` | Key 仅从环境变量读取，支持 `sig` 数字签名 |
| **R4** 车程口径 | `route.py` / `poi.nav_point` | 终点优先 `entr_location`；去/回程分别计算后求和 ≤7200s |
| **R5** 禁钓过滤 | 见 `Spec/M1/compliance-checklist.md` | 原型阶段先定义边界数据接口，M2 落地 |

## 关键实测发现（详见 Spec/M1/）

1. **`v3/distance` 的「2 次请求覆盖 100 候选」不成立**：该接口为「1 个终点 × ≤100 个起点」，
   回程（钓位→用户）可批量，去程（用户→钓位）终点必须逐个给出，故需 1 + N 次调用或改 v5。
   → 见 `Spec/M1/route-measurement.md`
2. **半径超限静默降级**：真实高德 `radius>50000` 不报错、静默按 3000m 处理，已在代码层硬拦截。
   → 见 `Spec/M1/sharding-selection.md`
