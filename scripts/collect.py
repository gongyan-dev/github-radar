import datetime as dt
import json
import os
import pathlib
import re
import urllib.request
import urllib.parse
import time

from summarize import attach, summarize

ROOT = pathlib.Path(__file__).resolve().parents[1]

def fetch(url, headers):
    # 网络偶发失败时重试 3 次，间隔 1s、2s
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read()
        except Exception:
            if attempt == 2: raise
            time.sleep(2 ** attempt)

def trending_weekly():
    html = fetch('https://github.com/trending?since=weekly', {'User-Agent': 'github-weekly-radar', 'Accept-Language': 'en-US'}).decode('utf-8')
    return parse_trending(html)

def parse_trending(html):
    ranked = []
    for article in re.findall(r'<article class="Box-row"[^>]*>(.*?)</article>', html, re.S):
        name = re.search(r'<h2\b[^>]*>.*?<a\b[^>]*href="/([^"/]+/[^"/]+)"', article, re.S)
        stars = re.search(r'([\d,]+)\s+stars? this week', article)
        if name and stars:
            ranked.append((name.group(1), int(stars.group(1).replace(',', ''))))
    if len(ranked) < 10:
        raise ValueError('GitHub Trending weekly returned fewer than 10 projects')
    return sorted(ranked, key=lambda item: (-item[1], item[0]))[:10]

def get(path):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'github-weekly-radar'}
    if os.getenv('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    return json.loads(fetch('https://api.github.com/' + path, headers))

def update_reports(reports, weekly, today):
    """每周归档一次。周一的定时任务失败或延迟时，本周之后的第一次成功运行补上归档。"""
    if not weekly:
        return reports
    monday = (today - dt.timedelta(days=today.weekday())).isoformat()
    if today.weekday() != 0 and any(r['date'] >= monday for r in reports):
        return reports
    reports = [r for r in reports if r['date'] != today.isoformat()]
    return reports + [{'date': today.isoformat(), 'projects': weekly}]

def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    trending = trending_weekly()
    items = {}
    for query in ['created:>=' + (now-dt.timedelta(days=7)).date().isoformat() + ' archived:false fork:false', 'stars:>1000 archived:false', 'stars:>50 archived:false created:>' + (today-dt.timedelta(days=90)).isoformat(), 'topic:ai stars:>100 archived:false']:
        for repo in get('search/repositories?' + urllib.parse.urlencode({'q': query, 'sort': 'stars', 'order': 'desc', 'per_page': 100}))['items']:
            items[repo['full_name']] = repo
        time.sleep(2)
    for name, _ in trending:
        items[name] = get('repos/' + name)
    projects = []
    for name, r in items.items():
        projects.append(dict(name=name, url=r['html_url'], description=r.get('description') or '暂无介绍', language=r.get('language') or '其他', stars=r['stargazers_count'], created=r['created_at'], topics=r.get('topics', []), updated=r['pushed_at'], license=(r.get('license') or {}).get('spdx_id', '未知')))
    # 中文介绍：热榜项目排在前面优先生成，结果缓存，只为新项目调用模型
    summaries_file = ROOT / 'data/summaries.json'
    summaries = json.loads(summaries_file.read_text('utf-8')) if summaries_file.exists() else {}
    trending_names = {name for name, _ in trending}
    summarize([p for p in projects if p['name'] in trending_names] + [p for p in projects if p['name'] not in trending_names], summaries, get)
    attach(projects, summaries)
    by_name = {p['name']: p for p in projects}
    weekly = [dict(by_name[name], weekly_stars=stars) for name, stars in trending]
    reports_file = ROOT / 'data/reports.json'
    reports = json.loads(reports_file.read_text('utf-8')) if reports_file.exists() else []
    reports = update_reports(reports, weekly, today)
    # 历史周报里的项目也补上介绍（只写进 data.json，不改 reports.json 的存档）
    shown_reports = [dict(r, projects=attach([dict(p) for p in r['projects']], summaries)) for r in reports]
    payload = {'updated': now.isoformat(), 'projects': projects, 'weekly': weekly, 'reports': shown_reports}
    # reports.json / summaries.json 保留缩进便于看 diff；data.json 给浏览器下载，用紧凑格式减小体积
    for file, data, indent in [(reports_file, reports, 2), (summaries_file, summaries, 2), (ROOT/'dist/data.json', payload, None)]:
        file.parent.mkdir(parents=True, exist_ok=True)
        temp = file.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=indent, separators=None if indent else (',', ':')), 'utf-8')
        temp.replace(file)
    print(f'Collected {len(projects)} projects; {len(reports)} weekly reports')

if __name__ == '__main__': main()
