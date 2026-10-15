// Screen renderers. Each is a pure function of its API payload.
import { h, fmt, signed, arrowLabel, qualityBadge, pill, panel, table, kv, cellRow, unavailable, inspectable } from './components.js';
import { lineChart, legendFor, curveChart, sparkline, percentileStrip } from './charts.js';
import { TimeSeriesChart } from './timeseries.js';

const CELL_HEAD = ['Series', 'Value', '1D', '1W', 'Src'];
const CELL_ALIGN = ['', 'r', 'r', 'r', ''];

const cellTable = (cells) => table(CELL_HEAD, cells.map(c => cellRow(c)), { align: CELL_ALIGN });

/* ------------------------------------------------------------------ DASH */
// Fixed two-by-three grid sized to the viewport. Nothing on DASH scrolls the page;
// each panel scrolls its own body if it overflows. The whole point of this screen is
// a 30-second read, and a read you have to scroll for is not a 30-second read.
export function renderDash(d, ctx) {
  const stack = (...kids) => h('div', { class: 'stack' }, ...kids.filter(Boolean));
  // The pressure panel spans both rows. It carries the headline number AND the
  // bullet read, so it is the one panel that should never need scrolling.
  const grid = h('div', { class: 'dash-fit' },
    pressurePanel(d.pressure),
    whyPanel(d.why, ctx),
    stack(spreadMini(d.spread), alertPanel(d.alerts)),
    panel('MORNING BRIEF', briefBody(d.brief), { hint: d.brief.word_count + ' words' }),
    driverPanel(d.pressure),
    stack(panel('TIER 1 · DIRECT DRIVERS', cellTable(d.tier1), { tight: true }),
      significancePanel(d.significance)),
    panel('EVENT CALENDAR', calendarTable(d.calendar), { tight: true, hint: 'next 10d' }));
  // A HousingWire-style scan strip on top: the actual rate levels at a glance,
  // plus the one-click borrower read. The dense terminal below is untouched.
  return h('div', { class: 'dash-wrap' }, kpiStrip(d, ctx), grid);
}

/* KPI scan strip. Reads real levels straight out of d.ticker (already in the
   dash payload), so this is provenance-badged and adds no new data path. */
// For a price that moves inverse to rates (MBS), the arrow should follow the
// price while the color follows the rate implication: price down is red (rates up).
function priceDelta(v, dp, suffix) {
  if (v == null || Number.isNaN(v)) return h('span', { class: 'dir flat' }, h('span', { class: 'arrow' }, '·'), '—');
  const up = v > 0;
  return h('span', { class: 'dir ' + (up ? 'down' : 'up'), title: up ? 'price up, rates down' : 'price down, rates up' },
    h('span', { class: 'arrow' }, up ? '▲' : '▼'),
    signed(v, dp, suffix));
}

function kpiTile(cell, { label, dp = 2, suffix = '' } = {}) {
  if (!cell || !cell.available) {
    return h('div', { class: 'kpi' },
      h('div', { class: 'lab' }, label || (cell && cell.name) || '—'),
      h('div', { class: 'kpi-val dim' }, '—'),
      h('div', { class: 'note small' }, 'unavailable'));
  }
  const delta = cell.invert_for_rates
    ? priceDelta(cell.change_1d, dp, suffix)
    : arrowLabel(cell.change_1d, { dp, suffix, words: false });
  return h('div', { class: 'kpi' },
    h('div', { class: 'kpi-top' },
      h('span', { class: 'lab' }, label || cell.ticker || cell.name),
      qualityBadge(cell.quality, cell.name)),
    h('div', { class: 'kpi-val' }, fmt(cell.value, dp) + suffix),
    delta);
}

function kpiStrip(d, ctx) {
  const items = (d.ticker && d.ticker.items) || [];
  const by = (id) => items.find((c) => c.series_id === id);
  const ev = d.ticker && d.ticker.next_event;
  const evTile = ev ? h('div', { class: 'kpi' },
    h('div', { class: 'lab' }, 'NEXT EVENT'),
    h('div', { class: 'kpi-val small' }, ev.name),
    h('div', { class: 'note small' },
      (ev.days_out === 0 ? 'TODAY' : 'T+' + ev.days_out + 'd') + (ev.impact ? ' · ' + ev.impact : ''))) : null;
  return h('div', { class: 'kpi-strip' },
    kpiTile(by('MORT30Y'), { label: '30Y FIXED', dp: 3, suffix: '%' }),
    kpiTile(by('UST10Y'), { label: '10Y UST', dp: 3, suffix: '%' }),
    kpiTile(by('MTG_UST_SPREAD'), { label: 'MTG SPREAD', dp: 0, suffix: ' bp' }),
    kpiTile(by('MBS_CC'), { label: 'MBS CC', dp: 3, suffix: '%' }),
    evTile,
    h('button', { class: 'kpi-cta', title: 'Plain-English read you can send a borrower',
      onclick: () => openBorrowerModal(ctx) },
      h('span', { class: 'kpi-cta-sub' }, 'ONE-CLICK'),
      h('span', { class: 'kpi-cta-main' }, 'WHAT TO TELL A BORROWER')));
}

/* The borrower register already lives in /api/brief. This surfaces it as a
   one-click popup with a copy button, HousingWire's "Generate AI Summary" move. */
