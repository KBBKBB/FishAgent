# CR-03 M2-B：Cloudflare Tunnel 部署与访问控制方案（B 为主）

> 状态：人类已确认 **托管 B（Cloudflare Tunnel 到家庭主机）+ 共用邀请码**。本文是**准备文档**：未创建 Tunnel、未改 DNS、未安装/注册 cloudflared、未发布、未采购、未改 8018、未提交 Git。
> 依据：`docs/change-requests.md` CR-03；人类确认（2026-10-24）iOS/Android 都做、外出可用、采用 PWA、无 Apple 账号；随后确认托管 B 与共用邀请码。
> 工程侧现状：M1 PWA、M2 本地安全、M1b 401/429 适配均已通过；180 passed、ruff clean；P2（O-CR03-01/02）已修复并复测关闭。真机与公网项未验证，不计 PASS。

---

## 1. 已确认决策与仍待人类提供

| 编号 | 决策项 | 状态 | 结论 / 默认建议 |
|---|---|---|---|
| D1 | 托管方式 | **已确认** | **B：Cloudflare Tunnel 到家庭主机** |
| D4 | 访问控制 | **已确认** | 试点共用邀请码（3–5 人），不建账号体系 |
| D2 | 域名、Cloudflare 账号、家庭主机 | 待提供 | 由人类提供；需同时确认 canonical 入口（默认裸域，`www` 仅 301）；技术侧只做配置与核对 |
| D3 | 预算 | 待确认 | Cloudflare 免费计划 + 域名年费 + 家庭电费；无服务器租金 |
| D5 | 高德/DeepSeek Key | 待授权 | 优先申请试点独立 Key；复用现有 Key 需单独授权 |
| D6 | 发布窗口与运维人 | 待确认 | ≥2 小时窗口，可回滚；运维人能重启服务、轮换令牌、每日看用量 |

**边界**：在 D2/D5/D6 到位并获明确发布授权前，不创建隧道、不改 DNS、不安装连接器、不对外开放。S1（8018）继续按现 H5 运行。

---

## 2. 拓扑与数据流

```
手机/桌面 PWA --HTTPS(443)--> Cloudflare 边缘（TLS 终止，可选 WAF）
                                    │ 出站加密隧道（源站不开放任何入站端口）
                                    ▼
                          家庭主机 Windows 10
                          cloudflared（Windows 服务，开机自启）
                                    │ http://127.0.0.1:8020
                                    ▼
                          uvicorn（单 worker，仅回环监听）
                            ├─ 高德 Web Service
                            ├─ Open-Meteo
                            └─ DeepSeek / LLM（可选）
```

- **DNS**：**唯一 canonical 入口为裸域 `example.com`**（如人类偏好 `www`，则对调，仍只保留一个入口）。裸域 CNAME 到 `<tunnel-id>.cfargotunnel.com`，由 Cloudflare 在根域自动展平；**必须走代理（橙云）**，由 Dashboard 的 Published application 自动创建，不手工建 A 记录。
- **`www.example.com` 不接入隧道**：只配置 301 → `https://example.com`（保留路径与查询）。会话 Cookie 是 host-only，若 `www` 与裸域同时跑应用，会出现"在 www 登录、回到裸域仍未登录"的假故障。
- **不需要**：公网 IP、端口映射、光猫桥接、路由器入站放行；家庭宽带处于 CGNAT 也可用。
- **需要**：主机可出站访问 Cloudflare（TCP 443；QUIC/UDP 7844 可选，受限时回退 HTTP/2）。
- **源站不可直连**：uvicorn 只监听 `127.0.0.1:8020`，局域网与公网都无法绕过 Cloudflare 直连应用；`8018` 完全不参与试点链路。

---

## 3. 前置条件与验收门槛

### 3.1 域名与 Cloudflare 账号

- 域名已托管在 Cloudflare（NS 指向 Cloudflare），使用**单一 canonical 入口**：默认裸域 `example.com`；`www.example.com` 仅做 301 跳转，不接入隧道。若人类偏好 `www`，两者对调，但**仍然只能有一个可登录入口**。
- Cloudflare 账号开启 2FA（TOTP 或硬件密钥），恢复码离线保存；注册商开启转移锁；账号密码唯一。
- 验收：`nslookup -type=ns example.com` 返回 Cloudflare 分配的 NS；Dashboard 中 Zone 状态为 Active；2FA 已启用；裸域未被其他服务占用；`www` 只能 301，不能独立提供应用与登录。

