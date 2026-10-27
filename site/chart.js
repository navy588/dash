// 의존성 없는 SVG 차트: 추세선(sparkline)과 십자선 툴팁이 있는 선 차트.
const NS = 'http://www.w3.org/2000/svg';

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

let gradSeq = 0;
function gradient(svg, color, opacity = 0.22) {
  const id = `g${++gradSeq}`;
  const defs = el('defs', {}, svg);
  const g = el('linearGradient', { id, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
  el('stop', { offset: '0%', style: `stop-color:${color};stop-opacity:${opacity}` }, g);
  el('stop', { offset: '100%', style: `stop-color:${color};stop-opacity:0` }, g);
  return `url(#${id})`;
}

export function sparkline(values, { width = 84, height = 28, color = 'var(--spark)', dotColor = color, area = false } = {}) {
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, class: 'spark', 'aria-hidden': 'true', preserveAspectRatio: 'none' });
  if (!values || values.length < 2) return svg;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * width,
    pad + (1 - (v - min) / span) * (height - pad * 2),
  ]);
  const line = pts.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ');
  if (area) {
    el('polygon', { points: `0,${height} ${line} ${width},${height}`, fill: gradient(svg, color), stroke: 'none' }, svg);
  }
  el('polyline', {
    points: line,
    fill: 'none', stroke: color, 'stroke-width': area ? 1.75 : 1.25, 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
    'vector-effect': 'non-scaling-stroke',
  }, svg);
  if (!area) {
    const [lx, ly] = pts[pts.length - 1];
    el('circle', { cx: lx, cy: ly, r: 2.5, fill: dotColor }, svg);
  }
  return svg;
}

// 보기 좋은 눈금 값
function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) || raw;
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(+v.toFixed(10));
  return { ticks, lo: ticks[0], hi: ticks[ticks.length - 1] };
}

/**
 * series: [{ name, color, values: number[] }] — 모두 같은 길이, x 위치는 xs 공유
 * xs: number[] (시간이면 ms, 범주면 0..n-1)
 * series[].dashed: 점선(전망치 등), series[].area: 아래를 옅은 그라데이션으로 채움
 * events: { [index]: { color, mark, render(tipElement) } } — 툴팁에 내용을 덧붙이고, mark면 점도 찍음
 * opts: { formatX(x, i), formatY(v), xTicks(xs) => [{x, label}], zeroLine }
 */