function openBorrowerModal(ctx) {
  const prior = document.getElementById('bm-host');
  if (prior) prior.remove();
  const esc = (e) => { if (e.key === 'Escape') close(); };
  const close = () => { host.remove(); document.removeEventListener('keydown', esc); };
  const body = h('div', { class: 'ins-body' }, h('p', { class: 'note small' }, 'Loading the borrower read…'));
  const actions = h('div', { class: 'ins-actions' }, h('button', { class: 'btn', onclick: close }, 'CLOSE'));
  const host = h('div', {
    id: 'bm-host', class: 'inspector', style: 'display:flex',
    role: 'dialog', 'aria-modal': 'true', 'aria-label': 'What to tell a borrower',
    onclick: (e) => { if (e.target === host) close(); },
  }, h('div', { class: 'ins-card', style: 'max-width:600px' },
    h('header', {}, h('div', {}, h('h2', {}, 'WHAT TO TELL A BORROWER')),
      h('button', { class: 'btn', onclick: close }, 'ESC')),
    body, actions));
  document.body.appendChild(host);
  document.addEventListener('keydown', esc);

  const briefURL = window.MRIT_STATIC ? 'data/brief.json' : '/api/brief';
  fetch(briefURL).then((r) => r.json()).then((d) => {
    const t = d && d.translations && d.translations.BORROWER;
    if (!t) { body.replaceChildren(h('p', { class: 'note' }, 'No borrower read is available right now.')); return; }
    body.replaceChildren(...[
      h('p', { class: 'bm-text' }, t.text),
      t.disclaimer ? h('p', { class: 'note small', style: 'margin-top:10px;color:var(--stale)' }, t.disclaimer) : null,
    ].filter(Boolean));
    actions.replaceChildren(
      pill('CONF ' + t.confidence, t.confidence),
      h('button', { class: 'btn', onclick: () => { close(); ctx.go('BRIEF'); } }, 'ALL REGISTERS →'),
      h('button', {
        class: 'btn primary', onclick: (e) => {
          if (navigator.clipboard) navigator.clipboard.writeText(t.text);
          e.target.textContent = 'COPIED';
          setTimeout(() => { e.target.textContent = 'COPY TEXT'; }, 1400);
        },
      }, 'COPY TEXT'));
  }).catch((err) => { body.replaceChildren(h('p', { class: 'note' }, 'Could not load the brief: ' + err.message)); });
}

export function significancePanel(sig) {
  if (!sig || !sig.moves || !sig.moves.length) return null;
  const rows = sig.moves.map(m => ({
    _hi: m.verdict === 'EXTREME' || m.verdict === 'LARGE',
    cells: [
      h('div', {}, h('div', {}, m.label),
        h('div', { class: 'note small' }, m.verdict_detail)),
      arrowLabel(m.move_bp, { dp: 1, suffix: ' bp', words: false }),
      h('span', { class: 'mono' }, m.z == null ? '—' : signed(m.z, 1) + 'σ'),
      h('div', { class: 'bar', title: m.abs_percentile + 'th percentile by magnitude' },
        h('span', { class: m.abs_percentile >= 85 ? 'up' : 'down',
          style: `width:${m.abs_percentile}%` })),
      h('span', { class: 'mono' }, fmt(m.abs_percentile, 0) + 'th'),
      pill(m.verdict, m.abs_percentile >= 85 ? 'HIGH' : m.abs_percentile >= 60 ? 'MEDIUM' : 'LOW'),
    ],
  }));
  return panel('HOW BIG IS THIS MOVE, REALLY', [
    table(['Horizon', 'Move', 'z', 'Percentile by magnitude', '', 'Verdict'], rows,
      { align: ['', 'r', 'r', '', 'r', ''] }),
    h('p', { class: 'note small', style: 'padding:9px 11px 0' }, sig.note),
  ], { tight: true, hint: sig.tenure_start ? 'compared against history and against your tenure since ' + sig.tenure_start : 'compared against full history' });
}

function pressurePanel(p) {
  const order = ['STRONG DOWNWARD', 'MODERATE DOWNWARD', 'NEUTRAL', 'MODERATE UPWARD', 'STRONG UPWARD'];
  const idx = order.indexOf(p.band);
  const meter = h('div', { class: 'meter' }, order.map((b, i) =>
    h('div', { class: i === idx ? (i < 2 ? 'on-down' : i > 2 ? 'on-up' : 'on-flat') : '',
      title: b })));
  const cls = p.net_bp > 0.5 ? 'up' : p.net_bp < -0.5 ? 'down' : 'flat';
  const pan = panel('RATE PRESSURE METER', [
    h('div', { class: 'lab' }, 'Net observed pressure on mortgage rates'),
    // Number and verdict share a line so the bullets below get the vertical room.
    h('div', { class: 'meter-head' },
      h('span', { class: 'huge ' + cls }, signed(p.net_bp, 1) + ' bp'),
      h('span', { class: cls, style: 'font:600 13px var(--mono);letter-spacing:.06em' },
        (p.net_bp > 0.5 ? '▲ ' : p.net_bp < -0.5 ? '▼ ' : '► ') + p.band_label.toUpperCase())),
    meter,
    h('div', { class: 'meterlabels' }, ['STRONG ▼', 'MOD ▼', 'NEUTRAL', 'MOD ▲', 'STRONG ▲'].map(x => h('span', {}, x))),
    // Bullets scroll; the head and the provenance footer stay pinned, so the
    // reading and its sourcing are never the parts that fall below the fold.
    h('div', { class: 'meter-scroll' }, bulletList(p.bullets)),
    provenanceFooter(p.provenance, p),
  ], { info: 'DASH' });
  pan.classList.add('panel-pressure');
  return pan;
}

/** The read, in scannable lines. Each carries where it came from and when. */
function bulletList(bullets) {
  if (!bullets || !bullets.length) return null;
  return h('ul', { class: 'bullets' }, bullets.map(b =>
    h('li', { class: 'b-' + b.direction.toLowerCase() },
      h('span', { class: 'b-arrow', 'aria-hidden': 'true' }, b.arrow),
      h('div', {},
        h('div', { class: 'b-text' }, b.text),
        inspectable(
          h('div', { class: 'b-src' },
            h('span', {}, b.source), ' · ', h('span', {}, b.obs_date), ' ',
            qualityBadge(b.quality)),
          b.series_id, b.text)))));
}

function provenanceFooter(prov, p) {
  if (!prov) return null;
  const when = (prov.generated_at || '').replace('T', ' ').replace('Z', ' UTC');
  return h('div', { class: 'prov-foot' },
    h('div', { class: 'lab' }, 'PULLED FROM'),
    h('div', {}, prov.sources.map((s, i) => h('span', {},
      i ? '  ·  ' : '', h('span', { class: 'prov-src' }, s.source),
      ' ', h('span', { class: 'prov-date' }, s.obs_date)))),
    h('div', { class: 'note small', style: 'margin-top:3px' },
      when + ' · ' + p.observed_count + ' observed, ' + p.inferred_count
      + ' inferred · click a line for its source'));
}

