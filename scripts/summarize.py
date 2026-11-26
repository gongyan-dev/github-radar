"""用大模型为每个项目生成中文介绍，结果缓存在 data/summaries.json，每个项目只生成一次。

接口为 OpenAI Chat Completions 兼容格式，通过环境变量配置：
  LLM_API_KEY    必填，未设置时跳过生成，只使用已有缓存
  LLM_BASE_URL   默认 https://smarttoken.ghnorth.cn/v1
  LLM_MODEL      默认 qwen3.8-27b
  MAX_SUMMARIES  单次运行最多新生成多少条，默认 300
"""
import base64
import concurrent.futures
import hashlib
import json
import os
import re
import urllib.request

PROMPT = (
    '你是开源项目编辑，为中文读者介绍 GitHub 项目。根据给出的仓库信息和 README，'
    '用简体中文写一段 50 到 90 字的介绍：先说它是什么、解决什么问题，再说主要特点或适合谁用。'
    '只写 README 里能确认的内容，不夸大，不用"强大""革命性"这类空话。'
    '只输出介绍正文，不要标题、引号、列表或 Markdown。'
)


def fingerprint(project):
    # 简介或标签变化时重新生成
    raw = (project['description'] or '') + '|' + ','.join(project.get('topics', []))
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]


def clean(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.S)
    text = re.sub(r'^[#>*\-\s"“]+|["”\s]+$', '', text.strip())
    return re.sub(r'\s+', ' ', text)


def readme(get, name):
    try:
        data = get('repos/' + name + '/readme')
        text = base64.b64decode(data.get('content', '')).decode('utf-8', 'ignore')
    except Exception:
        return ''
    text = re.sub(r'<[^>]+>|!\[[^\]]*\]\([^)]*\)', ' ', text)  # 去掉 HTML 标签和图片
    return re.sub(r'\n\s*\n+', '\n', text)[:6000]


def ask_llm(project, readme_text):
    base = (os.getenv('LLM_BASE_URL') or 'https://smarttoken.ghnorth.cn/v1').rstrip('/')
    info = (
        f"仓库：{project['name']}\n简介：{project['description']}\n"
        f"语言：{project['language']}\n标签：{', '.join(project.get('topics', [])) or '无'}\n\n"
        f"README 节选：\n{readme_text or '（无 README）'}"
    )
    body = json.dumps({
        'model': os.getenv('LLM_MODEL') or 'qwen3.8-27b',
        'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': info}],
        'max_tokens': 2000,
    }).encode('utf-8')
    request = urllib.request.Request(base + '/chat/completions', data=body, headers={
        'Authorization': 'Bearer ' + os.environ['LLM_API_KEY'],
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(request, timeout=120) as r:
        reply = json.load(r)
    return clean(reply['choices'][0]['message']['content'] or '')


def summarize(projects, cache, get, llm=None, workers=2):
    """为缓存中没有或已过期的项目生成介绍。返回新生成的条数；单个项目失败不影响整体。"""
    if llm is None:
        if not os.getenv('LLM_API_KEY'):
            print('LLM_API_KEY 未设置，跳过中文介绍生成')
            return 0
        llm = ask_llm
    todo = [p for p in projects if cache.get(p['name'], {}).get('fp') != fingerprint(p)]
    todo = todo[:int(os.getenv('MAX_SUMMARIES') or 300)]

    def work(p):
        try:
            text = llm(p, readme(get, p['name']))
            return p, text if len(text) >= 10 else None
        except Exception as e:
            print(f"生成介绍失败 {p['name']}: {e}")
            return p, None

    done = 0
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for p, text in pool.map(work, todo):
            if text:
                cache[p['name']] = {'summary': text, 'fp': fingerprint(p)}
                done += 1
    print(f'新生成中文介绍 {done}/{len(todo)} 条')
    return done


def attach(projects, cache):
    """把缓存里的介绍写进项目数据，供前端显示。"""
    for p in projects:
        if p['name'] in cache:
            p['summary'] = cache[p['name']]['summary']
    return projects
