# 开源雷达

静态项目库 + Python 标准库采集 + GitHub Actions 每日更新及每周归档。本周热榜展示 GitHub Trending 周榜中本周获得 Star 最多的 10 个项目。

## 当前状态

项目库从 GitHub 搜索热门、近期和 AI 仓库；本周热榜直接读取 GitHub Trending 周榜。每个项目附一段由大模型根据 README 生成的中文介绍。Sites 发布的是静态版本，不会执行 GitHub Actions。

## 在 GitHub 启用自动更新

1. 将本目录内容推送到自己的 GitHub 仓库（包括 .github）。
2. Settings → Pages → Source 选择 GitHub Actions。
3. 在 Actions 中允许工作流运行，手动执行 Collect and publish，确认成功。
4. 工作流每天北京时间 09:17 采集，周一归档当时的本周热榜 Top 10；周一没跑成功时，本周之后第一次成功运行会补归档。定时任务可能延迟；失败会保留旧数据。
   工作流分为 build 和 deploy 两个 job，部署偶发失败时可在运行页面只重跑 deploy。
5. 日常访问 GitHub Pages 的网址；Sites 的当前预览不会随 GitHub Pages 同步。

## 中文介绍

采集时为每个项目读取 README，调用大模型（OpenAI Chat Completions 兼容接口）生成 50～90 字的中文介绍，缓存在 `data/summaries.json`。每个项目只生成一次，简介或标签变化时重新生成；单次运行最多新生成 300 条（环境变量 `MAX_SUMMARIES`）。

在 Settings → Secrets and variables → Actions 中配置：

| 位置 | 名称 | 说明 |
|---|---|---|
| Secrets | `LLM_API_KEY` | 模型平台的 API Key，必填；未配置时跳过生成，页面显示英文原文 |
| Variables | `LLM_BASE_URL` | 可选，默认 `https://smarttoken.ghnorth.cn/v1` |
| Variables | `LLM_MODEL` | 可选，默认 `qwen3.8-27b` |

GitHub 采集本身使用自动提供的 github.token，无需配置。如果仓库规则不允许机器人直接推送，需要调整相应仓库权限或改为提交 PR。

## 本地

Python 3.12+，不需要第三方包。

    python scripts/collect.py          # 需要中文介绍时先设置环境变量 LLM_API_KEY
    python -m http.server 8080 --directory dist

未认证的 GitHub API 容易遇到共享 IP 限流；本地运行可从环境变量 GITHUB_TOKEN 读取令牌。

## 数据口径

本周热榜读取 GitHub Trending 的 weekly 页面，按页面显示的「stars this week」排序，取前 10 个仓库；既可包含新项目，也可包含本周走红的老项目。采集失败时不覆盖旧数据。每周归档一次当时的项目数据，避免历史榜单随当前数据变化。项目库另外使用 GitHub Search API 获取候选项目。

## 验证

    python -m unittest discover -s tests
    node --check dist/app.js
