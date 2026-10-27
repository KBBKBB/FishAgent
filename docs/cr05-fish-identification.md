# CR-05 图片识别鱼种 — 实现契约（v1.0，2026-10-27）

> 本文件是 CR-05 并行开发的唯一依据。改动契约须先改本文件。

## 1. 功能范围

Agent 板块新增「拍照/上传图片识别鱼种」。

- 网页端：上传图片（文件选择）
- 移动端：上传图片 + 调用摄像头拍照
- 识别结果包含：鱼种名、置信度、简要鱼类知识、钓饵推荐、注意事项
- 输出必须标注「AI 生成 · 仅供参考」，不承诺渔获

**不做**：识别结果的用户历史存储、图片持久化、鱼种图鉴库。

## 2. 接口

### `POST /api/agent/identify-fish`

`Content-Type: multipart/form-data`

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `image` | file | 是 | ≤ `FISHAGENT_IDENTIFY_MAX_UPLOAD_BYTES`（默认 8 MiB）；真实图片，非仅靠扩展名 |
| `note` | text | 否 | ≤ 100 字符，用户补充说明（如「这条是今早在水库钓的」） |

成功 200：

```json
{
  "identified": true,
  "species": "鲫鱼",
  "raw_species": "鲫鱼",
  "in_catalog": true,
  "confidence": "high",
  "summary": "鲫鱼是常见的淡水底层鱼，适应力强。",
  "habits": "喜栖水底，偏爱安静、有水草或缓流的环境。",
  "baits": ["蚯蚓", "红虫", "商品饵（腥香）"],
  "tips": "钓底为主，注意避开高温正午。",
  "caveats": "仅根据单张照片判断，角度与光线可能影响结果。",
  "mode": "llm",
  "ai_disclosure": "本内容由 AI 生成，仅供参考，不承诺渔获。",
  "generated_at": "2026-10-27T10:00:00Z"
}
```

未识别出鱼（正常 200，非错误）：

```json
{
  "identified": false,
  "species": null,
  "raw_species": null,
  "in_catalog": false,
  "confidence": null,
  "summary": null,
  "habits": null,
  "baits": [],
  "tips": null,
  "caveats": null,
  "mode": "llm",
  "ai_disclosure": "本内容由 AI 生成，仅供参考，不承诺渔获。",
  "generated_at": "2026-10-27T10:00:00Z",
  "message": "未能识别出鱼的种类，请换一张更清晰的照片（建议鱼体完整、光线充足）。"
}
```

字段口径：

- `species`：经 `core.species.normalize_species` 归一后的名称；不在 `KNOWN_SPECIES` 时保留模型原始答案，`in_catalog=false`。
  - **实测陷阱**：模型在 `identified=false` 时仍会把 `species` 填成「无法识别」「不确定」「未知」这类占位文本。当 `identified=false` 时 `species` 与 `raw_species` 必须一律置 `null`，绝不能把占位词当鱼种名返回给前端。
- `raw_species`：模型原始输出，便于排查。
- `confidence`：`high` / `medium` / `low` / `null`。
- `baits`：0–4 项，去空去重，每项 ≤ 20 字符。
- `mode`：`llm` 或 `mock`。
- 其它文本字段：≤ 200 字符；不可为承诺性表述（沿用 `violates_guardrails` 检查，命中则整体降级为未识别）。
- 响应**不含**图片本身、不含图片 URL、不含任何用户标识。

### 错误

| 状态 | code | 触发 |
|---|---|---|
| 413 | `PAYLOAD_TOO_LARGE` | 上传字节数超过上限 |
| 413 | `IMAGE_TOO_LARGE` | 分辨率超过 8000 万像素（格式受支持，只是太大）；`message` 带具体尺寸 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | 非图片 / 无法解码 / 不支持的格式 |
| 422 | `VALIDATION_ERROR` | 缺 `image` 字段、`note` 超长 |
| 429 | `QUOTA_EXCEEDED` | 每日 LLM 配额耗尽（带 `Retry-After`） |
| 503 | `PROVIDER_NOT_CONFIGURED` | 真实模式未配置 `LLM_API_KEY` |

错误体沿用统一结构 `{"detail": {"code", "message"}}`。

**配额口径**：与聊天一致，按用户主动动作处理，配额耗尽返回 429（不像鱼种列表需要降级，因为这里没有可降级的部分结果）。

