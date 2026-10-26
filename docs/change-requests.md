# FishAgent 变更需求记录

> 维护：小项 ｜ 建立：2026-10-23 ｜ 状态：CR-01 已完成（QA v1.5 PASS）；CR-02 已完成（QA v1.6 PASS + 人类真机确认）；CR-03 PWA：M1/M1b/M2 本地完成，M3 工程侧 A/B/C 完成（P0/P1/P2=0/0/0）；人类决定**先做内网 + PWA 安装试点**，公网 B（Cloudflare Tunnel + 共用邀请码）暂缓；内网 8020 HTTPS 已运行，服务端 + 桌面 Chrome 独立检查 **18 PASS / 0 FAIL**；iPhone 14（iOS 27.0.1）本地 CA 已安装并验证 `/health`，真机安装/standalone/离线/定位/高德待人类回传；Android 与公网 22 项 NOT-RUN
> 原则：只记录人类确认的需求、范围与验收；不代替产品/技术负责人做实现决策。

| ID | 日期 | 提出人 | 需求 | 负责人 | 状态 |
|---|---|---|---|---|---|
| CR-01 | 2026-10-23 | 人类 | “附近钓位”增加刷新按钮，用于查看其他钓位 | 小钱（后端）、小厚（H5） | **已完成（QA v1.5 PASS）** |
| CR-02 | 2026-10-23 | 人类 | 手机端点击“打开高德导航”直接调起高德 App，不再跳转高德网站 | 小厚（H5）、小测（复验） | **已完成（QA v1.6 + 真机确认）** |
| CR-03 | 2026-10-24 | 人类 | 将移动端网站封装为 APP | 小厚（PWA）、小钱（部署/安全）、小测（QA） | **M1/M1b/M2 本地完成；M3 工程侧完成；内网 PWA 试点进行中（8020 HTTPS 已运行，服务端+桌面 18 PASS/0 FAIL；iPhone 真机验收待人类回传，Android 未提供）；公网 B 暂缓** |
| CR-04 | 2026-10-25 | 人类 | Step 3 每个推荐钓位下新增“推荐鱼种”，来源小红书网友分享；搜不到时提示无推荐 | 小钱（后端）、小厚（H5）、小测（QA） | **第二轮修复完成（降级语义/前端超时/缓存键），待独立 QA 复验** |

## CR-01 附近钓位“换一批”

**背景**：当前 50km 一般评估 10 个候选、返回 Top5，另有 5 个符合条件但被 `limit` 截断，用户无法查看。

**方案（2026-10-23 真实复验后调整）**：首屏一次预取 `limit=10`，H5 展示前 5 个，“换一批”在本地切换到后 5 个。相比 offset 分页：

- 刷新即时，不再等待 10–15s，也不再重复调用高德；
- 同一次响应内无重复，不受跨请求排序变化影响；
- 50km 合格候选约 10 个，正好 2 批；不足 5 个时只有 1 批。

**行为**

- 首屏请求 `limit=10`，只展示 5 个；切换后展示剩余候选。
- “换一批”不再发请求；到末页后再点回到第 1 批并提示“已展示全部推荐，已回到第 1 批”。
- 切换位置或搜索半径时重置到第 1 批。
- 首屏加载中按钮禁用；换批不涉及网络，不做失败提示。
- 保留禁钓提示与“以当地公告为准”，不得弱化。

**接口与数据**

- `GET /api/spots/recommend` 的 `limit` 支持到 10；批次大小调整为 `max(limit, 10)`，使 `limit=10` 仍只评估约 10 个候选，维持首屏耗时。
- `offset` 参数保留为直连 API 的分页能力（本次 H5 不使用）。
- **P1 修复**：商业 POI 过滤补充后缀/关键词（如“经营部”）；真实复验第 2 批出现“水泥河沙经营部”，属非水体商业点。

**验收**

1. `limit=10` 返回最多 10 条；首屏前 5 条与旧版 Top5 一致。
2. 换批为本地切片：无额外网络请求、同一响应内无重复 id。
3. “水泥河沙经营部”被过滤；合法水体（锦江、府河、西郊河、磨底河、摸底河、清水河、东湖、小沙河、肖家河）不受影响。
4. 后端全量 pytest、ruff 通过；H5 375/1280 无横向溢出、console 0；Mock 与真实模式均可换批。
5. 小测独立复验并记录证据；通过后更新本表状态。

## CR-02 手机端“打开高德导航”直接调起高德 App

**背景**：当前钓位卡按钮使用后端 `navigation_url`（`https://uri.amap.com/marker...`），手机点击先打开高德网页，不符合“直接打开高德软件”的预期。

**范围（仅 H5）**