function whyPanel(w, ctx) {
  const row = (label, c) => c ? h('div', { style: 'margin-bottom:9px' },
    h('div', { class: 'lab' }, label),
    h('div', {}, h('strong', {}, c.name), ' ',
      arrowLabel(c.bp, { dp: 1, suffix: ' bp', words: true }), ' ',
      pill(c.basis, c.basis), ' ', pill(c.confidence + ' CONF', c.confidence)),
    h('div', { class: 'note small' }, c.detail)) : null;
  return panel('WHY RATES MOVED', [
    h('p', { class: 'note', style: 'margin:0 0 9px;color:var(--fg)' }, w.headline),
    row('PRIMARY DRIVER', w.primary),
    row('SECONDARY DRIVER', w.secondary),
    row('COUNTERFORCE', w.counterforce),
    h('p', { class: 'note small', style: 'margin:9px 0 0' }, w.summary),
    h('div', { style: 'margin-top:9px' }, pill('CONFIDENCE ' + w.confidence, w.confidence), ' ',
      h('span', { class: 'note small' }, w.confidence_reason)),
    h('button', { class: 'btn', style: 'margin-top:9px', onclick: () => ctx.go('WHY') }, 'FULL CAUSAL TRACE →'),
  ], { hint: 'confidence-scored', info: 'WHY' });
}

function driverPanel(p) {
  const max = Math.max(...p.contributors.map(c => Math.abs(c.bp)), 1);
  const rows = p.contributors.map((c, i) => ({
    cells: [
      h('span', { class: 'mono', style: 'color:var(--dim)' }, String(i + 1).padStart(2, '0')),
      inspectable(h('span', { title: c.detail }, c.name), c.series_id, c.name),
      arrowLabel(c.bp, { dp: 1, suffix: ' bp', words: false }),
      h('div', { class: 'bar', title: c.detail },
        h('span', { class: c.bp > 0 ? 'up' : 'down', style: `width:${Math.abs(c.bp) / max * 100}%` })),
      pill(c.basis, c.basis),
    ],
  }));
  return panel("TODAY'S RATE DRIVERS", [
    table(['#', 'Driver', 'Pressure', '', 'Basis'], rows, { align: ['', '', 'r', '', ''] }),
    h('p', { class: 'note small', style: 'padding:9px 11px 0' },
      '▲ pushes mortgage rates up. ▼ pushes them down. OBSERVED comes from published data. '
      + 'INFERRED is a macro release scaled by surprise size and shown for direction only.'),
  ], { tight: true });
}

function spreadMini(s) {
  if (!s) return panel('MORTGAGE SPREAD', unavailable('No spread history yet.'));
  return panel('MORTGAGE / 10Y SPREAD', [
    h('div', { class: 'big' }, fmt(s.spread_bp, 0) + ' bp'),
    h('div', { class: 'lab', style: 'margin-top:2px' }, s.band + ' · ' + fmt(s.percentile, 0) + 'TH PCTILE OF ' + s.years + 'Y'),
    kv([
      ['10Y avg', fmt(s.avg_bp, 0) + ' bp'],
      ['vs avg', signed(s.excess_vs_avg_bp, 0) + ' bp'],
      ['range', fmt(s.min_bp, 0) + ' – ' + fmt(s.max_bp, 0) + ' bp'],
      ['as of', s.obs_date],
    ]),
  ], { hint: s.quality });
}

function alertPanel(alerts) {
  if (!alerts || !alerts.length) {
    return panel('ALERTS', h('div', { class: 'note small' }, 'No thresholds breached. '
      + 'Rules cover 10Y ±5bp, MBS ±20 ticks, mortgage rate ±0.125%, spread extremes, '
      + 'and CPI or payroll surprises beyond 1 sigma.'));
  }
  return panel('ALERTS', alerts.map(a => h('div', { style: 'margin-bottom:9px' },
    h('div', {}, pill(a.severity, a.severity), ' ', h('strong', {}, a.label)),
    h('div', { class: 'note small' }, a.detail),
    h('div', { class: 'note small', style: 'color:var(--fg2)' }, 'Why it matters: ' + a.why))));
}

const briefBody = (b) => [
  h('div', { class: 'lab' }, b.title + ' · ' + b.date),
  h('p', { class: 'note', style: 'margin:7px 0 0;color:var(--fg)' }, b.body),
];

function calendarTable(events) {
  if (!events || !events.length) return h('div', { class: 'note small', style: 'padding:11px' }, 'Nothing scheduled.');
  return table(['When', 'Event', 'Impact', 'Sched'], events.map(e => ({
    _hi: e.impact === 'HIGH',
    cells: [
      h('span', { class: 'mono' }, e.days_out === 0 ? 'TODAY' : 'T+' + e.days_out),
      h('span', { title: e.why }, h('div', {}, e.name),
        h('div', { class: 'note small' }, e.date + ' ' + e.time)),
      pill(e.impact, e.impact),
      h('span', { class: 'badge q-' + (e.scheduled === 'CONFIRMED' ? 'LIVE' : 'MODELED') }, e.scheduled),
    ],
  })));
}

