let data, view = 'weekly', page = 1;
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

// 项目库和 Skills 是可排序、分页的长列表
const isList = () => view === 'all' || view === 'skills';

function rowsFor() {
  if (view === 'archive') return data.reports.find(r => r.date === $('report').value)?.projects || [];
  if (view === 'skills') return data.skills || [];
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
  else if (isList() && $('sort').value === 'growth' && p.growth != null)
    m.append(el('span', (p.growth_est ? '7 天约 ' : '7 天 ') + (p.growth < 0 ? '' : '+') + fmt(p.growth), 'growth'));
  else m.append(el('span', isList() && $('sort').value === 'updated' ? ago(p.updated) + '更新' : '创建于 ' + day(p.created), 'muted'));
  c.append(m);
  return c;
}

function render() {
  const q = $('search').value.toLowerCase().trim();
  const lang = $('language').value;
  let rows = rowsFor().filter(p => (!lang || p.language === lang) &&
    [p.name, p.summary || '', p.description, ...p.topics].join(' ').toLowerCase().includes(q));
  if (isList()) {
    const s = $('sort').value;
    const key = s === 'recent' ? p => new Date(p.created) : s === 'updated' ? p => new Date(p.updated) :
      s === 'growth' ? p => p.growth ?? -Infinity : p => p.stars;
    rows = [...rows].sort((a, b) => (key(b) - key(a)) || b.stars - a.stars);  // 还没有涨星数据的排在后面，按总 Star
  }

  $('note').textContent =
    view === 'weekly' ? '近 7 天新增 Star 最多的 10 个项目，由每日 Star 快照相减得出。' :
    view === 'archive' ? '每周一保存当时的本周热榜。' :
    view === 'skills' ? `找到 ${fmt(rows.length)} 个 Skills · 打了 agent-skills、claude-skills 等标签或仓库名带 skill 的 GitHub 仓库。` :
    `找到 ${fmt(rows.length)} 个项目 · 来自热门、近期及 AI 方向的 GitHub 仓库。`;

  const box = $('projects');
  box.replaceChildren();
  if (!rows.length) box.append(el('div', '没有匹配的项目，换个关键词试试。', 'empty'));
  // 项目库和 Skills 每页两行，按当前列数算每页条数；热榜和历史周报只有 10 个，不分页
  const size = isList() ? perPage() : rows.length || 1;
  const pages = Math.max(1, Math.ceil(rows.length / size));
  page = Math.min(page, pages);
  const start = (page - 1) * size;
  rows.slice(start, start + size).forEach((p, i) => box.append(card(p, start + i)));
  pager(pages);
}

function perPage() {
  const cols = getComputedStyle($('projects')).gridTemplateColumns.split(' ').length;
  return cols * 2;
}

// 页码：首尾页、当前页前后各 1 页，其余用省略号
function pager(pages) {
  const nav = $('pager');
  nav.replaceChildren();
  nav.hidden = pages <= 1;
  if (pages <= 1) return;
  const go = (n, text, cls) => {
    const b = el('button', text, cls);
    b.type = 'button';
    if (n === page || n < 1 || n > pages) b.disabled = true;
    else b.onclick = () => { page = n; render(); toTop(); };
    if (n === page && cls === 'num') b.setAttribute('aria-current', 'page');
    nav.append(b);
  };
  go(page - 1, '上一页', 'step');
  let last = 0;
  for (let n = 1; n <= pages; n++) {
    if (n !== 1 && n !== pages && Math.abs(n - page) > 1) continue;
    if (n - last > 1) nav.append(el('span', '…', 'gap'));
    go(n, String(n), 'num');
    last = n;
  }
  go(page + 1, '下一页', 'step');
}

// 翻页后回到列表顶部（筛选栏吸顶，滚到统计栏下方即可）
function toTop() {
  const s = document.querySelector('.stats');
  if (scrollY > s.offsetTop + s.offsetHeight) scrollTo({top: s.offsetTop + s.offsetHeight});
}

function reset() { page = 1; if (data) render(); }

fetch('data.json', {cache: 'no-cache'})
  .then(r => { if (!r.ok) throw Error(r.status); return r.json(); })
  .then(d => {
    data = d;
    $('count').textContent = fmt(d.projects.length);
    $('ready').textContent = fmt(d.weekly.length);
    $('skill-count').textContent = fmt((d.skills || []).length);
    $('summarized').textContent = fmt(new Set([...d.projects, ...(d.skills || [])].filter(p => p.summary).map(p => p.name)).size);
    $('date').textContent = day(d.updated);
    [...new Set([...d.projects, ...(d.skills || [])].map(p => p.language))].sort().forEach(l => {
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
// 窗口变宽变窄时列数会变，每页条数随之变化
let cols;
addEventListener('resize', () => {
  if (!data || !isList()) return;
  const n = perPage();
  if (n !== cols) { cols = n; render(); }
});

document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  view = b.dataset.view;
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('active', x === b));
  $('report').hidden = view !== 'archive';
  $('sort').hidden = !isList();
  reset();
});

// 深色模式：默认跟随系统，点击按钮在浅色/深色之间切换并记住
$('theme').onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  localStorage.setItem('theme', root.dataset.theme);
};
