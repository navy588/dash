import { sparkline, lineChart, timeTicks } from './chart.js';

const DATA = 'data';
const PERIOD_LABEL = { prev: '직전 대비', w1: '1주', m1: '1개월', ytd: '연초 대비', y1: '1년' };
const FREQ_PREV = { daily: '전일', weekly: '전주', monthly: '전월', quarterly: '전분기' };
const STALE_DAYS = { daily: 5, weekly: 12, monthly: 75, quarterly: 200 };
const SIGMA_THRESHOLD = 2;

const state = { period: 'prev', defs: new Map(), items: new Map(), groups: [], seriesCache: new Map(), detail: null, range: '1y' };

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

function periodLabel(def, period) {
  return period === 'prev' ? FREQ_PREV[def.freq] + ' 대비' : PERIOD_LABEL[period];
}

function isOutdated(def, item) {
  const age = (Date.now() - parseDate(item.last.date)) / 864e5;
  return age > STALE_DAYS[def.freq];
}

// ── 카드 ───────────────────────────────────────────────
function tile(def, item, { showSigma = false } = {}) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'card tile';
  b.dataset.id = def.id;

  const name = document.createElement('div');
  name.className = 'name';
  const nm = document.createElement('span');
  nm.textContent = def.name;
  name.appendChild(nm);
  if (item.status !== 'ok' || isOutdated(def, item)) {
    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.textContent = item.status === 'ok' ? '갱신 지연' : '이전 데이터';
    badge.title = item.error || '최근 데이터가 들어오지 않았습니다';
    name.appendChild(badge);
  }
  if (showSigma && item.sigma != null) {
    const badge = document.createElement('span');
    badge.className = 'badge sigma';
    badge.textContent = `평소의 ${fmtNum(Math.abs(item.sigma), 1)}배`;
    name.appendChild(badge);
  }
  b.appendChild(name);

  const value = document.createElement('div');
  value.className = 'value';
  if (def.unit === '$') value.append('$');
  value.append(fmtValue(def, item.last.value));
  if (def.unit && def.unit !== 'pt' && def.unit !== '$') {
    const u = document.createElement('small');
    u.textContent = def.unit;
    value.appendChild(u);
  }
  b.appendChild(value);
  b.appendChild(sparkline(item.spark));

  const period = showSigma ? 'prev' : state.period;
  const c = item.changes[period];
  const delta = document.createElement('div');
  const dir = direction(c);
  delta.className = `delta ${dir.cls}`;
  delta.textContent = c ? `${dir.arrow} ${fmtChange(def, c)}` : '–';
  b.appendChild(delta);

  const date = document.createElement('div');
  date.className = 'date';
  date.textContent = `${fmtDate(def, item.last.date)} 기준 · ${periodLabel(def, period)}`;
  b.appendChild(date);

  b.setAttribute('aria-label', `${def.name} ${withUnit(def, item.last.value)}, ${periodLabel(def, period)} ${c ? fmtChange(def, c) + ' ' + dir.word : '변화 없음'}, ${fmtDate(def, item.last.date)} 기준. 자세히 보기`);
  b.addEventListener('click', () => openDetail(def.id));
  return b;
}

function renderMovers() {
  const box = document.getElementById('movers');
  box.replaceChildren();
  const movers = [...state.items.values()]
    .filter(it => it.status === 'ok' && it.sigma != null && Math.abs(it.sigma) >= SIGMA_THRESHOLD)
    .filter(it => !isOutdated(state.defs.get(it.id), it))
    .filter(it => { const f = state.defs.get(it.id).freq; return f === 'daily' || f === 'weekly'; })
    .sort((a, b) => Math.abs(b.sigma) - Math.abs(a.sigma))
    .slice(0, 8);
  if (!movers.length) {
    const p = document.createElement('p');
    p.className = 'empty card';
    p.textContent = '평소보다 크게 움직인 지표가 없습니다.';
    box.appendChild(p);
    return;
  }
  for (const it of movers) box.appendChild(tile(state.defs.get(it.id), it, { showSigma: true }));
}

