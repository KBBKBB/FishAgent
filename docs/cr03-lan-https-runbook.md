# CR-03 内网 HTTPS + PWA 安装试点 Runbook

> 适用：人类 2026-10-24 决定「先做内网 + PWA 安装试点，公网 B 暂缓」。
> 目标：在**不动 8018/S1** 的前提下，用独立 **8020** 实例 + 局域网可信 HTTPS（mkcert 本地 CA）建立安全上下文，完成 iOS Safari 与 Android Chrome 的真机安装、standalone 启动、定位与高德唤起验证。
> 状态：**本机准备已执行**（2026-10-24）：mkcert 1.4.4 已安装、正式 CA 与 IP SAN 服务器证书已签发、8020 已以 HTTPS 常驻运行并通过主机自测。**两项管理员操作待补**（CA 写入 Windows 信任库、8020 防火墙规则），见 §6.2。手机端未安装任何东西，未改 8018，未提交 Git。
> 关系：本文补充 `docs/cr03-deployment-plan.md`（B 方案，待资源/授权），不改变其结论与哈希。

---

## 1. 结论（可行性确认）

**可行**，前提是手机安装并信任本地 CA。本机已验证的部分：

| 结论 | 依据 |
|---|---|
| uvicorn 可直接以 HTTPS 提供 H5 与 API | 用 CA 签发的 IP SAN 证书启动 8020，`/health`、`/`、`/api/fish-activity` 均 200 |
| IP SAN 证书可被校验 | `openssl s_client` 对 `192.168.31.68` 返回 `Verify return code: 0 (ok)` |
| PWA 关键静态资源 MIME 正确 | `/` → `text/html`；`/manifest.webmanifest` → `application/manifest+json`；`/sw.js` → `application/javascript`；图标 → `image/png` |
| 局域网 IP 绑定可用 | 绑定 `192.168.31.68:8020` 后从主机经该 IP 访问成功 |
| 不影响 S1 | 8018 仍为 `0.0.0.0:8018`、PID 70828，全程未重启、未改配置 |

**关键前提与当前状态**：

1. mkcert 已安装于 `D:\FishAgent\tools\mkcert\mkcert.exe`（1.4.4，SHA-256 已核对）。
2. 正式 CA 与服务器证书已生成；**CA 尚未写入 Windows 信任库**——`mkcert -install`/`certutil`/`Import-Certificate` 都会弹交互式确认，非交互会话无法完成，需管理员在桌面点一次（§6.2）。
3. 8020 防火墙规则**未创建**（需管理员）；当前 Windows 防火墙三个配置文件均为关闭状态（§6.2）。
4. 手机需手动安装 `rootCA.pem` 并完全信任；**不装 CA 就不是安全上下文，Service Worker 不会注册，Android 不会出现安装入口**。
5. 主机 IP 需固定（DHCP 保留或静态），否则 IP 变化后证书失效。

---

## 2. 为什么必须 HTTPS

`http://192.168.31.68:8018/` 不是安全上下文（只有 `localhost`/`127.0.0.1` 的 HTTP 被浏览器视为可信）：

- Service Worker 被禁用 → 无离线壳、无 `manifest` 安装能力。
- Android Chrome 不触发「安装应用」；iOS「添加到主屏幕」只生成普通书签，启动后仍是浏览器界面。
- 定位 API 可能被直接拒绝，无法验证「定位授权 / 拒绝回退」。
- 无法验证 standalone、SW v2 接管、离线提示等 PWA 核心项。

因此内网试点**必须**用 HTTPS；本地 CA 是唯一不暴露公网的可行方式。

---

## 3. 拓扑与边界

```
iPhone / Android ──同一 Wi-Fi（同一子网）──> 192.168.31.68:8020（uvicorn HTTPS）
                                                    │
                                                    └─ 仅局域网；无端口映射、无 UPnP、无隧道
8018（S1）── 保持 0.0.0.0:8018，原样运行，不参与本试点
```

**本轮不做**：不建 Cloudflare 隧道、不改 DNS、不做路由器端口映射/UPnP、不发布到公网、不安装到手机（人类操作）、不读取/回显 Key、不改 8018、不提交 Git。

**访问控制**：本阶段与 8018 一致，**不开启**邀请码/令牌（`FISHAGENT_PUBLIC_ACCESS_ENABLED=false`）。因此 401 跳转、登录回跳、429 限流等链路**留到公网阶段**验证。