- 移动端（iOS/Android）主链接改为高德 App URI scheme：
  - iOS：`iosamap://path?sourceApplication=FishAgent&dlat=<lat>&dlon=<lon>&dname=<name>&dev=0&t=0`
  - Android：`amapuri://route/plan/?sourceApplication=FishAgent&dlat=<lat>&dlon=<lon>&dname=<name>&dev=0&t=0`
  - 坐标取 `spot.entry_location_gcj02`（缺失时用 `location_gcj02`），保留 6 位小数；`dname` 用 `encodeURIComponent`。
- 桌面端保持现有 `navigation_url` 网页导航，新标签打开。
- 移动端提供可见回退“未安装高德？使用网页版”，指向现有安全 https 链接；不得只依赖 App 调起成功。
- 不修改后端/API 契约；不改按钮文案、禁钓提示与免责文案；不引入第三方库。

**验收**

1. iPhone/Android UA：主链接以 `iosamap://` / `amapuri://` 开头，含 `dlat/dlon/dname/dev=0&t=0`，坐标与入口坐标一致，名称正确编码。
2. 桌面 UA：主链接仍为 `https://uri.amap.com/...`，新标签打开。
3. 移动端可见回退链接，https 安全；即使 App 未安装也可继续使用网页版高德。
4. 375/1280 无横向溢出、console 0；CR-01 换批、切半径重置、合规文案不回归。
5. 小测独立复验；**真机调起需人类或持机人确认**（自动化只能验证链接构造与回退，不能证明 App 实际被拉起）。

**待确认/风险**

- 自定义 scheme 在部分微信/内置浏览器可能被拦截；回退链接必须可见。
- iOS 未安装高德时可能弹“无法打开页面”，回退链接可继续。
- 只改 H5 静态文件，无需重启 8018。

## CR-01 进度

| 日期 | 项 | 结果 |
|---|---|---|
| 2026-10-23 | 后端 offset 版（小钱） | `offset`、评估目标 `offset+limit`、11 条测试；137 passed、ruff clean |
| 2026-10-23 | 小项复核 | 独立复跑 137 passed、ruff clean；契约与共享文档一致 |
| 2026-10-23 | H5 offset 版（小厚） | 按钮、慢提示、失败保留、Mock 与回卷；38 PASS / 0 FAIL / 1 PENDING |
| 2026-10-23 | 小项真实复验 | 重启后 offset=0/5 均 200，12.87s / 12.77s；第 2 批出现“水泥河沙经营部”（P1）；另一次运行出现 1 个重复（磨底河），确认跨请求排序不稳定 |
| 2026-10-23 | P1 修复（小钱） | 商业 POI 关键词 +15；批次 `max(limit,10)`；154 passed、ruff clean；未重启 |
| 2026-10-23 | 小项复验（重启后） | `limit=10` 返回 **10/10 全自然水体**（锦江、府河、西郊河、磨底河、摸底河、浣花溪、清水河、东湖、小沙河、肖家河），12.92s，evaluated=10，无商业命中；往返最长 6458s；P1 工程关闭 |
| 2026-10-23 | H5 本地换批（小厚） | `limit=10` 预取、只渲染 5 个、本地切片、回卷提示、切半径重置；Mock/真实 41 PASS / 0 FAIL |
| 2026-10-23 | 小项独立真实复验 | 首屏 5 个、换批 0.36s、全程仅 1 次钓位请求、两批条目不同、回卷正常、375/1280 无溢出、console 0；50km 接口 15.222s。同名“锦江”为锦江区/成华区两个不同 POI（O-02），非重复 |
| 2026-10-23 | **小测独立 QA（v1.5）** | 154 passed、ruff clean；真实 `limit=10` 200/12.855s、10/10 自然水体、id 唯一、无商业名；`offset=5` 200/13.104s；H5 **49/49**（真实/Mock、回卷、重置、375/1280、console 0）；P0/P1/P2=0/0/0；O-02 经 id/行政区/距离核验为不同 POI；**可签收** |
| 2026-10-23 | **CR-01 关闭** | 实现、P1 修复、项目侧复验、独立 QA 均完成；H5 已生效（静态文件），无需重启；S1 整体准入不变 |

证据：`docs/evidence/real-mode/cr01-real-paging.json`、`cr01-pool-check.json`、`cr01-h5-check.log`、`cr01-independent-verify-2026-10-23.log`、`cr01-verify-375.png`、`web-cr01-*.png`；QA v1.5 `docs/qa-report.md` §13（SHA-256 `ac9bed9e041aebbbc7c224c34b20527772ed24c1d5c7bf48ca0ecefc57696825`，仓库/共享/归档一致）；QA 证据 `qa-outputs/FishAgent/20261023-1746/evidence/cr01/`。