/* ------------------------------------------------------------------- WHY */
export function renderWhy(w) {
  const c = w.causal;
  const chains = (c.contributions || []).map(x => h('div', { style: 'margin-bottom:13px' },
    h('div', {}, inspectable(h('strong', {}, x.label), seriesForNode(x.node), x.label), ' ',
      arrowLabel(x.contribution, { dp: 2, words: true }), ' ',
      h('span', { class: 'note small' }, 'shock ' + signed(x.shock, 2) + ' σ'),
      x.n_paths > 1 ? h('span', {}, ' ', pill(x.n_paths + ' CHANNELS',
        x.self_offsetting ? 'MEDIUM' : 'LOW')) : null),
    // When a driver reaches the mortgage rate more than once, show every leg.
    // Collapsing them to a net would hide the exact tension worth understanding.
    (x.legs && x.legs.length > 1)
      ? h('div', {}, x.legs.map(l => h('div', { style: 'padding:3px 0 3px 12px' },
        arrowLabel(l.contribution, { dp: 2, words: false }), ' ',
        h('span', { class: 'chain' }, l.chain))))
      : h('div', { class: 'chain' }, x.chain),
    x.self_offset_note
      ? h('div', { class: 'note small', style: 'color:var(--modeled);margin-top:3px' },
        x.self_offset_note)
      : (x.rationales.length ? h('div', { class: 'note small' }, x.rationales[0]) : null)));

  return h('div', { class: 'grid' },
    panel('EXPLANATION', [
      h('p', { class: 'note', style: 'margin:0;color:var(--fg);font-size:13px' }, w.headline),
      h('p', { class: 'note', style: 'margin:9px 0 0' }, w.summary),
      h('div', { style: 'margin-top:11px' }, pill('CONFIDENCE ' + w.confidence, w.confidence), ' ',
        h('span', { class: 'note small' }, w.confidence_reason)),
    ]),
    h('div', { class: 'grid g2' },
      panel('DRIVERS PUSHING RATES UP', driverList(w.upward_drivers, 'up')),
      panel('DRIVERS PUSHING RATES DOWN', driverList(w.downward_drivers, 'down'))),
    panel('CAUSAL TRACE', [
      h('p', { class: 'note small', style: 'margin:0 0 11px' },
        `Every chain below is a path through the relationship graph, ending at the 30-year `
        + `mortgage rate. Upward force ${c.upward_force}, downward force ${c.downward_force}. `
        + (c.competing ? 'Forces are OFFSETTING, which is why confidence is capped.'
          : 'Forces are aligned.')),
      chains.length ? chains : h('div', { class: 'note small' }, 'No macro shocks inside the actionable window.'),
    ]),
    significancePanel(w.significance),
    panel('STRUCTURAL INVARIANT', h('p', { class: 'note small', style: 'margin:0' },
      w.graph ? w.graph.invariant : '')));
}

const driverList = (list, dir) => (list && list.length)
  ? list.map(c => h('div', { style: 'margin-bottom:8px' },
    h('div', {}, arrowLabel(c.bp, { dp: 1, suffix: ' bp', words: false }), ' ', h('strong', {}, c.name),
      ' ', pill(c.basis, c.basis)),
    h('div', { class: 'note small' }, c.detail)))
  : h('div', { class: 'note small' }, 'None registering.');

// Map a causal node back to the series behind it so the label stays clickable.
const NODE_SERIES = {
  CORE_CPI: 'CORECPI_MOM', HEADLINE_CPI: 'CPI_YOY', PPI: 'PPI', SHELTER: 'SHELTER',
  AHE: 'AHE_YOY', NFP: 'NFP', UNRATE: 'UNRATE', CLAIMS: 'CLAIMS', JOLTS: 'JOLTS',
  OIL: 'OIL', BRENT: 'BRENT', VIX: 'VIX', HY_SPREAD: 'HY_SPREAD', RETAIL: 'RETAIL',
  UST_10Y: 'UST10Y', UST_2Y: 'UST2Y', MBS_SPREAD: 'MBS_SPREAD', MORTGAGE_30Y: 'MORT30Y',
};
const seriesForNode = (n) => NODE_SERIES[n];

/* ------------------------------------------------------------------- UST */
export function renderUST(d) {
  const i = d.interpretation || {};
  const svg = curveChart(d.curve);
  return h('div', { class: 'grid' },
    h('div', { class: 'grid g32' },
      panel('YIELD CURVE', [svg,
        h('div', { class: 'legend' },
          h('span', { html: '<i style="background:#e8a33d"></i>today' }),
          h('span', { html: '<i style="background:#4aa3df"></i>1 week ago' }),
          h('span', { html: '<i style="background:#8d9aa8"></i>1 month ago' }),
          h('span', { html: '<i style="background:#5f6c7a"></i>1 quarter ago' }))],
      { hint: 'log-spaced by maturity', info: 'UST' }),
      panel('CURVE SHAPE', [
        h('div', { class: 'big' }, fmt(i.slope_bp, 0) + ' bp'),
        h('div', { class: 'lab' }, '2s10s · ' + (i.shape || '').toUpperCase() + ' · ' + (i.motion || '').toUpperCase()),
        h('p', { class: 'note small', style: 'margin-top:9px' }, i.explanation || ''),
        h('div', { style: 'margin-top:9px' }, cellTable(d.slopes)),
      ])),
    panel('TREASURY CURVE', cellTable(d.cells), { tight: true, hint: d.source }));
}

/* ------------------------------------------------------------------- MBS */
export function renderMBS(d) {
  const s = d.stack;
  if (!s) return panel('MBS', unavailable('No current-coupon data. Run a refresh.'));
  // No price or ticks columns: without a licensed TBA feed those would be invented.
  // The stack shows yield, duration and spread by coupon, which are derived from the
  // current-coupon yield and honest about being a shape, not a quote.
  const rows = s.rows.map(r => ({
    _hi: r.is_production,
    cells: [
      h('span', { class: 'mono' }, r.coupon.toFixed(1) + (r.is_production ? '  ◄ PRODUCTION' : '')),
      h('span', { class: 'mono' }, fmt(r.yield, 3)),
      h('span', { class: 'mono' }, fmt(r.duration, 2)),
      h('span', { class: 'mono' }, fmt(r.spread_bp, 0)),
      h('span', { class: 'note small' }, r.moneyness),
    ],
  }));
  return h('div', { class: 'grid' },
    h('div', { class: 'banner' }, d.banner),
    h('div', { class: 'grid g23' },
      panel('MBS READ', cellTable(d.cells),
        { tight: true, hint: 'spread is LIVE · current coupon is DERIVED', info: 'MBS' }),
      h('div', { class: 'grid' },
        panel('CURRENT COUPON', [
          h('div', { class: 'big' }, fmt(s.current_coupon, 3) + '%'),
          h('div', { class: 'lab' }, 'as of ' + s.obs_date + ' · ' + s.quality),
          kv([['Benchmark', fmt(s.benchmark_yield, 3) + '% (5s10s blend)'],
            ['Production', s.production_coupon.toFixed(1)]]),
          h('p', { class: 'note small', style: 'margin-top:9px' }, s.model),
        ]),
        panel('HOW TO READ THIS', h('ul', { class: 'note', style: 'margin:0;padding-left:16px' },
          d.teaching.map(t => h('li', { style: 'margin-bottom:5px' }, t)))))),
    panel('FNMA 30Y COUPON STACK', table(
      ['Coupon', 'Yield', 'Dur', 'Spread bp', ''],
      rows, { align: ['', 'r', 'r', 'r', ''] }),
      { tight: true, hint: 'MODELED for shape · production coupon ' + s.production_coupon.toFixed(1) }));
}