**网络要求**：

- 手机与主机在同一 Wi-Fi/子网；访客网络或开启 **AP 隔离** 的网络无法互访。
- 主机网络配置文件必须是 **专用（Private）**：`Get-NetConnectionProfile` 的 `NetworkCategory` 应为 `Private`；为 `Public` 时不要进行本试点。
- 主机防火墙只对本机局域网放行 8020，不对公网放行。

### 3.1 运行侧硬条件（小测内网子集的准入项）

| # | 条件 | 本文落点 | 本机自测 |
|---|---|---|---|
| 1 | 监听 `0.0.0.0`（或 LAN IP）+ TLS，端口 8020，`--workers 1` | §5.1 | 已验：`0.0.0.0`/LAN IP 均可启动，8020 可用 |
| 2 | 无反向代理，`FISHAGENT_PILOT_TRUST_PROXY_HEADERS=false` | §5.1 | 已按 false 启动；未注入任何代理头 |
| 3 | 证书 SAN 精确含 `192.168.31.68`，IP 固定 | §4.1/§4.2 | 已验：SAN 含该 IP，`Verify return code: 0` |
| 4 | 防火墙仅内网 → 8020；无端口映射/UPnP；`PUBLIC_ACCESS_ENABLED=false`；建议 `MOCK_MODE=true` | §5.1/§5.2 | 已按 false/Mock 启动；无端口映射/UPnP；**防火墙规则待补（需管理员，且当前防火墙整体关闭）** |

---

## 4. 证书方案（mkcert 本地 CA + IP SAN）

### 4.1 前置

| 项 | 要求 |
|---|---|
| 权限 | 管理员 PowerShell（`mkcert -install`、防火墙规则需要） |
| 主机 IP | `192.168.31.68`，在路由器做 **DHCP 保留**或设静态；变更后证书需重签 |
| 工具 | mkcert 1.4.4：已下载到 `D:\FishAgent\tools\mkcert\mkcert.exe`，SHA-256 `d2660b50a9ed59eada480750561c96abc2ed4c9a38c6a24d93e30e0977631398`（与官方 release 一致）。winget 直连 GitHub 失败时可经本机代理下载 |
| 端口 | 8020 空闲；被占用时改用其他端口（证书不含端口，无需重签） |

### 4.2 生成 CA 与证书

```powershell
# 0) 使用已下载的 mkcert（不在 PATH 时用绝对路径）
$mkcert = "D:\FishAgent\tools\mkcert\mkcert.exe"

# 1) 安装本地 CA 到 Windows 信任库（管理员；会创建/复用一个 mkcert CA）
& $mkcert -install
& $mkcert -CAROOT          # 记下 CA 目录，rootCA.pem 在这里

# 2) 为局域网 IP 签发带 IP SAN 的服务器证书
$dir = "D:\FishAgent\certs"
New-Item -ItemType Directory -Force $dir | Out-Null
& $mkcert -cert-file "$dir\fishagent-lan.pem" -key-file "$dir\fishagent-lan-key.pem" `
  192.168.31.68 localhost 127.0.0.1

# 3) 确认 SAN 与 EKU（openssl 不在 PATH 时用 Git 自带的）
openssl x509 -in "$dir\fishagent-lan.pem" -noout -text |
  Select-String -Pattern "Subject Alternative Name|TLS Web Server Authentication"

