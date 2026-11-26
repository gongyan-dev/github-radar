"""GitHub 访问：带重试的请求、REST / GraphQL / 搜索、Trending 周榜。观察池、排序和采集脚本共用。"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = 'github-weekly-radar'


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


def fetch(url, headers, sleep=time.sleep, data=None):
    # 网络偶发失败和 5xx 重试 3 次，间隔 1s、2s；搜索接口的每分钟限流按 GitHub 给的重置时间等待后重试；
    # 其它 4xx（含每小时额度耗尽）直接报错，不白白重试浪费额度
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            wait = rate_limit_wait(e)
            if attempt == 2 or (wait is None and e.code < 500): raise
            sleep(wait or 2 ** attempt)
        except Exception:
            if attempt == 2: raise
            sleep(2 ** attempt)


def token():
    return os.getenv('GITHUB_TOKEN')


def get(path):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': UA}
    if token():
        headers['Authorization'] = 'Bearer ' + token()
    return json.loads(fetch('https://api.github.com/' + path, headers))


def graphql(query, variables=None):
    """GraphQL 必须带令牌。返回整个回复（含 data 和可能的 errors）。"""
    headers = {'Authorization': 'Bearer ' + token(), 'User-Agent': UA, 'Content-Type': 'application/json'}
    body = json.dumps({'query': query, 'variables': variables or {}}).encode()
    return json.loads(fetch('https://api.github.com/graphql', headers, data=body))


def trending_weekly():
    """GitHub Trending 周榜 [(全名, 本周 Star)]；页面拿不到或结构变了返回空列表，不影响其它数据。"""
    try:
        html = fetch('https://github.com/trending?since=weekly', {'User-Agent': UA, 'Accept-Language': 'en-US'}).decode('utf-8')
        return parse_trending(html, limit=None)
    except Exception as e:
        print(f'Trending 周榜获取失败：{e}')
        return []


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


def search(queries):
    """按 Star 从高到低搜索仓库，每个查询取前 100 个，按全名去重。"""
    items = {}
    for query in queries:
        for repo in get('search/repositories?' + urllib.parse.urlencode({'q': query, 'sort': 'stars', 'order': 'desc', 'per_page': 100}))['items']:
            items[repo['full_name']] = repo
        time.sleep(2)
    return items


GRAPHQL_FIELDS = 'nameWithOwner url description stargazerCount createdAt pushedAt isArchived isFork primaryLanguage{name} licenseInfo{spdxId} repositoryTopics(first:10){nodes{topic{name}}}'


def from_graphql(node):
    """GraphQL 返回的仓库转成和 REST 接口同样的字段，方便复用 to_project。"""
    return {'full_name': node['nameWithOwner'], 'html_url': node['url'], 'description': node['description'],
            'language': (node['primaryLanguage'] or {}).get('name'), 'stargazers_count': node['stargazerCount'],
            'created_at': node['createdAt'], 'pushed_at': node['pushedAt'], 'fork': node.get('isFork', False),
            'topics': [t['topic']['name'] for t in node['repositoryTopics']['nodes']],
            'license': {'spdx_id': node['licenseInfo']['spdxId']} if node['licenseInfo'] else None}


def lookup(names, batch=50, post=None):
    """批量查仓库信息，返回 {全名: 仓库}；确认不存在（改名、删除）或已归档的值为 None；
    请求失败、结果不确定的不出现在返回值里，调用方不要据此删除。
    有令牌时用 GraphQL，每次查 batch 个；没有令牌（本地匿名）时改用 REST 逐个查，最多 30 个，以免耗尽匿名额度。"""
    result = {}
    if not token() and post is None:
        for name in names[:30]:
            try:
                r = get('repos/' + name)
                result[name] = None if r.get('archived') else r
            except urllib.error.HTTPError as e:
                if e.code == 404: result[name] = None
            except Exception:
                pass
        return result
    post = post or graphql
    for i in range(0, len(names), batch):
        chunk = names[i:i + batch]
        parts = []
        for j, name in enumerate(chunk):
            owner, repo = name.split('/', 1)
            parts.append(f'r{j}: repository(owner: {json.dumps(owner)}, name: {json.dumps(repo)}) {{ {GRAPHQL_FIELDS} }}')
        try:
            data = post('{ ' + ' '.join(parts) + ' }').get('data')
        except Exception as e:
            print(f'批量查询仓库失败：{e}')
            continue
        if not data:  # 整批出错（限流等），结果不确定
            continue
        for j, name in enumerate(chunk):
            if f'r{j}' not in data: continue
            node = data[f'r{j}']
            result[name] = from_graphql(node) if node and not node['isArchived'] else None
    return result


def to_project(r):
    return dict(name=r['full_name'], url=r['html_url'], description=r.get('description') or '暂无介绍', language=r.get('language') or '其他',
                stars=r['stargazers_count'], created=r['created_at'], topics=r.get('topics', []), updated=r['pushed_at'],
                license=(r.get('license') or {}).get('spdx_id', '未知'), fork=bool(r.get('fork')))
