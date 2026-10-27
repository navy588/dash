import { sparkline, lineChart, timeTicks, bars, stackChart, treemap } from './chart.js';

const DATA = 'data';
const FREQ_PREV = { daily: '전일', weekly: '전주', monthly: '전월', quarterly: '전분기' };
const STALE_DAYS = { daily: 5, weekly: 12, monthly: 75, quarterly: 200 };
const SIGMA_THRESHOLD = 2;

const state = { period: 'prev', defs: new Map(), items: new Map(), groups: [], seriesCache: new Map(), detail: null, range: '1y',
  markets: null, market: null, mapPeriod: 'prev', breakdowns: new Set() };

// ── 테마 ───────────────────────────────────────────────
(function initTheme() {
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem('theme'); } catch {}
  if (saved) root.dataset.theme = saved;
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('theme', root.dataset.theme); } catch {}
    rerenderCharts();
  });
})();

// ── 포맷 ───────────────────────────────────────────────
const fmtNum = (v, d) => new Intl.NumberFormat('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);

function fmtValue(def, v) {
  return fmtNum(v, def.decimals ?? 2);
}

function withUnit(def, v) {
  if (def.unit === '$') return '$' + fmtValue(def, v);
  return fmtValue(def, v) + (def.unit === 'pt' ? '' : ' ' + def.unit);
}

function fmtChange(def, c) {
  const v = c.value;
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  const a = Math.abs(v);
  switch (def.change) {
    case 'pct': return `${sign}${fmtNum(a, 2)}%`;
    case 'bp': return `${sign}${fmtNum(a, a >= 100 ? 0 : 1)}bp`;
    case 'pp': return `${sign}${fmtNum(a, 2)}%p`;
    default: return def.unit === '$' ? `${sign}$${fmtNum(a, def.decimals ?? 2)}` : `${sign}${fmtNum(a, def.decimals ?? 2)}${def.unit === 'pt' ? '' : ' ' + def.unit}`;
  }
}

function direction(c) {
  if (!c || Math.abs(c.value) < 1e-9) return { cls: 'flat', arrow: '–', word: '보합' };
  return c.value > 0 ? { cls: 'up', arrow: '▲', word: '상승' } : { cls: 'down', arrow: '▼', word: '하락' };
}

function parseDate(s) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }

function fmtDate(def, s) {
  const d = parseDate(s);
  if (def.freq === 'monthly') return `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
  if (def.freq === 'quarterly') return `${d.getFullYear()}년 ${Math.floor(d.getMonth() / 3) + 1}분기`;
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`;
}

function fmtForecastDate(def, s) {
  const d = parseDate(s);
  if (def.freq === 'quarterly') return `${String(d.getFullYear()).slice(2)}년 ${Math.floor(d.getMonth() / 3) + 1}분기`;
  return `${String(d.getFullYear()).slice(2)}년 말`;
}

function isOutdated(def, item) {
  const age = (Date.now() - parseDate(item.last.date)) / 864e5;
  return age > STALE_DAYS[def.freq];
}

// ── 공통 조각 ─────────────────────────────────────────
const KEY_IDS = ['kospi', 'usdkrw', 'spx', 'nasdaq', 'ust10y', 'wti', 'gold', 'bitcoin'];
const PERIOD_LABEL = { prev: '직전', w1: '1주', m1: '1개월', ytd: '연초', y1: '1년' };
// 발표 주기보다 짧은 기간은 직전 대비와 같은 값이라 표시하지 않음
const SKIP = { daily: [], weekly: ['w1'], monthly: ['w1', 'm1'], quarterly: ['w1', 'm1'] };

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function pill(def, c) {
  const dir = direction(c);
  return el('span', `pill ${dir.cls}`, c ? fmtChange(def, c) : '–');
}

function valueNode(def, v, cls = 'val') {
  const span = el('span', cls);
  span.append((def.unit === '$' ? '$' : '') + fmtValue(def, v));
  if (def.unit && def.unit !== 'pt' && def.unit !== '$') span.appendChild(el('small', null, def.unit));
  return span;
}

// 추세선 색은 그 선이 보여 주는 기간(최근 몇 달)의 방향
function trendCls(item) {
  const s = item.spark || [];
  if (s.length < 2 || s[s.length - 1] === s[0]) return 'flat';
  return s[s.length - 1] > s[0] ? 'up' : 'down';
}

function spark(item, opts = {}) {
  return sparkline(item.spark, { color: `var(--${trendCls(item)})`, ...opts });
}

function badges(def, item) {
  const out = [];
  if (item.sigma != null && Math.abs(item.sigma) >= SIGMA_THRESHOLD && (def.freq === 'daily' || def.freq === 'weekly')) {
    out.push(Object.assign(el('span', `badge hot ${direction(item.changes.prev).cls}`, `평소 ${fmtNum(Math.abs(item.sigma), 1)}배`),
      { title: '직전 대비 변화가 최근 1년 평균 변동폭의 몇 배인지' }));
  }
  if (item.status !== 'ok') out.push(Object.assign(el('span', 'badge warn', '이전 데이터'), { title: item.error || '' }));
  else if (isOutdated(def, item)) out.push(el('span', 'badge warn', '갱신 지연'));
  return out;
}

function subText(def, item) {
  const subs = [];
  if (def.freq !== 'daily') subs.push(`${fmtDate(def, item.last.date)} 발표`);
  if (item.forecast?.points?.length) {
    const p = item.forecast.points[0];
    subs.push(`전망 ${fmtForecastDate(def, p.date)} ${withUnit(def, p.value)}`);
  }
  return subs.join(' · ');
}

// 발표 일정: item.release = { last, next, est } (월간·분기 지표)
const WEEKDAY = '일월화수목금토';
const fmtMD = s => { const d = parseDate(s); return `${d.getMonth() + 1}/${d.getDate()}(${WEEKDAY[d.getDay()]})`; };
function daysUntil(s) {
  const t = new Date(); t.setHours(0, 0, 0, 0);
  return Math.round((parseDate(s) - t) / 864e5);
}