# 4) 记录 SAN、有效期与叶证书 SHA-256 指纹（写入部署记录；不含私钥）
openssl x509 -in "$dir\fishagent-lan.pem" -noout -subject -dates -fingerprint -sha256
```

预期 SAN 含 `IP Address:192.168.31.68`、`IP Address:127.0.0.1`、`DNS:localhost`；EKU 含 `TLS Web Server Authentication`。

> mkcert 会复用已存在的本地 CA。如果本机此前为其他项目装过 mkcert CA，新证书会由同一个 CA 签发，手机装一次即可。`mkcert -uninstall` 会影响该 CA 签发的所有开发证书，**仅在确认无其他项目依赖后执行**。

> **本轮执行结果（2026-10-24）**：CA 已创建于 `C:\Users\koubinbin\AppData\Local\mkcert`，服务器证书已签发到 `D:\FishAgent\certs`（SAN、有效期、指纹见 §6.1）。`mkcert -install` 在本机非交互会话卡在证书安装确认（UAC/安全警告无法自动点击），**CA 未写入 Windows 信任库**；桌面 Chrome 自测改用 SPKI 精确放行。管理员补做命令见 §6.2。

### 4.3 证书存放与权限（不入 Git）

- 存放目录固定在**仓库之外**：`D:\FishAgent\certs\`。
- 仓库内任何位置都不得出现 `*.pem`、`*.key`、`rootCA*`；如临时放入仓库，必须先确认 `.gitignore` 生效，且用完删除。
- 私钥 ACL 仅运行账号与管理员（本轮已执行并核对；`fishagent` 服务账号尚未创建，暂用当前用户）：

```powershell
icacls "D:\FishAgent\certs" /inheritance:r /grant:r "koubinbin:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)" "*S-1-5-18:(OI)(CI)(F)"
# 结果：DESKTOP-9JIRF04\koubinbin / BUILTIN\Administrators / NT AUTHORITY\SYSTEM，继承已移除
```

- CA 私钥 `rootCA-key.pem` 位于 `C:\Users\koubinbin\AppData\Local\mkcert`（用户配置目录，默认仅该用户与管理员可读）。

- **只把 `rootCA.pem` 拷到手机；`rootCA-key.pem` 和服务器私钥永远不离开主机。**
- CA 私钥泄露 = 可伪造任意 HTTPS 站点，必须立即删除 CA、重装并重签。

### 4.4 给人类：手机安装 CA（照做即可）

**你只需要一个文件：`rootCA.crt`（由技术侧提供）。不要接收或安装任何 `.key` 文件、隧道令牌、邀请码或 API Key。**

建议先在手机上打开 `https://192.168.31.68:8020/health`：能看到 `{"status":"ok",...}` 即说明网络与证书文件没问题；若提示证书不受信任，继续下面步骤。

**iOS（Safari）**

1. 把 `rootCA.pem` 改名为 `rootCA.crt`，通过 AirDrop / 文件 / 邮件传到 iPhone 并点开。
2. 设置 → 通用 → VPN 与设备管理 → 已下载的描述文件 → 安装（需输入锁屏密码）。
3. **关键一步**：设置 → 通用 → 关于本机 → **证书信任设置** → 打开该 CA 的「启用完全信任」。
4. 验证：Safari 打开 `https://192.168.31.68:8020/health`，应显示 JSON 且**无证书警告**。

> 仅安装描述文件而不开「完全信任」，Safari 仍会报不受信任，SW 不会注册。

**Android（Chrome）**

1. 把 `rootCA.pem`（或 `rootCA.crt`）传到手机存储。
2. 设置 → 安全 → 加密与凭据 → 安装证书 → **CA 证书** → 仍然安装（不同厂商路径略有差异；Android 11+ 必须从设置进入，不能从浏览器直接安装）。
3. 验证：Chrome 打开 `https://192.168.31.68:8020/health`，应显示 JSON 且无「您的连接不是私密连接」。
4. 说明：用户安装的 CA 会被 **Chrome 浏览器**信任；部分 App 默认不信任用户 CA（与本试点无关，我们用浏览器/PWA）。

**若手机拒绝或无法安装 CA**：内网只能退化为「桌面 Chrome 同机验证」（`https://localhost:8020`），无法验证真机安装；替代方案是临时公网 HTTPS 隧道，**需人类单独授权**，不在本 Runbook 范围。

### 4.5 有效期与轮换

- mkcert 服务器证书默认有效期约 2 年 3 个月；iOS 的 398 天限制不适用于**用户手动安装的根 CA**，但若设备仍拒绝，优先检查「完全信任」是否开启。
- **IP 变化、证书过期、私钥疑似泄露**时：只需重签服务器证书（CA 不变，手机无需重装）；私钥泄露则连同 CA 一起重建。

---

## 5. 8020 HTTPS 启动