## CR-02 进度

| 日期 | 项 | 结果 |
|---|---|---|
| 2026-10-23 | 登记与核对（小项） | 后端 `navigation_url` 为 `https://uri.amap.com/marker...`；`SpotOut` 已含 `entry_location_gcj02`；无需后端改动，确定 H5 移动端 scheme + 网页回退方案 |
| 2026-10-23 | H5 实现（小厚） | 移动端 iOS/Android scheme、iPadOS 桌面 UA 识别、入口坐标/中心坐标回退、移动端“未安装高德？使用网页版”；71 PASS / 0 FAIL |
| 2026-10-23 | 项目侧复验（小项） | UA 矩阵 + 真实 iPhone：45 PASS / 0 FAIL；scheme/参数/坐标/名称、回退、桌面 https、CR-01 不回归、375/1280、console 0 |
| 2026-10-23 | **小测独立 QA（v1.6）** | 代码审阅 `amapAppUrl`/`renderSpot`/`safeHttpUrl`；Mock UA 矩阵 34/34 + 真实 8018 iPhone 24/24 = **58/58**；P0/P1/P2=0/0/0；O-CR02-01（移动端网页回退仍带 `callnative=1`，观察项）；**工程侧链接构造/回退可签收，真机不计 PASS** |
| 2026-10-23 20:10 | **人类真机确认** | 人类回复“确认手机端可以直接打开高德地图”（消息 `cmsg_01m5maqf5vdckb2fh45c37dkb7`）；主路径满足需求 |
| 2026-10-23 | **CR-02 关闭** | 实现、项目侧复验、独立 QA、真机确认均完成；H5 已生效（静态文件），无需重启；O-CR02-01 保留观察，暂不改动，如后续反馈回退问题再处理 |

证据：`docs/evidence/real-mode/cr02-h5-check.log`、`cr02-independent-verify-2026-10-23.log`、`cr02-iphone-375.png`、`cr02-android-375.png`、`cr02-ipados-768.png`、`cr02-desktop-1280.png`、`cr02-real-iphone-375.png`、`cr02-verify-iphone-375.png`、`cr02-verify-desktop-1280.png`；人类真机确认：群消息 `cmsg_01m5maqf5vdckb2fh45c37dkb7`（2026-10-23 20:10）；QA v1.6 `docs/qa-report.md` §14（SHA-256 `6d1cbb76223cfc428804d58861a825e0f0ddbef1d9bdc8d3a7b98efef100bb9a`，仓库/共享/归档一致）；QA 归档 `qa-outputs/FishAgent/20261023-1927/reports/qa-report-v1.6.md`。

## CR-03 移动端 H5 以 PWA 形式提供（已确认方案，待托管授权）

**人类确认（2026-10-24）**：① iOS 与 Android 都做；② 外出也可用；③ 采用 PWA；④ 无 Apple 开发者账号，不需要 App Store/TestFlight。

**范围**

- PWA 基础：`manifest.webmanifest`、图标（180/192/512）、Service Worker、`display: standalone`、主题色与启动图。
- 安装体验：Android Chrome 安装提示；iOS Safari“分享 → 添加到主屏幕”引导；安装后图标与启动页正常。
- 公网访问：HTTPS 域名 + 反向代理，手机/桌面同源访问。
- 访问控制：试点邀请码/令牌；每 IP/令牌限流与每日配额；CORS 白名单；密钥仅留服务器环境变量。
- 定位：HTTPS 下启用浏览器定位；拒绝时保留天府广场/手动坐标回退。
- 兼容：CR-01 换批、CR-02 高德 App 调起与网页回退不回归；AI 标识、禁钓提示、免责声明保留。
- 非范围：原生 App / App Store / TestFlight；离线鱼情计算；多用户账号体系（试点先用邀请码）。

**里程碑与负责人**

| 阶段 | 内容 | 负责人 | 依赖 | 验收 |
|---|---|---|---|---|
| M1 PWA 壳 | manifest/图标/SW/安装引导/standalone 适配 | 小厚 | 无 | 本地 HTTPS 或 localhost 可安装；375/1280 无溢出；console 0 |
| M2 公网与安全 | 域名/HTTPS/VPS 或隧道、邀请码、限流/配额、日志 | 小钱 | 人类确认托管方式与授权 | 未授权访问被拒；限额生效；无密钥泄露 |
| M3 真机 QA | iOS/Android 安装、定位、高德调起、更新、回归 | 小测 | M1+M2 | 双端通过；P0/P1/P2 记录 |
| M4 切换与文档 | 试点地址、安装说明、回滚、台账 | 小项 | M3 | 文档与共享目录更新 |

**人类决策（2026-10-24）**

