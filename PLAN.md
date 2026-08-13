# PLAN.md — 部署计划

## 目标

在本地 Windows 环境跑通 grok-register，优先验证 WebUI 入口（http://127.0.0.1:8092）。

## 阶段划分

### 阶段 1：环境落地（进行中）
- [x] 克隆仓库到 `projects/project015-grok-register`
- [x] 建项目骨架（requirements/design/logs/outputs + README/PLAN/STATUS）
- [x] 建 venv（Python 3.12.10）
- [ ] 安装 `requirements.txt`
- [ ] 安装 `requirements-web.txt`

### 阶段 2：配置与校验
- [ ] 复制 `config.example.json` → `config.json`
- [ ] 校验 DrissionPage 识别本机 Chrome
- [ ] 填邮箱 provider 凭证（cloudflare/duckmail/yyds 三选一）

### 阶段 3：运行验证
- [ ] 启动 WebUI，确认 8092 端口可访问
- [ ] （可选）CLI/GUI 冒烟测试

## 任务拆分

| 任务 | 命令/动作 | 状态 |
|------|----------|------|
| 装核心依赖 | `.venv/Scripts/pip.exe install -r requirements.txt` | 进行中 |
| 装 WebUI 依赖 | `.venv/Scripts/pip.exe install -r requirements-web.txt` | 待做 |
| 准备配置 | `Copy-Item config.example.json config.json` | 待做 |
| 校验 Chrome | 运行 DrissionPage 探测 | 待做 |
| 起 WebUI | `.venv/Scripts/python.exe -m web.server` | 待做 |
