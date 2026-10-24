// 의존성 없는 SVG 차트: 추세선(sparkline)과 십자선 툴팁이 있는 선 차트.
const NS = 'http://www.w3.org/2000/svg';

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

export function sparkline(values, { width = 84, height = 36 } = {}) {
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, class: 'spark', 'aria-hidden': 'true', preserveAspectRatio: 'none' });
  if (!values || values.length < 2) return svg;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * width,
    pad + (1 - (v - min) / span) * (height - pad * 2),
  ]);
  el('polyline', {
    points: pts.map(p => p.map(n => n.toFixed(1)).join(',')).join(' '),
    fill: 'none', stroke: 'var(--spark)', 'stroke-width': 1.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
    'vector-effect': 'non-scaling-stroke',
  }, svg);
  const [lx, ly] = pts[pts.length - 1];
  el('circle', { cx: lx, cy: ly, r: 2.5, fill: 'var(--spark)' }, svg);
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
 * opts: { formatX(x, i), formatY(v), xTicks(xs) => [{x, label}], zeroLine }
 */
export function lineChart(container, { xs, series, formatX, formatY, xTicks, zeroLine = false }) {
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
    el('path', { d, fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
    if (s.markers) {
      s.values.forEach((v, i) => v != null && el('circle', { cx: X(xs[i]), cy: Y(v), r: 4, fill: s.color, class: 'dot' }, svg));
    }
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
    return Math.abs(xs[a] - target) <= Math.abs(xs[b] - target) ? a : b;
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
    tip.hidden = false;
    const left = Math.min(Math.max(px, 70), W - 70);
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