/* ---------------------------------------------------------------- SPREAD */
export function renderSpread(d) {
  if (!d.available) return panel('SPREAD', unavailable('No spread history.'));
  const wk = d.weekly_decomposition, day = d.daily;
  const series = [{ name: 'Mortgage / 10Y spread (bp)', points: d.series, color: '#e8a33d' }];
  const chart = lineChart(series, { height: 240, label: 'Mortgage to Treasury spread history' });

  const decomp = wk ? panel('WHAT MOVED THE RATE (WEEK OVER WEEK)', [
    h('div', { class: 'lab' }, wk.from_date + ' → ' + wk.to_date),
    table(['Leg', 'Move', 'Share'], [
      { cells: ['30Y mortgage rate', arrowLabel(wk.mortgage_bp, { dp: 1, suffix: ' bp', words: false }), '100%'] },
      { cells: ['from Treasury yield', arrowLabel(wk.treasury_bp, { dp: 1, suffix: ' bp', words: false }), fmt(wk.treasury_share, 0) + '%'] },
      { cells: ['from mortgage spread', arrowLabel(wk.spread_bp, { dp: 1, suffix: ' bp', words: false }), wk.treasury_share != null ? fmt(100 - wk.treasury_share, 0) + '%' : '—'] },
    ], { align: ['', 'r', 'r'] }),
    h('p', { class: 'note small', style: 'padding-top:9px' }, wk.note),
  ], { tight: false, hint: 'EXACT IDENTITY' }) : null;

  return h('div', { class: 'grid' },
    h('div', { class: 'grid g3' },
      panel('SPREAD', [h('div', { class: 'huge' }, fmt(d.spread_bp, 0)),
        h('div', { class: 'lab' }, 'BASIS POINTS · ' + d.band),
        h('div', { class: 'note small', style: 'margin-top:6px' }, 'as of ' + d.obs_date)],
        { info: 'SPREAD' }),
      panel('COMPOSITION', kv([
        ['Mortgage rate', fmt(d.mortgage_rate, 2) + '%'],
        ['10Y Treasury', fmt(d.ust10, 2) + '%'],
        ['Spread', fmt(d.spread_bp, 0) + ' bp'],
        ['Treasury share', fmt(d.decomposition.treasury_pct, 1) + '% of the rate'],
        ['Spread share', fmt(d.decomposition.spread_pct, 1) + '% of the rate'],
      ])),
      panel('VERSUS HISTORY', kv([
        ['Percentile', fmt(d.percentile, 0) + 'th of ' + d.years + ' years'],
        ['Average', fmt(d.avg_bp, 0) + ' bp'],
        ['vs average', signed(d.excess_vs_avg_bp, 0) + ' bp'],
        ['Range', fmt(d.min_bp, 0) + ' – ' + fmt(d.max_bp, 0) + ' bp'],
        ['Observations', d.n_obs],
      ]))),
    panel('PERCENTILE BAND', [percentileStrip(d.percentile, d.bands),
      h('p', { class: 'note small', style: 'margin-top:6px' }, d.explanation)]),
    decomp,
    panel('DAILY VIEW', [kv([
      ['10Y today', fmt(day.ust10, 2) + '%'],
      ['10Y change', arrowLabel(day.ust10_bp, { dp: 1, suffix: ' bp', words: true })],
      ['Modeled mortgage', fmt(day.mortgage_est, 3) + '%'],
      ['Spread leg', h('span', { class: 'badge q-UNAVAILABLE' }, day.spread_leg)],
    ]), h('p', { class: 'note small', style: 'margin-top:9px' }, day.note)]),
    panel('SPREAD HISTORY', [chart], { tight: false, hint: d.n_obs + ' weekly observations' }));
}

/* ------------------------------------------------------------------- FED */
export function renderFed(d) {
  const s = d.stance;
  const scale = ['VERY DOVISH', 'DOVISH', 'NEUTRAL', 'HAWKISH', 'VERY HAWKISH'];
  const idx = scale.indexOf(s.stance);
  return h('div', { class: 'grid' },
    h('div', { class: 'grid g3' },
      panel('FED STANCE', [
        h('div', { class: 'big', style: 'font-size:22px' }, s.stance),
        h('div', { class: 'meter' }, scale.map((x, i) =>
          h('div', { class: i === idx ? (i < 2 ? 'on-down' : i > 2 ? 'on-up' : 'on-flat') : '', title: x }))),
        h('div', { class: 'meterlabels' }, scale.map(x => h('span', {}, x.split(' ').pop()[0] + (x.startsWith('VERY') ? 'V' : '')))),
        h('div', { class: 'lab', style: 'margin-top:9px' }, 'IMPLICATION FOR MORTGAGE RATES'),
        h('div', {}, s.rate_impact_label),
        h('div', { class: 'lab', style: 'margin-top:9px' }, 'INPUTS'),
        h('ul', { class: 'note small', style: 'margin:3px 0 0;padding-left:15px' },
          s.inputs.map(x => h('li', {}, x))),
      ], { hint: 'score ' + s.score, info: 'FED' }),
      panel('MARKET-IMPLIED FED PATH', (() => {
        const ep = (d.cells || []).find(c => c.series_id === 'FED_PROB_CUT');
        if (!ep || !ep.available || ep.value === null) return unavailable(s.probabilities_note);
        const bp = ep.value;
        const read = bp > 2 ? `${bp.toFixed(0)} bp of easing priced into the 1Y`
          : bp < -2 ? `${Math.abs(bp).toFixed(0)} bp of tightening priced into the 1Y`
            : 'the 1Y is priced in line with the current target';
        return [
          h('div', { class: 'big', style: 'font-size:22px' },
            (bp >= 0 ? '+' : '') + bp.toFixed(0) + ' bp'),
          h('div', { style: 'margin-top:2px' }, read),
          h('div', { style: 'margin-top:7px' }, qualityBadge(ep.quality, ep.notes)),
          h('p', { class: 'note small', style: 'margin-top:9px' }, s.probabilities_note),
        ];
      })()),
      panel('TRANSMISSION MECHANISM', [
        h('div', { class: 'chain', style: 'font-size:12px;line-height:2' },
          s.transmission.map((t, i) => h('span', {}, i ? ' → ' : '', h('span', { class: 'n' }, t)))),
        h('p', { class: 'note', style: 'margin-top:11px;color:var(--up)' }, s.caveat),
        h('p', { class: 'note small' }, d.transmission_note),
      ])),
    h('div', { class: 'grid g2' },
      panel('FED SERIES', cellTable(d.cells), { tight: true }),
      panel('2026 FOMC CALENDAR', table(['Date', 'Countdown'], d.fomc_dates.map(f => ({
        _hi: f.days_out >= 0 && f.days_out < 21,
        cells: [f.date, h('span', { class: 'mono' },
          f.days_out < 0 ? 'past' : f.days_out === 0 ? 'TODAY' : 'T-' + f.days_out + ' days')],
      })), { align: ['', 'r'] }), { tight: true })));
}

