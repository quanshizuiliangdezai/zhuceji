# 架构与部署拓扑（design/overview.md）

## 组件关系

```
grok-register
├── 入口层（三选一，共用 config.json + 注册核心）
│   ├── GUI      : grok_register_ttk.py (Tkinter)
│   ├── CLI      : grok_register_ttk.py cli
│   └── WebUI    : web/server.py (FastAPI + uvicorn) → http://127.0.0.1:8092
├── 注册核心
│   ├── registration_flow.py      # 注册流程编排
│   ├── registration_browser.py   # 浏览器交互（DrissionPage）
│   ├── browser_runtime.py         # Chrome 进程管理
│   └── registration_parallel.py  # 多线程
├── 邮件服务
│   └── mail_service.py            # cloudflare/duckmail/yyds 接收验证码
├── 代理池
│   └── proxy_pool.py              # pool 模式取代理
├── 账号输出
│   ├── account_outputs.py         # 账号落盘
│   └── cpa_export.py / cpa_xai/    # CPA 凭证导出
└── 配置
    ├── config.example.json → config.json
    └── proxies.txt（pool 模式）
```

## 部署拓扑（本机）

```
Windows 本机
├── Chrome (用户级安装) ← DrissionPage 驱动
├── .venv (Python 3.12.10)
├── WebUI 监听 127.0.0.1:8092
└── 出口流量 → 代理(10808/用户配置) → Grok 注册页 + 邮箱 API
```

## 关键决策
- **用 Python 3.12 而非 3.13**：项目官方验证 3.12；curl_cffi / DrissionPage 在 3.13 轮子兼容性风险更高。
- **不移动仓库文件**：根目录即 `source/`，移动会破坏导入链。
- **优先 WebUI**：对 Windows 用户最友好，浏览器即操作界面。
