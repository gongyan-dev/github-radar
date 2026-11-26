import datetime as dt
import json
import os
import pathlib
import re
import urllib.error
import urllib.request
import urllib.parse
import time

from summarize import attach, summarize

ROOT = pathlib.Path(__file__).resolve().parents[1]

def rate_limit_wait(e):
    """GitHub 限流（403/429）时该等几秒；不是限流或要等太久（超过 90s，通常是每小时额度用完）返回 None。"""
    if e.code not in (403, 429) or not e.headers:
        return None
    if (e.headers.get('Retry-After') or '').isdigit():
        wait = int(e.headers['Retry-After'])
    elif e.headers.get('X-RateLimit-Remaining') == '0' and (e.headers.get('X-RateLimit-Reset') or '').isdigit():
        wait = int(e.headers['X-RateLimit-Reset']) - time.time() + 1
    else:
        return None
    return max(wait, 1) if wait <= 90 else None

def fetch(url, headers, sleep=time.sleep):
    # 网络偶发失败和 5xx 重试 3 次，间隔 1s、2s；搜索接口的每分钟限流按 GitHub 给的重置时间等待后重试；
    # 其它 4xx（含每小时额度耗尽）直接报错，不白白重试浪费额度
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            wait = rate_limit_wait(e)
            if attempt == 2 or (wait is None and e.code < 500): raise
            sleep(wait or 2 ** attempt)
        except Exception:
            if attempt == 2: raise
            sleep(2 ** attempt)

def trending_weekly():
    html = fetch('https://github.com/trending?since=weekly', {'User-Agent': 'github-weekly-radar', 'Accept-Language': 'en-US'}).decode('utf-8')
    return parse_trending(html, limit=None)

def parse_trending(html, limit=10):
    ranked = []
    for article in re.findall(r'<article class="Box-row"[^>]*>(.*?)</article>', html, re.S):
        name = re.search(r'<h2\b[^>]*>.*?<a\b[^>]*href="/([^"/]+/[^"/]+)"', article, re.S)
        stars = re.search(r'([\d,]+)\s+stars? this week', article)
        if name and stars:
            ranked.append((name.group(1), int(stars.group(1).replace(',', ''))))
    if len(ranked) < 10:
        raise ValueError('GitHub Trending weekly returned fewer than 10 projects')
    return sorted(ranked, key=lambda item: (-item[1], item[0]))[:limit]