| 决策 | 结果 | 状态 |
|---|---|---|
| 托管方式 | **B. Cloudflare Tunnel 到家庭主机** | 已选定；**当前暂缓**，改为先做内网 + PWA 安装试点（2026-10-24） |
| 实施顺序 | **先内网 + PWA 安装，公网 B 暂缓** | 已选定；内网用 mkcert 本地 CA + 独立 8020 HTTPS，不建隧道、不暴露公网 |
| 访问控制 | **共用邀请码（3–5 人）** | 已选定；邀请码值待人类确定后私下交付 |
| canonical 域名 | **默认裸域（apex）**，`www` 301 → 裸域；若人类偏好 `www` 可对调 | 技术默认；Cookie 为 host-only，必须单一入口 |
| 性能阈值 | 主机恢复后 ≤60 秒可用；App 壳冷启动首屏 ≤5 秒；数据耗时另按 S1 P95 | 技术默认；D 组执行时记录实测 |
| 域名/Cloudflare 账号 | 未说明由谁提供 | **待确认**：人类提供或授权技术侧协助 |
| 发布授权/时间窗 | 未明确 | **待确认**：未授权前不建隧道、不改 DNS、不发布 |
| Key | 建议试点独立 Key | **待确认**；不得复用 S1 Key 的风险需人类接受 |
| 运维责任人 | 未定 | **待确认**；家庭主机断电/断网/重启需有人恢复 |

**风险（B 方案）**

- 公网暴露会放大高德/DeepSeek 配额与费用风险 → 邀请码 + 限流 + 配额已就绪，超限即停。
- 家庭宽带对外提供服务可能受运营商条款限制；Cloudflare 在中国大陆的访问速度/稳定性有限 → 先小范围试点，保留切回内网或转 A 的选项。
- 家庭主机断电、休眠、断网、IP 变化都会中断服务；Cloudflare Tunnel 可规避公网 IP/端口映射，但不能规避主机离线 → 需明确常开与恢复责任人。
- 隧道令牌等同主机入口凭证 → 只存主机环境/服务配置，不进群、不进 Git、不写文档；Cloudflare 账号需开启 2FA。
- iOS PWA 限制（无推送、存储可能被清理）→ 试点可接受。
- 高德 scheme 在 standalone 模式下可能被拦截 → 真机验证并保留网页回退。

**估算**：M1 1–2 人日；M2 1–3 人日（不含采购/备案等待）；M3 1–2 人日；M4 0.5 人日。合计约 4–7 人日，自托管资源就绪起算。

**当前状态**：M1 完成（小厚，77 PASS）；M1b 完成（小厚，37 PASS，SW v2）；M2 本地完成（小钱，180 passed、ruff clean，8018 未启用开关）；M3 工程侧完成（小测 v1.8：A 47/47、B 修复后 PASS、C 26/26、P2 复测 11/11，P0/P1/P2=0/0/0）。人类已选 **B（Cloudflare Tunnel）+ 共用邀请码**，并追加决定 **先做内网 + PWA 安装试点**（公网 B 暂缓）。内网方案：mkcert 本地 CA + IP SAN，独立 **8020** 实例 HTTPS，访问控制关闭、Mock 模式，**不动 8018/S1**；8020 已由小钱按批准启动并保持运行（PID 75304），runbook 定稿 406 行。小厚只读审计：`web/**` 0 阻塞差异、不改。小测内网独立检查已完成服务端 + 桌面 Chrome 部分：**18 PASS / 0 FAIL / 2 NOT-RUN（预期）/ 2 INFO**，HTTPS 安全上下文、SW v2、缓存、离线诚实性、证书/MIME、访问日志均符合；证据 11 件哈希全部校验通过。iPhone 14（iOS 27.0.1）本地 CA 已由人类安装并验证 `https://192.168.31.68:8020/health`；**iPhone 真机安装/standalone/离线/定位/高德 23 项仍 PENDING，Android 全部 NOT-RUN，公网 22 项 NOT-RUN**。公网 B 的 D2（域名/Cloudflare 账号/主机）、D5（Key）、D6（发布窗口/运维人）与发布授权仍待确认。CR-03 整体不判 GO。S1 仍按现 H5 运行，不受影响。

**进度**