### 3.2 家庭主机（Windows 10）

| 项 | 要求 | 验收方法 |
|---|---|---|
| 常开 | 24/7 在线，禁止睡眠/休眠 | `powercfg /change standby-timeout-ac 0`、`powercfg /change hibernate-timeout-ac 0`；24 小时外网探活无中断 |
| 网络 | 有线优先；上行 ≥10 Mbps（推荐 20+）；丢包 <1% | 连续 24h `ping`/`curl` 统计 |
| 延迟 | 到 Cloudflare 边缘 RTT 稳定（免费计划通常经香港/新加坡/日本节点，晚高峰可能抖动） | 发布前 3 天分时段采样，p95 见 §10 切换条件 |
| 电源 | 建议 UPS；断电后能自动恢复 | 断电演练：恢复后 5 分钟内两项服务自动在线 |
| 更新 | Windows Update 设为手动/活动时间，避免自动重启 | 检查设置；记录最近一次重启时间 |
| 磁盘 | ≥10 GB 可用；日志轮转开启 | `Get-PSDrive D` |
| 时间 | 系统时间自动同步 | `w32tm /query /status` |

### 3.3 应用侧

- Python 3.11+ 虚拟环境；依赖已安装；`backend/.env` 仅有服务账号与管理员可读。
- 单 worker、仅回环、关闭访问日志（见 §4）。
- 验收：本机 `/health` 200；未登录 `/api/fish-activity` 401 且带两项鉴权头；应用日志无访问行、无 IP/令牌/邀请码/Key。

---

## 4. 应用侧配置

### 4.1 环境文件（`backend/.env`）

路径由代码固定为 `backend/.env`（`config.ENV_FILE`）。**占位符模板**：

```dotenv
# --- 运行模式与上游 ---
FISHAGENT_MOCK_MODE=false
AMAP_WEB_KEY=<人类确认后填入；优先试点独立 Key>
LLM_API_KEY=<可选；不配置则 Agent 走确定性兜底>
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# --- 公网访问控制（CR-03）---
FISHAGENT_PUBLIC_ACCESS_ENABLED=true
FISHAGENT_PILOT_INVITE_CODE=<人类提供，≥12 位随机字符>
FISHAGENT_PILOT_TOKEN_SECRET=<主机本地生成，≥32 字符>
FISHAGENT_PILOT_TOKEN_TTL_SECONDS=43200
FISHAGENT_PILOT_COOKIE_NAME=fishagent_pilot
FISHAGENT_PILOT_COOKIE_SECURE=true
FISHAGENT_PILOT_CORS_ORIGINS=
FISHAGENT_PILOT_TRUST_PROXY_HEADERS=true
FISHAGENT_PILOT_RATE_LIMIT_IP_PER_MINUTE=60
FISHAGENT_PILOT_RATE_LIMIT_TOKEN_PER_MINUTE=60
FISHAGENT_PILOT_LOGIN_ATTEMPTS_PER_MINUTE=10

# --- 上游日配额（设在 D4 之下，作为安全刹车）---
FISHAGENT_AMAP_DAILY_QUOTA=1800
FISHAGENT_LLM_DAILY_QUOTA=180
FISHAGENT_OPEN_METEO_DAILY_QUOTA=900
FISHAGENT_QUOTA_DAY_TIMEZONE=Asia/Shanghai
```

关键项说明：

- `FISHAGENT_PILOT_CORS_ORIGINS=` **留空 = 仅同源**。H5 与 API 同域，无需 CORS 白名单；禁止填 `*`（启动会失败）。
- `FISHAGENT_PILOT_COOKIE_SECURE=true`：隧道出口是 HTTPS 域名，Cookie 必须只走 HTTPS。
- Cookie 不设置 `Domain`，因此是 **host-only**：只在 canonical 入口（默认裸域）有效。这也是 `www` 必须 301 而不能平行提供应用的原因。
- `FISHAGENT_PILOT_TRUST_PROXY_HEADERS=true`：限流按 `CF-Connecting-IP` 取真实客户端 IP。**成立前提是 8020 只监听回环、只有 cloudflared 能连**；一旦改成 `0.0.0.0`、做端口映射或允许直连源站，该头可被伪造，必须立即改回 `false`。
- 配额低于 D4 真值，超额即 429 并停止调用上游，不影响 S1。

主机本地生成密钥（输出只留在主机，不贴群、不入库）：