> **2026-10-30 更新：8018 已直接改为 HTTPS，8020 不再是必需品。**
>
> 原方案用 8020 作独立 HTTPS 实例、8018 保持明文，是为了「不动 S1」。但实践下来
> 明文 8018 在真机上**永久失去定位**：`navigator.geolocation` 只在安全上下文存在，
> 而 http 局域网地址下浏览器把「不提供定位」报成 `PERMISSION_DENIED`，看起来像权限
> 问题，实际是协议问题（详见 `api-contract.md` 4.5b 与 v2.6b）。
>
> 现在 8018 本身加载同一份证书（SAN 覆盖 `localhost` / `127.0.0.1` / `192.168.31.68`），
> 用仓库根的 `serve-https.bat` 启动：
>
> ```
> serve-https.bat          REM 默认 8018
> serve-https.bat 8020     REM 换端口
> ```
>
> 脚本会先校验解释器与证书文件是否存在再启动，缺证书时报错指向本 runbook。
> **明文 `http://<IP>:8018` 已不可用**（同一端口只提供 TLS）；同机调试请用
> `https://127.0.0.1:8018` 或 `https://localhost:8018`。
>
> ### 开机自启（启动文件夹方案）
>
> `scripts/start-fishagent.vbs` 启动服务且**不留控制台窗口**，它被复制到启动文件夹：
> `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\FishAgent.vbs`。
>
> - 用 `pythonw`/`.bat` 直接放启动项会常驻一个命令行窗口；`.vbs` 以隐藏方式拉起，登录不受阻。
> - **已占用 8018 时自动跳过**，不会每次登录都写一条端口占用错误。
> - 输出追加到 `D:\FishAgent\logs\uvicorn-8018.log`；启动失败可在此查因。
> - 仓库路径含中文，而 **cscript 按系统 ANSI 代码页读取 `.vbs`**：脚本本身必须保持**纯 ASCII**，
>   路径因此不在脚本里硬编码，而是按序解析：① 脚本上一级（在 `scripts\` 下时有效）；
>   ② `D:\FishAgent\repo-root.txt`（UTF-16，启动文件夹场景用这条）；③ `%FISHAGENT_ROOT%`。
>   **仓库搬家后必须更新 `repo-root.txt`**，否则启动项会失败并把原因写进日志。
> - 换端口时 VBS 里的 `Const PORT` 与 `serve-https.bat` 的端口需一起改。
>
> 8020 仍可用于「Mock 模式 + 不消耗上游」的真机安装验证，按 §5.1 单独启动即可；
> 两者不能同时占用同一端口。以下 §5.1 原始命令保留，用于 8020。

### 5.1 启动参数

```powershell
cd D:\学习\GitHubCode\FishAgent\backend
$env:FISHAGENT_MOCK_MODE = "true"                  # 真机安装验证用 Mock，不消耗上游
$env:FISHAGENT_PUBLIC_ACCESS_ENABLED = "false"     # 与 8018 一致，本阶段不开访问控制
$env:FISHAGENT_PILOT_TRUST_PROXY_HEADERS = "false" # 无反向代理

C:\Users\koubinbin\AppData\Local\Programs\Python\Python312\python.exe -m uvicorn fishagent.main:app `
  --host 0.0.0.0 --port 8020 --workers 1 --no-access-log `
  --ssl-certfile D:\FishAgent\certs\fishagent-lan.pem `
  --ssl-keyfile D:\FishAgent\certs\fishagent-lan-key.pem
```

> 本机没有 `backend\.venv`，8020 与 8018 使用同一个系统 Python 3.12 解释器（8018 命令行可核对）。本轮以 `nohup` 后台启动，日志写 `D:\FishAgent\logs\uvicorn-8020.log`；**未注册 NSSM/系统服务**，主机重启后需手动重新启动。

| 参数 | 作用 |
|---|---|
| `--host 0.0.0.0` | 允许局域网设备连接；**必须**配合 §5.2 防火墙限制到本子网 |
| `--port 8020` | 独立实例，不触碰 8018 |
| `--workers 1` | 配额/限流计数在进程内；多 worker 会各算各的 |
| `--no-access-log` | 不记录客户端 IP 与逐请求访问行 |
| `--ssl-certfile/--ssl-keyfile` | 启用 HTTPS；证书必须含 `192.168.31.68` 的 IP SAN |
| `--proxy-headers` | **不需要**（无反向代理；本阶段不加） |

> 环境变量优先于 `backend/.env`。若 `.env` 已启用访问控制或配置了真实 Key，上面的显式赋值可保证 8020 以 Mock + 无鉴权启动；**不要读取或回显 `.env` 内容**。
> 若主机 IP 固定且不希望监听全部网卡，可改用 `--host 192.168.31.68`；此时本机 `127.0.0.1` 不可用，验证请走局域网 IP。

### 5.2 防火墙（仅本子网）

