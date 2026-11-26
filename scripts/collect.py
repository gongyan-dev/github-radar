"""每周出榜：跑一轮观察池，排出本周热榜前十，生成中文介绍，打包页面数据。"""
import datetime as dt
import json

import pool
import rank
from github import get, graphql, token
from summarize import attach, summarize

ROOT = pool.ROOT


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
    today = pool.beijing_today()
    found = pool.run(today)
    projects, skills, history = found['projects'], found['skills'], found['history']
    # 项目库和 Skills 的「近 7 天涨星」排序用快照相减，算不出的留空
    for p in projects + skills:
        p['growth'] = rank.measure(p, history, today)[0]

    reports_file = ROOT / 'data/reports.json'
    reports = pool.load(reports_file, [])
    since = (now - dt.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
    counter = (lambda name, pages: rank.count_recent_stars(name, since, graphql, pages)) if token() else None
    weekly = rank.pick_weekly(found['members'], history, today, found['trending'], found['hot'], reports, counter)
    weekly_names = {p['name'] for p in weekly}

    # 中文介绍：热榜项目排在前面优先生成，其余按近 7 天涨星，结果缓存，只为新项目调用模型
    summaries_file = ROOT / 'data/summaries.json'
    summaries = pool.load(summaries_file, {})
    unique = list({p['name']: p for p in skills + projects + weekly}.values())
    summarize(sorted(unique, key=lambda p: (p['name'] not in weekly_names, -(p.get('growth') or p.get('weekly_stars') or 0))), summaries, get)
    attach(projects, summaries)
    attach(skills, summaries)
    attach(weekly, summaries)

    reports = update_reports(reports, weekly, today)
    # 历史周报里的项目也补上介绍（只写进 data.json，不改 reports.json 的存档）
    shown_reports = [dict(r, projects=attach([dict(p) for p in r['projects']], summaries)) for r in reports]
    payload = {'updated': now.isoformat(), 'projects': projects, 'skills': skills, 'weekly': weekly, 'reports': shown_reports}
    # reports.json / summaries.json 保留缩进便于看 diff；data.json 给浏览器下载，用紧凑格式减小体积
    pool.save(reports_file, json.dumps(reports, ensure_ascii=False, indent=2))
    pool.save(summaries_file, json.dumps(summaries, ensure_ascii=False, indent=2))
    pool.save(ROOT / 'dist/data.json', json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    print(f'Collected {len(projects)} projects, {len(skills)} skills, {len(found["members"])} pool members; {len(reports)} weekly reports')


if __name__ == '__main__':
    main()