```powershell
# 令牌签名密钥（≥32 字符）
$b = New-Object byte[] 48
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
[Convert]::ToBase64String($b)

# 邀请码（建议 ≥12 位，可用密码管理器生成）
```

写入权限（示例：专用本地账号 `fishagent`）：

```powershell
icacls "D:\FishAgent\backend\.env" /inheritance:r /grant:r "fishagent:(R)" "Administrators:(F)" "SYSTEM:(F)"
```

### 4.2 启动命令

```powershell
D:\FishAgent\backend\.venv\Scripts\python.exe -m uvicorn fishagent.main:app `
  --host 127.0.0.1 --port 8020 --workers 1 `
  --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1
```

| 参数 | 作用 | 必要性 |
|---|---|---|
| `--host 127.0.0.1` | 只接受本机连接，杜绝绕过隧道直连 | 必须 |
| `--workers 1` | 限流/配额计数在进程内，多 worker 会各算各的 | 必须 |
| `--no-access-log` | 不写客户端 IP/XFF（O-CR03-02） | 必须 |
| `--proxy-headers` | 采用 `X-Forwarded-For`/`X-Forwarded-Proto` | 建议显式声明 |
| `--forwarded-allow-ips 127.0.0.1` | 只信任本机 cloudflared，绝不写 `*` | 必须 |

> 本机 uvicorn 0.53 默认已开启 `--proxy-headers` 且只信任 `127.0.0.1,::1`；显式写出是为了让部署参数可审计。
> 应用侧 `FISHAGENT_PILOT_TRUST_PROXY_HEADERS=true` 优先取 Cloudflare 在边缘写入的 `CF-Connecting-IP`；它是唯一可信来源，因为云外客户端无法绕过 Cloudflare 到达源站。两层信任都只对回环成立。
> **P1 阻塞判据（D 组 RD-55）**：上线验收必须证明不同公网 IP 落在不同限流桶；若所有请求都退化为 `127.0.0.1`（同一桶），判 P1，部署不通过。验证方法见 §5 阶段 3。

### 4.3 注册为 Windows 服务（NSSM）

cloudflared 与 uvicorn 都需要"开机自启 + 失败重启"。uvicorn 用 NSSM 托管（WinSW 或任务计划程序亦可；**安装第三方工具需人类同意**）：

```powershell
nssm install FishAgent "D:\FishAgent\backend\.venv\Scripts\python.exe" `
  "-m uvicorn fishagent.main:app --host 127.0.0.1 --port 8020 --workers 1 --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1"
