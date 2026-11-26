"""观察池：每天发现候选、入池、记 Star 快照、清理不再活跃的仓库。

GitHub 不提供历史 Star 数，「本周涨星」要靠自己提前记快照，所以项目要在上榜之前就进池。
- 发现：全 GitHub 近 7 天加星前 200（ClickHouse 公开的 GH Archive 数据集）、Trending 周榜、项目库和 Skills 的搜索结果
- 快照：池里全部仓库每天记一次 Star 数（data/stars.json，每天一行）
- 出池：连续 28 天没被任何来源发现、且近 28 天涨星不到 200 的移出；确认已删除、改名或归档的移出

单独运行（每日任务）：python scripts/pool.py
"""
import datetime as dt
import json
import pathlib

from github import fetch, lookup, search, to_project, trending_weekly, UA
from rank import DAY, snapshot

ROOT = pathlib.Path(__file__).resolve().parents[1]
KEEP_DAYS = 35      # 快照保留天数：加速系数要用到 16 天前，出池判断要用到 28 天前
IDLE_DAYS = 28
MIN_GROWTH = 200


def library_queries(today):
    return ['created:>=' + (today - 7 * DAY).isoformat() + ' archived:false fork:false', 'stars:>1000 archived:false',
            'stars:>50 archived:false created:>' + (today - 90 * DAY).isoformat(), 'topic:ai stars:>100 archived:false']


def skill_queries(today):
    # 作者自己打了 skills 相关标签、或仓库名带 skill 的项目；最后一条专门捞 90 天内的新 skill
    return ['topic:agent-skills archived:false', 'topic:claude-skills archived:false', 'topic:claude-code-skills archived:false',
            'skills in:name stars:>100 archived:false', 'skill in:name stars:>30 archived:false created:>' + (today - 90 * DAY).isoformat()]


def discover(days=7, limit=200):
    """全 GitHub 近 days 天加星最多的 limit 个仓库 [(全名, 加星次数)]。
    事件数据是抽样的，次数远小于真实值，只用来发现候选和排先后；失败时返回空列表。"""
    sql = (f"SELECT repo_name, count() FROM github_events WHERE event_type = 'WatchEvent' AND created_at >= now() - INTERVAL {int(days)} DAY "
           f"GROUP BY repo_name ORDER BY count() DESC LIMIT {int(limit)} FORMAT JSONCompact")
    try:
        data = json.loads(fetch('https://play.clickhouse.com/?user=play', {'User-Agent': UA}, data=sql.encode()))
        return [(row[0], int(row[1])) for row in data['data'] if '/' in row[0]]
    except Exception as e:
        print(f'全 GitHub 加星数据获取失败，本次只用其它来源：{e}')
        return []


def seed(history, today):
    """第一次运行时，把已有快照里出现过的仓库都收进池，入池日期取最早出现的那天。"""
    pool = {}
    for d in sorted(history):
        for name in history[d]:
            pool.setdefault(name, {'added': d, 'source': 'seed', 'seen': today.isoformat()})
    return pool


def admit(pool, found, today):
    """found：[(全名, 来源)]。新的入池；已在池里的刷新最后发现日期。"""
    for name, source in found:
        entry = pool.setdefault(name, {'added': today.isoformat(), 'source': source})
        entry['seen'] = today.isoformat()
    return pool


def record_stars(history, projects, today, keep=KEEP_DAYS):
    """每天记一次各项目的 Star 数（同一天多次运行以最后一次为准），只保留最近 keep 天。"""
    history[today.isoformat()] = {p['name']: p['stars'] for p in projects}
    oldest = (today - keep * DAY).isoformat()
    return {d: v for d, v in sorted(history.items()) if d >= oldest}


def prune(pool, history, today, idle=IDLE_DAYS, min_growth=MIN_GROWTH):
    """移出连续 idle 天没被发现、且近 idle 天涨星不到 min_growth 的仓库；快照不够判断的先留着。返回移出的名单。"""
    removed = []
    now = history.get(today.isoformat(), {})
    for name, entry in list(pool.items()):
        if (today - dt.date.fromisoformat(entry['seen'])).days < idle or name not in now:
            continue
        base = snapshot(history, name, today - idle * DAY, today - KEEP_DAYS * DAY)
        if base and now[name] - base[1] < min_growth:
            del pool[name]
            removed.append(name)
    return removed


def load(path, default):
    return json.loads(path.read_text('utf-8')) if path.exists() else default


def save(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(text, 'utf-8')
    temp.replace(path)


def save_history(path, history):
    # Star 快照每天一行，diff 只多一行
    save(path, '{\n' + ',\n'.join(json.dumps(d) + ':' + json.dumps(v, separators=(',', ':')) for d, v in history.items()) + '\n}\n')


def run(today, root=ROOT):
    """跑一轮观察池，保存 data/pool.json 和 data/stars.json。
    返回 projects（项目库）、skills、members（池里全部查到的仓库）、trending、hot、history，供出榜使用。"""
    pool_file, stars_file = root / 'data/pool.json', root / 'data/stars.json'
    history = load(stars_file, {})
    pool = load(pool_file, None) or seed(history, today)

    trending = trending_weekly()
    hot = discover()
    projects = [to_project(r) for r in search(library_queries(today)).values()]
    skills = [to_project(r) for r in search(skill_queries(today)).values()]
    found = ([(n, 'clickhouse') for n, _ in hot] + [(n, 'trending') for n, _ in trending] +
             [(p['name'], 'library') for p in projects] + [(p['name'], 'skills') for p in skills])
    admit(pool, found, today)

    info = {p['name']: p for p in projects + skills}
    gone = []
    for name, repo in lookup([n for n in pool if n not in info]).items():
        if repo is None:
            del pool[name]
            gone.append(name)
        else:
            new = repo['full_name']  # 改名的仓库 GitHub 会跳到新名字，池里也换成新名字
            if new != name:
                pool.setdefault(new, pool.pop(name))
            info[new] = to_project(repo)
    members = [info[n] for n in pool if n in info]

    history = record_stars(history, members, today)
    removed = prune(pool, history, today)
    members = [p for p in members if p['name'] in pool]

    save(pool_file, json.dumps(dict(sorted(pool.items())), ensure_ascii=False, indent=1) + '\n')
    save_history(stars_file, history)
    print(f'观察池 {len(pool)} 个仓库，本次快照 {len(members)} 个；移出 {len(removed)} 个不活跃、{len(gone)} 个已删除或归档')
    return dict(projects=projects, skills=skills, members=members, trending=trending, hot=hot, history=history)


def beijing_today():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()


if __name__ == '__main__':
    run(beijing_today())
