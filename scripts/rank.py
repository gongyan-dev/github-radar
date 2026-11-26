"""本周热榜排序：涨星计算、Star 时间戳兜底、打分和准入。

得分 = 本周涨星 × 加速系数 × 连续上榜衰减
- 本周涨星：今天的 Star 减去 7～9 天前最近的一份快照，按实际天数折算回 7 天
- 加速系数：本周涨星 ÷ max(上周涨星, 100)，限制在 0.8～1.5；没有上周数据取 1.0
- 连续上榜衰减：上周在榜 ×0.7，连续两周及以上 ×0.5
准入：非 fork，本周涨星至少 500；过线的不足 10 个时按涨星补满。页面显示真实涨星，得分只用来排序。
"""
import datetime as dt

DAY = dt.timedelta(days=1)


def snapshot(history, name, newest, oldest):
    """在 [oldest, newest] 日期范围内取最新的一份快照，返回 (日期, Star) 或 None。"""
    lo, hi = oldest.isoformat(), newest.isoformat()
    for d in sorted(history, reverse=True):
        if lo <= d <= hi and name in history[d]:
            return dt.date.fromisoformat(d), history[d][name]
    return None


def week_growth(history, name, end, end_stars):
    """截至 end 这一天的 7 天涨星：用 7～9 天前最近的快照相减，按实际天数折算回 7 天；没有基线返回 None。"""
    base = snapshot(history, name, end - 7 * DAY, end - 9 * DAY)
    if base is None:
        return None
    days = (end - base[0]).days
    return round((end_stars - base[1]) * 7 / days)


def created_since(project, day):
    return project['created'][:10] >= day.isoformat()


def measure(project, history, today):
    """本周涨星，返回 (涨星, 来源)。来源：snapshot 快照相减、new 7 天内新建（现有 Star 全是本周涨的）；算不出返回 (None, None)。"""
    g = week_growth(history, project['name'], today, project['stars'])
    if g is not None:
        return g, 'snapshot'
    if created_since(project, today - 7 * DAY):
        return project['stars'], 'new'
    return None, None


def previous_week(project, history, today):
    """上周（8～14 天前那一周）的涨星；没有数据返回 None。
    本周才建的仓库也返回 None：上周 0 会让加速系数自动拉满，系统性抬高所有新仓库。"""
    name = project['name']
    end = snapshot(history, name, today - 7 * DAY, today - 9 * DAY)
    if end is None:
        return None
    g = week_growth(history, name, end[0], end[1])
    if g is None and created_since(project, end[0] - 7 * DAY):
        g = end[1]
    return g


STARGAZERS = ('query($owner:String!,$name:String!,$before:String){repository(owner:$owner,name:$name){'
              'stargazers(last:100,before:$before,orderBy:{field:STARRED_AT,direction:ASC}){'
              'pageInfo{hasPreviousPage startCursor} edges{starredAt}}}}')


def count_recent_stars(name, since, post, max_pages=50):
    """从最新的 Star 往前翻，数 since（UTC ISO 时间字符串）之后加的 Star。
    返回 (数量, 翻页次数, 是否数到上限没数完)。只统计现存的 Star，期间取消的不计。"""
    owner, repo = name.split('/', 1)
    before, count = None, 0
    for page in range(1, max_pages + 1):
        conn = post(STARGAZERS, {'owner': owner, 'name': repo, 'before': before})['data']['repository']['stargazers']
        recent = [e for e in conn['edges'] if e['starredAt'] >= since]
        count += len(recent)
        if len(recent) < len(conn['edges']) or not conn['pageInfo']['hasPreviousPage']:
            return count, page, False
        before = conn['pageInfo']['startCursor']
    return count, max_pages, True


def streak(name, reports, today):
    """从上周往前，连续几周的周报上过榜；中间哪周没上榜或没有周报就断开。"""
    week_of = lambda d: d - d.weekday() * DAY
    expected = week_of(today) - 7 * DAY
    n = 0
    for r in sorted(reports, key=lambda r: r['date'], reverse=True):
        week = week_of(dt.date.fromisoformat(r['date']))
        if week > expected:  # 本周自己的存档（重跑时）跳过
            continue
        if week < expected or not any(p['name'] == name for p in r['projects']):
            break
        n += 1
        expected -= 7 * DAY
    return n


def score(weekly, prev, runs):
    accel = 1.0 if prev is None else min(1.5, max(0.8, weekly / max(prev, 100)))
    decay = 1.0 if runs == 0 else 0.7 if runs == 1 else 0.5
    return weekly * accel * decay


def pick_weekly(members, history, today, trending=(), hot=(), reports=(), counter=None, n=10, floor=500, fallback=15, budget=300):
    """本周热榜前 n。
    members：观察池里全部仓库（to_project 格式）；trending：[(全名, 本周 Star)]；hot：ClickHouse 近 7 天加星榜 [(全名, 次数)]；
    counter(name, max_pages) -> (数量, 翻页次数, 是否到上限)，数 Star 时间戳用，没有令牌时传 None。
    涨星取值依次为：快照相减 > 7 天内新建 > 数 Star 时间戳（只对 hot 前 fallback 个、总翻页不超过 budget）> Trending 数字（标约）。"""
    trend = dict(trending)
    rows = []
    for p in members:
        if p.get('fork'):
            continue
        w, src = measure(p, history, today)
        rows.append(dict(p, weekly_stars=w, source=src))

    if counter:
        order = {name: i for i, (name, _) in enumerate(hot)}
        missing = sorted((r for r in rows if r['weekly_stars'] is None and r['name'] in order), key=lambda r: order[r['name']])
        for r in missing[:fallback]:
            if budget <= 0:
                break
            try:
                count, pages, capped = counter(r['name'], min(50, budget))
            except Exception as e:
                print(f'数 Star 时间戳失败 {r["name"]}：{e}')
                continue
            budget -= pages
            r['weekly_stars'], r['source'] = (max(count, trend.get(r['name'], 0)) if capped else count), 'stargazers'

    for r in rows:
        if r['weekly_stars'] is None and r['name'] in trend:
            r['weekly_stars'], r['source'], r['weekly_est'] = trend[r['name']], 'trending', True

    ranked = []
    for r in rows:
        if r['weekly_stars'] is None:
            continue
        r['prev_stars'] = previous_week(r, history, today)
        r['streak'] = streak(r['name'], reports, today)
        r['score'] = round(score(r['weekly_stars'], r['prev_stars'], r['streak']), 1)
        ranked.append(r)
    qualified = sorted((r for r in ranked if r['weekly_stars'] >= floor), key=lambda r: (-r['score'], r['name']))
    rest = sorted((r for r in ranked if r['weekly_stars'] < floor), key=lambda r: (-r['weekly_stars'], r['name']))
    return (qualified + rest)[:n]