export function lineChart(container, { xs, series, formatX, formatY, xTicks, zeroLine = false, events = {}, extremes = false }) {
  container.replaceChildren();
  const rect = container.getBoundingClientRect();
  const W = Math.max(rect.width, 200), H = Math.max(rect.height, 160);
  const m = { t: 12, r: 12, b: 26, l: 8 };

  const all = series.flatMap(s => s.values).filter(v => v != null && Number.isFinite(v));
  if (!all.length || xs.length < 2) {
    container.textContent = '표시할 데이터가 없습니다.';
    return;
  }
  let lo = Math.min(...all), hi = Math.max(...all);
  if (zeroLine) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  const padY = (hi - lo) * 0.06 || Math.abs(hi) * 0.02 || 1;
  const { ticks, lo: tlo, hi: thi } = niceTicks(lo - padY, hi + padY, H < 240 ? 4 : 5);

  // 왼쪽 여백은 가장 긴 눈금 라벨 길이에 맞춤
  const labels = ticks.map(formatY);
  m.l = Math.max(...labels.map(s => s.length)) * 6.6 + 10;

  const x0 = xs[0], x1 = xs[xs.length - 1];
  const X = x => m.l + ((x - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const Y = v => m.t + (1 - (v - tlo) / (thi - tlo || 1)) * (H - m.t - m.b);

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': series.map(s => s.name).join(', ') + ' 차트' }, container);
  const axis = el('g', { class: 'axis' }, svg);
  ticks.forEach((t, i) => {
    el('line', { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: zeroLine && t === 0 ? 'baseline' : 'gridline' }, axis);
    const tx = el('text', { x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }, axis);
    tx.textContent = labels[i];
  });
  for (const { x, label } of xTicks(xs, W)) {
    const tx = el('text', { x: X(x), y: H - 6, 'text-anchor': 'middle' }, axis);
    tx.textContent = label;
  }

  // 데이터가 픽셀보다 많으면 픽셀당 마지막 값만 그림
  const plotW = W - m.l - m.r;
  for (const s of series) {
    let d = '', lastPx = -1, pen = false;
    s.values.forEach((v, i) => {
      if (v == null || !Number.isFinite(v)) { pen = false; return; }
      const px = X(xs[i]);
      if (xs.length > plotW * 2 && Math.floor(px) === lastPx && i !== xs.length - 1) return;
      lastPx = Math.floor(px);
      d += `${pen ? 'L' : 'M'}${px.toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
    });
    if (s.area && d) {
      const firstX = d.match(/^M([\d.-]+)/)[1], lastX = d.match(/([\d.-]+),[\d.-]+$/)[1];
      el('path', { d: `${d}L${lastX},${H - m.b}L${firstX},${H - m.b}Z`, fill: gradient(svg, s.color, 0.18), stroke: 'none' }, svg);
    }
    el('path', { d, fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
      ...(s.dashed ? { 'stroke-dasharray': '5 4' } : {}) }, svg);
    if (s.markers) {
      s.values.forEach((v, i) => v != null && el('circle', { cx: X(xs[i]), cy: Y(v), r: 4, fill: s.color, class: 'dot' }, svg));
    }
  }

  // 기간 내 최고·최저 표시 (첫 시리즈)
  if (extremes) {
    const vals = series[0].values;
    let hiI = -1, loI = -1;
    vals.forEach((v, i) => {
      if (v == null) return;
      if (hiI < 0 || v > vals[hiI]) hiI = i;
      if (loI < 0 || v < vals[loI]) loI = i;
    });
    for (const [i, label, dy] of [[hiI, '최고', -9], [loI, '최저', 17]]) {
      if (i < 0 || hiI === loI) continue;
      const px = X(xs[i]);
      el('circle', { cx: px, cy: Y(vals[i]), r: 3, fill: series[0].color, class: 'dot' }, svg);
      const t = el('text', { x: Math.min(Math.max(px, m.l + 40), W - m.r - 40), y: Y(vals[i]) + dy, 'text-anchor': 'middle', class: 'ext' }, svg);
      t.textContent = `${label} ${formatY(vals[i])}`;
    }
  }

  // 이벤트 표시 (데이터가 있는 첫 시리즈 위에)
  const base = series[0];
  const eventIdx = Object.keys(events).map(Number).filter(i => events[i].mark && base.values[i] != null).sort((a, b) => a - b);
  for (const i of eventIdx) {
    el('circle', { cx: X(xs[i]), cy: Y(base.values[i]), r: 4.5, fill: events[i].color, class: 'dot event' }, svg);
  }

  // 십자선 + 툴팁
  const hair = el('line', { y1: m.t, y2: H - m.b, class: 'hair', visibility: 'hidden' }, svg);
  const dots = series.map(s => el('circle', { r: 4.5, fill: s.color, class: 'dot', visibility: 'hidden' }, svg));
  const tip = document.createElement('div');
  tip.className = 'tip';
  tip.hidden = true;
  container.appendChild(tip);

  const nearest = px => {
    const target = x0 + ((px - m.l) / plotW) * (x1 - x0);
    let a = 0, b = xs.length - 1;
    while (b - a > 1) { const mid = (a + b) >> 1; (xs[mid] < target ? (a = mid) : (b = mid)); }
    const i = Math.abs(xs[a] - target) <= Math.abs(xs[b] - target) ? a : b;
    // 이벤트 점 근처(10px)면 이벤트에 붙임
    const ev = eventIdx.reduce((best, k) => (Math.abs(X(xs[k]) - px) < Math.abs(X(xs[best ?? k]) - px) ? k : best), null);
    return ev != null && Math.abs(X(xs[ev]) - px) <= 10 ? ev : i;
  };
  let current = xs.length - 1;
  const show = i => {
    current = i;
    const px = X(xs[i]);
    hair.setAttribute('x1', px); hair.setAttribute('x2', px); hair.setAttribute('visibility', 'visible');
    tip.replaceChildren();
    const head = document.createElement('div');
    head.className = 'muted';
    head.textContent = formatX(xs[i], i);
    tip.appendChild(head);
    series.forEach((s, k) => {
      const v = s.values[i];
      const dot = dots[k];
      if (v == null) { dot.setAttribute('visibility', 'hidden'); return; }
      dot.setAttribute('cx', px); dot.setAttribute('cy', Y(v)); dot.setAttribute('visibility', 'visible');
      const row = document.createElement('div');
      row.className = 'row';
      if (series.length > 1) {
        const key = document.createElement('i');
        key.className = 'key'; key.style.background = s.color;
        row.appendChild(key);
      }
      const val = document.createElement('strong');
      val.textContent = formatY(v);
      row.appendChild(val);
      if (series.length > 1) {
        const name = document.createElement('span');
        name.className = 'muted'; name.textContent = s.name;
        row.appendChild(name);
      }
      tip.appendChild(row);
    });
    if (events[i]) events[i].render(tip);
    tip.classList.toggle('wide', !!events[i]);
    tip.hidden = false;
    const half = events[i] ? 140 : 70;
    const left = Math.min(Math.max(px, half), W - half);
    tip.style.left = `${left}px`;
    const topV = Math.min(...series.map(s => s.values[i]).filter(v => v != null));
    tip.style.top = `${Math.max(Y(Math.max(...series.map(s => s.values[i] ?? topV))) - 10, 44)}px`;
  };
  const hide = () => {
    hair.setAttribute('visibility', 'hidden');
    dots.forEach(d => d.setAttribute('visibility', 'hidden'));
    tip.hidden = true;
  };
  svg.addEventListener('pointermove', e => {
    const r = svg.getBoundingClientRect();
    show(nearest(((e.clientX - r.left) / r.width) * W));
  });
  svg.addEventListener('pointerleave', hide);
  svg.setAttribute('tabindex', '0');
  svg.addEventListener('focus', () => show(current));
  svg.addEventListener('blur', hide);
  svg.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft') { show(Math.max(0, current - 1)); e.preventDefault(); }
    if (e.key === 'ArrowRight') { show(Math.min(xs.length - 1, current + 1)); e.preventDefault(); }
    if (e.key === 'PageUp' || e.key === 'PageDown') {
      const next = e.key === 'PageDown' ? eventIdx.find(k => k > current) : [...eventIdx].reverse().find(k => k < current);
      if (next != null) show(next);
      e.preventDefault();
    }
  });
}

export function timeTicks(xs, width) {
  const span = xs[xs.length - 1] - xs[0];
  const day = 864e5;
  const n = Math.max(2, Math.floor(width / 90));
  const out = [];
  const seen = new Set();
  for (let k = 0; k < n; k++) {
    const x = xs[0] + (span * (k + 0.5)) / n;
    const d = new Date(x);
    const label = span > 3 * 365 * day ? `${d.getFullYear()}`
      : span > 120 * day ? `${String(d.getFullYear()).slice(2)}.${d.getMonth() + 1}`
      : `${d.getMonth() + 1}/${d.getDate()}`;
    if (!seen.has(label)) { seen.add(label); out.push({ x, label }); }
  }
  return out;
}


// 작은 막대 차트 (월별 지표용). 마지막 막대만 진하게.
let hatchSeq = 0;
/** 빗금 채우기(속보치 등 잠정 값 표시용) */
function hatch(svg, color) {
  const id = `h${++hatchSeq}`;
  const defs = el('defs', {}, svg);
  const p = el('pattern', { id, width: 5, height: 5, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
  el('rect', { width: 5, height: 5, style: `fill:${color};opacity:.18` }, p);
  el('line', { x1: 0, y1: 0, x2: 0, y2: 5, style: `stroke:${color};stroke-width:2.6` }, p);
  return `url(#${id})`;
}

/** 막대 추세선. hatched: 빗금으로 그릴 막대 위치(예: 속보치) */
export function bars(values, { width = 120, height = 36, color = 'var(--brand)', hatched = [] } = {}) {
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, class: 'spark bars', 'aria-hidden': 'true', preserveAspectRatio: 'none' });
  if (!values || !values.length) return svg;
  // 0을 가로지르지 않으면 바닥을 최솟값 근처로 올려 작은 변화도 보이게
  const mn = Math.min(...values), mx = Math.max(...values);
  const cross = mn < 0 && mx > 0;
  const lo = cross ? mn : mn >= 0 ? Math.max(0, mn - (mx - mn) * 0.35 - Math.abs(mx) * 0.02) : mn - (mx - mn) * 0.1;
  const hi = cross ? mx : mx <= 0 ? Math.min(0, mx + (mx - mn) * 0.35 + Math.abs(mn) * 0.02) : mx + (mx - mn) * 0.1;
  const span = hi - lo || 1;
  const base = cross ? 0 : mn >= 0 ? lo : hi;
  const Y = v => (1 - (v - lo) / span) * (height - 2) + 1;
  const n = values.length, gap = 2, w = (width - gap * (n - 1)) / n;
  const hfill = hatched.length ? hatch(svg, color) : null;
  values.forEach((v, i) => {
    const y0 = Y(base), y1 = Y(v);
    const h = hatched.includes(i);
    const r = el('rect', { x: i * (w + gap), y: Math.min(y0, y1), width: Math.max(w, 1), height: Math.max(Math.abs(y1 - y0), 1.5), rx: Math.min(2, w / 2),
      style: h ? `fill:${hfill};stroke:${color};stroke-width:1.2` : `fill:${color};opacity:${i === n - 1 ? 1 : 0.32}` }, svg);
    if (h) r.setAttribute('class', 'hatched');
  });
  return svg;
}

/**
 * 누적 막대 + 합계 선. 양수는 위로, 음수는 아래로 쌓습니다.
 * parts: [{ name, color, values }], total: { name, values }
 */
export function stackChart(container, { labels, parts, total, formatX, formatY }) {
  container.replaceChildren();
  const rect = container.getBoundingClientRect();
  const W = Math.max(rect.width, 200), H = Math.max(rect.height, 160);
  const m = { t: 12, r: 12, b: 26, l: 8 };
  const n = labels.length;
  if (!n) { container.textContent = '표시할 데이터가 없습니다.'; return; }
  const pos = [], neg = [];
  for (let i = 0; i < n; i++) {
    pos.push(parts.reduce((a, p) => a + Math.max(p.values[i] || 0, 0), 0));
    neg.push(parts.reduce((a, p) => a + Math.min(p.values[i] || 0, 0), 0));
  }
  const all = [...pos, ...neg, ...(total ? total.values.filter(v => v != null) : []), 0];
  const lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.06 || 1;
  const { ticks, lo: tlo, hi: thi } = niceTicks(lo - pad, hi + pad, 5);
  const labelsY = ticks.map(formatY);
  m.l = Math.max(...labelsY.map(s => s.length)) * 6.6 + 10;
  const plotW = W - m.l - m.r;
  const bw = plotW / n;
  const X = i => m.l + bw * (i + 0.5);
  const Y = v => m.t + (1 - (v - tlo) / (thi - tlo || 1)) * (H - m.t - m.b);

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': (total?.name || '') + ' 기여도 차트' }, container);
  const axis = el('g', { class: 'axis' }, svg);
  ticks.forEach((t, i) => {
    el('line', { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 ? 'baseline' : 'gridline' }, axis);
    const tx = el('text', { x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }, axis);
    tx.textContent = labelsY[i];
  });
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / 70))));
  for (let i = n - 1; i >= 0; i -= every) {
    const tx = el('text', { x: X(i), y: H - 6, 'text-anchor': 'middle' }, axis);
    tx.textContent = formatX(i, true);
  }
  const w = Math.max(bw * 0.72, 1);
  for (let i = 0; i < n; i++) {
    let up = 0, down = 0;
    for (const p of parts) {
      const v = p.values[i] || 0;
      if (!v) continue;
      const a = v > 0 ? up : down, b = a + v;
      if (v > 0) up = b; else down = b;
      el('rect', { x: X(i) - w / 2, y: Math.min(Y(a), Y(b)), width: w, height: Math.max(Math.abs(Y(b) - Y(a)) - 0.5, 0.5),
        style: `fill:${p.color}` }, svg);
    }
  }
  if (total) {
    let d = '';
    total.values.forEach((v, i) => { if (v != null) d += `${d ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; });
    el('path', { d, fill: 'none', stroke: 'var(--ink)', 'stroke-width': 1.75, 'stroke-linejoin': 'round' }, svg);
  }

  const hl = el('rect', { y: m.t, height: H - m.t - m.b, width: bw, class: 'hl', visibility: 'hidden' }, svg);
  svg.insertBefore(hl, svg.children[1]);
  const tip = document.createElement('div');
  tip.className = 'tip';
  tip.hidden = true;
  container.appendChild(tip);
  let current = n - 1;
  const show = i => {
    current = i;
    hl.setAttribute('x', X(i) - bw / 2); hl.setAttribute('visibility', 'visible');
    tip.replaceChildren();
    const head = document.createElement('div');
    head.className = 'muted'; head.textContent = formatX(i, false);
    tip.appendChild(head);
    if (total && total.values[i] != null) {
      const r = document.createElement('div'); r.className = 'row';
      const st = document.createElement('strong'); st.textContent = formatY(total.values[i]);
      const nm = document.createElement('span'); nm.className = 'muted'; nm.textContent = total.name;
      r.append(st, nm); tip.appendChild(r);
    }
    for (const p of [...parts].reverse()) {
      const r = document.createElement('div'); r.className = 'row';
      const k = document.createElement('i'); k.className = 'key sq'; k.style.background = p.color;
      const nm = document.createElement('span'); nm.textContent = p.name;
      const v = document.createElement('b'); v.textContent = formatY(p.values[i] ?? 0);
      r.append(k, nm, v); tip.appendChild(r);
    }
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max(X(i), 90), W - 90)}px`;
    tip.style.top = `${Math.max(Y(pos[i]) - 10, 120)}px`;
  };
  svg.addEventListener('pointermove', e => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    show(Math.min(n - 1, Math.max(0, Math.floor((px - m.l) / bw))));
  });
  svg.addEventListener('pointerleave', () => { tip.hidden = true; hl.setAttribute('visibility', 'hidden'); });
  svg.setAttribute('tabindex', '0');
  svg.addEventListener('focus', () => show(current));
  svg.addEventListener('blur', () => { tip.hidden = true; hl.setAttribute('visibility', 'hidden'); });
  svg.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft') { show(Math.max(0, current - 1)); e.preventDefault(); }
    if (e.key === 'ArrowRight') { show(Math.min(n - 1, current + 1)); e.preventDefault(); }
  });
}