function renderGroups() {
  const root = document.getElementById('groups');
  root.replaceChildren();
  for (const g of state.groups) {
    const defs = [...state.defs.values()].filter(d => d.group === g.id && state.items.get(d.id)?.last);
    if (!defs.length) continue;
    const sec = document.createElement('section');
    sec.className = 'block';
    sec.setAttribute('aria-labelledby', `g-${g.id}`);
    const h = document.createElement('h2');
    h.id = `g-${g.id}`;
    h.textContent = g.name;
    sec.appendChild(h);
    const grid = document.createElement('div');
    grid.className = 'grid';
    for (const d of defs) grid.appendChild(tile(d, state.items.get(d.id)));
    sec.appendChild(grid);
    root.appendChild(sec);
  }
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

const RANGE_DAYS = { '3m': 92, '1y': 366, '3y': 3 * 366, '10y': 10 * 366, all: Infinity };

async function openDetail(id) {
  const def = state.defs.get(id), item = state.items.get(id);
  const dlg = document.getElementById('detail');
  state.detail = id;
  document.getElementById('detail-title').textContent = def.name;
  const c = item.changes.prev;
  const dir = direction(c);
  document.getElementById('detail-sub').textContent =
    `${withUnit(def, item.last.value)} · ${FREQ_PREV[def.freq]} 대비 ${c ? dir.arrow + ' ' + fmtChange(def, c) : '–'} · ${fmtDate(def, item.last.date)} 기준`;
  if (!dlg.open) dlg.showModal();
  if (def.freq !== 'daily' && def.freq !== 'weekly' && state.range === '3m') setRange('1y');
  const chartBox = document.getElementById('detail-chart');
  chartBox.textContent = '불러오는 중…';
  try {
    const s = await loadSeries(id);
    if (state.detail === id) drawDetail(def, s);
  } catch {
    chartBox.textContent = '시계열을 불러오지 못했습니다.';
  }
}

function drawDetail(def, s) {
  const lastT = parseDate(s.dates[s.dates.length - 1]).getTime();
  const from = lastT - RANGE_DAYS[state.range] * 864e5;
  const xs = [], vals = [], dates = [];
  s.dates.forEach((d, i) => {
    const t = parseDate(d).getTime();
    if (t >= from) { xs.push(t); vals.push(s.values[i]); dates.push(d); }
  });
  lineChart(document.getElementById('detail-chart'), {
    xs,
    series: [{ name: def.name, color: cssVar('--series-1'), values: vals }],
    formatX: (_, i) => fmtDate(def, dates[i]),
    formatY: v => (def.unit === '$' ? '$' : '') + fmtValue(def, v) + (def.unit === '%' || def.unit === '%p' ? '%' : ''),
    xTicks: timeTicks,
    zeroLine: vals.some(v => v < 0) && vals.some(v => v > 0),
  });

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

// ── 기간 선택 ───────────────────────────────────────────
document.getElementById('period').addEventListener('click', e => {
  const b = e.target.closest('button[data-period]');
  if (!b) return;
  state.period = b.dataset.period;
  for (const x of document.querySelectorAll('#period button')) x.setAttribute('aria-checked', String(x === b));
  renderGroups();
});

let latestCurve = null;
function rerenderCharts() {
  renderCurve(latestCurve);
  if (state.detail) loadSeries(state.detail).then(s => state.detail && drawDetail(state.defs.get(state.detail), s));
}
let resizeTimer;
addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(rerenderCharts, 150); });

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
  document.getElementById('updated').textContent =
    `${t.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' })} 갱신`;

  const notice = document.getElementById('notice');
  const ageH = (Date.now() - t) / 36e5;
  const msgs = [];
  if (ageH > 36) msgs.push(`마지막 갱신이 ${Math.floor(ageH / 24)}일 전입니다. 자동 수집이 멈췄을 수 있습니다.`);
  const { stale, missing } = latest.counts;
  if (stale || missing) msgs.push(`${stale + missing}개 지표는 이번에 새로 받지 못해 이전 데이터로 표시합니다.`);
  if (msgs.length) { notice.textContent = msgs.join(' '); notice.hidden = false; }

  renderMovers();
  renderGroups();
  latestCurve = latest.curve;
  renderCurve(latestCurve);
}

main().catch(err => {
  console.error(err);
  document.getElementById('updated').textContent = '데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
});