nssm set FishAgent AppDirectory "D:\FishAgent\backend"
nssm set FishAgent AppStdout "D:\FishAgent\logs\app.out.log"
nssm set FishAgent AppStderr "D:\FishAgent\logs\app.err.log"
nssm set FishAgent AppRotateFiles 1
nssm set FishAgent AppRotateOnline 1
nssm set FishAgent AppRotateBytes 10485760
nssm set FishAgent AppExit Default Restart
nssm set FishAgent AppRestartDelay 5000
nssm set FishAgent Start SERVICE_AUTO_START
nssm set FishAgent ObjectName ".\fishagent" "<本机输入账号密码>"
nssm start FishAgent
```

验证：

```powershell
nssm status FishAgent                                  # SERVICE_RUNNING
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8020/health
Get-NetTCPConnection -LocalPort 8020 -State Listen     # 只应出现 127.0.0.1
```

### 4.4 日志

- 应用：NSSM 重定向到 `D:\FishAgent\logs\app.*.log`，10 MB 轮转；内容不含 IP、令牌、邀请码、Key（已由 QA 与单测覆盖）。
- cloudflared：以 Windows 服务运行时在**事件查看器 → Windows 日志 → 应用程序**筛选 `cloudflared` 查看；不使用 debug 级日志（可能记录更多请求细节）。
- 不引入额外日志管道；访问日志保持关闭。保留期建议 7–14 天，按磁盘容量调整。

### 4.5 超时与主机离线预期

- **Cloudflare 源站响应上限约 100 秒**，超时返回 524。当前 LLM 单次超时 30s，`/api/agent/chat` 最多预留 2 次调用（约 60s）再加工具耗时，理论上低于上限，但上游卡顿叠加时可能逼近。
  - 验收（待隧道实测）：单次 chat **< 90 秒**且无 524；超限先调低 `LLM_TIMEOUT_SECONDS`，仍不满足再评估代码级总超时。
  - 超时或失败必须返回明确错误，**不得挂起、不得用假数据填充**。
- **主机离线/隧道断开**：用户侧预期看到 Cloudflare 5xx（502 / 1033 / 530 等错误页）。
  - 恢复目标：从主机或服务恢复起算 **≤60 秒**重新可访问；见 §5 阶段 4 的恢复步骤与计时方法。
- **性能阈值分开口径**：主机恢复 ≤60 秒、App 壳冷启动首屏 ≤5 秒；**数据请求耗时按 S1 P95 口径单独统计**，不并入 5 秒，也不因超时伪造数据。

---

## 5. 上线 runbook（按顺序执行；每步都有验收）

### 阶段 0：本机应用就绪（技术侧，可在授权前完成）

1. 安装依赖、创建 `backend/.env`、设置 ACL、注册 `FishAgent` 服务。
2. 验收：`/health` 200；未登录 `/api/fish-activity` 401 且含 `Cache-Control: no-store` 与 `WWW-Authenticate`；`Get-NetTCPConnection` 仅回环；应用日志无访问行。

### 阶段 1：Cloudflare 侧建隧道与入口（人类在 Dashboard 操作）

1. Zero Trust → **Networks → Tunnels** → **Create a tunnel** → 选择 **Cloudflared** → 命名（如 `fishagent-pilot`）→ 保存。
2. 选择 **Windows**，复制安装命令（含隧道令牌）。**令牌只在本机使用，不贴群、不入库、不进文档/证据。**
3. 等待连接器显示 **Healthy** → Continue。
4. 添加路由：**Add route → Published application**（旧版界面为 **Public Hostname**）：
   - **裸域 canonical**：Subdomain 留空；Domain：人类提供的域名（如 `example.com`）；Path：留空。
   - 若人类偏好 `www`：Subdomain 填 `www`，并把裸域 301 到 `www`；**只保留这一个入口**。
   - Service：`HTTP` + `127.0.0.1:8020`。
   - 保存后 Cloudflare 自动创建**代理状态**的 CNAME（`<tunnel-id>.cfargotunnel.com`；根域由 Cloudflare 展平）。
5. SSL/TLS：加密模式 **Full**；开启 **Always Use HTTPS**（HTTP 301 到 HTTPS）。
6. **www 处理**：给非 canonical 的 `www` 建代理记录，并用 **Redirect Rule（Single Redirect）** 301 到 `https://<canonical-host>`，保留 path 与 query。**不要**把 `www` 也加到隧道的 Public Hostname。
7. **缓存规则（Bypass cache）**：`/`、`/sw.js`、`/manifest.webmanifest` 三条设置 Bypass，避免 HTML 与 Service Worker 被边缘缓存导致 PWA 更新滞后。`/api/*` 由应用返回 `Cache-Control: no-store`，无需额外规则。
8. **不得干扰应用与登录**：
   - 关闭 **Rocket Loader**（会改写/注入脚本，且与登录页 CSP `default-src 'none'` 冲突）；
   - 关闭 **Email Address Obfuscation**（会注入脚本，本应用无邮箱展示需求）；
   - 关闭 **Bot Fight Mode**；不要对 `/api/*`、`/pilot/login` 启用 Managed Challenge / JS Challenge；
   - 若开启 WAF 托管规则，为 `/api/*` 与 `/pilot/login` 建 **Skip** 规则，**登录 POST 必须直达源站**。
9. 可选：开启免费托管规则/WAF、Tunnel 健康通知到人类邮箱。
10. 验收：Dashboard 中隧道 Healthy；canonical 主机为代理 CNAME；`http://<canonical-host>/health` 301 到 HTTPS；`http://www.<domain>/x?y=1` 301 到 `https://<canonical-host>/x?y=1`；`www` 不能独立打开应用或完成登录。

### 阶段 2：主机侧安装连接器（人类在本机执行）

```powershell
# 管理员 PowerShell；<TOKEN> 从 Dashboard 复制，只在本机粘贴
cloudflared.exe service install <TOKEN>
sc.exe config Cloudflared start= auto
sc.exe failure Cloudflared reset= 86400 actions= restart/5000/restart/15000/restart/60000
Get-Service Cloudflared
```