| 日期 | 项 | 结果 |
|---|---|---|
| 2026-10-24 | 人类确认 | 双端都做、外出可用、采用 PWA、无 Apple 账号（PWA 不需要） |
| 2026-10-24 | M1 PWA 壳（小厚） | manifest、5 个图标、SW、安装引导、离线横幅；77 PASS / 0 FAIL；CR-01 41、CR-02 71 回归通过；仅 `web/**`，未重启 8018 |
| 2026-10-24 | 小项复核（M1） | manifest 字段完整、5 图标尺寸正确、MIME `application/manifest+json`；SW/index 引用正常；8018 已提供新静态文件；日志 77 PASS、0 FAIL |
| 2026-10-24 | M2 本地实现（小钱） | 推荐方案 A（云服务器+域名）；邀请码换签名 Cookie、401/过期、CORS 白名单、IP/令牌限流、上游日配额（高德 2000/Open-Meteo 1000/LLM 200）、CSP 登录页；全部由 `FISHAGENT_PUBLIC_ACCESS_ENABLED` 控制，默认关闭；179 passed、ruff clean；8021 冒烟后停止；未动 8018、未发布、未迁移 Key |
| 2026-10-24 | 小项复核（M2） | 独立复跑 179 passed、ruff clean；8018 仍为 PID 70828、`/pilot/login` 404（开关未启用）、`/` 200；方案文档 md5 `add1894a0a9b1672a0b69e7ef65f39f9` 仓库/共享一致 |
| 2026-10-24 | M1b H5 鉴权与限流（小厚） | 401（`UNAUTHORIZED`/`INVALID_TOKEN`/`TOKEN_EXPIRED`）跳转 `/pilot/login?next=...` 且防重入；429 按 `Retry-After` 提示、不自动重试；SW `CACHE_VERSION` 升至 `fishagent-v2`；37 PASS / 0 FAIL；CR-03 77、CR-01 41、CR-02 71 回归无失败；仅 `web/**`，未重启 8018 |
| 2026-10-24 | 小项复核（M1b） | `web/app.js` 含 `AUTH_ERROR_CODES`/`redirectToLogin`/`parseRetryAfter`；SW 版本 v2；4 份 H5 日志均为 0 FAIL |
| 2026-10-24 | M3 阶段一 QA（小测 v1.7） | A 组 M1 PWA 47/47 PASS；B 组 M2 本地安全 42/45，P2×2：O-CR03-01（错误邀请码 401 缺 `Cache-Control: no-store`、`WWW-Authenticate`）、O-CR03-02（uvicorn 访问日志记录客户端 IP）；C 组（M1b）待分派、D 组真机/HTTPS 41 项待托管；P0/P1/P2 = 0/0/2；报告 SHA-256 `277c73e0575ec09a92b178d6aff8c323c36db1a3470201c205660d87ad55fe6a`（仓库/共享/归档一致） |
| 2026-10-24 | QA 执行偏差（小测，已披露） | B 组开始前误调用 2 次真实上游（`GET /api/fish-activity` 200、`GET /api/spots/recommend` 超时），可能产生少量高德/LLM 配额消耗；已立即停止，未读取/回显 Key，8018 未改动；已在 QA 报告 §15.9 记录 |
| 2026-10-24 | P2 修复（小钱） | O-CR03-01：`AUTH_CHALLENGE` + `error_headers()` 统一四类 401 的 `no-store`/`WWW-Authenticate`，补单测；O-CR03-02：部署方案定稿 `uvicorn ... --no-access-log`，新增 §3.1 访问日志策略并同步监控/上线章节；180 passed、ruff clean；独立端口实测四类 401 头一致、访问日志 0 行；8018 未重启、未启用、未调用数据接口 |
| 2026-10-24 | 小项复核（P2） | `errors.py`/`middleware.py` 实现一致，四类 401 路径全覆盖；测试含四项断言；独立复跑 180 passed、ruff clean；部署方案 md5 `1b0167dbe8fdb58f4b50f1851bd30b54` 仓库/共享一致；未动 8018 |
| 2026-10-24 | M3 阶段二 QA（小测 v1.8） | C 组 M1b 集成 **26/26 PASS**（三类 401 跳转保留 `next`、`/pilot/` 无循环、非契约 401 不误跳、429 两类文案含 `Retry-After` 且 2.1s 内 0 次重试、CR-01/CR-02 回归）；P2 复测 **11/11 PASS**（四类 401 头、`--no-access-log` 0 访问行）；O-CR03-01/02 关闭；P0/P1/P2=0/0/0；报告 SHA-256 `c9a0c7bdbcfcbb404e831605548adebaf98ebfb3162c7bffbe8e4f0326d631e6`（仓库/共享/归档一致） |
| 2026-10-24 | 小项复核（M3 阶段二） | 三处报告哈希一致；§15.7/§15.13 与交付声明一致；证据含阶段二 4 张截图与实例日志；8018 仍 PID 70828、未重启、未开访问控制；临时实例已停止 |
| 2026-10-24 | 人类决策（托管） | 选择 **B. Cloudflare Tunnel 到家庭主机**；访问控制采用 **共用邀请码**；域名/账号/主机与发布授权仍待确认 |
| 进行中 | B 部署准备（小钱） | 更新 `cr03-deployment-plan.md`：B 方案 runbook、cloudflared 配置、家庭主机常开/恢复、令牌保密、Cloudflare 账号安全、回滚到内网；不建隧道、不改 DNS、不发布 |
| 2026-10-24 | D 组清单 B 适配（小测） | 41 项 → 60 项（新增 RD-42..RD-60：canonical/Cookie host-only、Cloudflare 缓存与 Rocket Loader/WAF、代理 IP `CF-Connecting-IP`、主机异常/冷启动）；v2.1 定稿写入 canonical=apex、`www` 301、恢复 ≤60s、壳首屏 ≤5s、RD-55 为 P1 判定门；SHA-256 `42094ce6e4c437c1c97d6eb3314e5c785f0fee07775feefef0cad4efd08d3b8f`（仓库/归档一致）；未执行、不计 PASS，待资源/授权 |
| 2026-10-24 | B 部署文档定稿（小钱） | `cr03-deployment-plan.md` 改为 B 为主（423 行）：canonical/`www` 301、`TRUST_PROXY_HEADERS` + `--forwarded-allow-ips 127.0.0.1`、Cloudflare Bypass/关闭 Rocket Loader/Bot Fight、100s/524 超时上限、NSSM 托管、10 项资源清单、回滚条件；MD5 `8d6006c3508e48a5a997183a51aaad26`，SHA-256 `2d255f2743ea1a3613cd91bfd98ec6c5623a22a4402229020f809fd79884e79b`（仓库/共享一致）；本地验证 180 passed、ruff clean；未建隧道/改 DNS/安装/发布 |
| 2026-10-24 | 人类决策（实施顺序） | 回复“可先做内网+PWA安装试点”：公网 B 暂缓，先做内网安装验收；已说明 HTTP 非安全上下文、需本地可信 HTTPS |
| 2026-10-24 | 内网 PWA 静态条件审计（小厚，只读） | `cr03-internal-pwa-diff.md`：manifest/SW/iOS meta/图标 **0 阻塞差异**，建议不改共用 `web/**`；列出 3 项运行条件（完全信任本地 CA、IP SAN 精确匹配且 IP 固定、8020 根路径 + LAN TLS 且 `TRUST_PROXY_HEADERS=false`）；SHA-256 `f42f8aa9e6bff07d29593adb5db83f9808c5bf9ced34ba964e4d84baa4a4da57`（仓库/共享一致）；未改文件、未碰 8018 |
| 2026-10-24 | 内网 QA 子集（小测） | `cr03-internal-pilot-subset.md`：60 项裁剪为 **31 全量 + 5 部分（整项不判 PASS）+ 2 条件 + 22 必须公网**；给出前置门禁、执行顺序（安装组优先）、取证要求与 `ENV-LIMIT` 判定规则；SHA-256 `9a9bbb289b85f476ac82f5d192c8f974acd578a59766fab2deff174642beb380`（仓库/共享一致）；未执行、不计 PASS |
| 2026-10-24 | 内网 HTTPS runbook（小钱） | 已定稿并本机自测可行（见下）；只准备与自测，不装到手机、不建隧道 |
| 2026-10-24 | B 文档交叉核对（小测） | 三处全部 PASS、0 阻塞差异：启动参数/回环监听/`TRUST_PROXY_HEADERS` 与 RD-55 三项一致；100s/524、chat <90s、恢复 ≤60s 与 RD-53..59 一致；Bypass 与 WAF/Rocket Loader 规则与 RD-46/47 一致；非阻塞：§8 L333 版本标注仍为 v2，实际为 v2.1，待下次修订 |
| 待办 | 小钱（P3，下次文档修订） | `cr03-deployment-plan.md` §8 L333 “60 项清单（v2）”改为 v2.1，并更新哈希；不单独唤醒 |
| 2026-10-24 | 内网 HTTPS 执行（小钱，人类已批准） | 证书已签发到 `D:\FishAgent\certs`（SAN `DNS:localhost, IP:192.168.31.68, IP:127.0.0.1`，有效期至 2029-01-24，叶证书指纹 `1A:B6:D5:DC…73:14`，ACL 收紧）；**8020 HTTPS 已启动并保持运行**（`0.0.0.0:8020`，PID 75304，Mock、`PUBLIC_ACCESS_ENABLED=false`、`TRUST_PROXY_HEADERS=false`、`--workers 1 --no-access-log`，未注册服务）；自测全通过（双地址 200、证书链 ok、MIME、SW `activated` + `fishagent-v2-static`、离线壳无假数据、访问日志 0 行、8018 仍 PID 70828）；runbook 更新至 406 行（执行记录 + 补做项 + 风险），MD5 `a96859ac…d93d`、SHA-256 `9a49278f…cac9`，仓库/共享一致 |
| 2026-10-24 | 内网前置条件（原待办，部分已解除） | ① `mkcert -install` 未完成（交互式确认被阻塞，仅影响桌面浏览器信任）；② 防火墙规则未创建（`New-NetFirewallRule` 拒绝访问），Windows 防火墙三配置文件均关闭，8020 无子网限制（无端口映射/隧道，不对公网暴露）；③ ✅ iPhone 已装 `rootCA.crt` 并完全信任（Android 待设备）；④ 路由器固定 IP 待做；⑤ ✅ 设备型号/系统版本已回（iPhone 14 / iOS 27.0.1）；剩余项见下方“人类（管理员，UAC，剩余）” |
| 2026-10-24 | 人类批准本机操作（seq=485） | “批准”理解为授权技术侧执行 mkcert 安装、`mkcert -install`、签发证书、8020 防火墙规则与启动 8020；已在群内复述口径并给出叫停方式 |
| 2026-10-24 | iPhone 本地 CA 安装（人类） | 人类经微信接收 `rootCA.crt` → 按指引安装并开启完全信任；iPhone 14 / iOS 27.0.1 访问 `https://192.168.31.68:8020/health` 正常、无证书告警（seq=500/504）；仅装 CA，未转发私钥 |
| 2026-10-24 | 内网独立检查（小测） | 服务端 + 桌面 Chrome：**18 PASS / 0 FAIL / 2 NOT-RUN（C09/P05，鉴权关闭属预期）/ 2 INFO**；HTTPS 安全上下文、SW `activated` + `fishagent-v2-static`、10/10 预缓存、离线 503 诚实文案、恢复自动刷新、`/api/*` 不入缓存、证书链/SAN/指纹/有效期、MIME、访问日志 0 行（8018 PID 70828 未变、8020 未重启）；RD 60 项：PARTIAL 11 / PENDING 23 / NOT-RUN 26；证据 11 件哈希全部校验通过，`SHA256SUMS.txt` `e056c278…f9c3`，执行记录 `49721451…5f20`（仓库/共享核心 4 件一致） |
| 待办 | 人类（iPhone 真机验收） | 按 A–F 步骤回传：能否“添加到主屏幕”、standalone 无浏览器栏、离线壳无假数据、定位允许/拒绝回退、高德 App 调起与网页回退；对应 RD-01..11/19/21..27/34/35/37..41/48/51/52/58 共 23 项 PENDING |
| 待办 | 人类（Android） | 是否有可用 Android 设备；有则装 Android 用户 CA 后执行 Android 侧检查（RD-01/02/20/36 等 NOT-RUN） |
| 待办 | 人类（管理员，UAC，剩余） | ① `mkcert -install` 仍未完成（仅影响桌面浏览器信任）；② 防火墙规则未创建，Windows 防火墙三配置文件均关闭，8020 当前无子网限制（无端口映射/隧道，不对公网暴露）；③ 路由器固定 IP/DHCP 保留 `192.168.31.68` |
| 待办 | 人类（公网 B） | 域名与 Cloudflare 账号归属、家庭主机就绪与常开、邀请码值/发放方式、是否复用 Key、发布授权与时间窗、运维责任人 |
| 待办 | M3（小测） | iPhone 23 项 PENDING 待人类结果回传；Android 与公网 22 项及 RD-01..07 域名重跑留待设备/B 授权后 |