/* ------------------------------------------------------------------ TIER */
export function renderTier(d) {
  const rows = d.releases.map(r => ({
    _hi: r.classification.startsWith('VERY'),
    cells: [
      h('span', { title: r.notes }, h('div', {}, r.name),
        h('div', { class: 'note small' }, r.period + ' · ' + r.impact)),
      h('span', { class: 'mono' }, fmt(r.previous, 2)),
      h('span', { class: 'mono', title: 'benchmark: ' + r.benchmark }, fmt(r.consensus, 2)),
      h('span', { class: 'mono val' }, fmt(r.actual, 2)),
      arrowLabel(r.surprise, { dp: 2, words: false, upWord: 'above', downWord: 'below', flatWord: 'inline' }),
      h('span', { class: 'mono' }, r.surprise_z == null ? '—' : signed(r.surprise_z, 2) + 'σ'),
      h('span', { class: r.classification.includes('BULL') ? 'down' : r.classification.includes('BEAR') ? 'up' : 'flat' },
        (r.classification.includes('BULL') ? '▼ ' : r.classification.includes('BEAR') ? '▲ ' : '► ')
        + r.classification_label),
    ],
  }));
  return h('div', { class: 'grid' },
    panel('RELEASES · ' + d.tier_name.toUpperCase(), [
      table(['Release', 'Previous', 'Benchmark', 'Actual', 'Surprise', 'z', 'Rate impact'],
        rows, { align: ['', 'r', 'r', 'r', 'r', 'r', ''] }),
      h('p', { class: 'note small', style: 'padding:9px 11px 0' },
        d.class_note + ' No free consensus feed exists, so the benchmark column is the trailing '
        + 'mean of the series unless a consensus has been entered manually. Hover it to confirm which.'),
    ], { tight: true }),
    panel('SERIES · TIER ' + d.tier, cellTable(d.cells), { tight: true }));
}

/* -------------------------------------------------------------- CALENDAR */
export function renderCalendar(d) {
  const rows = d.events.map(e => ({
    _hi: e.impact === 'HIGH',
    cells: [
      h('span', { class: 'mono' }, e.days_out === 0 ? 'TODAY' : 'T+' + e.days_out),
      h('span', { class: 'mono' }, e.date + ' ' + e.time),
      h('div', {}, h('div', {}, e.name), h('div', { class: 'note small' }, e.why)),
      pill(e.impact, e.impact),
      h('span', { class: 'mono' }, e.previous != null ? fmt(e.previous, 2) : '—'),
      h('span', { class: 'mono' }, e.consensus != null ? fmt(e.consensus, 2) : '—'),
      h('span', { class: 'mono' }, e.last_actual != null ? fmt(e.last_actual, 2) : '—'),
      h('span', { class: 'note small' }, e.last_classification || '—'),
      h('span', { class: 'badge q-' + (e.scheduled === 'CONFIRMED' ? 'LIVE' : 'MODELED') }, e.scheduled),
    ],
  }));
  return h('div', { class: 'grid' },
    panel('MARKET EVENT CALENDAR', [
      table(['Countdown', 'When', 'Event', 'Impact', 'Prev', 'Bench', 'Last actual', 'Last impact', 'Sched'],
        rows, { align: ['', '', '', '', 'r', 'r', 'r', '', ''] }),
      h('p', { class: 'note small', style: 'padding:9px 11px 0' }, d.note),
    ], { tight: true }),
    d.alerts && d.alerts.length ? panel('ACTIVE ALERTS', d.alerts.map(a =>
      h('div', { style: 'margin-bottom:9px' },
        h('div', {}, pill(a.severity, a.severity), ' ', h('strong', {}, a.label)),
        h('div', { class: 'note small' }, a.detail),
        h('div', { class: 'note small' }, 'Why it matters: ' + a.why)))) : null);
}