function releaseNode(item) {
  const r = item.release;
  if (!r?.next) return null;
  const n = daysUntil(r.next);
  if (n < 0) return null;
  const line = el('span', 'mc-rel');
  line.append(`다음 발표 ${fmtMD(r.next)}${r.est ? ' 예정' : ''}`);
  if (n <= 3) line.appendChild(el('span', `dday${n === 0 ? ' today' : ''}`, n === 0 ? '오늘 발표' : `D-${n}`));
  line.title = `${r.last ? `이번 발표 ${fmtMD(r.last)} · ` : ''}다음 발표 ${fmtMD(r.next)}${r.est ? ' (평소 일정으로 추정)' : ''}`;
  return line;
}

function releaseText(item) {
  const r = item.release;
  if (!r) return '';
  const parts = [];
  if (r.last) parts.push(`이번 발표 ${fmtMD(r.last)}`);
  if (r.next && daysUntil(r.next) >= 0) parts.push(`다음 발표 ${fmtMD(r.next)}${r.est ? ' 예정(추정)' : ''}`);
  return parts.join(' · ');
}

function ariaFor(def, item, period = 'prev') {
  const c = item.changes[period];
  const label = period === 'prev' ? `${FREQ_PREV[def.freq]} 대비` : `${PERIOD_LABEL[period]} 대비`;
  return `${def.name} ${withUnit(def, item.last.value)}, ${label} ${c ? fmtChange(def, c) : '변화 없음'}, ${fmtDate(def, item.last.date)} 기준. 자세히 보기`;
}

// 지표 옆 동그란 표식 (나라·자산을 한눈에)
const AVATAR = {
  nikkei: 'JP', shanghai: 'CN', hangseng: 'HK', taiex: 'TW', stoxx50: 'EU', dax: 'DE', ftse: 'UK',
  usdkrw: '₩', jpykrw: '¥', dxy: '$', eurusd: '€', usdjpy: '¥', usdcny: '元', gbpusd: '£',
  wti: 'OIL', brent: 'OIL', ttf: 'GAS', natgas: 'GAS', jkm: 'LNG', ironore: 'Fe', copper: 'Cu',
  aluminum: 'Al', nickel: 'Ni', gold: 'Au', silver: 'Ag', bitcoin: '₿', krbase: 'KR', qld: '2x', tqqq: '3x',
};
const GROUP_AVATAR = { macro: 'US', krmacro: 'KR', korea: 'KR', us: 'US', rates: 'US' };
function avatar(def) {
  const t = AVATAR[def.id] || GROUP_AVATAR[def.group] || def.name.slice(0, 2);
  const a = el('span', `av g-${def.group}`, t);
  a.setAttribute('aria-hidden', 'true');
  if (t.length >= 3) a.classList.add('sm');
  return a;
}

const isMacro = def => def.group === 'macro' || def.group === 'krmacro';
const periodFor = def => (SKIP[def.freq].includes(state.period) ? null : state.period);

// ── 주요 지표 카드 ─────────────────────────────────────
function renderKeys() {
  const box = document.getElementById('keys');
  box.replaceChildren();
  for (const id of KEY_IDS) {
    const def = state.defs.get(id), item = state.items.get(id);
    if (!def || !item) continue;
    const b = el('button', 'keycard');
    b.type = 'button';
    b.dataset.id = id;
    b.setAttribute('aria-label', ariaFor(def, item));
    const top = el('div', 'kc-top');
    top.append(avatar(def), el('span', 'kc-name', def.name));
    const mid = el('div', 'kc-mid');
    mid.append(valueNode(def, item.last.value, 'kc-val'), pill(def, item.changes.prev));
    const sp = item.spark || [];
    const range = el('div', 'kc-range');
    if (sp.length > 1) {
      range.append(el('span', null, `최저 ${fmtValue(def, Math.min(...sp))}`), el('span', null, `최고 ${fmtValue(def, Math.max(...sp))}`));
    }
    b.append(top, mid, spark(item, { width: 200, height: 64, area: true }), range);
    b.addEventListener('click', () => openDetail(id));
    box.appendChild(b);
  }
}

// ── 분야별 시세 ─────────────────────────────────────────
function changeNode(def, item) {
  const period = periodFor(def);
  const p = period ? pill(def, item.changes[period]) : el('span', 'pill na', '–');
  if (period === 'prev' || !period) p.title = `${FREQ_PREV[def.freq]} 대비`;
  return p;
}

function listRow(def, item) {
  const b = el('button', 'lrow ind');
  b.type = 'button';
  b.dataset.id = def.id;
  b.setAttribute('aria-label', ariaFor(def, item, periodFor(def) || 'prev'));

  const left = el('span', 'lr-left');
  const nm = el('span', 'lr-name');
  nm.append(el('span', 'nm-text', def.name), ...badges(def, item));
  left.appendChild(nm);
  const sub = subText(def, item);
  left.appendChild(el('span', 'lr-sub', sub || fmtDate(def, item.last.date)));

  const right = el('span', 'lr-right');
  right.append(valueNode(def, item.last.value, 'lr-val'), changeNode(def, item));
  b.append(avatar(def), left, spark(item, { width: 120, height: 36, area: true }), right);
  b.addEventListener('click', () => openDetail(def.id));
  return b;
}

// 경제지표는 카드: 최근 발표치 막대와 이전 발표치
function macroCard(def, item) {
  const b = el('button', 'mcard ind');
  b.type = 'button';
  b.dataset.id = def.id;
  b.setAttribute('aria-label', ariaFor(def, item, periodFor(def) || 'prev'));
  const top = el('span', 'mc-top');
  top.append(el('span', 'mc-name', def.name), ...badges(def, item));
  const mid = el('span', 'mc-mid');
  mid.append(valueNode(def, item.last.value, 'mc-val'), changeNode(def, item));
  const prev = item.changes.prev;
  const sub = [`${fmtDate(def, item.last.date)}${def.freq === 'daily' ? ' 기준' : ''}${item.prelim ? ' ' + item.prelim : ''}`];
  if (prev?.ref != null) sub.push(`이전 ${withUnit(def, prev.ref)}`);
  if (item.forecast?.points?.length) sub.push(subText(def, item).split(' · ').pop());
  const sp = (item.spark || []).slice(def.freq === 'quarterly' ? -12 : def.freq === 'monthly' ? -24 : -60);
  const chart = def.freq === 'daily' || def.freq === 'weekly'
    ? sparkline(sp, { width: 240, height: 48, color: `var(--${trendCls(item)})`, area: true })
    : bars(sp, { width: 240, height: 48, color: `var(--${trendCls({ spark: sp.slice(-2) })})`, hatched: item.prelim ? [sp.length - 1] : [] });
  b.append(top, mid, chart, el('span', 'mc-sub', sub.join(' · ')));
  const rel = releaseNode(item);
  if (rel) b.appendChild(rel);
  b.addEventListener('click', () => openDetail(def.id));
  return b;
}