配额扣减只在**一处**发生，避免重复计数：`api/identify.py` 在真实模式调用视觉模型前，若 `get_pilot_state()` 非 `None`，调用 `ledger.consume("llm")`，每次请求扣 1 个单位。`UpstreamQuotaExceeded` 直接抛出，由 `main.py` 已注册的 `quota_exceeded_handler` 转成 429 + `Retry-After`；**不要**在路由里自己拼 429 响应。`get_pilot_state()` 为 `None`（未开启试点访问控制）时不做配额控制。`pilot/middleware.py` 中针对 `/api/agent/chat` 的既有预留逻辑保持不变，本功能不修改中间件。

## 3. 图片处理（`core/image_guard.py`）

1. 读入上限 `max_upload_bytes`，超限直接 413（读取时即截断，不整体载入内存）。
2. 用 Pillow 实际解码校验，不信任 `Content-Type` 与扩展名：
   - 仅接受 JPEG / PNG / WEBP / GIF / HEIF / AVIF。其中 HEIF（即 iPhone 的 HEIC）与 AVIF 由 `pillow-heif` 提供解码能力——Safari 在上传时不保证转码，从「文件」App 选取的照片可能原样送达，因此必须由服务端直接支持。
   - 设置 `Image.MAX_IMAGE_PIXELS = 80_000_000` 防解压炸弹，超限返回 **413 `IMAGE_TOO_LARGE`（不是 415）**，`message` 带具体尺寸
   - **注意**：Pillow 在超过上限 2 倍时才抛 `DecompressionBombError`，1–2 倍之间只发 `DecompressionBombWarning`。因此必须把 warning 转异常（`warnings.simplefilter("error", Image.DecompressionBombWarning)` 或显式比对 `width*height`），不能只依赖硬错误。
   - **上限教训（2026-10-27 实故障）**：上限原为 4000 万像素，导致 iPhone Pro 的 48MP 照片（8064×6048 = 4880 万像素）被直接拒掉，全景照片（10800×4000）同样。iPhone 各档位实测：12MP / 24MP / 48MP 分别是 1220 万 / 2447 万 / 4877 万像素。现调到 8000 万像素，覆盖到 48MP 与全景仍有余量。
   - **内存代价（全分辨率解码，`draft()` 对 HEIF 无效）**：12MP≈91 MB、24MP≈179 MB、48MP≈356 MB、72MP≈524 MB 峰值 RSS。上限同时也是内存边界，调整前须重测。
   - **解码并发按内存计费，而不是固定槽位数**：实测峰值 RSS 约 **7.5 字节/像素**（12MP≈91 MB、24MP≈179 MB、48MP≈356 MB、72MP≈524 MB），接近线性，因此单张代价可由文件头预估。`prepare_image` 先花 ~0.1 ms 只读文件头拿尺寸（不做像素解码），再按预估 MB 向解码预算（默认 1024 MB）申请配额，同时受并发数上限（默认 4）约束——后者独立存在，因为解码是 CPU 密集的（48 MP 单核约 1 s），只按内存放行会让大量小图压垮 CPU。
   - 小图因此可以多张并行（4 张 12MP ≈ 364 MB 同时进行），大图按预算排队。预算 1536 MB 是刻意选的：4 个槽位 × 366 MB（48MP）≈ 1464 MB，1024 MB 预算装不下，会让 4 个槽位里有一半对大图永久闲置。
   - 读取与头部探测都在准入之外，排队中的请求只占自身字节数。
   - 死锁规避：先取并发槽位，再申请内存配额。持有内存配额的请求绝不会回头等并发槽位，因此不构成环。
   - 信号量按 event loop 惰性创建：`asyncio.Semaphore` 会绑定首次等待它的 loop，全局单例在第二个 loop（每个 `asyncio.run` 都是一个）上会抛 `bound to a different event loop`。
   - **不要把分辨率超限混同为格式不支持**：两者用户处置完全不同（前者缩小图片，后者换格式）。历史上二者都返回 415，前端因而统一显示「不支持的图片格式」，把真实原因掩盖掉了。
   - 拒绝时按原因记 `logger.info`（格式名 / 尺寸 / 异常类型），**绝不记录图片内容或 base64**。
