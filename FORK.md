# zhuceji Fork 说明

本仓库是 [AaronL725/grok-register](https://github.com/AaronL725/grok-register) 的二次开发分支，新增以下自用功能：

- `scripts/extract_sso_keys.py`：从 `cpa_auths/*.json` 提取 SSO Key。
- `scripts/sso_extractor/`：独立的 FastAPI 面板（端口 8093），列出已注册账号、一键复制 SSO Key、生成 sub2api 批量导入 JSON。
- 项目治理文档：`STATUS.md`、`PLAN.md`、`requirements/`、`design/`、`logs/`。

## 分支策略

| 分支 | 用途 | 是否默认 |
|---|---|---|
| `main` | 上游代码 + 自定义功能 | ✅ |
| `upstream-sync` | 纯上游镜像，用于比对/合并 | 否 |

## 上游更新不会冲掉自定义功能

采用 GitHub Actions 每小时自动拉取上游，并通过 **merge** 方式合并到 `main`：

1. 工作流把 `upstream-sync` 重置为 `AaronL725/grok-register` 的 `main`。
2. 把 `upstream/main` merge 进 `main`。
3. 如果上游改的文件和自定义功能改的文件有重叠，工作流会失败，需要你手动解决冲突——**这是 Git 的正常保护机制，不会自动覆盖你的代码**。

因为自定义功能 mostly 是新增文件（`scripts/`、`FORK.md`、`.github/workflows/`），正常上游更新不会冲突。

## 需要的仓库 Secret

仓库设置 → Secrets and variables → Actions → New repository secret：

- 名称：`WORKFLOW_PAT`
- 值：一个 GitHub Personal Access Token，权限至少勾选 `repo` + `workflow`。

## 手动同步（如果 Actions 失败）

```bash
git fetch upstream
git checkout main
git merge upstream/main
# 如有冲突，解决后：
git add .
git commit -m "merge upstream"
git push origin main
```