// ── 트리맵 (squarified) ─────────────────────────────────
function squarify(items, x, y, w, h) {
  // items: [{ value, ... }] 내림차순. 반환: [{ item, x, y, w, h }]
  const out = [];
  const total = items.reduce((a, b) => a + b.value, 0);
  if (!total || w <= 0 || h <= 0) return out;
  const scale = (w * h) / total;
  let rest = items.map(it => ({ it, a: it.value * scale }));
  while (rest.length) {
    const short = Math.min(w, h);
    let row = [rest[0]], best = worst(row, short);
    let k = 1;
    while (k < rest.length) {
      const next = worst([...row, rest[k]], short);
      if (next > best) break;
      row.push(rest[k]); best = next; k++;
    }
    const sum = row.reduce((a, r) => a + r.a, 0);
    const thick = sum / short;
    let off = 0;
    for (const r of row) {
      const len = r.a / thick;
      if (w >= h) out.push({ item: r.it, x, y: y + off, w: thick, h: len });
      else out.push({ item: r.it, x: x + off, y, w: len, h: thick });
      off += len;
    }
    if (w >= h) { x += thick; w -= thick; } else { y += thick; h -= thick; }
    rest = rest.slice(k);
  }
  return out;
}

function worst(row, short) {
  const sum = row.reduce((a, r) => a + r.a, 0);
  const mx = Math.max(...row.map(r => r.a)), mn = Math.min(...row.map(r => r.a));
  return Math.max((short * short * mx) / (sum * sum), (sum * sum) / (short * short * mn));
}