```powershell
# 确认网络为专用
Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory

# 只放行本子网的 8020/TCP
New-NetFirewallRule -DisplayName "FishAgent PWA 8020 (LAN only)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8020 `
  -Profile Private -RemoteAddress LocalSubnet
```

- **不要**为公网/公用配置文件放行；**不要**在路由器做端口映射或开启 UPnP。
- 如误放行，删除规则：`Remove-NetFirewallRule -DisplayName "FishAgent PWA 8020 (LAN only)"`。

> **本轮执行结果（2026-10-24）**：规则**未能创建**——`New-NetFirewallRule` 返回「拒绝访问」，需管理员；非交互会话无法完成 UAC 确认。同时本机 `Get-NetFirewallProfile` 显示 Domain/Private/Public 三个配置文件的 `Enabled` 均为 **False**（Windows 防火墙整体关闭）。因此当前 8020 在局域网可达，但**没有按子网限制的入站规则**。补做命令与安全提示见 §6.2。

### 5.3 主机验证

```powershell
# CA 尚未进入 Windows 信任库，curl 用 --cacert 显式校验（等价于信任后访问）
$root = "C:\Users\koubinbin\AppData\Local\mkcert\rootCA.pem"
curl.exe --cacert $root -s -o NUL -w "%{http_code}`n" "https://192.168.31.68:8020/health"   # 200
curl.exe --cacert $root -s -o NUL -w "%{http_code}`n" "https://127.0.0.1:8020/health"       # 200

# 监听地址：应为 0.0.0.0:8020，且 8018 仍为原 PID
Get-NetTCPConnection -LocalPort 8020,8018 -State Listen |
  Select-Object LocalAddress,LocalPort,OwningProcess

# 证书链（openssl 不在 PATH 时用 C:\Program Files\Git\usr\bin\openssl.exe）
echo | openssl s_client -connect 192.168.31.68:8020 -servername 192.168.31.68 -CAfile $root 2>$null |
  Select-String "Verify return code"
```

预期：两次 `200`；监听为 `0.0.0.0:8020`；`Verify return code: 0 (ok)`；8018 的 PID 不变。CA 写入信任库后，桌面浏览器可直接打开同一地址（无警告）。

---

## 6. 执行记录与自测证据（2026-10-24）

### 6.1 已执行

| 项 | 实际值 |
|---|---|
| 主机与网络 | `192.168.31.68/24`，网络配置文件 Private（执行前核对） |
| mkcert | `D:\FishAgent\tools\mkcert\mkcert.exe`，`v1.4.4`，SHA-256 `d2660b50a9ed59eada480750561c96abc2ed4c9a38c6a24d93e30e0977631398` |
| CA 目录（CAROOT） | `C:\Users\koubinbin\AppData\Local\mkcert`；`rootCA.pem` 有效期 2026-10-24 → 2036-10-24 |
| CA SHA-256 | `1E:4E:A3:D0:CC:A6:E6:A2:6C:18:18:D3:67:FA:5E:3F:5E:3E:F9:CF:28:1F:8D:89:AF:65:18:3B:B7:77:EC:E0` |
| 服务器证书 | `D:\FishAgent\certs\fishagent-lan.pem`；SAN `DNS:localhost, IP:192.168.31.68, IP:127.0.0.1`；EKU `TLS Web Server Authentication`；有效期 2026-10-24 → **2029-01-24** |
| 叶证书 SHA-256 | `1A:B6:D5:DC:FB:CA:35:0D:C7:45:72:12:BA:59:91:3E:0B:0C:5B:68:B9:3D:FD:32:6B:71:8A:28:FE:52:73:14` |
| 私钥 | `D:\FishAgent\certs\fishagent-lan-key.pem`（仅在主机；ACL 已收紧；不入 Git、不进群） |
| 8020 实例 | `0.0.0.0:8020`，PID **75304**，`--workers 1 --no-access-log`，Mock 开、访问控制关、`TRUST_PROXY_HEADERS=false`；日志 `D:\FishAgent\logs\uvicorn-8020.log`；**未注册服务**，重启后需手动拉起 |
| 8018 隔离 | 仍为 `0.0.0.0:8018`、PID **70828**，未重启、未改配置 |

| 检查 | 方法 | 结果 |
|---|---|---|
| 双地址健康检查 | `curl --cacert rootCA.pem` 访问 `https://127.0.0.1:8020/health`、`https://192.168.31.68:8020/health` | 均 200 `{"status":"ok","version":"0.1.0","mock_mode":true}` |
| 证书链与 IP SAN | `openssl s_client -connect 192.168.31.68:8020 -servername 192.168.31.68 -CAfile rootCA.pem` | `Verify return code: 0 (ok)`；SAN 精确含 `192.168.31.68` |
| `/` | `curl -D -` | 200 `text/html; charset=utf-8` |
| `/manifest.webmanifest` | 同上 | 200 `application/manifest+json` |
| `/sw.js` | 同上 | 200 `application/javascript` |
| `/icons/icon-192.png` | 同上 | 200 `image/png` |
| Mock API | `GET /api/fish-activity?lat=30.2&lon=120.1` | 200，返回评分 JSON |
| **安全上下文与 SW 注册** | Playwright 驱动本机 Chrome 打开 `https://192.168.31.68:8020/` | `isSecureContext=true`；SW `activated`，scope `https://192.168.31.68:8020/`，`controller=https://192.168.31.68:8020/sw.js`；`caches.keys()` = `["fishagent-v2-static"]` |
| **离线壳** | SW 接管后断网重载 | 命中缓存壳，显示「当前离线…恢复网络后自动继续」；API 返回 503 离线提示，**不显示假数据** |
| **安全响应头** | `curl -D -` 抓 `/`、`/sw.js`、`/manifest`、`/api/*` | 仅 `server: uvicorn` 与常规内容头；**无 CSP/HSTS/X-Content-Type-Options/X-Frame-Options**（说明见下） |
| 访问日志 | 多次请求后查 `uvicorn-8020.log` | 仅 4 行启动日志，`HTTP/1.1` 访问行 **0** |
| 防火墙规则 | `New-NetFirewallRule ...` | **未创建**——「拒绝访问」，需管理员（见 §6.2） |