/* --------------------------------------------------------------- HISTORY */
export function renderHistory(d, ctx) {
  const wrap = h('div', { class: 'grid' });
  if (ctx.activeChart && ctx.activeChart.destroy) ctx.activeChart.destroy();
  const chart = TimeSeriesChart(d, {
    range: ctx.state.chartRange, mode: ctx.state.chartMode,
    events: [...ctx.state.chartEvents], height: 300,
    onPickSeries: () => openSeriesPicker(d, ctx),
    onAddCompare: () => openComparePicker(d, ctx),
    onRemoveCompare: (sid) => ctx.setChart({ removeCompare: sid }),
    onToggleEvents: () => openEventPicker(d, ctx),
  });
  ctx.activeChart = chart;
  // Remember what the user picked so a refetch (add/remove overlay) does not
  // bounce them back to the default range and mode.
  chart.el.addEventListener('click', () => {
    ctx.state.chartRange = chart.state.range;
    ctx.state.chartMode = chart.state.mode;
  }, true);

  const c = d.context || {};
  wrap.className = 'grid hist-layout';
  wrap.append(
    panel(d.series[0].name.toUpperCase() + ' — INTERACTIVE HISTORY', chart.el,
      { hint: 'scroll to zoom · drag to pan · hover to inspect', info: 'HISTORY' }),
    h('div', { class: 'grid hist-rail' },
      c.alerts && c.alerts.length ? alertPanel(c.alerts) : null,
      c.bullets ? panel('THE READ', h('ul', { class: 'bullets' }, c.bullets.map(b =>
        h('li', { class: 'b-' + b.direction.toLowerCase() },
          h('span', { class: 'b-arrow' }, b.arrow),
          h('div', {}, h('div', { class: 'b-text' }, b.text),
            h('div', { class: 'b-src' }, b.source + ' · ' + b.obs_date))))))
        : null,
      panel('MARKET MOVERS', cellTable(c.movers || []), { tight: true }),
      c.drivers ? panel('WHAT IS PUSHING RATES', table(['Driver', 'Pressure', 'Basis'],
        c.drivers.map(x => ({ cells: [
          inspectable(h('span', { title: x.detail }, x.name), x.series_id, x.name),
          arrowLabel(x.bp, { dp: 1, suffix: ' bp', words: false }),
          pill(x.basis, x.basis)] })), { align: ['', 'r', ''] }), { tight: true }) : null,
      panel('NEXT EVENTS', calendarTable(c.upcoming || []), { tight: true, hint: 'next 14d' })),
    panel('READING THIS CHART', h('p', { class: 'note small', style: 'margin:0' },
      'Hover anywhere for the exact observation, the move since the prior print, and the '
      + 'move since the window start. Ranges shorter than the series frequency are disabled '
      + 'rather than interpolated: a weekly survey has no intraday value to show you. '
      + 'Dashed lines are MODELED series. Add a comparison to overlay Treasuries, MBS, the '
      + 'spread, inflation or oil; unlike units get their own axis, or switch to NORMALIZED '
      + 'to rebase everything to zero at the window start.')));
  return wrap;
}

function openSeriesPicker(d, ctx) {
  let chosen = d.series[0].series_id;
  const body = h('div', {},
    h('p', { class: 'note small', style: 'margin:0 0 10px' },
      'The crosshair snaps to whichever series in view has the most observations, so a '
      + 'daily overlay already gives you daily granularity. Changing the PRIMARY also '
      + 'changes which ranges are offered: a weekly survey cannot answer 1D or 5D, a '
      + 'daily series can.'),
    ...d.catalog.compare.map(g => h('div', { style: 'margin-bottom:10px' },
      h('div', { class: 'lab' }, g.group),
      h('div', { class: 'ins-chips' }, g.items.map(it =>
        h('button', {
          class: 'chip', 'aria-pressed': chosen === it.id, disabled: !it.has_data,
          title: it.has_data ? it.name : 'No data yet for this series',
          onclick: (e) => {
            chosen = it.id;
            [...e.target.closest('.ins-body').querySelectorAll('.chip')]
              .forEach(c => c.setAttribute('aria-pressed', c.textContent.trim() === chosen));
          },
        }, it.id))))));
  ctx.modal('PRIMARY SERIES', body, () => ctx.setChart({ series: chosen }));
}

function openComparePicker(d, ctx) {
  const current = new Set(ctx.state.chartCompare);
  const body = h('div', {}, d.catalog.compare.map(g =>
    h('div', { style: 'margin-bottom:10px' },
      h('div', { class: 'lab' }, g.group),
      h('div', { class: 'ins-chips' }, g.items.map(it =>
        h('button', {
          class: 'chip', 'aria-pressed': current.has(it.id),
          disabled: !it.has_data || it.id === d.series[0].series_id,
          title: !it.has_data ? 'No data yet for this series'
            : it.id === d.series[0].series_id ? 'Already the primary series'
              : it.name + ' (' + it.unit + ')',
          onclick: (e) => {
            if (current.has(it.id)) current.delete(it.id); else current.add(it.id);
            e.target.setAttribute('aria-pressed', current.has(it.id));
          },
        }, it.id))))));
  ctx.modal('ADD COMPARISON', body, () =>
    ctx.setChart({ compare: [...current] }));
}

function openEventPicker(d, ctx) {
  const current = new Set(ctx.state.chartEvents);
  const body = h('div', {},
    h('p', { class: 'note small', style: 'margin:0 0 9px' },
      'Markers sit on the timeline at the bottom of the plot. Hover one for the print and '
      + 'the measured rate move around it. FOMC dates come from the published schedule; '
      + 'agency releases are projected from their usual monthly rhythm and labeled '
      + 'PROJECTED, because a scraped historical release calendar is not available here.'),
    h('div', { class: 'ins-chips' }, d.catalog.events.map(e =>
      h('button', {
        class: 'chip', 'aria-pressed': current.has(e.kind),
        title: e.confirmed_dates ? 'Confirmed dates' : 'Projected dates',
        onclick: (ev) => {
          if (current.has(e.kind)) current.delete(e.kind); else current.add(e.kind);
          ev.target.setAttribute('aria-pressed', current.has(e.kind));
        },
      }, e.label))));
  ctx.modal('EVENT MARKERS', body, () => ctx.setChart({ events: [...current] }));
}