- 需要预先安装 cloudflared（官方 MSI 或 `winget install -e --id Cloudflare.cloudflared`）；安装系统服务需管理员权限。
- 服务名通常为 `Cloudflared`，启动类型应为"自动"；失败后按 5s/15s/60s 重启。
- 命令会进入 PowerShell 历史；如担心残留，执行后清理历史（可选）。**令牌泄露处置**：Dashboard 中刷新隧道令牌（Refresh token）→ 主机 `cloudflared.exe service uninstall` 后用新令牌重新安装 → 确认旧连接器消失。
- 卸载/停用：`cloudflared.exe service uninstall`（或 `sc stop Cloudflared`）。

### 阶段 3：外网验收（技术侧，人类在场）

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" "https://example.com/health"                    # 200
curl.exe -s -D - -o NUL "https://example.com/pilot/login"                              # 200 + CSP/XFO/no-store
curl.exe -i "https://example.com/api/fish-activity?lat=30.2&lon=120.1"                 # 401 + 两项鉴权头
curl.exe -i -X POST "https://example.com/api/pilot/login" -H "Content-Type: application/json" -d '{"code":"wrong"}'   # 401 INVALID_INVITE_CODE
curl.exe -i "http://www.example.com/x?y=1"                                            # 301 -> https://example.com/x?y=1
```

浏览器（无痕窗口）用正确邀请码登录，确认：

| 检查 | 期望 |
|---|---|
| canonical | 裸域可登录；`www` 只 301，不能独立登录；换到 `www` 后回到裸域仍是已登录（host-only Cookie 生效） |
| `Set-Cookie` | `HttpOnly; Secure; SameSite=Lax; Path=/`，**无 `Domain=`** |
| 401 跳转 | `/pilot/login?next=<当前路径>`，登录后回跳，无循环 |
| 429 | 文案含 `Retry-After` 秒数，不自动重试 |
| `/api/pilot/usage` | 登录后 200，amap/open_meteo/llm 用量可见 |
| 真实 IP（RD-55，P1） | 两个不同公网 IP 落在不同限流桶（见下方专项） |
| 缓存/WAF | `/sw.js`、`/manifest.webmanifest`、`/` 响应头无可疑缓存；Rocket Loader 未注入；登录 POST 未被 challenge |
| 超时 | 单次 chat < 90 秒，无 524；超时返回明确错误，不挂起、不伪造数据 |
| 日志 | 应用日志无访问行；无 IP/令牌/邀请码/Key |
| 主机重启 | 见阶段 4；恢复 ≤60 秒 |

**RD-55 真实客户端 IP 专项（P1 阻塞判据）**

1. 准备两个不同公网出口：手机蜂窝网络（关闭 Wi-Fi）与另一条宽带/热点。
2. A 网络连续提交 6 次错误邀请码；B 网络再提交 6 次错误邀请码。
3. 期望：两边的第 1–6 次均为 401，互不牵连（各自限流桶 10 次/分钟）；随后各自第 11 次才 429。
4. 若两边共享计数、或很快整体 429、或表现为同一来源，说明 IP 退化为 `127.0.0.1` → **判 P1，部署不通过**，先修正代理头/直连暴露问题再验。
5. 同时从外网尝试 `http://<家庭公网IP>:8020`（若有公网 IP）：必须超时/拒绝；确认路由器无端口映射、UPnP 关闭。

外网探测通过后，才进入 D 组真机验证（§8）；**D 组通过前不向试点用户发放邀请码**。

### 阶段 4：故障与恢复演练（技术侧，需人类在场）

1. 记录基线：`https://example.com/health` 200。
2. 停应用服务：`nssm stop FishAgent`；预期外网 502/1033/530，且**不显示假数据**。
3. 启动应用服务并计时：`nssm start FishAgent`，轮询 `/health`，**恢复 ≤60 秒**。
4. 停隧道：`sc stop Cloudflared`；再启动并计时，外网恢复 ≤60 秒；Dashboard 连接器回到 Healthy。
5. 主机重启演练（单独时间窗）：重启后 `Get-Service Cloudflared, FishAgent` 均为 Running，外网恢复 ≤60 秒（从服务可用起算）。
6. 结果记入 D 组证据；不达标需定位是服务启动慢、隧道重连慢还是 DNS/边缘缓存。

---

## 6. 安全要求（必须逐条满足）

