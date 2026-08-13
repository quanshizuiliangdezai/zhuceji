# progress.md — 实时进度快照

## 2026-08-13

### 09:13
- 用户问 PowerShell 报错（误把 Linux/macOS 命令 `source .venv/bin/activate`、`cp` 用在 Windows；且混入了 camoufox 项目的命令）。
- 结论：报错根因是「按了别的项目的教程 + 不在项目目录」。

### 09:16
- 用户要求部署 https://github.com/AaronL725/grok-register。
- 项目性质：Python 工具，用真实 Chrome 批量注册 Grok 账号；GUI/CLI/WebUI 三入口。

### 09:18
- 克隆仓库到 `projects/project015-grok-register`（git 代理 10808 可用）。
- 探明环境：Python 3.13.14（managed）+ 系统 Python 3.12.10；Chrome 用户级安装于 `C:\Users\13370\AppData\Local\Google\Chrome\Application\chrome.exe`；另有 Edge 与 Playwright Chromium。
- 决策：用系统 Python 3.12.10 建 venv（项目官方验证 3.12，避开 3.13 轮子风险）。

### 09:19
- 建 venv `.venv/`，后台启动 `requirements.txt` 安装（任务 `3jAKSp`）。
- 用户问是否按规范 → 发现漏建项目骨架与文档。

### 09:20
- 补齐治理结构：建 `requirements/ design/ logs/ outputs/`，写 README/PLAN/STATUS。
- 下一步：等依赖装完 → 装 WebUI 依赖 → 复制 config → 校验 Chrome → 起 WebUI。

## 09:22 ✅ 部署完成
- 核心依赖安装成功（DrissionPage 4.1.1.4 + curl_cffi 0.13.0 等，Python 3.12 轮子 OK）
- WebUI 依赖安装成功（fastapi 0.115.14 / uvicorn 0.34.3 / httpx 0.28.1）
- `config.json` 已复制（默认 cloudflare provider）
- Chrome 识别成功：用户级路径 `C:\Users\13370\AppData\Local\Google\Chrome\Application\chrome.exe`
- WebUI 启动验证：HTTP 200，标题 `grok-register Console`，监听 `http://127.0.0.1:8092`
- 后台进程任务 ID：`ZU8bjA`（运行中）

## 待办（下一步，需用户操作）
1. 浏览器打开 http://127.0.0.1:8092
2. 确认「邮箱后端」下拉 = `duckmail`（已默认，匿名免 key）
3. `register_count` 设 `1` → 点 **开始注册**
4. 成功账号落盘 `accounts_*.txt` 与 `./cpa_auths/`；失败进 `*.pending.jsonl`

## 09:29 用户决策（小白，无 YYDS key）
- 用户自认小白，没有 YYDS api key。
- 选定路线：先去社区领临时邮箱 key（DuckMail / YYDS / Cloud Mail 三选一），不自己搭 Cloudflare。
- 代理：用户只有 `10808`（原 GitHub 代理），不确定能否通 Grok。
- 实测：沙箱经 `10808` 访问 `grok.com` 返回 **200**，`x.ai` 返回 403（WAF，不影响注册）。→ 判定 `10808` 可通 Grok，先不买新代理。
- 已把 `config.json` 的 `proxy` 填为 `http://127.0.0.1:10808`，`proxy_mode`=single。

## 09:38 转折：找到免费免 key 路线（DuckMail 匿名）
- 用户让我帮忙找临时邮箱 key → 查到 **DuckMail 是免费公共服务 `https://api.duckmail.sbs`，且匿名（无 key）模式即可用公共域名收验证码**。
- 实测：DuckMail `/domains` 直连 & 走 10808 代理均返回 200，公共服务可达。
- 代码核证：`mail_service.py:435` key 为空则匿名创建账户，`duckmail_api_key` 非必填。
- 行动：把 `config.json` 的 `email_provider` 从 `yyds` 改为 `duckmail`，`duckmail_api_key` 留空。
- 重启 WebUI（杀旧 pid 14836 → 新进程 pid 14980，任务 `aisd8j`），配置已加载 `duckmail` 匿名模式。
- **结论：用户无需领任何 key、无需花钱、无需搭 Cloudflare，直接可注册。**

## 13:53 注册跑通 + sub2api 导入
- 用户在 8092 WebUI 注册成功（成功数量 1），凭证落盘 `cpa_auths/xai-*.json` 与 `accounts_*.txt`。
- cpa_auths 的 `access_token` 是 **Grok Web SSO token**（`_normalize_sso_token` 处理 `sso=` 前缀），base_url=`https://cli-chat-proxy.grok.com/v1`。

## 14:35 sub2api 导入「批量创建」失败 → 定位根因
- 用户在 sub2api 后台「SSO Cookie 导入」点转换，报 `GROK_SSO_TIMEOUT: xAI SSO conversion timed out ... accounts.x.ai i/o timeout`。
- 根因：sub2api 服务器（59.49.48.147 山西电信）访问 x.ai 网络层超时（非用户 key 问题）。本机经 10808 访问 accounts.x.ai 是 403（WAF），握手通但应用层拦。

## 14:48 方案 B 落地：SSO 提取器集成「生成 sub2api JSON」（绕开 x.ai）
- 查 sub2api 源码确认：批量创建端点 `POST /api/v1/admin/accounts/batch` **直接持久化 Grok OAuth credentials，不调用 x.ai**（仅 OpenAI/Antigravity 走隐私探测，Grok 不触发）。
- 因此可用 SSO token 直接当 `access_token` + `base_url=cli-chat-proxy.grok.com/v1`，生成 sub2api 导入 JSON，上传即入库。
- 给 `scripts/sso_extractor/` 的 server.py + index.html 增加 `/api/export-sub2api` 接口与「生成 sub2api JSON」按钮（含全部/单个导出、前端下载）。
- 重启 8093 服务，验证：`/api/accounts` 200、`/api/export-sub2api` 返回正确 Grok OAuth JSON（platform=grok, type=oauth, credentials.access_token=SSO, base_url=cli-chat-proxy.grok.com/v1）、首页 200。
- 修复一处 bug：server.py 重写时漏 import `FileResponse`（已补）。
- 当前有效 token 约 1 小时后过期（expires 2026-08-13T07:51:51Z），需尽快导入。
