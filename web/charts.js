// Hand-rolled SVG charts. No CDN, no build step, full control of the terminal look.
const NS = 'http://www.w3.org/2000/svg';
const SERIES_COLORS = ['#e8a33d', '#4aa3df', '#3ecf8e', '#c77dff', '#ef5350', '#8d9aa8'];

function el(name, attrs = {}, text) {
  const n = document.createElementNS(NS, name);
  for (const k in attrs) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
  if (text != null) n.textContent = text;
  return n;
}

function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 0.5; max += 0.5; }
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

const fmtDate = (d) => d.slice(2, 4) + "'" + d.slice(5, 7);

/**
 * Multi-series line chart with independent left/right axes.
 * series: [{name, unit, points:[{d,v}], axis:'left'|'right'}]
 */
export function lineChart(series, opts = {}) {
  const W = opts.width || 900, H = opts.height || 260;
  const M = { t: 12, r: 54, b: 24, l: 52 };
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', preserveAspectRatio: 'none',
    'aria-label': opts.label || 'time series chart' });
  const live = series.filter(s => s.points && s.points.length > 1);
  if (!live.length) { svg.appendChild(el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' }, 'DATA UNAVAILABLE')); return svg; }

  const dates = [...new Set(live.flatMap(s => s.points.map(p => p.d)))].sort();
  const x = (d) => M.l + (dates.indexOf(d) / Math.max(1, dates.length - 1)) * (W - M.l - M.r);

  const groups = { left: live.filter(s => s.axis !== 'right'), right: live.filter(s => s.axis === 'right') };
  const scales = {};
  for (const side of ['left', 'right']) {
    const pts = groups[side].flatMap(s => s.points.map(p => p.v));
    if (!pts.length) continue;
    let lo = Math.min(...pts), hi = Math.max(...pts);
    const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.05 || 1;
    lo -= pad; hi += pad;
    scales[side] = { lo, hi, y: (v) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b) };
  }

  // gridlines + left axis
  if (scales.left) {
    for (const t of niceTicks(scales.left.lo, scales.left.hi)) {
      const y = scales.left.y(t);
      svg.appendChild(el('line', { class: 'gridline', x1: M.l, x2: W - M.r, y1: y, y2: y }));
      svg.appendChild(el('text', { x: M.l - 6, y: y + 3, 'text-anchor': 'end', 'font-size': 9 }, t.toFixed(2)));
    }
  }
  if (scales.right) {
    for (const t of niceTicks(scales.right.lo, scales.right.hi)) {
      svg.appendChild(el('text', { x: W - M.r + 6, y: scales.right.y(t) + 3, 'font-size': 9,
        fill: SERIES_COLORS[groups.left.length % SERIES_COLORS.length] }, t.toFixed(2)));
    }
  }
  // x labels
  const stride = Math.max(1, Math.floor(dates.length / 8));
  dates.forEach((d, i) => {
    if (i % stride) return;
    svg.appendChild(el('text', { x: x(d), y: H - 8, 'text-anchor': 'middle', 'font-size': 9 }, fmtDate(d)));
  });

  live.forEach((s, i) => {
    const sc = scales[s.axis === 'right' ? 'right' : 'left'];
    if (!sc) return;
    const color = s.color || SERIES_COLORS[i % SERIES_COLORS.length];
    const d = s.points.map((p, j) => `${j ? 'L' : 'M'}${x(p.d).toFixed(1)},${sc.y(p.v).toFixed(1)}`).join('');
    svg.appendChild(el('path', { d, fill: 'none', stroke: color, 'stroke-width': 1.6,
      'stroke-linejoin': 'round' }));
    const last = s.points[s.points.length - 1];
    svg.appendChild(el('circle', { cx: x(last.d), cy: sc.y(last.v), r: 2.6, fill: color }));
    s._color = color;
  });
  return svg;
}

export function legendFor(series) {
  const div = document.createElement('div');
  div.className = 'legend';
  series.forEach((s, i) => {
    const c = s._color || SERIES_COLORS[i % SERIES_COLORS.length];
    const sp = document.createElement('span');
    sp.innerHTML = `<i style="background:${c}"></i>${s.name}${s.axis === 'right' ? ' (right)' : ''}`;
    div.appendChild(sp);
  });
  return div;
}

