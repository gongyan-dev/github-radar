const PAGE = 30;
let data, view = 'weekly', limit = PAGE;
const $ = id => document.getElementById(id);
const fmt = n => new Intl.NumberFormat('zh-CN').format(n);
const day = s => new Date(s).toLocaleDateString('zh-CN', {timeZone: 'Asia/Shanghai'});

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

// 距今多久，用于“x 天前更新”
function ago(s) {
  const d = Math.floor((Date.now() - new Date(s)) / 864e5);
  if (d < 1) return '今天';
  if (d < 30) return d + ' 天前';
  if (d < 365) return Math.floor(d / 30) + ' 个月前';
  return Math.floor(d / 365) + ' 年前';
}

// 按语言名生成稳定的颜色
function hue(lang) {
  let h = 0;
  for (const c of lang) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 45% 50%)`;
}

function rowsFor() {
  if (view === 'archive') return data.reports.find(r => r.date === $('report').value)?.projects || [];
  return view === 'weekly' ? data.weekly : data.projects;
}

function card(p, i) {
  const c = el('article', undefined, 'card');

  const top = el('div', undefined, 'top');
  const lang = el('span', p.language, 'lang');
  lang.style.setProperty('--dot', hue(p.language));
  top.append(el('span', String(i + 1).padStart(2, '0'), 'rank'), lang);

  const h = el('h2');
  const a = el('a', p.name);
  a.href = p.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
  h.append(a);

  c.append(top, h);
  if (p.summary) {
    c.append(el('p', p.summary, 'summary'));
    if (p.description && p.description !== '暂无介绍') {
      const o = el('p', p.description, 'origin');
      o.title = p.description;
      c.append(o);
    }
  } else {
    c.append(el('p', p.description, 'summary pending'));
  }

  if (p.topics.length) {
    const tags = el('div', undefined, 'tags');
    p.topics.slice(0, 4).forEach(t => tags.append(el('span', t)));
    c.append(tags);
  }

  const m = el('div', undefined, 'metrics');
  m.append(el('span', '★ ' + fmt(p.stars)));
  if (p.weekly_stars !== undefined) m.append(el('span', '本周 +' + fmt(p.weekly_stars), 'growth'));
  else m.append(el('span', view === 'all' && $('sort').value === 'updated' ? ago(p.updated) + '更新' : '创建于 ' + day(p.created), 'muted'));
  c.append(m);
  return c;
}

function render() {
  const q = $('search').value.toLowerCase().trim();
  const lang = $('language').value;
  let rows = rowsFor().filter(p => (!lang || p.language === lang) &&
    [p.name, p.summary || '', p.description, ...p.topics].join(' ').toLowerCase().includes(q));
  if (view === 'all') {
    const s = $('sort').value;
    const key = s === 'recent' ? p => new Date(p.created) : s === 'updated' ? p => new Date(p.updated) : p => p.stars;
    rows = [...rows].sort((a, b) => key(b) - key(a));
  }

  $('note').textContent =
    view === 'weekly' ? 'GitHub Trending 周榜中，本周新增 Star 最多的 10 个项目。' :
    view === 'archive' ? '每周一保存当时的 GitHub Trending 周榜。' :
    `找到 ${fmt(rows.length)} 个项目 · 来自热门、近期及 AI 方向的 GitHub 仓库。`;

  const box = $('projects');
  box.replaceChildren();
  if (!rows.length) box.append(el('div', '没有匹配的项目，换个关键词试试。', 'empty'));
  rows.slice(0, limit).forEach((p, i) => box.append(card(p, i)));
  $('more').hidden = rows.length <= limit;
  $('more').textContent = `加载更多（还有 ${fmt(rows.length - limit)} 个）`;
}

function reset() { limit = PAGE; if (data) render(); }

fetch('data.json', {cache: 'no-cache'})
  .then(r => { if (!r.ok) throw Error(r.status); return r.json(); })
  .then(d => {
    data = d;
    $('count').textContent = fmt(d.projects.length);
    $('ready').textContent = fmt(d.weekly.length);
    $('summarized').textContent = fmt(d.projects.filter(p => p.summary).length);
    $('date').textContent = day(d.updated);
    [...new Set(d.projects.map(p => p.language))].sort().forEach(l => {
      const o = el('option', l); o.value = l; $('language').append(o);
    });
    [...d.reports].reverse().forEach(r => {
      const o = el('option', r.date + ' 期'); o.value = r.date; $('report').append(o);
    });
    render();
  })
  .catch(() => { $('note').textContent = '数据加载失败，请刷新重试。'; });

let timer;
$('search').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(reset, 150); });
['language', 'sort', 'report'].forEach(id => $(id).addEventListener('change', reset));
$('more').onclick = () => { limit += PAGE; render(); };

document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  view = b.dataset.view;
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('active', x === b));
  $('report').hidden = view !== 'archive';
  $('sort').hidden = view !== 'all';
  reset();
});

// 深色模式：默认跟随系统，点击按钮在浅色/深色之间切换并记住
$('theme').onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  localStorage.setItem('theme', root.dataset.theme);
};