/**
 * 두 단계 트리맵 (그룹 → 항목). HTML 상자로 그려 글자가 또렷합니다.
 * groups: [{ name, items: [{ value, label, sub, color, ink, onClick, tip(el) }] }]
 */
export function treemap(container, groups, { header = 18 } = {}) {
  container.replaceChildren();
  const W = container.clientWidth, H = container.clientHeight;
  const gs = groups.map(g => ({ ...g, value: g.items.reduce((a, b) => a + b.value, 0) }))
    .filter(g => g.value > 0).sort((a, b) => b.value - a.value);
  const tip = document.createElement('div');
  tip.className = 'tip tm-tip';
  tip.hidden = true;
  for (const g of squarify(gs, 0, 0, W, H)) {
    const box = document.createElement('div');
    box.className = 'tm-group';
    Object.assign(box.style, { left: `${g.x}px`, top: `${g.y}px`, width: `${g.w}px`, height: `${g.h}px` });
    const showHead = g.h > 60 && g.w > 60;
    if (showHead) {
      const hd = document.createElement('div');
      hd.className = 'tm-head';
      hd.textContent = g.item.name;
      box.appendChild(hd);
    }
    const top = showHead ? header : 0;
    const items = [...g.item.items].sort((a, b) => b.value - a.value);
    for (const c of squarify(items, 0, top, g.w, g.h - top)) {
      const it = c.item;
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'tm-cell';
      Object.assign(cell.style, { left: `${c.x}px`, top: `${c.y}px`, width: `${c.w}px`, height: `${c.h}px`, background: it.color, color: it.ink });
      const area = c.w * c.h;
      if (c.w > 34 && c.h > 22) {
        const size = Math.max(10, Math.min(26, Math.sqrt(area) / 5.2));
        const lb = document.createElement('span');
        lb.className = 'tm-label';
        lb.style.fontSize = `${size}px`;
        lb.textContent = it.label;
        cell.appendChild(lb);
        if (c.h > size * 2.4) {
          const sb = document.createElement('span');
          sb.className = 'tm-sub';
          sb.style.fontSize = `${Math.max(10, size * 0.72)}px`;
          sb.textContent = it.sub;
          cell.appendChild(sb);
        }
      }
      cell.setAttribute('aria-label', `${it.label} ${it.sub}`);
      const place = e => {
        const r = container.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        tip.style.left = `${Math.min(Math.max(x, 110), W - 110)}px`;
        tip.style.top = `${Math.max(y - 14, 70)}px`;
      };
      cell.addEventListener('pointerenter', e => { tip.replaceChildren(); it.tip(tip); tip.hidden = false; place(e); });
      cell.addEventListener('pointermove', place);
      cell.addEventListener('pointerleave', () => { tip.hidden = true; });
      if (it.onClick) cell.addEventListener('click', it.onClick);
      box.appendChild(cell);
    }
    container.appendChild(box);
  }
  container.appendChild(tip);
}