/** Yield curve: current versus prior periods, log-spaced x by maturity. */
export function curveChart(curves, opts = {}) {
  const W = opts.width || 900, H = opts.height || 250;
  const M = { t: 14, r: 16, b: 26, l: 46 };
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Treasury yield curve' });
  const names = Object.keys(curves).filter(k => curves[k] && curves[k].length);
  if (!names.length) { svg.appendChild(el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' }, 'DATA UNAVAILABLE')); return svg; }

  const all = names.flatMap(k => curves[k]);
  const lo0 = Math.min(...all.map(p => p.yield)), hi0 = Math.max(...all.map(p => p.yield));
  const pad = (hi0 - lo0) * 0.15 || 0.25;
  const lo = lo0 - pad, hi = hi0 + pad;
  const lx = (y) => Math.log(y);
  const yrs = curves[names[0]].map(p => p.years);
  const x0 = lx(Math.min(...yrs)), x1 = lx(Math.max(...yrs));
  const X = (y) => M.l + ((lx(y) - x0) / (x1 - x0)) * (W - M.l - M.r);
  const Y = (v) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);

  for (const t of niceTicks(lo, hi)) {
    svg.appendChild(el('line', { class: 'gridline', x1: M.l, x2: W - M.r, y1: Y(t), y2: Y(t) }));
    svg.appendChild(el('text', { x: M.l - 6, y: Y(t) + 3, 'text-anchor': 'end', 'font-size': 9 }, t.toFixed(2) + '%'));
  }
  curves[names[0]].forEach(p => {
    svg.appendChild(el('text', { x: X(p.years), y: H - 8, 'text-anchor': 'middle', 'font-size': 9 },
      p.series_id.replace('UST', '')));
  });

  const style = { current: { c: '#e8a33d', w: 2.1, dash: null },
    week: { c: '#4aa3df', w: 1.3, dash: '3 3' },
    month: { c: '#8d9aa8', w: 1.1, dash: '2 4' },
    quarter: { c: '#5f6c7a', w: 1, dash: '1 5' } };
  ['quarter', 'month', 'week', 'current'].forEach(k => {
    const pts = curves[k]; if (!pts || !pts.length) return;
    const st = style[k] || style.current;
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.years).toFixed(1)},${Y(p.yield).toFixed(1)}`).join('');
    svg.appendChild(el('path', { d, fill: 'none', stroke: st.c, 'stroke-width': st.w,
      'stroke-dasharray': st.dash, 'stroke-linejoin': 'round' }));
    if (k === 'current') pts.forEach(p => svg.appendChild(el('circle', { cx: X(p.years), cy: Y(p.yield), r: 2.4, fill: st.c })));
  });
  return svg;
}

/** Sparkline for table rows. */
export function sparkline(points, opts = {}) {
  const W = opts.width || 90, H = opts.height || 20;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true' });
  if (!points || points.length < 2) return svg;
  const vs = points.map(p => (typeof p === 'object' ? p.v : p));
  const lo = Math.min(...vs), hi = Math.max(...vs), r = hi - lo || 1;
  const d = vs.map((v, i) => `${i ? 'L' : 'M'}${(i / (vs.length - 1) * W).toFixed(1)},${(H - ((v - lo) / r) * (H - 2) - 1).toFixed(1)}`).join('');
  svg.appendChild(el('path', { d, fill: 'none', stroke: opts.color || '#4aa3df', 'stroke-width': 1.2 }));
  return svg;
}

/** Percentile band strip for the spread screen. */
export function percentileStrip(pct, bands, opts = {}) {
  const W = opts.width || 900, H = 46;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img',
    'aria-label': `Spread at the ${pct} percentile` });
  const colors = ['#3ecf8e', '#69c07a', '#8d9aa8', '#d98b45', '#ef5350'];
  const edges = [0, 10, 30, 70, 90, 100];
  for (let i = 0; i < 5; i++) {
    const x = (edges[i] / 100) * W, w = ((edges[i + 1] - edges[i]) / 100) * W;
    svg.appendChild(el('rect', { x, y: 12, width: w, height: 14, fill: colors[i], opacity: .34 }));
    svg.appendChild(el('text', { x: x + w / 2, y: 38, 'text-anchor': 'middle', 'font-size': 8.5 },
      (bands[i] && bands[i].label) || ''));
  }
  if (pct != null) {
    const x = (pct / 100) * W;
    svg.appendChild(el('line', { x1: x, x2: x, y1: 6, y2: 32, stroke: '#e8a33d', 'stroke-width': 2 }));
    svg.appendChild(el('text', { x: Math.min(W - 24, Math.max(18, x)), y: 8, 'text-anchor': 'middle',
      'font-size': 9.5, fill: '#e8a33d' }, pct.toFixed(0) + 'th'));
  }
  return svg;
}
