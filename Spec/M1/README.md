# M1 调研深化 —— 执行与结论总览

> 本目录是 `Spec/Roadmap.md` **第二章「M1 调研深化」**的产出物落地。
> M1 的定位：**不写业务代码，只验证假设。产出是「能不能做」的答案，不是功能。**

| 项 | 内容 |
|---|---|
| 阶段 | M1 调研深化 |
| 上游依据 | 《项目立项文档.md》第四/六/九章；`Spec/Roadmap.md` §2；`Spec/TechStack.md` §4/§5 |
| 可行原型 | `prototype/`（坐标转换 + POI 双路召回 + 车程精算 + 鱼情规则，已跑通） |
| 决策门 | **G1**（M1 末，见 `verification-report.md`） |

---

## 一、任务状态总览

图例：`[x]` 完成（本地可验证部分） / `[~]` 进行中（需真实 Key/资质） / `[!]` 阻塞 / `[ ]` 未开始

| 编号 | 任务 | 状态 | 结论/产出 |
|---|---|---|---|
| M1-T01 | 水域 POI 双路召回实测 | `[~]` | 方法+原型就绪；召回率需真实 Key → `poi-recall.md` |
| M1-T02 | 周边搜索半径分片方案实测 | `[x]` | 选型：网格分片；调用量对照表 → `sharding-selection.md` |
| M1-T03 | `entr_location` 端点可用性验证 | `[~]` | 解析/回退逻辑就绪；缺失率需真实 Key → `route-measurement.md` |
| M1-T04 | 距离测量接口开放性 + 实时路况 | `[~]` | **发现参数结构问题**（见下）→ `route-measurement.md` |
| M1-T05 | 坐标系转换验证 | `[x]` | 本地算法往返误差 <1mm，偏移 360~620m → `coordinate-conversion.md` |
| M1-T06 | 各接口独立配额实测 | `[ ]` | 实测模板 → `weather-and-quota.md` §B |
| M1-T07 | 城区有效水域存量实测 | `[ ]` | 方法（三档城市×5 点取中位数）→ `poi-recall.md` §4 |
| M1-T08 | 气象数据源可用性验证 | `[x]` | Open-Meteo 实测通过 → `weather-and-quota.md` §A |
| M1-T09 | 小程序定位权限可行性 | `[ ]` | 合规待办（🔴 可阻塞项目）→ `compliance-checklist.md` |
| M1-T10 | 生成式 AI 备案路径咨询 | `[ ]` | 合规待办（🔴 工期长）→ `compliance-checklist.md` |
| M1-T11 | 高德条款 POI 缓存/持久化限制 | `[ ]` | 法务待办（🔴 护城河地基）→ `compliance-checklist.md` |
| M1-T12 | 《数据源授权清单 v1》 | `[~]` | 初版已建 → `data-source-authorization.md` |
| M1-T13 | 气象信息传播合规确认 | `[ ]` | 法务待办 → `compliance-checklist.md` |
| M1-C01~C04 | 竞品调研（G1 必答） | `[ ]` | 分析框架 + 尖锐问题 → `competitor-research.md` |

> **说明**：本仓库运行环境无高德 Key，故凡涉及高德真实接口的实测（T01/T03/T04/T06/T07）
> 均已完成**代码与流程就绪**，实测数值留待配置 `AMAP_KEY` 后填入。凡不依赖外部 Key 的
> 环节（T02/T05/T08）已给出**真实结论**。

---

## 二、本阶段三个关键发现（影响后续设计）

### 发现 1：`v3/distance` 的「2 次请求覆盖 100 候选」在参数结构上不成立

立项文档 2.2 设想「去程与回程各一次请求即可覆盖 100 个候选」。但该接口实际为
**「1 个终点 × ≤100 个起点」**：回程（钓位→用户，以用户为唯一终点）可一次批量，
**去程（用户→钓位）终点必须逐个给出**，无法在同一次请求内覆盖多个候选。
→ 真实调用量应为 `1 + N` 或改用 `v5/direction/driving` 并发。详见 `route-measurement.md`。
（这正是 M1 的价值：把立项阶段的乐观估算提前证伪，避免 M2 成本失控。）

### 发现 2：半径超限静默降级已可在代码层硬拦截

`v3/place/around` 的 `radius>50000` 不报错、静默按 3000m 处理。原型已在
`poi.validate_radius()` 硬拦截（R2），并有单测覆盖；分片覆盖 150km 需约 25~45 片
（取决于间距系数）。详见 `sharding-selection.md`。

### 发现 3：核心差异化主张已被竞品覆盖 → 卖点优先级已调整

竞品实证显示「气压 + 鱼情预测」已被垂类 App 高使用率实现（详见 `competitor-research.md`）。
**已按 G1 建议落地卖点重排**：`Spec/Mission.md` v1.1 §四（核心差异点 = 往返 2h 车程可达性 + 敢劝退；
气压鱼情降为基线功能），并同步 `Spec/TechStack.md` v1.1 §1.1 资源优先级。

---

## 三、产出物清单对照（Roadmap §2.4）

| Roadmap 产出物 | 本目录文件 | 状态 |
|---|---|---|
| 可行原型 demo | `../prototype/` | ✅ 已跑通（mock 与真实链路代码） |
| 调研结论报告（A1–A4、A7） | `verification-report.md` | ⏳ 待真实 Key/资质填数 |
| 竞品分析报告 | `competitor-research.md` | ⏳ 框架就绪，待人工下载复核 |
| 分片方案选型结论 | `sharding-selection.md` | ✅ |
| 配额实测对照表 | `weather-and-quota.md` §B | ⏳ 模板就绪 |
| 《数据源授权清单 v1》 | `data-source-authorization.md` | ⏳ 初版 |
| 法务书面结论 | `compliance-checklist.md` | ⏳ 待办清单 |

---

## 四、下一步（进入 G1 前必须补齐）

1. 申请/提供高德个人 Key，跑 `prototype/demo.py`（真实模式），填 T01/T03/T04/T06/T07 数值。
2. 由法务/运营推进 T09–T13 与竞品调研 C01–C04。
3. 汇总至 `verification-report.md`，据 A1–A4 结果做 **G1 Go / No-Go** 判定。