**SW 自测条件说明**：CA 未写入 Windows 信任库，测试用 Chrome `--ignore-certificate-errors-spki-list=<叶证书 SPKI>` **仅放行本证书**（未全局关闭证书校验）；页面仍判定为安全上下文并成功注册 SW。真机安装 CA 后属于正常受信任证书，条件只会更宽松；仍以真机复核为准。

**安全头说明**：当前 H5 壳与 API 未返回 CSP/HSTS/XCTO/XFO。HSTS 对 IP 源站无实际意义（浏览器按 IP 访问时通常忽略），CSP 需结合现有内联样式/脚本评估，均不属于"能否安装"的前提；本阶段不改共用 `web/**`，公网 B 阶段再由小厚/小项决定是否加边缘或应用层安全头。访问控制开启时，登录页自带 CSP/XFO/no-store（见 `pilot/login_page.py`），本阶段未启用。

**尚未验证（需人类装 CA + 真机）**：手机信任 CA、Safari/Chrome 无警告、安装入口、standalone、真机 SW 接管、离线提示、定位授权/拒绝、高德唤起。这些计入 D 组内网子集，实测前不判 PASS。

### 6.2 两项待管理员补做（阻塞项，非代码问题）

**A. 把 CA 写入 Windows 信任库**（只影响桌面 Chrome/Edge；手机各自安装 `rootCA.pem`，不依赖此项）

在**管理员 PowerShell** 中执行一次，出现确认框时点「是」：

```powershell
& "D:\FishAgent\tools\mkcert\mkcert.exe" -install
& "D:\FishAgent\tools\mkcert\mkcert.exe" -CAROOT

# 验证：应能在信任库看到该 CA（指纹 1E4EA3D0...）
Get-ChildItem Cert:\CurrentUser\Root, Cert:\LocalMachine\Root |
  Where-Object { $_.Subject -like '*mkcert development CA*' } |
  Select-Object Subject, NotAfter, Thumbprint
```

**B. 新增 8020 防火墙规则（仅 Private + LocalSubnet）**，并确认防火墙状态

```powershell
# 1) 建规则
New-NetFirewallRule -DisplayName "FishAgent PWA 8020 (LAN only)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8020 `
  -Profile Private -RemoteAddress LocalSubnet

# 2) 核对（本机当前三个配置文件均为 Enabled=False，需人类决定是否开启 Private）
Get-NetFirewallProfile | Select-Object Name, Enabled
Get-NetFirewallRule -DisplayName "FishAgent PWA 8020 (LAN only)" |
  Select-Object DisplayName, Enabled, Direction, Action, Profile
