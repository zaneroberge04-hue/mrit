// Reusable interactive time-series chart. Hand-rolled SVG, no dependencies.
//
// Deliberately generic: it knows about series, units, frequencies and event markers,
// and nothing at all about mortgages. The same component drives Treasuries, MBS,
// spreads, inflation or oil by passing a different payload.
//
// Performance shape: the full history ships once and lives in memory. Range and mode
// switches are pure array windows with no network. Hover only moves the crosshair
// and rewrites the tooltip; it never redraws the plot.

import { h } from './components.js';

const NS = 'http://www.w3.org/2000/svg';
const DAY = 86400000;
const MAX_RENDER_POINTS = 1400;   // above this, downsample for drawing only

const svgEl = (n, a = {}, t) => {
  const e = document.createElementNS(NS, n);
  for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]);
  if (t != null) e.textContent = t;
  return e;
};

const dayNum = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / DAY;
const fromDay = (n) => new Date(n * DAY);

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function fmtDate(d, long) {
  const t = fromDay(d);
  const m = MONTHS[t.getUTCMonth()];
  return long ? `${m} ${t.getUTCDate()}, ${t.getUTCFullYear()}`
    : `${m} '${String(t.getUTCFullYear()).slice(2)}`;
}

const UNIT_SUFFIX = { percent: '%', bps: ' bp', usd: '', ticks: '', index: '', thousands: 'k' };
const unitFmt = (v, unit, dp) => {
  if (v == null || Number.isNaN(v)) return '—';
  const d = dp != null ? dp : (unit === 'bps' || unit === 'thousands' ? 0 : 2);
  return (unit === 'usd' ? '$' : '') + v.toFixed(d) + (UNIT_SUFFIX[unit] || '');
};
// Sign goes outside the currency symbol: "-$1.39", never "$-1.39".
const signedFmt = (v, unit, dp) => {
  if (v == null) return '—';
  const body = unitFmt(Math.abs(v), unit, dp);
  return (v < 0 ? '-' : '+') + body;
};

function niceTicks(min, max, count = 5) {
  if (!(max > min)) { min -= 0.5; max += 0.5; }
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  const step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/** Largest-Triangle-Three-Buckets: keeps visual peaks and troughs that naive
 *  every-nth sampling drops. Rendering only — hover always reads the real array. */
function lttb(points, target) {
  const n = points.length;
  if (n <= target || target < 3) return points;
  const out = [points[0]];
  const every = (n - 2) / (target - 2);
  let a = 0;
  for (let i = 0; i < target - 2; i++) {
    const rangeStart = Math.floor((i + 1) * every) + 1;
    const rangeEnd = Math.min(Math.floor((i + 2) * every) + 1, n);
    let avgX = 0, avgY = 0;
    for (let j = rangeStart; j < rangeEnd; j++) { avgX += points[j][0]; avgY += points[j][1]; }
    const cnt = Math.max(1, rangeEnd - rangeStart);
    avgX /= cnt; avgY /= cnt;
    const from = Math.floor(i * every) + 1;
    const to = Math.floor((i + 1) * every) + 1;
    const ax = points[a][0], ay = points[a][1];
    let best = -1, bestIdx = from;
    for (let j = from; j < Math.min(to, n); j++) {
      const area = Math.abs((ax - avgX) * (points[j][1] - ay) - (ax - points[j][0]) * (avgY - ay));
      if (area > best) { best = area; bestIdx = j; }
    }
    out.push(points[bestIdx]);
    a = bestIdx;
  }
  out.push(points[n - 1]);
  return out;
}

const bisect = (arr, x) => {
  let lo = 0, hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid][0] < x) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && Math.abs(arr[lo - 1][0] - x) <= Math.abs(arr[lo][0] - x)) return lo - 1;
  return lo;
};