| 项 | 要求 |
|---|---|
| 隧道令牌 | 等同入口凭证：只由人类在本机写入服务配置；**不得发到群里、不得写入仓库/文档/证据/截图**；怀疑泄露立即刷新令牌并重装连接器 |
| 账号 | Cloudflare 2FA；恢复码离线保存；不使用共享账号；域名注册商转移锁 |
| 源站 | 仅 `127.0.0.1:8020`；不做端口映射；不建指向家庭 IP 的 DNS；Cloudflare 上只发布这一个 hostname，不加 preview/临时域名 |
| Cookie | `Secure` + `HttpOnly` + `SameSite=Lax`；令牌不落 URL、不进 localStorage |
| 邀请码 | ≥12 位随机；只经人工私下渠道发放；轮换后旧会话仍有效，需同时轮换令牌密钥强制全员重新登录 |
| 主机 | 专用低权限服务账号；`.env` ACL；开启 BitLocker（建议）；Windows 防火墙默认拒绝入站；及时打补丁；不在主机上浏览/下载无关内容 |
| Key | 只在 `backend/.env`；不进前端、日志、文档、群聊；不复用个人账号 Key，优先试点独立 Key |
| 日志 | uvicorn 访问日志关闭；cloudflared 不用 debug；日志保留 7–14 天主机关联 |
| 配额 | 日配额低于 D4 真值；超限 429 即停，避免费用失控 |

---

## 7. 本地可验证项（已完成 / 待隧道）

本轮在独立端口用 **Mock + 假邀请码/假密钥** 验证（不触达真实上游；测试后实例已停止）：

| 项 | 方法 | 结果 |
|---|---|---|
| 四类 401 响应头 | curl 抓包 | `UNAUTHORIZED`/`INVALID_TOKEN`/`TOKEN_EXPIRED`/`INVALID_INVITE_CODE` 均带 `Cache-Control: no-store` + `WWW-Authenticate: Bearer realm="fishagent-pilot"` |
| 代理头限流 | `CF-Connecting-IP` 固定为同一 IP 连续登录（本机验证时限流阈值调低为 3/分钟） | 第 1–3 次 401，第 4 次 429（`Retry-After: 56`）；换一个 IP 立即可再试（401），证明按真实客户端 IP 分桶 |
| Cookie 属性 | 正确邀请码登录 | `HttpOnly; Secure; SameSite=lax; Path=/; Max-Age=43200` |
| 同源 CORS | 跨源 `Origin` 请求 | 未返回 `Access-Control-Allow-Origin`（未配置白名单即仅同源） |
| 访问日志 | 8 次请求后检查服务日志 | 仅 4 行启动信息，`HTTP/1.1` 访问行 0 |
| 单 worker | 启动参数审计 | `--workers 1`；计数在进程内存，扩容需 Redis |
| 单元/接口测试 | `pytest tests -q`、`ruff check` | 180 passed；All checks passed |
| 8018 隔离 | 只读 `/health` | 200；未重启、未启用开关、未调用数据接口 |

**不能本地证明、标注"待隧道"**（均须在隧道上线后按 §5 阶段 3/4 实测，实测前不得判 PASS）：

- DNS 解析与证书链、HTTP→HTTPS 跳转、公网可达性、真实域名下的 Cookie 收发。
- **canonical 单一入口**：裸域可登录、`www` 仅 301、`www` 与裸域不会出现"登录后回到未登录"。
- **RD-55 真实客户端 IP 分桶（P1）**：两个不同公网 IP 各自独立计数；若退化为同一桶判 P1 失败。
- **Cloudflare 缓存/WAF 行为**：`/`、`/sw.js`、`/manifest.webmanifest` 不被边缘缓存；Rocket Loader 未注入；登录 POST 未被 challenge。
- **源站 100 秒上限**：单次 chat < 90 秒、无 524、超时返回明确错误。
- 家庭宽带实际延迟/丢包、主机断电与重启恢复（≤60 秒）、真机安装/standalone/定位。

---

## 8. 与 D 组（真机 + HTTPS）的衔接

本文只负责"入口可用、鉴权生效、日志合规"。D 组 **60 项清单（v2）** 由小测维护，在隧道上线后执行，覆盖：Android 安装入口、iOS"分享 → 添加到主屏幕"、standalone 启动、图标/启动图、SW v2 接管、离线提示、HTTPS 定位授权与拒绝回退、高德 App 调起与网页回退、真实域名下的 401/429/退出登录、多设备限流、主机休眠/断网/重启表现、冷启动首屏耗时、canonical/`www` 跳转、缓存/WAF 干扰、源站超时。