**M1 已知限制**：无头浏览器只能验证安装入口逻辑，真机安装、iOS 添加到主屏幕、standalone 启动需 M3 覆盖；安装与定位依赖 HTTPS；每次发布 `web/` 需递增 `sw.js` 的 `CACHE_VERSION`。

**P2 关闭记录**：O-CR03-01 四类 401（含错误邀请码）已统一带 `Cache-Control: no-store` 与 `WWW-Authenticate: Bearer realm="fishagent-pilot"`；O-CR03-02 部署方案定稿 `uvicorn ... --workers 1 --no-access-log`（systemd 同参），反代访问日志按同一原则处理。小测 v1.8 独立复测 11/11 PASS 关闭。另有本地 `127.0.0.1:8023` 的 2026-10-22 遗留测试实例（PID 8100，父进程已退出，pilot 未启用）已停止；非 8018、无公网暴露。小钱自测时曾误打 3 次业务请求到该实例，可能消耗少量配额，已主动披露。

**未完成的验证（D 组）**：60 项当前状态 **PARTIAL 11 / PENDING 23 / NOT-RUN 26**（合计 60，已校验）。服务端与桌面 Chrome 由小测独立完成 18 PASS / 0 FAIL；内网可做的 36 项中，**iPhone 23 项 PENDING 待人类按 A–F 步骤回传真机证据**，Android 相关（RD-01/02/20/36 等）**NOT-RUN 待设备**；22 项（登录/邀请码/Cookie、Cloudflare 证书/canonical/缓存/WAF、真实域名限流与 IP 分桶、主机异常/100s）必须公网 B。整项 PASS 需双端真机或公网证据，内网/桌面 PASS 不代表公网 PASS；换 Origin 后 RD-01..07 需在域名重跑。**CR-03 不判 GO。**