def get(path):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'github-weekly-radar'}
    if os.getenv('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    return json.loads(fetch('https://api.github.com/' + path, headers))

def search(queries):
    """按 Star 从高到低搜索仓库，每个查询取前 100 个，按全名去重。"""
    items = {}
    for query in queries:
        for repo in get('search/repositories?' + urllib.parse.urlencode({'q': query, 'sort': 'stars', 'order': 'desc', 'per_page': 100}))['items']:
            items[repo['full_name']] = repo
        time.sleep(2)
    return items

def to_project(r):
    return dict(name=r['full_name'], url=r['html_url'], description=r.get('description') or '暂无介绍', language=r.get('language') or '其他', stars=r['stargazers_count'], created=r['created_at'], topics=r.get('topics', []), updated=r['pushed_at'], license=(r.get('license') or {}).get('spdx_id', '未知'))

def update_reports(reports, weekly, today):
    """每周归档一次。周一的定时任务失败或延迟时，本周之后的第一次成功运行补上归档。"""
    if not weekly:
        return reports
    monday = (today - dt.timedelta(days=today.weekday())).isoformat()
    if today.weekday() != 0 and any(r['date'] >= monday for r in reports):
        return reports
    reports = [r for r in reports if r['date'] != today.isoformat()]
    return reports + [{'date': today.isoformat(), 'projects': weekly}]

def record_stars(history, projects, today, keep=30):
    """每天记一次各项目的 Star 数（同一天多次运行以最后一次为准），只保留最近 keep 天。"""
    history[today.isoformat()] = {p['name']: p['stars'] for p in projects}
    oldest = (today - dt.timedelta(days=keep)).isoformat()
    return {d: v for d, v in sorted(history.items()) if d >= oldest}

def growth(project, history, today):
    """近 7 天涨星，返回 (涨星数, 是否估算)；算不出时返回 (None, False)。
    有 7 天前（或更早）的快照时取其中最近的一份直接相减；
    7 天内新建的仓库，现有 Star 全是这几天涨的；
    其余只有不足 7 天的快照时，按已有天数折算成 7 天，标为估算。"""
    name, stars = project['name'], project['stars']
    cutoff = (today - dt.timedelta(days=7)).isoformat()
    seen = [(d, v[name]) for d, v in sorted(history.items()) if name in v and d < today.isoformat()]
    before = [x for x in seen if x[0] <= cutoff]
    if before:
        return stars - before[-1][1], False
    if project['created'][:10] >= cutoff:
        return stars, False
    if seen:
        days = (today - dt.date.fromisoformat(seen[0][0])).days
        return round((stars - seen[0][1]) * 7 / days), True
    return None, False

def pick_weekly(projects, trending, n=10):
    """本周热榜：在全部候选里按近 7 天涨星取前 n。
    优先用自己快照算出的确切涨星；没有确切值的 Trending 项目用 Trending 页面的「stars this week」；
    只有估算值的其他项目不参与，避免折算误差把它们顶上榜。"""
    trend = dict(trending)
    def value(p):
        if p.get('growth') is not None and not p.get('growth_est'):
            return p['growth']
        return trend.get(p['name'])
    ranked = [dict(p, weekly_stars=v) for p in projects if (v := value(p)) is not None]
    return sorted(ranked, key=lambda p: (-p['weekly_stars'], p['name']))[:n]

def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    trending = trending_weekly()
    items = search(['created:>=' + (now-dt.timedelta(days=7)).date().isoformat() + ' archived:false fork:false', 'stars:>1000 archived:false', 'stars:>50 archived:false created:>' + (today-dt.timedelta(days=90)).isoformat(), 'topic:ai stars:>100 archived:false'])
    for name, _ in trending:
        if name not in items:  # 搜索结果里已有的不再单独请求，省 API 额度
            items[name] = get('repos/' + name)
    projects = [to_project(r) for r in items.values()]
    # Skills 栏：作者自己打了 skills 相关标签、或仓库名带 skill 的项目；最后一条专门捞 90 天内的新 skill
    skills = [to_project(r) for r in search(['topic:agent-skills archived:false', 'topic:claude-skills archived:false', 'topic:claude-code-skills archived:false', 'skills in:name stars:>100 archived:false', 'skill in:name stars:>30 archived:false created:>' + (today-dt.timedelta(days=90)).isoformat()]).values()]
    stars_file = ROOT / 'data/stars.json'
    history = record_stars(json.loads(stars_file.read_text('utf-8')) if stars_file.exists() else {}, projects + skills, today)
    for p in projects + skills:
        p['growth'], estimated = growth(p, history, today)
        if estimated: p['growth_est'] = True
    weekly_names = [p['name'] for p in pick_weekly(projects, trending)]
    # 中文介绍：热榜项目排在前面优先生成，其余按近 7 天涨星，结果缓存，只为新项目调用模型
    summaries_file = ROOT / 'data/summaries.json'
    summaries = json.loads(summaries_file.read_text('utf-8')) if summaries_file.exists() else {}
    unique = list({p['name']: p for p in skills + projects}.values())
    order = sorted(unique, key=lambda p: (p['name'] not in weekly_names, -(p['growth'] or 0)))
    summarize(order, summaries, get)
    attach(projects, summaries)
    attach(skills, summaries)
    weekly = pick_weekly(projects, trending)
    reports_file = ROOT / 'data/reports.json'
    reports = json.loads(reports_file.read_text('utf-8')) if reports_file.exists() else []
    reports = update_reports(reports, weekly, today)
    # 历史周报里的项目也补上介绍（只写进 data.json，不改 reports.json 的存档）
    shown_reports = [dict(r, projects=attach([dict(p) for p in r['projects']], summaries)) for r in reports]
    payload = {'updated': now.isoformat(), 'projects': projects, 'skills': skills, 'weekly': weekly, 'reports': shown_reports}
    # reports.json / summaries.json 保留缩进便于看 diff；data.json 给浏览器下载，用紧凑格式减小体积
    for file, data, indent in [(reports_file, reports, 2), (summaries_file, summaries, 2), (ROOT/'dist/data.json', payload, None), (stars_file, history, 'daily')]:
        file.parent.mkdir(parents=True, exist_ok=True)
        temp = file.with_suffix('.tmp')
        if indent == 'daily':  # Star 快照每天一行，diff 只多一行
            text = '{\n' + ',\n'.join(json.dumps(d) + ':' + json.dumps(v, separators=(',', ':')) for d, v in data.items()) + '\n}\n'
        else:
            text = json.dumps(data, ensure_ascii=False, indent=indent, separators=None if indent else (',', ':'))
        temp.write_text(text, 'utf-8')
        temp.replace(file)
    print(f'Collected {len(projects)} projects, {len(skills)} skills; {len(reports)} weekly reports')

if __name__ == '__main__': main()