function renderTabs() {
  const tabs = document.getElementById('tabs');
  tabs.replaceChildren();
  for (const g of visibleGroups()) {
    const t = el('a', 'tab', g.name);
    t.href = `#g-${g.id}`;
    t.dataset.group = g.id;
    t.addEventListener('click', e => {
      e.preventDefault();
      document.getElementById(`g-${g.id}`).scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
      setActiveTab(g.id);
    });
    tabs.appendChild(t);
  }
}

function setActiveTab(id) {
  for (const t of document.querySelectorAll('#tabs .tab')) {
    const on = t.dataset.group === id;
    t.classList.toggle('on', on);
    if (on) t.setAttribute('aria-current', 'true'); else t.removeAttribute('aria-current');
    if (on && t.scrollIntoView && t.parentElement.scrollWidth > t.parentElement.clientWidth) {
      t.parentElement.scrollTo({ left: t.offsetLeft - 16, behavior: 'smooth' });
    }
  }
}

function visibleGroups() {
  return state.groups.filter(g => [...state.defs.values()].some(d => d.group === g.id && state.items.get(d.id)?.last));
}

let spy;
function renderGroups() {
  const root = document.getElementById('groups');
  root.replaceChildren();
  for (const g of visibleGroups()) {
    const defs = [...state.defs.values()].filter(d => d.group === g.id && state.items.get(d.id)?.last);
    const sec = el('section', 'gsec');
    sec.id = `g-${g.id}`;
    sec.dataset.group = g.id;
    const head = el('div', 'gsec-head');
    head.append(el('h3', null, g.name), el('span', 'count', `${defs.length}`));
    if (state.breakdowns.size && defs.some(d => state.breakdowns.has(d.id))) head.appendChild(el('span', 'tag', '분해 차트'));
    sec.appendChild(head);
    if (isMacro(defs[0])) {
      const grid = el('div', 'mgrid');
      for (const d of defs) grid.appendChild(macroCard(d, state.items.get(d.id)));
      sec.appendChild(grid);
    } else {
      const card = el('div', 'card list');
      for (const d of defs) card.appendChild(listRow(d, state.items.get(d.id)));
      sec.appendChild(card);
    }
    root.appendChild(sec);
  }
  const dates = [...state.defs.values()].filter(d => d.freq === 'daily' && state.items.get(d.id)).map(d => state.items.get(d.id).last.date).sort();
  root.appendChild(el('p', 'list-foot',
    (dates.length ? `${fmtDate({ freq: 'daily' }, dates[dates.length - 1])} 기준 · ` : '') +
    `변화는 ${state.period === 'prev' ? '직전 발표(전일·전주·전월) 대비' : PERIOD_LABEL[state.period] + ' 대비'} · 추세선은 최근 3개월`));

  // 스크롤 위치에 맞춰 분야 탭 강조
  spy?.disconnect();
  spy = new IntersectionObserver(entries => {
    const vis = entries.filter(e => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (vis) setActiveTab(vis.target.dataset.group);
  }, { rootMargin: '-140px 0px -60% 0px' });
  for (const sec of root.querySelectorAll('.gsec')) spy.observe(sec);
}

document.getElementById('period').addEventListener('click', e => {
  const b = e.target.closest('button[data-period]');
  if (!b) return;
  state.period = b.dataset.period;
  for (const x of document.querySelectorAll('#period button')) x.setAttribute('aria-checked', String(x === b));
  renderGroups();
});

// ── 시장 지도 (트리맵) ──────────────────────────────────
const MAP_SCALE = { prev: 3, w1: 6, m1: 10, ytd: 30, y1: 40 };
const MAP_INDEX = { spx: ['spx', 'S&P 500 지수'], nasdaq: ['nasdaq', '나스닥 종합지수'], kospi: ['kospi', '코스피 지수'], kosdaq: ['kosdaq', '코스닥 지수'] };
const MAP_PERIOD_LABEL = { prev: '하루', w1: '1주', m1: '1개월', ytd: '연초 대비', y1: '1년' };

function heatColor(v, period) {
  if (v == null) return { bg: 'var(--tile)', ink: 'var(--ink-2)' };
  const k = Math.min(Math.abs(v) / MAP_SCALE[period], 1);
  const pct = Math.round(18 + k * 72);
  const hue = v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : 'var(--tile)';
  return { bg: `color-mix(in oklab, ${hue} ${pct}%, var(--tile))`, ink: pct > 48 ? '#fff' : 'var(--ink)' };
}

const fmtPct = v => (v == null ? '–' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${fmtNum(Math.abs(v), 2)}%`);
const fmtCap = (v, krw) => krw ? `${fmtNum(v / 1e12, 1)}조원` : `$${fmtNum(v / 1e9, 0)}B`;

function drawTreemap(box, market, period, { compact = false } = {}) {
  const krw = market.id === 'kospi' || market.id === 'kosdaq';
  const bySector = new Map();
  for (const it of market.items) {
    if (!bySector.has(it.s)) bySector.set(it.s, []);
    const v = it.chg[period];
    const c = heatColor(v, period);
    bySector.get(it.s).push({
      value: it.cap, label: krw ? it.n : it.t, sub: fmtPct(v), color: c.bg, ink: c.ink,
      tip: tip => {
        const h = el('strong', null, `${it.n}${krw ? '' : ` (${it.t})`}`);
        const r1 = el('div', 'row');
        r1.append(el('span', `big ${v > 0 ? 'up' : v < 0 ? 'down' : 'flat'}`, fmtPct(v)), el('span', 'muted', MAP_PERIOD_LABEL[period]));
        const r2 = el('div', 'muted', `${it.s} · 비중 ${fmtNum(it.w, 2)}% · 시총 ${fmtCap(it.cap, krw)}`);
        const r3 = el('div', 'muted', `${krw ? '' : '$'}${fmtNum(it.price, krw ? 0 : 2)}${krw ? '원' : ''} · ${it.date.replaceAll('-', '.')}`);
        tip.append(h, r1, r2, r3);
      },
    });
  }
  treemap(box, [...bySector].map(([name, items]) => ({ name, items })), { header: compact ? 0 : 18 });
}

function mapSide(market, period) {
  const side = document.getElementById('map-side');
  side.replaceChildren();
  const krw = market.id === 'kospi' || market.id === 'kosdaq';
  const items = market.items.filter(i => i.chg[period] != null);
  // 지수 기여도 ≈ 비중 × 등락률
  const contrib = items.map(i => ({ ...i, c: (i.w * i.chg[period]) / 100 })).sort((a, b) => b.c - a.c);
  const total = contrib.reduce((a, b) => a + b.c, 0);
  // 지수 실제 등락이 있으면 그것을 크게, 지도 종목 합산은 설명과 함께 작게
  const [idxId, idxName] = MAP_INDEX[market.id] || [];
  const idx = state.items.get(idxId)?.changes?.[period];
  const cls = v => (v > 0 ? 'up' : v < 0 ? 'down' : '');
  const sum = el('div', 'ms-sum');
  const covered = `시가총액 상위 ${items.length}개 종목`;
  if (idx) {
    sum.append(el('span', 'muted', `${idxName} ${MAP_PERIOD_LABEL[period]} 등락`), el('strong', cls(idx.value), fmtPct(idx.value)));
    const note = el('span', 'ms-note');
    note.append(`지도에 담은 ${covered}만 합치면 `, el('b', cls(total), fmtPct(total)), '입니다. 나머지 종목이 빠져 있어 지수와 조금 다를 수 있습니다.');
    sum.appendChild(note);
  } else {
    sum.append(el('span', 'muted', `${covered} 합산 등락 (${MAP_PERIOD_LABEL[period]})`), el('strong', cls(total), fmtPct(total)),
      el('span', 'ms-note', '지도에 담은 종목의 등락률을 시가총액 비중대로 더한 값으로, 지수 등락의 근사치입니다.'));
  }
  side.appendChild(sum);

  const list = (title, rows) => {
    const sec = el('div', 'ms-block');
    sec.appendChild(el('h4', null, title));
    const mx = Math.max(...contrib.map(r => Math.abs(r.c)), 1e-9);
    for (const r of rows) {
      const row = el('div', 'ms-row');
      const bar = el('span', `ms-bar ${r.c > 0 ? 'up' : 'down'}`);
      bar.style.width = `${Math.max(4, (Math.abs(r.c) / mx) * 100)}%`;
      const name = el('span', 'ms-name', krw ? r.n : `${r.n}`);
      const v = el('span', `ms-v ${r.chg[period] > 0 ? 'up' : r.chg[period] < 0 ? 'down' : ''}`, fmtPct(r.chg[period]));
      const barWrap = el('span', 'ms-barwrap');
      barWrap.appendChild(bar);
      row.append(name, barWrap, v);
      row.title = `지수 기여 ${r.c >= 0 ? '+' : '−'}${fmtNum(Math.abs(r.c), 2)}%p · 비중 ${fmtNum(r.w, 2)}%`;
      sec.appendChild(row);
    }
    side.appendChild(sec);
  };
  list('지수를 끌어올린 종목', contrib.filter(r => r.c > 0).slice(0, 5));
  list('지수를 끌어내린 종목', contrib.filter(r => r.c < 0).reverse().slice(0, 5));

  // 업종별 가중 등락
  const sectors = new Map();
  for (const i of items) {
    const s = sectors.get(i.s) || { w: 0, c: 0 };
    s.w += i.w; s.c += i.w * i.chg[period];
    sectors.set(i.s, s);
  }
  const sec = el('div', 'ms-block');
  sec.appendChild(el('h4', null, '업종별 등락'));
  const rows = [...sectors].map(([n, s]) => ({ n, v: s.c / s.w, w: s.w })).sort((a, b) => b.v - a.v);
  const mx = Math.max(...rows.map(r => Math.abs(r.v)), 1e-9);
  for (const r of rows) {
    const row = el('div', 'ms-row');
    const barWrap = el('span', 'ms-barwrap center');
    const bar = el('span', `ms-bar ${r.v > 0 ? 'up' : 'down'}`);
    bar.style.width = `${(Math.abs(r.v) / mx) * 50}%`;
    bar.style[r.v > 0 ? 'left' : 'right'] = '50%';
    barWrap.appendChild(bar);
    row.append(el('span', 'ms-name', r.n), barWrap, el('span', `ms-v ${r.v > 0 ? 'up' : r.v < 0 ? 'down' : ''}`, fmtPct(r.v)));
    row.title = `비중 ${fmtNum(r.w, 1)}%`;
    sec.appendChild(row);
  }
  side.appendChild(sec);
}

function renderMap() {
  if (!state.markets?.markets?.length) return;
  const market = state.markets.markets.find(m => m.id === state.market) || state.markets.markets[0];
  state.market = market.id;
  const seg = document.getElementById('map-market');
  if (!seg.children.length) {
    for (const m of state.markets.markets) {
      const b = el('button', null, m.name);
      b.type = 'button'; b.setAttribute('role', 'radio'); b.dataset.market = m.id;
      b.addEventListener('click', () => { state.market = m.id; try { localStorage.setItem('market', m.id); } catch {} renderMap(); });
      seg.appendChild(b);
    }
  }
  for (const b of seg.children) b.setAttribute('aria-checked', String(b.dataset.market === market.id));
  document.getElementById('map-section').hidden = false;
  drawTreemap(document.getElementById('map'), market, state.mapPeriod);
  const d = market.as_of.split('-');
  document.getElementById('map-note').textContent =
    `${market.name} 시가총액 상위 ${market.items.length}종목 · 상자 크기 = 시가총액 비중 · ${+d[1]}월 ${+d[2]}일 종가`;
  const sc = document.getElementById('map-scale');
  sc.replaceChildren();
  const S = MAP_SCALE[state.mapPeriod];
  for (const v of [-S, -S / 2, 0, S / 2, S]) {
    const c = heatColor(v || null, state.mapPeriod);
    const i = el('i', null, `${v > 0 ? '+' : v < 0 ? '−' : ''}${fmtNum(Math.abs(v), S < 5 ? 1 : 0)}%`);
    i.style.background = c.bg; i.style.color = c.ink;
    sc.appendChild(i);
  }
  mapSide(market, state.mapPeriod);
}

document.getElementById('map-period').addEventListener('click', e => {
  const b = e.target.closest('button[data-period]');
  if (!b) return;
  state.mapPeriod = b.dataset.period;
  for (const x of document.querySelectorAll('#map-period button')) x.setAttribute('aria-checked', String(x === b));
  renderMap();
});

async function loadMarkets() {
  try {
    const r = await fetch(`${DATA}/breakdown/markets.json`, { cache: 'no-cache' });
    if (!r.ok) return;
    state.markets = await r.json();
    try { state.market = localStorage.getItem('market'); } catch {}
    renderMap();
  } catch {}
}

// ── 검색 ───────────────────────────────────────────────
const searchDlg = document.getElementById('search');
const searchInput = document.getElementById('search-input');
const searchList = document.getElementById('search-results');
let searchSel = 0;
function renderSearch() {
  const q = searchInput.value.trim().toLowerCase().replace(/\s+/g, '');
  const groupName = Object.fromEntries(state.groups.map(g => [g.id, g.name]));
  const hits = [...state.defs.values()].filter(d => state.items.get(d.id)?.last).filter(d => {
    if (!q) return true;
    const hay = `${d.name}${d.id}${groupName[d.group]}${d.news || ''}`.toLowerCase().replace(/\s+/g, '');
    return hay.includes(q);
  }).slice(0, 30);
  searchSel = Math.min(searchSel, Math.max(hits.length - 1, 0));
  searchList.replaceChildren();
  hits.forEach((d, i) => {
    const item = state.items.get(d.id);
    const li = el('li', 'sr');
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', String(i === searchSel));
    li.dataset.id = d.id;
    const mid = el('span', 'sr-mid');
    mid.append(el('span', 'sr-name', d.name), el('span', 'sr-group', groupName[d.group]));
    const right = el('span', 'sr-right');
    right.append(valueNode(d, item.last.value, 'sr-val'), pill(d, item.changes.prev));
    li.append(avatar(d), mid, right);
    li.addEventListener('click', () => { searchDlg.close(); openDetail(d.id); });
    li.addEventListener('pointermove', () => { if (searchSel !== i) { searchSel = i; renderSearch(); } });
    searchList.appendChild(li);
  });
  if (!hits.length) searchList.appendChild(el('li', 'sr-empty', '찾는 지표가 없습니다.'));
}
function openSearch() {
  searchInput.value = '';
  searchSel = 0;
  renderSearch();
  searchDlg.showModal();
  searchInput.focus();
}
document.getElementById('search-open').addEventListener('click', openSearch);
searchInput.addEventListener('input', () => { searchSel = 0; renderSearch(); });
searchInput.addEventListener('keydown', e => {
  const n = searchList.querySelectorAll('.sr').length;
  if (e.key === 'ArrowDown') { searchSel = Math.min(n - 1, searchSel + 1); renderSearch(); e.preventDefault(); }
  if (e.key === 'ArrowUp') { searchSel = Math.max(0, searchSel - 1); renderSearch(); e.preventDefault(); }
  if (e.key === 'Enter') {
    const li = searchList.querySelectorAll('.sr')[searchSel];
    // 같은 Enter가 새로 열린 상세 창의 닫기 버튼을 누르지 않도록 다음 틱에 엽니다
    e.preventDefault();
    if (li) { searchDlg.close(); setTimeout(() => openDetail(li.dataset.id)); }
  }
});
searchDlg.addEventListener('click', e => { if (e.target === searchDlg) searchDlg.close(); });
addEventListener('keydown', e => {
  if ((e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))) && !e.target.closest('input, textarea') && !document.querySelector('dialog[open]')) {
    e.preventDefault();
    openSearch();
  }
});

// ── 오늘의 브리핑 ───────────────────────────────────────
// 브리핑은 없어도 화면이 동작하도록 실패를 무시합니다 (pipeline/briefing.py 가 생성)
async function renderBriefing() {
  let brief;
  try {
    const r = await fetch(`${DATA}/briefing.json`, { cache: 'no-cache' });
    if (!r.ok) return;
    brief = await r.json();
  } catch { return; }
  const d = parseDate(brief.as_of);
  document.getElementById('briefing-asof').textContent = `오늘의 시장 · ${d.getMonth() + 1}월 ${d.getDate()}일 마감`;
  const mood = document.getElementById('briefing-mood');
  if (brief.mood && brief.mood !== '혼조') {
    mood.textContent = brief.mood;
    mood.className = `mood ${brief.mood === '위험회피' ? 'off' : 'on'}`;
    mood.hidden = false;
  }
  document.getElementById('briefing-headline').textContent = brief.headline.replace(/^(위험회피|위험선호) · /, '');

  const reads = document.getElementById('briefing-reads');
  reads.replaceChildren(...(brief.reads || []).map(t => el('li', null, t)));

  const list = document.getElementById('briefing-list');
  list.replaceChildren();
  for (const s of brief.stories || []) {
    const def = state.defs.get(s.id), item = state.items.get(s.id);
    if (!def || !item) continue;
    const li = el('li', 'story');
    const btn = el('button', 'story-main');
    btn.type = 'button';
    btn.setAttribute('aria-label', ariaFor(def, item));
    btn.addEventListener('click', () => openDetail(s.id));
    const top = el('span', 'st-top');
    top.append(avatar(def), el('span', 'st-name', def.name), ...badges(def, item).filter(x => x.classList.contains('hot')));
    const mid = el('span', 'st-mid');
    mid.append(valueNode(def, item.last.value, 'st-val'), pill(def, item.changes.prev));
    btn.append(top, mid, spark(item, { width: 280, height: 64, area: true }));
    li.appendChild(btn);
    const ctx = s.text.split(' · ').slice(1).join(', ').split(', ').filter(Boolean);
    if (ctx.length) {
      const chips = el('div', 'chips');
      for (const c of ctx) chips.appendChild(el('span', 'chip', c));
      li.appendChild(chips);
    }
    const h = s.headlines?.[0];
    if (h) {
      const p = el('p', 'why');
      p.appendChild(el('span', 'why-label', '왜?'));
      if (/^https?:\/\//.test(h.url)) {
        const a = el('a', null, h.title);
        a.href = h.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        p.appendChild(a);
      } else p.append(h.title);
      if (h.source) p.appendChild(el('span', 'src', h.source));
      if (s.headlines.length > 1) p.appendChild(el('span', 'src', ` 외 ${s.headlines.length - 1}건`));
      li.appendChild(p);
    }
    list.appendChild(li);
  }
  list.hidden = !list.children.length;

  const sig = document.getElementById('briefing-signals');
  sig.replaceChildren(...(brief.signals || []).map(t => el('li', null, t)));
  sig.closest('section').hidden = !sig.children.length;
  document.getElementById('briefing-block').hidden = false;
}

// ── 금리 커브 ───────────────────────────────────────────
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function renderCurve(curve) {
  const block = document.getElementById('curve-block');
  if (!curve || curve.length < 3) { block.hidden = true; return; }
  const series = [
    { name: `현재 (${curve[0].now_date.replaceAll('-', '.')})`, color: cssVar('--series-1'), values: curve.map(p => p.now), markers: true },
    { name: '1개월 전', color: cssVar('--series-2'), values: curve.map(p => p.m1), markers: true },
    { name: '1년 전', color: cssVar('--series-3'), values: curve.map(p => p.y1), markers: true },
  ];
  const legend = document.getElementById('curve-legend');
  legend.replaceChildren();
  for (const s of series) {
    const span = document.createElement('span');
    const i = document.createElement('i');
    i.style.background = s.color;
    span.append(i, s.name);
    legend.appendChild(span);
  }
  const xs = curve.map((_, i) => i);
  lineChart(document.getElementById('curve-chart'), {
    xs, series,
    formatX: (_, i) => `만기 ${curve[i].label}`,
    formatY: v => `${fmtNum(v, 2)}%`,
    xTicks: () => curve.map((p, i) => ({ x: i, label: p.label })),
  });
}

// ── 상세 ───────────────────────────────────────────────
async function loadSeries(id) {
  if (!state.seriesCache.has(id)) {
    state.seriesCache.set(id, fetch(`${DATA}/series/${id}.json`).then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }));
  }
  return state.seriesCache.get(id);
}

state.notes = new Map();
async function loadNotes(id) {
  if (!state.notes.has(id)) {
    try {
      const r = await fetch(`${DATA}/notes/${id}.json`);
      state.notes.set(id, r.ok ? (await r.json()).events : []);
    } catch { state.notes.set(id, []); }
  }
  return state.notes.get(id);
}

function headlineList(ev, { links = false } = {}) {
  const ul = document.createElement('ul');
  ul.className = 'headlines';
  for (const h of ev.headlines.slice(0, 3)) {
    const li = document.createElement('li');
    if (links && /^https?:\/\//.test(h.url)) {
      const a = document.createElement('a');
      a.href = h.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      a.textContent = h.title;
      li.appendChild(a);
    } else {
      li.textContent = h.title;
    }
    if (h.source) {
      const src = document.createElement('span');
      src.className = 'muted';
      src.textContent = ` · ${h.source}`;
      li.appendChild(src);
    }
    ul.appendChild(li);
  }
  return ul;
}

const RANGE_DAYS = { '3m': 92, '1y': 366, '3y': 3 * 366, '10y': 10 * 366, all: Infinity };

async function openDetail(id, { focus } = {}) {
  const def = state.defs.get(id), item = state.items.get(id);
  const dlg = document.getElementById('detail');
  state.detail = id;
  document.getElementById('detail-title').textContent = def.name;
  const c = item.changes.prev;
  const dir = direction(c);
  const val = document.getElementById('detail-value');
  val.replaceChildren(valueNode(def, item.last.value, 'dv-val'), pill(def, c));
  document.getElementById('detail-sub').textContent = [
    `${FREQ_PREV[def.freq]} 대비 ${c ? dir.word : '–'}`,
    `${fmtDate(def, item.last.date)} ${item.prelim ? item.prelim + '(이후 수정될 수 있음)' : '기준'}`,
    item.forecast?.points?.length ? subText(def, item).split(' · ').pop() : '',
    releaseText(item),
  ].filter(Boolean).join(' · ');
  if (!dlg.open) dlg.showModal();
  if (def.freq !== 'daily' && def.freq !== 'weekly' && state.range === '3m') setRange('1y');
  const chartBox = document.getElementById('detail-chart');
  chartBox.textContent = '불러오는 중…';
  document.getElementById('detail-breakdown').hidden = true;
  document.getElementById('detail-stats').replaceChildren();
  try {
    const [s] = await Promise.all([loadSeries(id), loadNotes(id)]);
    if (state.detail === id) drawDetail(def, s);
    renderStats(def, s);
    await renderBreakdown(def);
    if (focus === 'breakdown' && state.detail === id) document.getElementById('detail-breakdown').scrollIntoView({ block: 'start' });
  } catch {
    chartBox.textContent = '시계열을 불러오지 못했습니다.';
  }
}

function drawDetail(def, s) {
  const item = state.items.get(def.id);
  const lastT = parseDate(s.dates[s.dates.length - 1]).getTime();
  const from = lastT - RANGE_DAYS[state.range] * 864e5;
  const xs = [], vals = [], dates = [];
  s.dates.forEach((d, i) => {
    const t = parseDate(d).getTime();
    if (t >= from) { xs.push(t); vals.push(s.values[i]); dates.push(d); }
  });
  const nActual = xs.length;

  // 전망치: 마지막 실제값에서 이어지는 점선
  const trend = vals.length > 1 ? (vals[vals.length - 1] >= vals[0] ? 'up' : 'down') : 'flat';
  const series = [{ name: def.name, color: cssVar(`--${trend}`), values: vals.slice(), area: true }];
  const fc = item?.forecast?.points || [];
  if (fc.length) {
    const fvals = new Array(nActual).fill(null);
    fvals[nActual - 1] = vals[nActual - 1];
    for (const p of fc) {
      xs.push(parseDate(p.date).getTime()); dates.push(p.date);
      series[0].values.push(null); fvals.push(p.value);
    }
    series.push({ name: `전망 (${item.forecast.label})`, color: cssVar('--ink-3'), values: fvals, dashed: true, markers: true });
  }

  // 큰 움직임과 관련 뉴스
  const events = {};
  const notes = (state.notes.get(def.id) || []).filter(ev => ev.headlines?.length);
  const idxByDate = new Map(dates.map((d, i) => [d, i]));
  const evText = ev => {
    if (ev.change == null) return '관련 뉴스';
    const dir = direction({ value: ev.change });
    const sig = ev.sigma != null ? ` · 평소의 ${fmtNum(Math.abs(ev.sigma), 1)}배` : '';
    return `${FREQ_PREV[def.freq]} 대비 ${dir.arrow} ${fmtChange(def, { value: ev.change })}${sig}`;
  };
  for (const ev of notes) {
    const i = idxByDate.get(ev.date);
    if (i == null || i >= nActual) continue;
    const dir = direction(ev.change == null ? null : { value: ev.change });
    events[i] = {
      color: `var(--${dir.cls})`,
      mark: ev.sigma != null && Math.abs(ev.sigma) >= SIGMA_THRESHOLD,
      render: tip => {
        const head = document.createElement('div');
        head.className = `why ${dir.cls}`;
        head.textContent = `${evText(ev)} · 왜 움직였나`;
        tip.append(head, headlineList(ev));
      },
    };
  }

  lineChart(document.getElementById('detail-chart'), {
    xs, series, events,
    formatX: (_, i) => fmtDate(def, dates[i]) + (i >= nActual ? ' (전망)' : ''),
    formatY: v => (def.unit === '$' ? '$' : '') + fmtValue(def, v) + (def.unit === '%' || def.unit === '%p' ? '%' : ''),
    xTicks: timeTicks,
    zeroLine: vals.some(v => v < 0) && vals.some(v => v > 0),
    extremes: true,
  });

  const legend = document.getElementById('detail-legend');
  legend.replaceChildren();
  if (fc.length) {
    for (const [label, color, dashed] of [['실제', series[0].color, false], [`전망 · ${item.forecast.label}`, cssVar('--ink-3'), true]]) {
      const span = document.createElement('span');
      const i = document.createElement('i');
      i.style.background = dashed ? `repeating-linear-gradient(90deg, ${color} 0 5px, transparent 5px 9px)` : color;
      span.append(i, label);
      legend.appendChild(span);
    }
  }
  if (Object.keys(events).length) {
    const span = document.createElement('span');
    span.className = 'muted';
    span.textContent = '차트에 커서를 대면 그날 왜 움직였는지 관련 뉴스가 함께 나옵니다 (● 평소보다 크게 움직인 날)';
    legend.appendChild(span);
  }

  // 시점별 변동 이유 목록 (링크 포함, 최근 순)
  const list = document.getElementById('detail-events');
  list.replaceChildren();
  const shown = notes.filter(ev => idxByDate.has(ev.date) && idxByDate.get(ev.date) < nActual).reverse().slice(0, 30);
  list.hidden = !shown.length;
  if (shown.length) {
    const h = document.createElement('h3');
    h.textContent = '날짜별 변화와 관련 뉴스 (최근 30개)';
    list.appendChild(h);
    for (const ev of shown) {
      const dir = direction(ev.change == null ? null : { value: ev.change });
      const row = document.createElement('div');
      row.className = 'event-row';
      const when = document.createElement('div');
      when.className = `when ${dir.cls}`;
      when.textContent = `${fmtDate(def, ev.date)} · ${evText(ev)}`;
      row.append(when, headlineList(ev, { links: true }));
      list.appendChild(row);
    }
  }

  const table = document.getElementById('detail-table');
  table.replaceChildren();
  const head = table.createTHead().insertRow();
  for (const t of ['날짜', `값${def.unit && def.unit !== 'pt' ? ` (${def.unit})` : ''}`]) {
    const th = document.createElement('th'); th.textContent = t; head.appendChild(th);
  }
  const body = table.createTBody();
  for (let i = dates.length - 1; i >= Math.max(0, dates.length - 120); i--) {
    const r = body.insertRow();
    r.insertCell().textContent = fmtDate(def, dates[i]);
    r.insertCell().textContent = fmtValue(def, vals[i]);
  }
}

// 요약 숫자: 기간별 변화와 52주 범위
function renderStats(def, s) {
  const box = document.getElementById('detail-stats');
  box.replaceChildren();
  const item = state.items.get(def.id);
  for (const k of ['w1', 'm1', 'ytd', 'y1']) {
    if (SKIP[def.freq].includes(k) || !item.changes[k]) continue;
    const c = el('div', 'stat');
    c.append(el('span', 'muted', `${PERIOD_LABEL[k]}${k === 'ytd' ? '' : ' 전'} 대비`), pill(def, item.changes[k]));
    box.appendChild(c);
  }
  const lastT = parseDate(s.dates[s.dates.length - 1]).getTime();
  const yr = s.values.filter((v, i) => parseDate(s.dates[i]).getTime() >= lastT - 366 * 864e5);
  if (yr.length > 3) {
    const lo = Math.min(...yr), hi = Math.max(...yr), v = item.last.value;
    const c = el('div', 'stat range52');
    const bar = el('span', 'r52');
    const dot = el('i');
    dot.style.left = `${hi > lo ? ((v - lo) / (hi - lo)) * 100 : 50}%`;
    bar.appendChild(dot);
    const lab = el('span', 'r52-lab');
    lab.append(el('span', null, withUnit(def, lo)), el('span', null, withUnit(def, hi)));
    c.append(el('span', 'muted', '1년 범위'), bar, lab);
    box.appendChild(c);
  }
}

// 분해 차트 (breakdown/<id>.json) 와 지수 구성종목 지도
const PART_COLORS = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5'];
const breakdownCache = new Map();
async function renderBreakdown(def) {
  const box = document.getElementById('detail-breakdown');
  box.replaceChildren();
  box.hidden = true;
  const market = state.markets?.markets?.find(m => m.id === def.id);
  if (market) {
    box.appendChild(el('h3', null, `${market.name} 구성종목 지도`));
    box.appendChild(el('p', 'muted small', `시가총액 상위 ${market.items.length}종목 · 상자 크기 = 비중 · 색 = ${FREQ_PREV.daily} 대비 등락`));
    const tm = el('div', 'treemap small');
    box.appendChild(tm);
    box.hidden = false;
    drawTreemap(tm, market, 'prev', { compact: true });
    return;
  }
  if (!state.breakdowns.has(def.id)) return;
  let data = breakdownCache.get(def.id);
  if (!data) {
    try {
      const r = await fetch(`${DATA}/breakdown/${def.id}.json`);
      if (!r.ok) return;
      data = await r.json();
      breakdownCache.set(def.id, data);
    } catch { return; }
  }
  if (state.detail !== def.id) return;
  box.appendChild(el('h3', null, data.title));
  box.hidden = false;
  for (const c of data.charts) {
    const wrap = el('div', 'bd-chart');
    wrap.appendChild(el('h4', null, c.title));
    const legend = el('div', 'legend');
    const parts = c.parts.map((p, i) => ({ ...p, color: cssVar(PART_COLORS[i]) }));
    for (const p of parts) {
      const sp = el('span');
      const k = el('i'); k.style.background = p.color;
      sp.append(k, p.name);
      legend.appendChild(sp);
    }
    const tl = el('span');
    const tk = el('i'); tk.style.background = cssVar('--ink');
    tl.append(tk, c.total.name);
    legend.appendChild(tl);
    const chart = el('div', 'chart bd');
    wrap.append(legend, chart, el('p', 'muted small', c.note));
    box.appendChild(wrap);
    const unit = c.unit === '%p' ? '%p' : '%';
    const fy = v => `${fmtNum(v, 1)}${unit}`;
    if (c.kind === 'stack') {
      const n = Math.min(c.dates.length, def.freq === 'quarterly' ? 24 : 48);
      const sl = a => a.slice(-n);
      const dates = sl(c.dates);
      stackChart(chart, {
        labels: dates,
        parts: parts.map(p => ({ ...p, values: sl(p.values) })),
        total: { name: c.total.name, values: sl(c.total.values) },
        formatX: (i, short) => {
          const d = parseDate(dates[i]);
          if (def.freq === 'quarterly') return short ? `${String(d.getFullYear()).slice(2)}Q${Math.floor(d.getMonth() / 3) + 1}` : `${d.getFullYear()}년 ${Math.floor(d.getMonth() / 3) + 1}분기`;
          return short ? `${String(d.getFullYear()).slice(2)}.${d.getMonth() + 1}` : `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
        },
        formatY: fy,
      });
    } else {
      const xs = c.dates.map(d => parseDate(d).getTime());
      lineChart(chart, {
        xs,
        series: [{ name: c.total.name, color: cssVar('--ink'), values: c.total.values },
          ...parts.map(p => ({ name: p.name, color: p.color, values: p.values }))],
        formatX: (_, i) => fmtDate({ freq: 'daily' }, c.dates[i]),
        formatY: v => `${fmtNum(v, 2)}%`,
        xTicks: timeTicks,
        zeroLine: parts.some(p => p.values.some(v => v < 0)),
      });
    }
  }
}

