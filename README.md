# 开源雷达

静态项目库 + Python 标准库采集 + GitHub Actions 每日更新及每周归档。本周热榜展示 GitHub Trending 周榜中本周获得 Star 最多的 10 个项目。

## 当前状态

项目库从 GitHub 搜索热门、近期和 AI 仓库；Skills 栏搜索打了 agent-skills、claude-skills、claude-code-skills 标签或仓库名带 skill 的仓库；本周热榜按近 7 天新增 Star 排序（每日 Star 快照存在 `data/stars.json`）。每个项目附一段由大模型根据 README 生成的中文介绍。Sites 发布的是静态版本，不会执行 GitHub Actions。

## 在 GitHub 启用自动更新

1. 将本目录内容推送到自己的 GitHub 仓库（包括 .github）。
2. Settings → Pages → Source 选择 GitHub Actions。
3. 在 Actions 中允许工作流运行，手动执行 Collect and publish，确认成功。
4. 工作流每天北京时间 09:17 采集，周一归档当时的本周热榜 Top 10；周一没跑成功时，本周之后第一次成功运行会补归档。定时任务可能延迟；失败会保留旧数据。
   工作流分为 build 和 deploy 两个 job，部署偶发失败时可在运行页面只重跑 deploy。
5. 日常访问 GitHub Pages 的网址；Sites 的当前预览不会随 GitHub Pages 同步。

## 中文介绍

采集时为每个项目读取 README，调用大模型（OpenAI Chat Completions 兼容接口）生成 50～90 字的中文介绍，缓存在 `data/summaries.json`。每个项目只生成一次，简介或标签变化时重新生成；单次运行最多新生成 300 条（环境变量 `MAX_SUMMARIES`）。限流、超时会自动重试；运行日志末尾会汇总失败原因。

在 Settings → Secrets and variables → Actions 中配置：

| 位置 | 名称 | 说明 |
|---|---|---|
| Secrets | `LLM_API_KEY` | 模型平台的 API Key，必填；未配置时跳过生成，页面显示英文原文 |
| Variables | `LLM_BASE_URL` | 可选，默认 `https://smarttoken.ghnorth.cn/v1` |
| Variables | `LLM_MODEL` | 可选，默认 `qwen3.8-27b` |
| Variables | `LLM_EXTRA_BODY` | 可选，JSON，并入请求体。思考模型生成慢、回复为空时可设 `{"enable_thinking": false}`（参数名以模型平台文档为准） |

GitHub 采集本身使用自动提供的 github.token，无需配置。如果仓库规则不允许机器人直接推送，需要调整相应仓库权限或改为提交 PR。

## 本地

Python 3.12+，不需要第三方包。

    python scripts/collect.py          # 需要中文介绍时先设置环境变量 LLM_API_KEY
    python -m http.server 8080 --directory dist

一次完整采集约调用 GitHub API 10 次搜索加若干次单仓库查询；README 走 raw.githubusercontent.com 下载，不占 API 额度。未认证时每小时只有 60 次普通请求、每分钟 10 次搜索，本地多跑几次容易用完，可设置环境变量 GITHUB_TOKEN（只读公开仓库的 fine-grained token 即可）。搜索接口的每分钟限流会自动等待重试。

## 数据口径

本周热榜：每天记录所有收录项目的 Star 数，用当天减去 7 天前的快照得到近 7 天新增 Star，取前 10。GitHub Trending 周榜上的项目一并纳入候选，自己没有确切数据时用 Trending 页面的「stars this week」。项目库和 Skills 默认也按近 7 天涨星排序，快照不足 7 天时按已有天数折算并标「约」。采集失败时不覆盖旧数据。每周归档一次当时的热榜，避免历史榜单随当前数据变化。

## 验证

    python -m unittest discover -s tests
    node --check dist/app.js
