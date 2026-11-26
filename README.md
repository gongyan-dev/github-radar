# 开源雷达

静态项目库 + Python 标准库采集 + GitHub Actions。每天给观察池记 Star 快照，每周一出本周热榜前 10（含 Skills）并归档。

## 当前状态

项目库从 GitHub 搜索热门、近期和 AI 仓库；Skills 栏搜索打了 agent-skills、claude-skills、claude-code-skills 标签或仓库名带 skill 的仓库；本周热榜见下方「数据口径」。每个项目附一段由大模型根据 README 生成的中文介绍。Sites 发布的是静态版本，不会执行 GitHub Actions。

| 脚本 | 作用 |
|---|---|
| `scripts/pool.py` | 观察池：发现候选、入池、记当天 Star 快照、清理不活跃仓库；每日任务单独运行它 |
| `scripts/rank.py` | 本周热榜排序：涨星计算、Star 时间戳兜底、打分和准入 |
| `scripts/collect.py` | 每周出榜：跑一轮观察池 → 排序 → 中文介绍 → 归档 → 打包 `dist/data.json` |
| `scripts/github.py` | GitHub 请求、重试和限流处理 |

## 在 GitHub 启用自动更新

1. 将本目录内容推送到自己的 GitHub 仓库（包括 .github）。
2. Settings → Pages → Source 选择 GitHub Actions。
3. 在 Actions 中允许工作流运行，手动执行 Collect and publish，确认成功。
4. 工作流每周一北京时间 09:17 采集并归档当周热榜 Top 10，补 300 条中文介绍；周一没跑成功时，本周之后第一次成功运行会补归档。定时任务可能延迟；失败会保留旧数据。
   周二到周日北京时间 08:30 只跑观察池，记当天的 Star 快照，不出榜、不部署。快照漏了一两天没关系，基线允许取 7～9 天前的快照。
   推送代码触发的运行只补 30 条中文介绍，几分钟内部署；推送会取消正在跑的旧运行（推送运行本身也记快照），定时运行之间排队不互相取消。手动运行时可填 max_summaries 指定补多少条。
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

**观察池**（`data/pool.json`）。GitHub 不提供历史 Star 数，涨星只能靠自己提前记快照，所以项目要在上榜之前就进池。

- 入池：每天把全 GitHub 近 7 天加星前 200（ClickHouse 公开的 GH Archive 事件数据集，抽样数据，只用来发现候选）、Trending 周榜、项目库和 Skills 的仓库收进池，记录入池日期、来源和最后一次被发现的日期。
- 快照：池里全部仓库每天记一次 Star 数（`data/stars.json`，每天一行，保留 35 天）。
- 出池：连续 28 天没被任何来源发现、且近 28 天涨星不到 200 的移出；确认已删除或归档的移出；改名的换成新名字。

**本周热榜**：全 GitHub 范围，项目和 Skills 一起排，fork 不参与。

    得分 = 本周涨星 × 加速系数 × 连续上榜衰减

- 本周涨星依次取：今天减去 7～9 天前最近一份快照（按实际天数折算回 7 天）> 7 天内新建的仓库取全部 Star > 对 ClickHouse 榜前 15 个没有基线的仓库，用 GraphQL 从最新的 Star 往前数时间戳（每个最多 50 页，总共不超过 300 页）> Trending 页面的「stars this week」，标「约」。
- 加速系数 = 本周涨星 ÷ max(上周涨星, 100)，限制在 0.8～1.5；没有上周数据（含本周才建的仓库）取 1.0。
- 连续上榜衰减：上周在榜 ×0.7，连续两周及以上 ×0.5。
- 准入：本周涨星至少 500，按得分排；过线的不足 10 个时，按涨星补满。

页面显示真实的本周涨星、较上周涨跌和连续上榜周数，得分只用来排序（鼠标悬停可看）。项目库和 Skills 的「近 7 天涨星」排序同样用快照相减，没有基线的留空。采集失败时不覆盖旧数据。每周归档一次当时的热榜，避免历史榜单随当前数据变化。

## 验证

    python -m unittest discover -s tests
    node --check dist/app.js
