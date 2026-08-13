# 部署前置条件（requirements/needs.md）

## 硬件/系统
- Windows 10/11（已具备，用户级账户，非管理员）
- 可访问外网 + 代理（Grok 注册页需可直连或经代理）

## 软件依赖
| 依赖 | 状态 | 说明 |
|------|------|------|
| Python 3.12.10 | ✅ 已用 | 系统安装版 `C:\Users\13370\AppData\Local\Programs\Python\Python312\` |
| venv | ✅ 已建 | 位于项目 `.venv/` |
| 核心依赖 requirements.txt | 🔄 安装中 | 后台任务 `3jAKSp` |
| WebUI 依赖 requirements-web.txt | ⬜ 待装 | fastapi/uvicorn/httpx |
| **真实 Chrome** | ✅ 已装 | `C:\Users\13370\AppData\Local\Google\Chrome\Application\chrome.exe` |

## 必填凭证（运行前需用户提供）
- **已选邮箱后端：`duckmail`（匿名 / 免 key 模式，2026-08-13 确认）**
  - 公共服务 `https://api.duckmail.sbs`，**无需任何 API Key**，公共域名直接收验证码
  - `duckmail_api_key` 留空即可（匿名模式）；仅当要用私有域名时才需 `dk_` 开头的 key
  - 代码依据：`mail_service.py:435` `key = api_key or get_duckmail_api_key()`，key 为空则不加 Authorization，走匿名创建账户
- **代理（Grok 封中国 IP，已实测可用）**：`proxy_mode`=single，`proxy`=`http://127.0.0.1:10808`
  - 实测：沙箱经 `10808` 访问 `grok.com` 返回 200，可通 Grok；先不买新代理
  - 若注册被地区/IP 反刷拦截，再考虑住宅/干净 IP
- **注册数量**：`register_count` 先设 `1` 试水

## 配置清单（config.json 关键项）
- `email_provider`：选上面其一
- `register_count`：注册数量
- `proxy_mode`：`auto` / `pool` / `none`
- `multi_thread_enabled`：是否多线程
- `cpa_export_enabled`：是否导出 CPA 凭证

> 注：以上凭证由用户持有，AI 不代填敏感 Key；填好后 `config.json` 已被 .gitignore 忽略，勿提交。