function setRange(range) {
  state.range = range;
  for (const b of document.querySelectorAll('#ranges button')) b.setAttribute('aria-checked', String(b.dataset.range === range));
}

document.getElementById('ranges').addEventListener('click', async e => {
  const b = e.target.closest('button[data-range]');
  if (!b || !state.detail) return;
  setRange(b.dataset.range);
  drawDetail(state.defs.get(state.detail), await loadSeries(state.detail));
});
document.getElementById('detail-close').addEventListener('click', () => document.getElementById('detail').close());
document.getElementById('detail').addEventListener('click', e => { if (e.target.id === 'detail') e.target.close(); });
document.getElementById('detail').addEventListener('close', () => { state.detail = null; });

let latestCurve = null;
function rerenderCharts() {
  renderCurve(latestCurve);
  renderMap();
  if (state.detail) renderBreakdown(state.defs.get(state.detail));
  if (state.detail) loadSeries(state.detail).then(s => state.detail && drawDetail(state.defs.get(state.detail), s));
}
let resizeTimer;
addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(rerenderCharts, 150); });

// 자동 갱신 시각: 매일 07:00, 16:30 (한국시간)
function nextUpdate(from) {
  const kstNow = new Date(Math.max(Date.now(), from.getTime()) + 9 * 36e5);
  const mins = kstNow.getUTCHours() * 60 + kstNow.getUTCMinutes();
  if (mins < 7 * 60) return '오늘 07:00';
  if (mins < 16 * 60 + 30) return '오늘 16:30';
  return '내일 07:00';
}