**M2 已知限制**：配额计数在进程内存，重启清零、多 worker 不共享，试点须单 worker（扩容需 Redis）；Agent 路径在配额中途耗尽的边界情况可能降级为文本回答而非 429；共用邀请码无法按人撤销，泄露需同时轮换邀请码与令牌密钥。建议实际阈值设在 D4 之下（如 1800/180/900）。

**M2 方案文档**：`docs/cr03-deployment-plan.md`（仓库与共享目录一致）。

## CR-04 附近钓位新增“推荐鱼种”

**人类确认（2026-10-25）**

- 在 Step 3 “附近钓位”每个推荐地址下新增“推荐鱼种”，例如“推荐鱼种：草鱼、鲤鱼”。
- 鱼种为当前钓位中存在的鱼种，信息来源为小红书网友推荐。
- 小红书搜不到时，明确告知“暂无相关鱼种推荐”。

**实现决策（人类选定）**

| 决策 | 结果 |
|---|---|
| 数据来源 | **可插拔 `SpeciesProvider` + Mock**：先交付完整接口、页面与无结果兜底；真实小红书适配器预留协议与注册点，不在本轮抓取 |
| 加载方式 | **独立批量接口异步填充**：钓位列表先渲染，`POST /api/spots/species` 返回后补“推荐鱼种”行；失败不影响钓位主流程 |