3. 最长边缩放到 `max_side`（默认 1280），转 RGB，重新编码 JPEG quality=85。
4. **重新编码后不写回 EXIF**（手机照片含 GPS 坐标，必须丢弃）。实测：`img.convert("RGB").save(buf, "JPEG", quality=85)` 不带 `exif=` 参数时，输出 EXIF 为空字典，GPS 一并消失。
5. 返回 `(jpeg_bytes, "image/jpeg")`，**不落盘、不缓存**。

实测参考（本机）：4000×3000 手机照片缩放至 1280×960 后约 33 KB，base64 约 42 KB，prompt_tokens 约 761。

## 4. 模型调用（`providers/vision_fish.py`）

- 复用 OpenAI 兼容客户端；模型取 `settings.vision_model`，为空时回落 `settings.llm_model`。
- 请求 messages：system（识别指令 + 严格 JSON schema）+ user（`image_url` data-URI + 可选 note 文本）。
- `max_tokens` 800，`temperature` 0.2。
- 解析：容忍 ``` 代码围栏，取首个 `{` 到末个 `}`。
- **陷阱**：该端点可能返回空 `content` 而只给 `reasoning_content`。`content` 为空一律视为失败，不得把 `reasoning_content` 当答案。
- 任何异常、超时、JSON 失败 → 返回 `None`，由上层转成「未识别」，不得 5xx。

System prompt 要求模型输出：

```json
{"identified":true,"species":"鲫鱼","confidence":"high","summary":"…","habits":"…","baits":["蚯蚓"],"tips":"…","caveats":"…"}
```

约束写入 prompt：不确定就 `identified:false`；不得编造；不承诺渔获。

## 5. 配置项（`config.py`）

| 变量 | 默认 | 约束 |
|---|---|---|
| `LLM_VISION_MODEL` | `""`（回落 `LLM_MODEL`） | — |
| `FISHAGENT_IDENTIFY_MAX_UPLOAD_BYTES` | `8388608` | 64 KiB–20 MiB |
| `FISHAGENT_IDENTIFY_MAX_SIDE` | `1280` | 256–2048 |
| `FISHAGENT_IDENTIFY_TIMEOUT_SECONDS` | `60.0` | 5–180 |
| `FISHAGENT_IDENTIFY_DECODE_MEMORY_BUDGET_MB` | `1536` | 256–8192 |
| `FISHAGENT_IDENTIFY_MAX_CONCURRENT_DECODES` | `4` | 1–8 |

## 6. 前端（`web/`）

- 聊天输入区左侧新增两个图标按钮：
  - 「上传图片」：`<input type="file" accept="image/*">`（始终显示）
  - 「拍照」：`<input type="file" accept="image/*" capture="environment">`（仅在触摸设备 `(pointer: coarse)` 显示）
- 选中后先在对话流里渲染用户消息：缩略图 + 「识别这张图片」文案；按钮进入 loading 并禁用。
- 结果卡片（在对话流内，`msg-assistant`）：
  - 鱼种名 + 置信度徽标（high 绿 / medium 黄 / low 灰）
  - 「AI 生成 · 仅供参考」徽标
  - 简要知识、习性、钓饵（chips）、提示、注意事项
  - 未收录鱼种（`in_catalog=false`）追加提示「该鱼种未在我们的常见列表中，信息仅供参考」
  - 未识别时显示服务端 `message`
- 前端必须在 `URL.revokeObjectURL` 释放预览，不得把图片转 base64 存进 `state`。
- 错误映射：413 → 按 `code` 区分——`IMAGE_TOO_LARGE` 直接透传服务端 `message`（含尺寸与建议），否则「图片过大，请压缩后重试」；415 → 「不支持的图片格式」；429 → 沿用现有 `rateLimitMessage`；503 → 「图片识别服务未配置」。
- 本地预检：`file.type` 为空串时**不要**在前端拦截（iOS 从「文件」App 选取的 HEIC 会出现这种情况），交给服务端按真实解码判断。
- `sw.js` `CACHE_VERSION` 升到 `fishagent-v8`。
- 移动端 375px 下不得横向溢出。

## 7. 依赖

`pyproject.toml` 新增：`python-multipart>=0.0.9`、`pillow>=10`、`pillow-heif>=0.16`（HEIC/AVIF 解码）。

## 8. 合规

- 不上传图片到第三方以外的任何地方；图片只在内存中处理，请求结束即丢弃。
- 不记录图片内容或 base64 到日志。
- 结果必须带 AI 标识与免责；出现承诺性表述时整体降级。
- `test_compliance.py` 的密钥/直连检查同样适用于新增前端代码。