**D 组阈值（口径固定，不混算）**：

| 指标 | 阈值 | 说明 |
|---|---|---|
| 主机恢复 | **≤60 秒** | 从服务或主机恢复起算到外网 `/health` 200；§5 阶段 4 计时 |
| App 壳冷启动首屏 | **≤5 秒** | 仅壳与首屏渲染，不含数据请求 |
| 数据请求耗时 | 按 S1 P95 | 单独统计，不并入 5 秒；超时不得伪造数据 |

**RD-55 真实客户端 IP 是 P1 阻塞判据**：两个不同公网 IP 必须落在不同限流桶（方法见 §5 阶段 3）；退化为 `127.0.0.1` 单一桶即 D 组不通过。

**D 组通过前，CR-03 不判 GO，不向试点用户发放邀请码。**

---

## 9. 回滚与切换

### 9.1 回滚到内网（保留代码与数据）

1. 停隧道：`sc stop Cloudflared` 或 `cloudflared.exe service uninstall`；或在 Dashboard 删除 Public Hostname。
2. 外网立即表现为 Cloudflare 错误页（隧道未连接），源站不暴露。
3. 应用可继续在 `127.0.0.1:8020` 供本机/内网调试（如需内网访问再单独评估，不默认放开）。
4. 恢复：重新安装/启动连接器即可，DNS 无需改动（Public Hostname 仍在时）。
5. **canonical 不变**：回滚与恢复都保持同一入口（裸域为主，`www` 只会 301）。**不要临时把 `www` 指向源站**来"救火"——那会立刻产生 host-only Cookie 分裂（`www` 登录、裸域未登录），且已安装 PWA 的 Origin 仍是 canonical。如必须换入口，按 9.2 的"换域名即重装"处理。

### 9.2 切回 A（云服务器）的条件

满足任一即启动评估：连续 3 天 p95 TTFB > 2 s 或错误率 > 5%；每周主机不可用 ≥2 次或单次 >30 分钟；运营商条款/封禁风险出现；试点用户 >5 人或需要对外长期开放；家庭主机发生不可恢复的硬件/系统故障。

切换方式：在 A 上按同一套应用配置部署 → 将入口域名改为指向 A 的代理记录（或新建域名）→ 保留 B 作为演练/回退入口。**PWA 已安装用户绑定 Origin，换域名意味着重新安装**，切换前需通知试点用户。

### 9.3 切回内网或停机的判定

出现以下任一情况，停止对外并回到内网（§9.1）：RD-55 判 P1 且短期无法修正；单次 chat 反复 524 且降 `LLM_TIMEOUT_SECONDS` 仍不达标；登录 POST 被 Cloudflare challenge 拦截且无法用 Skip 规则解除；主机在发布窗口内无法满足 ≤60 秒恢复目标；运营商明确限制或封禁。

---

## 10. 风险登记（B 专项）