/* --------------------------------------------------------------- PRICING */
export function renderPricing(d, ctx) {
  const r = d.result, inp = r.inputs, o = d.options;
  const field = (label, name, node) => h('label', { class: 'field' }, label, node);
  const sel = (name, values, cur) => h('select', {
    onchange: (e) => ctx.setPricing({ [name]: e.target.value }),
  }, values.map(v => h('option', { value: v, selected: String(v) === String(cur) }, String(v).replace(/_/g, ' '))));
  const num = (name, cur, step = 1) => h('input', {
    type: 'number', value: cur, step,
    onchange: (e) => ctx.setPricing({ [name]: e.target.value }),
  });

  const adj = r.adjustments.map(a => ({
    cells: [
      h('div', {}, h('div', {}, a.name), h('div', { class: 'note small' }, a.why)),
      pill(a.kind, a.kind === 'BUYDOWN' ? 'OBSERVED' : ''),
      h('span', { class: 'mono' }, a.points == null ? '—' : signed(a.points, 3)),
      arrowLabel(a.rate_effect, { dp: 3, suffix: '%', words: false, upWord: 'worse', downWord: 'better' }),
    ],
  }));

  const bd = d.buydowns.map(b => panel('BUYDOWN ' + b.structure, [
    table(['Year', 'Rate', 'Payment', 'Subsidy/mo'], b.schedule.map(s => ({
      cells: [String(s.year), fmt(s.rate, 3) + '%', '$' + fmt(s.payment, 0), '$' + fmt(s.monthly_subsidy, 0)],
    })), { align: ['', 'r', 'r', 'r'] }),
    h('div', { style: 'padding:9px 11px 0' },
      h('div', { class: 'lab' }, 'TOTAL SELLER OR BUILDER COST'),
      h('div', { class: 'big' }, '$' + fmt(b.total_cost, 0)),
      h('div', { class: 'note small' }, (b.total_cost / (inp.loan_amount || 1) * 100).toFixed(2)
        + '% of loan amount. ' + b.note)),
  ], { tight: true }));

  return h('div', { class: 'grid' },
    h('div', { class: 'banner' }, d.disclaimer),
    h('div', { class: 'grid g32' },
      panel('SCENARIO', [
        h('div', { class: 'controls' },
          field('FICO', 'fico', num('fico', inp.fico, 5)),
          field('LTV %', 'ltv', num('ltv', inp.ltv, 0.5)),
          field('Loan amount', 'loan_amount', num('loan_amount', inp.loan_amount, 5000)),
          field('Product', 'product', sel('product', o.products, inp.product)),
          field('Occupancy', 'occupancy', sel('occupancy', o.occupancies, inp.occupancy)),
          field('Property', 'property_type', sel('property_type', o.property_types, inp.property_type)),
          field('DTI %', 'dti', num('dti', inp.dti, 1)),
          field('Points', 'points', num('points', inp.points, 0.125)),
          field('Term', 'term', sel('term', o.terms, inp.term))),
      ]),
      panel('MARKET RATE ≠ BORROWER RATE', [
        h('div', { class: 'grid g2' },
          h('div', {}, h('div', { class: 'lab' }, 'MARKET RATE'),
            h('div', { class: 'big' }, fmt(d.market_rate, 3) + '%'),
            qualityBadge(d.market_rate_quality)),
          h('div', {}, h('div', { class: 'lab' }, 'ILLUSTRATIVE BORROWER RATE'),
            h('div', { class: 'big up' }, fmt(r.borrower_rate, 3) + '%'),
            arrowLabel(r.delta, { dp: 3, suffix: '%', words: true, upWord: 'worse than market', downWord: 'better than market' }))),
        kv([
          ['Total adjustments', signed(r.total_points, 3) + ' points'],
          ['Cost in dollars', '$' + fmt(r.cost_dollars, 0)],
          ['P&I payment', '$' + fmt(r.payment, 2) + '/mo'],
        ]),
        h('p', { class: 'note small', style: 'margin-top:9px' }, r.teaching_point),
      ], { info: 'PRICING' })),
    panel('ADJUSTMENT STACK', table(['Adjustment', 'Kind', 'Points', 'Rate effect'], adj,
      { align: ['', '', 'r', 'r'] }), { tight: true }),
    h('div', { class: 'grid g3' }, bd));
}

/* ----------------------------------------------------------------- BRIEF */
export function renderBrief(d) {
  const t = d.translations;
  const card = (key, label, hint) => panel(label, [
    h('p', { class: 'note', style: 'margin:0;color:var(--fg);line-height:1.65' }, t[key].text),
    h('div', { style: 'margin-top:9px' }, pill('CONF ' + t[key].confidence, t[key].confidence), ' ',
      h('button', {
        class: 'btn', onclick: (e) => {
          navigator.clipboard && navigator.clipboard.writeText(t[key].text);
          e.target.textContent = 'COPIED';
          setTimeout(() => { e.target.textContent = 'COPY'; }, 1400);
        },
      }, 'COPY')),
    h('p', { class: 'note small', style: 'margin-top:7px;color:var(--stale)' }, t[key].disclaimer),
  ], { hint });

  const e = d.eod;
  return h('div', { class: 'grid' },
    h('div', { class: 'grid g2' },
      panel(d.morning.title, briefBody(d.morning), { hint: d.morning.word_count + '/150 words' }),
      panel(e.title, [kv([
        ['What moved', e.what_moved],
        ['Treasury', signed(e.treasury_move_bp, 1) + ' bp'],
        ['MBS (modeled)', signed(e.mbs_move_ticks, 1) + ' ticks'],
        ['Spread', e.spread_direction + ' to ' + fmt(e.spread_bp, 0) + ' bp (' + e.spread_band + ')'],
        ['Lender reprice', e.lender_reprice],
        ['Rate expectations', e.expectations_change],
        ['Tomorrow', e.tomorrow.join(', ')],
      ]), h('p', { class: 'note small', style: 'margin-top:9px' }, e.reprice_caveat)])),
    h('div', { class: 'grid g2' },
      card('BORROWER', 'EXPLAIN TO BORROWER', 'no jargon'),
      card('REALTOR', 'EXPLAIN TO REALTOR', 'transaction framing')),
    h('div', { class: 'grid g2' },
      card('LO', 'EXPLAIN TO LO', 'full technical'),
      card('EXEC', 'EXECUTIVE SUMMARY', 'one paragraph')));
}

/* ---------------------------------------------------------------- STATUS */
export function renderStatus(d) {
  const rows = d.fetches.map(f => ({
    _hi: f.status === 'FAIL',
    cells: [f.source_id, h('span', { class: f.status === 'OK' ? 'down' : 'up' },
      (f.status === 'OK' ? '▼ ' : '▲ ') + f.status),
    h('span', { class: 'mono' }, f.finished_at), h('span', { class: 'note small' }, f.detail)],
  }));
  const q = Object.entries(d.quality_counts).map(([k, v]) => h('span', { style: 'margin-right:12px' },
    qualityBadge(k), ' ', h('span', { class: 'mono' }, v)));
  return h('div', { class: 'grid' },
    panel('DATA QUALITY', [h('div', {}, q),
      h('p', { class: 'note small', style: 'margin-top:9px' },
        `${d.series_with_data} of ${d.series_total} registered series have data. `
        + `${d.missing.length} are awaiting a source.`)]),
    panel('SOURCE STATUS', table(['Source', 'Status', 'Last run', 'Detail'], rows), { tight: true }),
    panel('MISSING SERIES', h('div', { class: 'note small' }, d.missing.join('  ·  ') || 'none')));
}
