# STATUS.md — 会话交接

## 当前状态（顶部，最新）

✅ **部署完成 / 可直接开注册（DuckMail 匿名免 key）** | 2026-08-13

- 仓库已克隆至 `projects/project015-grok-register`（根目录，未移动文件）
- 项目骨架已建（requirements/design/logs/outputs + README/PLAN/STATUS）
- venv 已建（Python 3.12.10）：`.venv/`
- 核心 + WebUI 依赖已装（DrissionPage 4.1.1.4 / fastapi 0.115.14 / uvicorn 0.34.3）
- **`email_provider` = `duckmail`（匿名免 key），`duckmail_api_key` 留空**
- `proxy_mode`=single，`proxy`=`http://127.0.0.1:10808`（实测可通 Grok）
- Chrome 识别成功（用户级路径）
- WebUI 已验证 HTTP 200，监听 `http://127.0.0.1:8092`（后台任务 `aisd8j`）

## 下次入口（直接开注册）

1. 浏览器打开 http://127.0.0.1:8092
2. 确认「邮箱后端」下拉 = `duckmail`（已默认，匿名免 key，无需填任何 key）
3. `register_count` 设 `1` → 点 **开始注册**
4. 若重启 WebUI：`.venv\Scripts\Activate.ps1` 后 `python -m web.server`

## SSO 提取 UI 模块（独立工具，不污染上游）

- 路径：`scripts/sso_extractor/`（server.py + index.html）
- 作用：只读 `cpa_auths/*.json`，网页列出账号 + access_token（SSO Key）+ 过期状态，一键复制；新增「生成 sub2api JSON」按钮（绕开 x.ai 网络问题）
- 启动：`.venv\Scripts\python.exe scripts/sso_extractor\server.py`（端口 **8093**）
- 访问：http://127.0.0.1:8093
- 设计原则：**不改 grok-register 上游代码**，避免上游同步冲突
- 用法：注册完 → 打开 8093 → 推荐点「生成 sub2api JSON」下载文件 → 到 sub2api 后台「批量创建账号」上传（直存，不经 x.ai）；或复制 SSO Key 贴到 sub2api「SSO Cookie 导入」框（需服务器能访问 x.ai）

## sub2api 接入结论（已查证）

- sub2api 前端支持 `platform: grok`。**失败根因**：`sso-to-oauth` 接口后端强制访问 x.ai，而 sub2api 服务器（59.49.48.147 山西电信）访问 x.ai 超时（报 GROK_SSO_TIMEOUT）。绕过：用「批量创建账号」上传 JSON，直存 token 不经 x.ai。
- 导入方式：sub2api 后台添加 Grok 账号 → SSO Cookie 导入 → 粘贴 `access_token`（来自 cpa_auths/*.json）→ 转换
- **不要**用 grok-register 的「grok2api 远端池自动推送」（强制 HTTPS，且 pool 是 http:// 会被拒）
- CPA 导出（`cpa_export_enabled=true`）**不能关**，脚本/UI 都依赖其生成的 cpa_auths/*.json

## 历史归档

- 2026-08-13 09:13 用户问 PowerShell 报错；09:16 要求部署 grok-register；09:18 克隆完成；09:19 建 venv 并后台装依赖；09:20 用户问是否按规范 → 补齐项目骨架与文档。