```

> 当前 Windows 防火墙整体关闭，8020 对能路由到 `192.168.31.68` 的设备（同网段/VMware 主机网络）可达；**没有端口映射、没有隧道，不对公网暴露**。建议建规则后至少开启 Private 配置文件；是否开启 Domain/Public 需结合主机用途单独评估。**在规则与防火墙状态确认前，不要把该主机当作"已隔离"环境。**

**给人类/小项的交付物**：只需把 `C:\Users\koubinbin\AppData\Local\mkcert\rootCA.pem` 改名为 `rootCA.crt` 传到手机（§4.4）。**不要传 `rootCA-key.pem` 或服务器私钥。**

---

## 7. 真机验收步骤（安装 CA 后执行）

### 7.1 安装与安全上下文

| 检查 | iOS | Android |
|---|---|---|
| 打开 `https://192.168.31.68:8020/health` | Safari 显示 JSON，无警告 | Chrome 显示 JSON，无警告 |
| 安全上下文 | 地址栏锁形图标正常 | 地址栏锁形图标正常 |
| Service Worker | 控制台 `navigator.serviceWorker.controller` 非空 | 同左 |

### 7.2 安装与 standalone

| 检查 | 期望 |
|---|---|
| iOS 安装 | 分享 → 添加到主屏幕 → 图标出现在桌面 → 从图标启动为独立窗口（无 Safari 工具栏） |
| Android 安装 | Chrome 菜单出现「安装应用/添加到主屏幕」，或页面内安装提示；安装后从桌面图标启动 |
| manifest | `start_url`/`scope` 为 `/`；图标 192/512 与 maskable 均加载成功；`display: standalone` 生效 |
| SW 缓存 | 控制台 `caches.keys()` 含 `fishagent-v2-static` |
| 离线 | 开飞行模式后冷启动，显示壳与离线提示，**不显示假数据**；恢复网络后可继续取数 |
| 更新 | 改动静态资源后提升 `CACHE_VERSION`，关闭所有旧页再启动，确认新缓存接管 |

### 7.3 定位与高德

| 检查 | 期望 |
|---|---|
| 定位授权 | 首次请求系统弹窗；允许后能取到坐标并完成分析 |
| 定位拒绝 | 拒绝后页面给出明确提示并可手动输入坐标，不白屏 |
| 高德唤起 | standalone 下点击导航能调起高德 App；未安装时回退网页/提示，不报错 |

### 7.4 不在本轮验证（需公网）

邀请码登录、401→登录页→回跳、Cookie `Secure` 真实域名、429 限流与 `Retry-After`、Cloudflare 缓存/WAF、源站 100s/524、主机离线 502/1033/530、公网真实 IP 分桶（RD-55）。

---

## 8. 常见失败与回退

| 现象 | 排查 | 处理 |
|---|---|---|
| 手机提示证书不受信任 | 只装了描述文件未开完全信任；装错 CA（不是 mkcert 的 rootCA） | iOS 开「完全信任」；Android 重装为用户 CA；核对 `mkcert -CAROOT` 下的 `rootCA.pem` |
| 页面能开但 SW 不注册 | 证书仍不被信任；访问了 `http://`；浏览器缓存旧状态 | 确认锁图标正常；强制关闭浏览器重开；清站点数据 |
| Android 无安装入口 | SW 无 fetch 处理、manifest 不合规、非 HTTPS、Chrome 尚未判定可安装 | 检查 `/sw.js` 200 且 MIME 为 JS；manifest 字段与图标；确认锁图标；刷新并停留片刻后从菜单选「安装应用/添加到主屏幕」 |
| 手机打不开 8020 | 不同子网、访客网络、AP 隔离、防火墙阻止 | 关闭 AP 隔离；`Test-NetConnection 192.168.31.68 -Port 8020`；检查防火墙规则仅 Private/LocalSubnet |
| 桌面浏览器提示证书不受信任 | CA 未写入 Windows 信任库（§6.2A 未执行） | 管理员执行 `mkcert -install`；在此之前用 `curl --cacert` 或 SPKI 放行验证 |
| 8020 对同网段设备可达但规则不存在 | 防火墙规则未创建 / 防火墙整体关闭 | 按 §6.2B 建规则并开启 Private；确认无端口映射/UPnP |
| 主机 IP 变了 | 证书 SAN 不含新 IP | 重新签发服务器证书；在路由器做 DHCP 保留避免复发 |
| 8020 被占用 | 其他进程监听 | `Get-NetTCPConnection -LocalPort 8020`；换端口启动（证书无需重签） |
| mkcert CA 与其他开发证书冲突 | 复用了同一 CA | 记录影响范围；如必须隔离，另建专用 CA（不影响本轮流程） |