// ── 시작 ───────────────────────────────────────────────
async function main() {
  const [reg, latest] = await Promise.all([
    fetch(`${DATA}/indicators.json`).then(r => r.json()),
    fetch(`${DATA}/latest.json`, { cache: 'no-cache' }).then(r => r.json()),
  ]);
  state.groups = reg.groups;
  for (const d of reg.indicators) state.defs.set(d.id, d);
  for (const it of latest.indicators) if (it.last) state.items.set(it.id, it);

  const t = new Date(latest.generated_at);
  const kst = { timeZone: 'Asia/Seoul' };
  document.getElementById('updated').textContent =
    `마지막 업데이트 ${t.toLocaleString('ko-KR', { ...kst, month: 'long', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false })} · 다음 ${nextUpdate(t)}`;

  const notice = document.getElementById('notice');
  const ageH = (Date.now() - t) / 36e5;
  const msgs = [];
  if (ageH > 36) msgs.push(`마지막 갱신이 ${Math.floor(ageH / 24)}일 전입니다. 자동 수집이 멈췄을 수 있습니다.`);
  const { stale, missing } = latest.counts;
  if (stale || missing) msgs.push(`${stale + missing}개 지표는 이번에 새로 받지 못해 이전 데이터로 표시합니다.`);
  if (msgs.length) { notice.textContent = msgs.join(' '); notice.hidden = false; }

  try {
    const r = await fetch(`${DATA}/breakdown/index.json`, { cache: 'no-cache' });
    if (r.ok) state.breakdowns = new Set(await r.json());
  } catch {}
  renderTabs();
  renderGroups();
  renderKeys();
  renderBriefing();
  loadMarkets();
  latestCurve = latest.curve;
  renderCurve(latestCurve);
  const more = document.getElementById('curve-more');
  if (state.breakdowns.has('ust10y') && state.items.has('ust10y')) {
    more.hidden = false;
    more.addEventListener('click', () => openDetail('ust10y', { focus: 'breakdown' }));
  }
}

main().catch(err => {
  console.error(err);
  document.getElementById('updated').textContent = '데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
});