// ---------------------------------------------------------------- transforms
function transform(pts, mode, unit) {
  if (!pts.length) return pts;
  if (mode === 'rate') return pts;
  // Only a percent series converts to basis points. A dollar series differences in
  // dollars; scaling it by 100 turned a $44 crude move into "+4400 bp".
  const k = unit === 'percent' ? 100 : 1;
  const base = pts[0][1];
  if (mode === 'bp') return pts.map(p => [p[0], (p[1] - base) * k]);
  if (mode === 'norm') return pts.map(p => [p[0], base ? (p[1] / base - 1) * 100 : 0]);
  if (mode === 'change') {
    const out = [[pts[0][0], 0]];
    for (let i = 1; i < pts.length; i++) out.push([pts[i][0], (pts[i][1] - pts[i - 1][1]) * k]);
    return out;
  }
  return pts;
}
// Unit a series reports in under each mode. NORMALIZED is the only mode that makes
// unlike units commensurable, so it is the only one that shares a single axis.
const modeUnit = (mode, unit) =>
  mode === 'rate' ? unit
    : mode === 'norm' ? 'percent'
      : (unit === 'percent' ? 'bps' : unit);
const SHARES_AXIS = { rate: false, bp: false, change: false, norm: true };

// ================================================================ component
export function TimeSeriesChart(payload, opts = {}) {
  const st = {
    range: opts.range || '1Y',
    mode: opts.mode || 'rate',
    events: new Set(opts.events || []),
    view: null,            // [minDay, maxDay] when zoomed/panned
    custom: null,          // [fromDay, toDay] from the date inputs
    hoverIdx: null,
    normalizeUnits: false,
  };

  const series = payload.series.filter(s => s.available && s.points.length);
  const primary = series[0];
  if (!primary) {
    return { el: h('div', { class: 'unavail' }, 'DATA UNAVAILABLE',
      h('br'), h('span', { class: 'note small' },
        (payload.series[0] && payload.series[0].reason) || 'No observations for this series.')) };
  }

  // numeric x once, then never re-parse
  const prepared = series.map(s => ({
    ...s, pts: s.points.map(p => [dayNum(p[0]), p[1]]),
  }));

  const root = h('div', { class: 'ts' });
  const statsEl = h('div', { class: 'ts-stats' });
  const toolbar = h('div', { class: 'ts-toolbar' });
  const plotWrap = h('div', { class: 'ts-plot' });
  const tip = h('div', { class: 'ts-tip', hidden: true, style: 'display:none' });
  const legend = h('div', { class: 'ts-legend' });
  const foot = h('div', { class: 'ts-foot' });
  const evTip = h('div', { class: 'ts-tip ts-evtip', hidden: true, style: 'display:none' });
  plotWrap.append(tip, evTip);
  root.append(statsEl, toolbar, plotWrap, legend, foot);

  let geom = null;                       // populated by draw()
  let crossG = null;
  let drag = null;                       // survives re-render; see wireInteraction

  // ------------------------------------------------------------- windowing
  function windowFor() {
    const all = prepared[0].pts;
    const last = all[all.length - 1][0];
    if (st.view) return st.view;
    if (st.custom) return st.custom;
    const r = payload.ranges.find(x => x.id === st.range);
    if (!r) return [all[0][0], last];
    if (r.id === 'MAX') return [all[0][0], last];
    if (r.id === 'YTD') {
      const y = fromDay(last).getUTCFullYear();
      return [Date.UTC(y, 0, 1) / DAY, last];
    }
    return [last - r.days, last];
  }

  const sliceTo = (pts, lo, hi) => {
    const out = [];
    for (let i = 0; i < pts.length; i++) {
      if (pts[i][0] >= lo && pts[i][0] <= hi) out.push(pts[i]);
    }
    return out;
  };

  function visible() {
    const [lo, hi] = windowFor();
    return prepared.map(s => {
      const raw = sliceTo(s.pts, lo, hi);
      return { ...s, raw, shown: transform(raw, st.mode, s.unit) };
    }).filter(s => s.raw.length);
  }

  /** Index of the series the crosshair should snap to: the one with the most
   *  observations in view. Snapping to the primary made a weekly mortgage rate
   *  drag every daily overlay down to weekly granularity on hover. */
  function snapIdx(vis) {
    let best = 0;
    for (let i = 1; i < vis.length; i++) {
      if (vis[i].raw.length > vis[best].raw.length) best = i;
    }
    return best;
  }

  // ------------------------------------------------------------- stats head
  function renderStats(vis) {
    statsEl.innerHTML = '';
    const p = vis[0];
    if (!p) return;
    const u = p.unit;
    const r = p.raw;
    const start = r[0][1], end = r[r.length - 1][1];
    const vals = r.map(x => x[1]);
    const hi = Math.max(...vals), lo = Math.min(...vals);
    const hiD = r[vals.indexOf(hi)][0], loD = r[vals.indexOf(lo)][0];
    const chg = end - start;
    const inBp = u === 'percent';
    const bp = inBp ? chg * 100 : chg;
    const bpUnit = inBp ? 'bps' : u;
    const bpDp = inBp ? 0 : 2;
    const pct = start ? (chg / start) * 100 : null;
    const prev = r.length > 1 ? r[r.length - 2][1] : null;
    const dMove = prev == null ? null : (end - prev) * (inBp ? 100 : 1);
    const dir = chg > 0 ? 'up' : chg < 0 ? 'down' : 'flat';
    const arrow = chg > 0 ? '▲' : chg < 0 ? '▼' : '►';

    const block = (label, value, cls) => h('div', { class: 'ts-stat' },
      h('div', { class: 'lab' }, label), h('div', { class: 'ts-statv ' + (cls || '') }, value));

    statsEl.append(
      h('div', { class: 'ts-hero' },
        h('div', { class: 'lab' }, p.name.toUpperCase()),
        h('div', { class: 'ts-price' }, unitFmt(end, u, u === 'bps' ? 0 : 2)),
        h('div', { class: 'ts-delta ' + dir },
          `${arrow} ${signedFmt(chg, u, 2)}  `,
          h('span', { class: 'mono' }, `${signedFmt(bp, bpUnit, bpDp)}`),
          pct != null ? h('span', { class: 'ts-pct' }, `  ${signedFmt(pct, 'percent', 2)}`) : null,
          h('span', { class: 'ts-over' }, ` over ${st.range}`)),
        dMove != null ? h('div', { class: 'note small' },
          `Latest observation move ${signedFmt(dMove, bpUnit, bpDp)} versus the prior print`) : null),
      h('div', { class: 'ts-statgrid' },
        block('START', unitFmt(start, u), ''),
        block('CURRENT', unitFmt(end, u), ''),
        block('CHANGE', signedFmt(bp, bpUnit, bpDp), dir),
        block('HIGH', unitFmt(hi, u), ''),
        block('LOW', unitFmt(lo, u), ''),
        block('OBS', String(r.length), 'dim')),
      h('div', { class: 'note small ts-hilo' },
        `High ${fmtDate(hiD, true)} · Low ${fmtDate(loD, true)} · `
        + `Window ${fmtDate(r[0][0], true)} to ${fmtDate(r[r.length - 1][0], true)}`));
  }

  // ------------------------------------------------------------- toolbar
  function renderToolbar() {
    toolbar.innerHTML = '';
    const ranges = h('div', { class: 'ts-ranges' }, payload.ranges.map(r =>
      h('button', {
        class: 'btn', 'aria-pressed': !st.view && !st.custom && st.range === r.id,
        disabled: !r.enabled,
        title: r.enabled ? `Show ${r.id}` : r.reason,
        onclick: () => { st.range = r.id; st.view = null; st.custom = null; render(); },
      }, r.id)));

    const modes = h('div', { class: 'ts-modes' }, payload.catalog.modes.map(m =>
      h('button', {
        class: 'btn', 'aria-pressed': st.mode === m.id, title: m.hint,
        onclick: () => { st.mode = m.id; render(); },
      }, m.label)));

    const mkDate = (which) => h('input', {
      type: 'date', class: 'ts-date',
      value: st.custom ? fromDay(st.custom[which === 'from' ? 0 : 1]).toISOString().slice(0, 10) : '',
      onchange: (e) => {
        const all = prepared[0].pts;
        const cur = st.custom || [all[0][0], all[all.length - 1][0]];
        const v = e.target.value ? dayNum(e.target.value) : null;
        if (v == null) return;
        st.custom = which === 'from' ? [v, cur[1]] : [cur[0], v];
        st.view = null;
        render();
      },
    });

    const seriesBtn = opts.onPickSeries ? h('button', {
      class: 'btn', title: 'Chart a different series as the primary. A daily series '
        + 'gives daily granularity on hover; the mortgage survey is weekly.',
      onclick: () => opts.onPickSeries(st),
    }, 'SERIES: ' + primary.series_id) : null;

    toolbar.append(seriesBtn, ranges,
      h('div', { class: 'ts-custom' },
        h('span', { class: 'lab' }, 'FROM'), mkDate('from'),
        h('span', { class: 'lab' }, 'TO'), mkDate('to')),
      modes,
      h('div', { class: 'ts-tools' },
        h('button', {
          class: 'btn', title: 'Reset zoom and pan back to the selected range',
          disabled: !st.view && !st.custom,
          onclick: () => { st.view = null; st.custom = null; render(); },
        }, 'RESET ZOOM'),
        opts.onAddCompare ? h('button', {
          class: 'btn', title: 'Overlay another market series',
          onclick: () => opts.onAddCompare(st),
        }, '+ COMPARISON') : null,
        payload.catalog.events.length ? h('button', {
          class: 'btn', 'aria-pressed': st.events.size > 0,
          title: 'Toggle economic event markers on the timeline',
          onclick: () => opts.onToggleEvents && opts.onToggleEvents(st),
        }, 'EVENTS ' + (st.events.size ? `(${st.events.size})` : '')) : null));
  }

  // ------------------------------------------------------------- draw
  function draw(vis) {
    const old = plotWrap.querySelector('svg');
    if (old) old.remove();

    const W = plotWrap.clientWidth || 900;
    const H = opts.height || 380;
    const shared = SHARES_AXIS[st.mode];
    const unitOf = (s) => modeUnit(st.mode, s.unit);
    const rightAxes = (vis.length > 1 && !shared)
      ? [...new Set(vis.slice(1).map(unitOf))].filter(u => u !== unitOf(vis[0])) : [];
    const M = { t: 10, r: 16 + rightAxes.length * 46, b: 22, l: 52 };

    const svg = svgEl('svg', {
      viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'ts-svg',
      role: 'img', 'aria-label': `${vis[0].name} time series chart`,
    });

    const [lo, hi] = windowFor();
    const xmin = Math.min(...vis.map(s => s.shown[0][0]));
    const xmax = Math.max(...vis.map(s => s.shown[s.shown.length - 1][0]));
    const span = Math.max(1, xmax - xmin);
    const X = (d) => M.l + ((d - xmin) / span) * (W - M.l - M.r);

    // Axis groups: left keeps the primary unit; each extra unit earns its own right axis.
    const axes = {};
    const assign = (s) => (shared || unitOf(s) === unitOf(vis[0]))
      ? 'left' : 'r' + rightAxes.indexOf(unitOf(s));
    for (const s of vis) {
      const key = assign(s);
      const vals = s.shown.map(p => p[1]);
      const a = axes[key] || (axes[key] = { lo: Infinity, hi: -Infinity, unit: unitOf(s), series: [] });
      a.lo = Math.min(a.lo, ...vals);
      a.hi = Math.max(a.hi, ...vals);
      a.series.push(s);
    }
    for (const k in axes) {
      const a = axes[k];
      const pad = (a.hi - a.lo) * 0.10 || Math.abs(a.hi || 1) * 0.05 || 0.5;
      a.lo -= pad; a.hi += pad;
      a.Y = (v) => M.t + (1 - (v - a.lo) / (a.hi - a.lo)) * (H - M.t - M.b);
    }

    // gridlines + left axis
    const la = axes.left;
    if (la) {
      for (const t of niceTicks(la.lo, la.hi)) {
        svg.appendChild(svgEl('line', { class: 'ts-grid', x1: M.l, x2: W - M.r, y1: la.Y(t), y2: la.Y(t) }));
        svg.appendChild(svgEl('text', { x: M.l - 6, y: la.Y(t) + 3, 'text-anchor': 'end', 'font-size': 9.5 },
          unitFmt(t, la.unit, la.unit === 'bps' ? 0 : 2)));
      }
    }
    rightAxes.forEach((unit, i) => {
      const a = axes['r' + i];
      if (!a) return;
      const col = a.series[0].color;
      for (const t of niceTicks(a.lo, a.hi, 4)) {
        svg.appendChild(svgEl('text', {
          x: W - M.r + 6 + i * 46, y: a.Y(t) + 3, 'font-size': 9.5, fill: col,
        }, unitFmt(t, unit, unit === 'bps' ? 0 : 2)));
      }
    });

    // x ticks, spaced by the span so labels never collide
    const years = span / 365;
    const tickCount = Math.max(3, Math.min(9, Math.floor(W / 110)));
    for (let i = 0; i <= tickCount; i++) {
      const d = xmin + (span * i) / tickCount;
      svg.appendChild(svgEl('line', { class: 'ts-grid', x1: X(d), x2: X(d), y1: M.t, y2: H - M.b }));
      const t = fromDay(d);
      const lbl = years > 4 ? String(t.getUTCFullYear())
        : years > 0.75 ? fmtDate(d)
          : `${MONTHS[t.getUTCMonth()]} ${t.getUTCDate()}`;
      svg.appendChild(svgEl('text', { x: X(d), y: H - 7, 'text-anchor': 'middle', 'font-size': 9.5 }, lbl));
    }

    // series paths
    vis.forEach((s) => {
      const a = axes[assign(s)];
      const pts = lttb(s.shown, MAX_RENDER_POINTS);
      s._rendered = pts.length;
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)},${a.Y(p[1]).toFixed(1)}`).join('');
      svg.appendChild(svgEl('path', {
        d, fill: 'none', stroke: s.color, 'stroke-width': s === vis[0] ? 1.8 : 1.2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round',
        'stroke-dasharray': s.quality === 'MODELED' ? '4 2' : null,
      }));
      const last = pts[pts.length - 1];
      svg.appendChild(svgEl('circle', { cx: X(last[0]), cy: a.Y(last[1]), r: 2.8, fill: s.color }));
    });

    // event markers
    const evs = (payload.events || []).filter(e =>
      st.events.has(e.kind) && dayNum(e.date) >= xmin && dayNum(e.date) <= xmax);
    const evG = svgEl('g', { class: 'ts-events' });
    evs.forEach(e => {
      const x = X(dayNum(e.date));
      const mk = svgEl('g', { class: 'ts-ev', tabindex: '0',
        'aria-label': `${e.label} ${e.date}` });
      mk.appendChild(svgEl('line', { x1: x, x2: x, y1: M.t, y2: H - M.b, class: 'ts-evline' }));
      mk.appendChild(svgEl('rect', { x: x - 4, y: H - M.b - 8, width: 8, height: 8,
        class: 'ts-evmark ev-' + e.impact }));
      mk.addEventListener('mouseenter', () => showEventTip(e, x));
      mk.addEventListener('mouseleave', hideEventTip);
      mk.addEventListener('focus', () => showEventTip(e, x));
      mk.addEventListener('blur', hideEventTip);
      evG.appendChild(mk);
    });
    svg.appendChild(evG);

    // crosshair, drawn once and only moved on hover
    crossG = svgEl('g', { class: 'ts-cross', style: 'display:none' });
    crossG.appendChild(svgEl('line', { class: 'ts-crossline', y1: M.t, y2: H - M.b }));
    const dots = vis.map(s => {
      const c = svgEl('circle', { r: 3.4, fill: 'var(--panel)', stroke: s.color, 'stroke-width': 2 });
      crossG.appendChild(c);
      return c;
    });
    svg.appendChild(crossG);

    const hit = svgEl('rect', {
      x: M.l, y: M.t, width: Math.max(1, W - M.l - M.r), height: Math.max(1, H - M.t - M.b),
      fill: 'transparent', style: 'cursor:crosshair',
    });
    svg.appendChild(hit);
    plotWrap.insertBefore(svg, tip);

    geom = { W, H, M, X, xmin, xmax, span, axes, vis, dots, hit, assign, svg };
    wireInteraction();
  }

  // ------------------------------------------------------------- interaction
  function wireInteraction() {
    const { hit, X, M, W, vis, dots, axes, assign } = geom;

    const pxToDay = (clientX) => {
      const r = geom.svg.getBoundingClientRect();
      const scale = geom.W / r.width;
      const px = (clientX - r.left) * scale;
      return geom.xmin + ((px - M.l) / (W - M.l - M.r)) * geom.span;
    };

    // Coalesce on the OBSERVATION index rather than on requestAnimationFrame.
    // Moving the mouse within one observation does no work at all, which is cheaper
    // than a rAF gate and has no stall mode when the tab is backgrounded.
    let lastIdx = -1;
    const snap = snapIdx(vis);
    const onMove = (ev) => {
      const cx = ev.touches ? ev.touches[0].clientX : ev.clientX;
      const day = pxToDay(cx);
      const idx = bisect(vis[snap].shown, day);
      const p0 = vis[snap].shown[idx];
      if (!p0) return;
      if (idx === lastIdx && crossG.style.display !== 'none') return;
      lastIdx = idx;
      const x = X(p0[0]);
      crossG.style.display = '';
      crossG.firstChild.setAttribute('x1', x);
      crossG.firstChild.setAttribute('x2', x);
      vis.forEach((s, i) => {
        const j = bisect(s.raw, p0[0]);
        const p = s.shown[j];
        if (!p) { dots[i].style.display = 'none'; return; }
        dots[i].style.display = '';
        dots[i].setAttribute('cx', X(p[0]));
        dots[i].setAttribute('cy', axes[assign(s)].Y(p[1]));
      });
      showTip(idx, x, ev, snap);
    };

    hit.addEventListener('mousemove', onMove);
    hit.addEventListener('touchmove', (e) => { onMove(e); }, { passive: true });
    hit.addEventListener('mouseleave', () => {
      lastIdx = -1;
      crossG.style.display = 'none'; tip.hidden = true; tip.style.display = 'none';
    });

    // wheel zoom around the cursor
    hit.addEventListener('wheel', (e) => {
      e.preventDefault();
      const all = prepared[0].pts;
      const [lo, hi] = windowFor();
      const focus = pxToDay(e.clientX);
      const factor = e.deltaY > 0 ? 1.18 : 1 / 1.18;
      let nLo = focus - (focus - lo) * factor;
      let nHi = focus + (hi - focus) * factor;
      const minSpan = 14;
      if (nHi - nLo < minSpan) return;
      nLo = Math.max(all[0][0], nLo);
      nHi = Math.min(all[all.length - 1][0], nHi);
      if (nHi - nLo < minSpan) return;
      st.view = [nLo, nHi];
      render();
    }, { passive: false });

    // drag to pan. Only the element-level listeners are (re)bound here; the window
    // listeners are registered once for the component's lifetime, below.
    const down = (e) => {
      const cx = e.touches ? e.touches[0].clientX : e.clientX;
      drag = { x: cx, win: windowFor().slice() };
      geom.svg.classList.add('dragging');
    };
    hit.addEventListener('mousedown', down);
    hit.addEventListener('touchstart', down, { passive: true });
  }

  function showTip(idx, x, ev, snap = 0) {
    const { vis } = geom;
    const lead = vis[snap];
    const p0raw = lead.raw[idx];
    if (!p0raw) return;
    const u0 = lead.unit;
    const prev = idx > 0 ? lead.raw[idx - 1] : null;
    const first = lead.raw[0];
    // Percent series move in basis points; dollars and index levels move in their
    // own units. Printing a $1.39 oil move as "-139 bp" was simply wrong.
    const inBp = u0 === 'percent';
    const scale = inBp ? 100 : 1;
    const moveUnit = inBp ? 'bps' : u0;
    const moveDp = inBp ? 0 : 2;
    const obsMove = prev ? (p0raw[1] - prev[1]) * scale : null;
    const perMove = (p0raw[1] - first[1]) * scale;
    const freqWord = { WEEKLY: 'Weekly', DAILY: 'Daily', 'REAL-TIME': 'Intraday',
      MONTHLY: 'Monthly', QUARTERLY: 'Quarterly' }[lead.frequency_label] || 'Observation';

    const rows = [
      h('div', { class: 'ts-tipdate' }, fmtDate(p0raw[0], true)),
      h('div', { class: 'ts-tiplead' }, lead.series_id + ' · ' + lead.frequency_label),
      h('div', { class: 'ts-tipval' }, unitFmt(p0raw[1], u0, u0 === 'bps' ? 0 : 2)),
      h('div', { class: 'ts-tiprow' },
        h('span', {}, `${freqWord} move`),
        h('span', { class: 'mono ' + (obsMove > 0 ? 'up' : obsMove < 0 ? 'down' : 'flat') },
          obsMove == null ? '—' : signedFmt(obsMove, moveUnit, moveDp))),
      h('div', { class: 'ts-tiprow' },
        h('span', {}, 'Period move'),
        h('span', { class: 'mono ' + (perMove > 0 ? 'up' : perMove < 0 ? 'down' : 'flat') },
          signedFmt(perMove, moveUnit, moveDp))),
    ];
    vis.forEach((s, i) => {
      if (i === snap) return;
      const j = bisect(s.raw, p0raw[0]);
      const p = s.raw[j];
      if (!p) return;
      // Stamp the row with the series' OWN observation date. A weekly print sitting
      // next to a daily one must never read as if both were observed the same day.
      const drift = Math.abs(p[0] - p0raw[0]);
      rows.push(h('div', { class: 'ts-tiprow ts-tipcmp' },
        h('span', {}, h('i', { style: `background:${s.color}` }), s.series_id,
          drift >= 1 ? h('span', { class: 'ts-drift' }, ' ' + fmtDate(p[0], true)) : null),
        h('span', { class: 'mono' }, unitFmt(p[1], s.unit, s.unit === 'bps' ? 0 : 2))));
    });

    tip.innerHTML = '';
    tip.append(...rows);
    tip.hidden = false;
    tip.style.display = '';
    // flip to the other side of the crosshair near the right edge so the tooltip
    // never covers the part of the line you are actually inspecting
    const wRect = plotWrap.getBoundingClientRect();
    const sRect = geom.svg.getBoundingClientRect();
    const px = sRect.left - wRect.left + (x / geom.W) * sRect.width;
    const tw = tip.offsetWidth || 190;
    tip.style.left = (px + tw + 18 > wRect.width ? px - tw - 14 : px + 14) + 'px';
    tip.style.top = '8px';
  }

  function showEventTip(e, x) {
    const wRect = plotWrap.getBoundingClientRect();
    const sRect = geom.svg.getBoundingClientRect();
    const px = sRect.left - wRect.left + (x / geom.W) * sRect.width;
    const row = (k, v, cls) => v == null ? null
      : h('div', { class: 'ts-tiprow' }, h('span', {}, k), h('span', { class: 'mono ' + (cls || '') }, v));
    evTip.innerHTML = '';
    // .append() coerces non-Nodes to strings, so an absent row printed literally
    // as "null". Filter before appending.
    evTip.append(...[
      h('div', { class: 'ts-tipdate' }, `${e.label} — ${fmtDate(dayNum(e.date), true)}`),
      row('Actual', e.actual != null ? String(+e.actual.toFixed(2)) : null),
      row('Forecast', e.forecast != null ? String(+e.forecast.toFixed(2)) : null),
      row('Rate before', e.rate_before != null ? e.rate_before.toFixed(2) + '%' : null),
      row('Rate after', e.rate_after != null ? e.rate_after.toFixed(2) + '%' : null),
      row('Move', e.move_bp != null ? signedFmt(e.move_bp, 'bps', 0) : null,
        e.move_bp > 0 ? 'up' : e.move_bp < 0 ? 'down' : 'flat'),
      e.forecast == null ? h('div', { class: 'ts-tipnote' },
        'No forecast on file for this print. Consensus needs a paid feed, so only the '
        + 'newest release carries one.') : null,
      h('div', { class: 'ts-tipnote' },
        h('span', { class: 'badge q-' + (e.date_confidence === 'CONFIRMED' ? 'LIVE' : 'MODELED') },
          e.date_confidence), ' ', e.date_note),
    ].filter(Boolean));
    evTip.hidden = false;
    evTip.style.display = '';
    const tw = evTip.offsetWidth || 240;
    evTip.style.left = Math.max(4, Math.min(px + 12, wRect.width - tw - 4)) + 'px';
    evTip.style.bottom = '34px';
  }
  const hideEventTip = () => { evTip.hidden = true; evTip.style.display = 'none'; };

  // ------------------------------------------------------------- legend/foot
  function renderLegend(vis) {
    legend.innerHTML = '';
    const shared = SHARES_AXIS[st.mode];
    const unitOf = (s) => modeUnit(st.mode, s.unit);
    const rightUnits = (vis.length > 1 && !shared)
      ? [...new Set(vis.slice(1).map(unitOf))].filter(u => u !== unitOf(vis[0])) : [];
    vis.forEach((s, i) => {
      const axis = (shared || unitOf(s) === unitOf(vis[0]))
        ? 'left' : `right ${rightUnits.indexOf(unitOf(s)) + 1}`;
      legend.appendChild(h('span', { class: 'ts-legitem', title: s.notes || '' },
        h('i', { style: `background:${s.color}` }),
        h('span', {}, s.name),
        h('span', { class: 'ts-axis' }, `${axis} axis · ${unitOf(s)}`),
        h('span', { class: 'badge q-' + s.quality }, s.quality),
        i && opts.onRemoveCompare ? h('button', {
          class: 'ts-x', title: 'Remove this overlay',
          onclick: () => opts.onRemoveCompare(s.series_id),
        }, '×') : null));
    });
    if (st.mode !== 'rate') {
      legend.appendChild(h('span', { class: 'note small' },
        st.mode === 'norm'
          ? 'Normalized: every series rebased to 0% at the window start, which is the only '
            + 'honest way to compare unlike units on one axis.'
          : 'Each unit keeps its own axis in this mode. Basis points and dollars are not '
            + 'the same quantity, so they are not forced onto one scale. Use NORMALIZED to '
            + 'compare unlike series directly.'));
    }
  }

  function renderFoot(vis) {
    foot.innerHTML = '';
    const p = vis[0];
    const stale = p.quality === 'STALE';
    foot.append(
      h('div', { class: 'ts-freq' },
        h('span', { class: 'badge q-' + p.quality }, stale ? 'DELAYED DATA' : p.frequency_label),
        h('span', { class: 'note small' },
          ` ${p.name} · ${p.source} · last observation ${p.obs_date} · fetched ${p.last_updated}`)),
      p.source_caveat ? h('div', { class: 'note small ins-caveat' }, p.source_caveat) : null,
      h('div', { class: 'note small' },
        `${p.full_stats.n} observations on file, ${p.full_stats.first} to ${p.full_stats.last}. `
        + `Rendering ${p._rendered || 0} of ${vis[0].raw.length} in view`
        + (p._rendered < vis[0].raw.length
          ? ', downsampled for drawing only. Hover always reads the real observation.'
          : '.')));
  }

  // ------------------------------------------------------------- render
  function render() {
    const vis = visible();
    if (!vis.length) {
      plotWrap.querySelectorAll('svg').forEach(s => s.remove());
      statsEl.innerHTML = '';
      legend.innerHTML = '';
      foot.innerHTML = '';
      plotWrap.appendChild(h('div', { class: 'unavail' },
        'NO OBSERVATIONS IN THIS WINDOW', h('br'),
        h('span', { class: 'note small' },
          `${primary.name} is a ${primary.frequency_label.toLowerCase()} series. `
          + 'Widen the range rather than expecting a value that was never published.')));
      return;
    }
    renderStats(vis);
    renderToolbar();
    draw(vis);
    renderLegend(vis);
    renderFoot(vis);
  }

  // Registered ONCE. Panning re-renders, which rebuilds the SVG, so anything bound
  // inside draw()/wireInteraction() would be torn off mid-gesture and re-added,
  // leaking a listener per frame.
  const onWinMove = (e) => {
    if (!drag || !geom) return;
    const cx = e.touches ? e.touches[0].clientX : e.clientX;
    const r = geom.svg.getBoundingClientRect();
    const plotFrac = (geom.W - geom.M.l - geom.M.r) / geom.W;
    const perPx = geom.span / Math.max(1, r.width * plotFrac);
    const shift = -(cx - drag.x) * perPx;
    const all = prepared[0].pts;
    let [lo, hi] = drag.win;
    const w = hi - lo;
    lo += shift; hi += shift;
    if (lo < all[0][0]) { lo = all[0][0]; hi = lo + w; }
    if (hi > all[all.length - 1][0]) { hi = all[all.length - 1][0]; lo = hi - w; }
    st.view = [lo, hi];
    render();
  };
  const onWinUp = () => {
    if (!drag) return;
    drag = null;
    if (geom) geom.svg.classList.remove('dragging');
  };
  window.addEventListener('mousemove', onWinMove);
  window.addEventListener('mouseup', onWinUp);
  window.addEventListener('touchmove', onWinMove, { passive: true });
  window.addEventListener('touchend', onWinUp);

  let ro = null;
  if (window.ResizeObserver) {
    let last = 0;
    ro = new ResizeObserver(() => {
      const w = plotWrap.clientWidth;
      if (Math.abs(w - last) < 8) return;
      last = w;
      if (geom) render();
    });
    ro.observe(plotWrap);
  }

  // Render synchronously; a backgrounded tab must still produce a chart.
  render();
  return {
    el: root, state: st, render,
    destroy: () => {
      if (ro) ro.disconnect();
      window.removeEventListener('mousemove', onWinMove);
      window.removeEventListener('mouseup', onWinUp);
      window.removeEventListener('touchmove', onWinMove);
      window.removeEventListener('touchend', onWinUp);
    },
  };
}