| 风险 | 影响 | 缓解 | 残余风险 |
|---|---|---|---|
| 家庭宽带条款限制对外服务 | 被限速/停机 | 隧道为出站连接；提前核对运营商条款；准备 A 方案 | 条款解释权在运营商 |
| Cloudflare 大陆访问质量（免费计划无大陆节点） | 晚高峰延迟/抖动 | 发布前 3 天分时段采样；必要时切 A | 跨境线路不可控 |
| 主机断电/断网/休眠 | 全站不可用（用户见 502/1033/530） | UPS、禁休眠、服务自启、失败重启、健康通知；恢复目标 ≤60 秒并按 §5 阶段 4 演练 | 宽带故障期间无法服务 |
| `www` 与裸域同时可用 | host-only Cookie 分裂，表现为"登录后仍未登录" | 只保留一个 canonical 入口，`www` 仅 301（含 path/query）；验收表逐项检查 | 用户手动输入另一主机名时仍有困惑 |
| 真实 IP 退化（RD-55，P1） | 全局限流共用一桶：要么误伤全部用户，要么等于没限流 | 只回环监听 + `CF-Connecting-IP` + 两公网 IP 验收；退化为 `127.0.0.1` 即判 P1、不发布 | 代理行为变更需复测 |
| 源站 100 秒上限 | 长对话 524 | 单次 chat 验收 < 90 秒；先降 `LLM_TIMEOUT_SECONDS`；超时明确报错 | 上游极慢时仍可能触顶 |
| Cloudflare WAF/challenge 误伤 | 登录 POST 被拦、`app.js` 被 challenge，表现为"点了没反应" | 关闭 Rocket Loader / Email Obfuscation / Bot Fight Mode；`/api/*`、`/pilot/login` 建 Skip；登录 POST 直达源站 | 规则调整后需回归 |
| 边缘缓存旧 SW/HTML | PWA 更新滞后 | `/`、`/sw.js`、`/manifest.webmanifest` Bypass cache | 浏览器自身缓存仍需关闭旧页 |
| Windows Update 自动重启 | 短时中断 | 手动更新窗口、活动时间、重启后自愈 | 安全补丁延迟的权衡 |
| 隧道令牌泄露 | 他人可接入同一隧道 | 令牌只在本机使用；刷新令牌并重装；检查连接器列表 | 泄露到发现之间的窗口 |
| Cloudflare 账号被盗 | DNS/隧道被改 | 2FA、唯一密码、恢复码离线、转移锁 | 钓鱼/终端被控 |
| 主机被入侵 | Key 与邀请码泄露 | 低权限服务账号、最小安装、补丁、BitLocker、ACL | 家用终端防护弱于机房 |
| 共用邀请码扩散 | 未授权访问 | 限流、日配额、用量监控；轮换邀请码+令牌密钥 | 无法定位到个人 |
| 配额中途耗尽 | Agent 路径可能降级而非 429 | 进入 Agent 前预留 LLM、检查上游；配额设在 D4 之下 | 边界窗口仍可能降级 |
| 域名/Origin 变更 | 已安装 PWA 失效 | 固定单一 hostname；变更前通知并重装 | 用户流失 |
| 单点家庭主机 | 无冗余 | 接受试点期单点；A 作为回退 | 试点可用性上限受家庭环境约束 |

---

## 11. 资源清单（人类提供 / 确认，含验收标准）

| # | 项 | 提供方 | 验收标准 |
|---|---|---|---|
| 1 | 域名（已托管 Cloudflare） | 人类 | NS 指向 Cloudflare、Zone Active、可作为唯一 canonical 入口（默认裸域；如选 `www` 则裸域 301） |
| 2 | Cloudflare 账号 | 人类 | 2FA 已开、恢复码离线、密码唯一、注册商转移锁 |
| 3 | 家庭主机（Windows 10） | 人类 | 24/7 常开、禁休眠、有线优先、磁盘 ≥10 GB、断电/重启后自愈 ≤60 秒 |
| 4 | 网络质量 | 人类 + 技术侧实测 | 上行 ≥10 Mbps、丢包 <1%、连续 24h 探活无中断 |
| 5 | 邀请码值 | 人类 | ≥12 位随机、私下发放、未出现在群/仓库/文档 |
| 6 | 试点 Key（高德/LLM） | 人类授权 | 优先独立 Key；复用需书面确认；配额低于 D4 |
| 7 | 发布窗口 | 人类 | ≥2 小时、可回滚、技术侧与运维人在线 |
| 8 | 运维责任人 | 人类指定 | 能重启两项服务、刷新隧道令牌、每日查看用量 |
| 9 | 第三方服务托管工具（NSSM 或 WinSW） | 人类同意 | 官方来源下载、校验版本、仅本机安装 |
| 10 | 隧道名称与公开域名 | 技术侧提议，人类确认 | `fishagent-pilot` / canonical 入口（默认裸域 `example.com`，`www` 仅 301），发布后不再变更 |

**技术侧在资源到位后负责**：环境文件与服务注册、Cloudflare 配置核对、外网验收、回滚演练、向小测移交 D 组入口。

**本轮明确未做**：未创建隧道、未改 DNS、未安装/注册 cloudflared、未发布、未采购、未迁移/读取/回显任何 Key、未改 8018、未提交 Git。

---

## 12. 待办

| 项 | 负责人 | 依赖 |
|---|---|---|
| B 方案文档、资源清单、runbook、本地验证 | 小钱 | 已完成（本文） |
| 向人类索取域名/账号/主机/邀请码/窗口/运维人 | 小项 | 本文 §11 |
| 应用服务与 Cloudflare 配置、外网验收 | 小钱 + 人类 | 资源与发布授权 |
| D 组真机 + HTTPS 60 项（含 RD-55 P1、canonical、超时/恢复阈值） | 小测 | 隧道上线 + 邀请码 |
| 试点地址、安装说明、台账、M4 切换 | 小项 | D 组通过 |