**范围**

- 后端：`SpeciesProvider` 协议；`MockSpeciesProvider`（确定性、覆盖有/无推荐两条路径）与 `NullSpeciesProvider`；`POST /api/spots/species`；鱼种别名归一、白名单、去重、单钓位最多 4 个；按归一化 `(name, water_type)` 元组缓存（成功 3600s，空/降级 `min(TTL, 300)`）；超时/异常/异常载荷降级为 200 + **全部空结果** + `degraded=true`。
- H5：钓位卡新增“推荐鱼种：…”行，附来源与“仅供参考”；先渲染钓位、后异步补齐；空结果显示“暂无相关鱼种推荐”；鱼种请求 4.5s 超时、401 不全局跳转、空名钓位过滤、按 `spot_id` 映射，降级文案与空结果区分。
- 配置：`FISHAGENT_SPECIES_PROVIDER`（`mock` / `bing` / `none` / `disabled`）、`FISHAGENT_SPECIES_TIMEOUT_SECONDS`、`FISHAGENT_SPECIES_CACHE_TTL_SECONDS`。
- 非范围：真实小红书抓取（需 Cookie 或第三方授权）、Agent 对话引用鱼种、按用户个性化、鱼获数据。

**数据源调研（2026-10-26）**

- `astron-xiaohongshu-mcp 0.1.5` 实测：仅暴露 5 个工具，搜索函数未注册为 MCP 工具；游客态搜索页 HTML 无笔记数据（0 条），无法按钓位检索小红书。另 `mcp>=2` 会导致 `mcp.server.fastmcp` 缺失，需手动降级 `mcp<2`。
- 百度：requests 与 headless Chrome 访问均强制跳转图形验证码，无法自动检索。
- Bing：可用，但 `site:xiaohongshu.com` 无效、小红书内容几乎无收录；对多词查询会退化为只匹配首个专有名词。
- 结论：改用 **Bing 结果摘要 + 白名单匹配**（Phase 1），不抓正文、不依赖 LLM。

**验收**

1. 每个钓位卡显示“推荐鱼种：…”或“暂无相关鱼种推荐”，并标注来源与“仅供参考”。
2. 鱼种接口超时/异常时钓位接口仍 200，页面不报错；对应行降级为无推荐。
3. 批量 1–10 项，结果顺序与请求一致；同名同类型重复项只查询一次。
4. Mock 模式可演示“有推荐”和“无推荐”；真实模式默认 `none`，不伪造社区数据。
5. `pytest`、`ruff` 通过；不承诺渔获，既有合规文案不回归。

**状态**：第二轮修复完成（后端降级语义、H5 超时/空名/401、缓存键、测试与契约文档 v1.6），待独立 QA 复验。配额异常口径已裁决：按契约 4.6 降级为 200，不返回 429。