**回退（停止试点）**

```powershell
# 1) 停止 8020 实例（若是 NSSM 托管则 nssm stop <服务名>）
Get-NetTCPConnection -LocalPort 8020 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess }

# 2) 删除仅本试点新增的防火墙规则
Remove-NetFirewallRule -DisplayName "FishAgent PWA 8020 (LAN only)"

# 3) 可选：移除本地 CA（会影响该 CA 签发的其他开发证书，确认后再执行）
# mkcert -uninstall

# 4) 删除证书目录（含私钥）
Remove-Item -Recurse -Force "D:\FishAgent\certs"
```

8018/S1 全程不受影响；无需回滚任何 8018 配置。

---

## 9. 安全要求与残余风险

| 项 | 要求 / 说明 |
|---|---|
| 本地 CA | 等同信任锚：CA 私钥只留主机；手机只装 `rootCA.pem`；试点结束按 §8 移除 |
| 证书与私钥 | 放仓库外 `D:\FishAgent\certs`；ACL 已限 `koubinbin`/Administrators/SYSTEM；不进 Git、不进群、不进文档 |
| 局域网暴露 | 8020 无鉴权（与 8018 一致），同网段设备均可访问并消耗上游配额；Mock 模式无上游成本 |
| 防火墙 | 目标：仅 `Private` + `LocalSubnet`。**当前状态：规则未建、三个配置文件均关闭**；在补做 §6.2B 前，8020 对所有可路由到主机的设备可达（仍无端口映射/隧道/公网暴露） |
| 日志 | `--no-access-log`；应用日志不含 IP、令牌、邀请码、Key |
| 主机 | 服务账号低权限；`backend/.env` ACL；不在主机上浏览无关内容 |
| 残余风险 | 同网段恶意设备可调用 API；用户 CA 被信任期间可被用于伪造其他站点（仅该手机）；IP 变化导致证书失效；**CA 未入 Windows 信任库**（桌面浏览器会告警）；**防火墙关闭且规则未建**（暴露面大于设计目标）；8020 为手动进程，主机重启/注销后不会自启 |

---

## 10. 需要人类提供 / 操作

| # | 事项 | 状态 / 说明 |
|---|---|---|
| 1 | 把 `rootCA.pem` 传到手机并安装（iOS 描述文件 + 完全信任；Android 用户 CA） | **待人类**；文件来自 `C:\Users\koubinbin\AppData\Local\mkcert\rootCA.pem`，步骤见 §4.4 |
| 2 | 固定主机 IP `192.168.31.68` | **待人类**；路由器 DHCP 保留或静态 |
| 3 | 管理员执行 `mkcert -install`（桌面信任库，一次确认） | **待补做**，命令见 §6.2A；不影响手机安装 |
| 4 | 管理员新增 8020 防火墙规则并决定是否开启 Private 配置文件 | **待补做**，命令见 §6.2B；当前防火墙关闭 |
| 5 | 告知设备型号与系统版本 | **待人类**；用于 D 组证据与兼容性判断 |
| 6 | 确认试点网络无 AP 隔离 | **待人类**；手机与主机同一 Wi-Fi 可互访 |

---

## 11. 状态与边界

- **已执行**：mkcert 安装与校验、正式 CA/服务器证书签发、`D:\FishAgent\certs` ACL、8020 HTTPS 常驻（PID 75304）、主机自测（§6.1）。
- **未执行 / 待补**：CA 写入 Windows 信任库（§6.2A）、8020 防火墙规则（§6.2B）、手机端安装、standalone/定位/高德真机验证。
- **未做**：未改 8018、未重启 8018、未注册系统服务、未改路由器/DNS、未建隧道、未做端口映射、未发布、未提交 Git。
- 8020 为手动后台进程：主机重启、注销或进程被杀后需按 §5.1 重新启动；重启后先用 §5.3 复核。
- 公网 B 方案（Cloudflare Tunnel）仍按 `docs/cr03-deployment-plan.md` 执行，需域名/账号/主机/授权到位后另开。
