// Provenance inspector. Click any number anywhere: where it came from, what the
// level means, how it reaches a mortgage rate, and a live link to the source.
import { h, fmt, signed, arrowLabel, qualityBadge, pill, kv, table } from './components.js';
import { lineChart } from './charts.js';

let lastFocus = null;

const el = (id) => document.getElementById(id);

// Read a view by its api name. In static mode (the deployed site) these map to the
// JSON files build_static.py baked; in local dev they hit the live /api routes. Only
// the two parameterless endpoints the inspector uses (series/<id>, screen-meta/<name>)
// are needed here, so the mapping is a straight filename.
async function apiJSON(path) {
  const url = window.MRIT_STATIC ? ('data/' + path + '.json') : ('/api/' + path);
  const r = await fetch(url);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

function shell() {
  let d = el('inspector');
  if (d) return d;
  d = h('div', {
    id: 'inspector', class: 'inspector', role: 'dialog', 'aria-modal': 'true',
    'aria-label': 'Data inspector', style: 'display:none',
    onclick: (e) => { if (e.target === d) close(); },
  }, h('div', { class: 'ins-card' },
    h('header', {},
      h('div', { id: 'ins-title' }),
      h('button', { class: 'btn', onclick: close, 'aria-label': 'Close inspector' }, 'ESC')),
    h('div', { id: 'ins-body', class: 'ins-body' })));
  d.hidden = true;
  document.body.appendChild(d);
  return d;
}

export function close() {
  const d = el('inspector');
  if (!d) return;
  d.hidden = true;
  d.style.display = 'none';
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}

export const isOpen = () => {
  const d = el('inspector');
  return d && !d.hidden;
};

function open(titleNode, bodyNode) {
  const d = shell();
  lastFocus = document.activeElement;
  el('ins-title').innerHTML = '';
  el('ins-title').appendChild(titleNode);
  const b = el('ins-body');
  b.innerHTML = '';
  b.appendChild(bodyNode);
  d.hidden = false;
  d.style.display = 'flex';
  b.scrollTop = 0;
  d.querySelector('.btn').focus();
}

const sect = (title, ...kids) => h('section', { class: 'ins-sect' },
  h('h3', {}, title), ...kids.filter(Boolean));

const link = (url, text) => url
  ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', class: 'ins-link' },
    text || url, h('span', { class: 'ext' }, '↗'))
  : h('span', { class: 'note small' }, 'no public link');

/* ------------------------------------------------------------ series inspector */
export async function inspect(sid) {
  open(h('div', {}, h('span', { class: 'ins-kicker' }, 'LOADING'), h('h2', {}, sid)),
    h('div', { class: 'note' }, 'Fetching provenance…'));
  let d;
  try {
    d = await apiJSON('series/' + encodeURIComponent(sid));
  } catch (e) {
    return open(h('h2', {}, sid), h('div', { class: 'banner err' }, 'Failed: ' + e.message));
  }
  if (d.error) return open(h('h2', {}, sid), h('div', { class: 'banner err' }, d.error));

  const { meta, cell, provenance: p, insights: ins, impact: imp } = d;
  const dp = meta.unit === 'bps' || meta.unit === 'ticks' ? 1 : 3;

  const title = h('div', {},
    h('span', { class: 'ins-kicker' },
      'TIER ' + meta.tier + ' · ' + (imp.tier_name || '').toUpperCase() + ' · ' + meta.id),
    h('h2', {}, meta.name));

  // ---- the number itself
  const headline = h('div', { class: 'ins-headline' },
    h('div', {},
      h('div', { class: 'lab' }, 'CURRENT'),
      h('div', { class: 'huge' }, cell.available ? fmt(cell.value, dp) : 'N/A'),
      h('div', { class: 'note small' }, unitLabel(meta.unit))),
    h('div', {},
      h('div', { class: 'lab' }, 'CHANGE'),
      h('div', {}, '1D ', arrowLabel(cell.change_1d, { dp, invert: !!meta.invert_for_rates, words: false })),
      h('div', {}, '1W ', arrowLabel(cell.change_1w, { dp, invert: !!meta.invert_for_rates, words: false })),
      h('div', {}, '1M ', arrowLabel(cell.change_1m, { dp, invert: !!meta.invert_for_rates, words: false }))),
    h('div', {},
      h('div', { class: 'lab' }, 'DATA QUALITY'),
      h('div', { style: 'margin:4px 0' }, qualityBadge(p.quality)),
      h('div', { class: 'note small' }, p.quality_meaning)));

  // ---- where it comes from
  const prov = sect('WHERE THIS NUMBER COMES FROM',
    kv([
      ['Source', h('strong', {}, p.source_name)],
      p.dataset && ['Dataset', p.dataset],
      p.ticker && p.ticker !== meta.id && ['Ticker', h('code', {}, p.ticker)],
      ['Observed', p.obs_date
        ? p.obs_date + (p.age_days != null ? '  (' + p.age_days + ' days ago)' : '')
        : h('span', { class: 'note small' }, 'never fetched')],
      p.fetched_at && ['Fetched', p.fetched_at],
      ['Updates', p.cadence || p.refresh_window],
      ['Access', p.auth],
    ]),
    h('div', { class: 'ins-links' },
      p.deep_link ? link(p.deep_link, 'Open this exact series at the source') : null,
      p.url ? link(p.url, p.deep_link ? 'Source home' : 'Open the source') : null),
    p.endpoint ? h('div', { class: 'ins-endpoint' },
      h('div', { class: 'lab' }, 'ENDPOINT MRIT CALLS'),
      h('code', {}, p.endpoint)) : null,
    p.reliability ? h('p', { class: 'note small' }, h('strong', {}, 'Reliability. '), p.reliability) : null,
    p.caveat ? h('p', { class: 'note ins-caveat' }, h('strong', {}, 'Read this before you quote it. '), p.caveat) : null);

  // ---- how it is computed, if it is
  const deriv = p.derivation ? sect('HOW IT IS COMPUTED',
    h('div', { class: 'ins-formula' }, p.derivation.formula),
    p.derivation.note ? h('p', { class: 'note small' }, p.derivation.note) : null,
    h('div', { class: 'lab', style: 'margin-top:8px' }, 'INPUTS  (click to inspect)'),
    h('div', { class: 'ins-chips' }, p.derivation.inputs.map(x =>
      h('button', { class: 'chip', onclick: () => inspect(x) }, x)))) : null;

  // ---- what the level means
  const r1 = ins.range_1y, r5 = ins.range_5y, mv = ins.move;
  const insight = ins.available ? sect('WHAT THIS LEVEL MEANS',
    ins.stat_line ? h('p', { class: 'note', style: 'color:var(--fg)' }, ins.stat_line) : null,
    kv([
      r1 && ['1-year range', fmt(r1.min, dp) + ' to ' + fmt(r1.max, dp)
        + '   ·   ' + fmt(r1.percentile, 0) + 'th percentile'],
      r5 && ['5-year range', fmt(r5.min, dp) + ' to ' + fmt(r5.max, dp)
        + '   ·   ' + fmt(r5.percentile, 0) + 'th percentile'],
      mv && ['Latest move', h('span', {}, signed(mv.move_bp, 1) + ' bp  ',
        pill(mv.verdict, mv.percentile >= 85 ? 'HIGH' : mv.percentile >= 60 ? 'MEDIUM' : 'LOW'))],
      mv && mv.largest_up && ['Biggest ever up', signed(mv.largest_up.bp, 0) + ' bp on ' + mv.largest_up.date],
      mv && mv.largest_down && ['Biggest ever down', signed(mv.largest_down.bp, 0) + ' bp on ' + mv.largest_down.date],
    ].filter(Boolean)),
    mv ? h('p', { class: 'note small' }, mv.detail) : null)
    : sect('WHAT THIS LEVEL MEANS', h('div', { class: 'unavail' }, ins.reason || 'No data.'));

  // ---- how it reaches a mortgage rate
  const impact = sect('HOW IT REACHES A MORTGAGE RATE',
    h('p', { class: 'note', style: 'color:var(--fg)' }, imp.meaning),
    imp.chains.length ? h('div', {}, imp.chains.map(c => h('div', { class: 'ins-chain' },
      h('div', { class: 'chain' }, c.chain),
      h('div', { class: 'note small' },
        'path strength ' + (c.weight * 100).toFixed(0) + '%  ·  confidence '
        + (c.confidence >= 0.85 ? 'HIGH' : c.confidence >= 0.55 ? 'MEDIUM' : 'LOW')),
      c.rationales[0] ? h('div', { class: 'note small' }, c.rationales[0]) : null)))
      : h('p', { class: 'note small' }, imp.no_chain_note));

  // ---- history
  const chart = d.points && d.points.length > 5
    ? sect('HISTORY', lineChart([{ name: meta.name, points: d.points, color: '#e8a33d' }],
      { height: 190 }),
    h('div', { class: 'note small' }, d.points.length + ' observations from '
        + d.points[0].d + ' to ' + d.points[d.points.length - 1].d))
    : null;

  // ---- related
  const rel = d.related && d.related.length ? sect('RELATED SERIES',
    h('div', { class: 'ins-chips' }, d.related.map(r =>
      h('button', {
        class: 'chip' + (r.relation === 'TIER' ? ' dim' : ''),
        title: r.name + '  (' + r.relation.toLowerCase() + ')',
        onclick: () => inspect(r.id),
      }, r.relation === 'INPUT' ? '↑ ' : r.relation === 'FEEDS' ? '↓ ' : '', r.id)))) : null;

  open(title, h('div', {}, headline, prov, deriv, insight, impact, chart, rel));
}

function unitLabel(u) {
  return ({ percent: 'percent', bps: 'basis points', ticks: '32nds',
    price32: 'dollar price', thousands: 'thousands', usd_mm: 'USD millions',
    usd: 'US dollars', index: 'index level', months: 'months' })[u] || u || '';
}

/* ------------------------------------------------------------ screen inspector */
export async function inspectScreen(screen) {
  let d;
  try {
    d = await apiJSON('screen-meta/' + encodeURIComponent(screen));
  } catch (e) {
    return;
  }
  if (d.error) return;
  open(h('div', {},
    h('span', { class: 'ins-kicker' }, 'SCREEN · ' + d.screen),
    h('h2', {}, d.title)),
  h('div', {},
    sect('WHAT THIS SCREEN ANSWERS',
      h('p', { class: 'note', style: 'color:var(--fg);font-size:14px' }, d.question),
      h('p', { class: 'note' }, d.purpose)),
    sect('HOW TO READ IT', h('p', { class: 'note' }, d.how_to_read)),
    sect('SERIES ON THIS SCREEN',
      h('div', { class: 'ins-chips' }, d.series.map(s =>
        h('button', { class: 'chip', title: s.name, onclick: () => inspect(s.id) }, s.id)))),
    sect('SOURCES FEEDING IT', d.sources.map(s => h('div', { class: 'ins-chain' },
      h('div', {}, h('strong', {}, s.name), '  ', link(s.url, 'open')),
      h('div', { class: 'note small' }, s.auth),
      s.caveat ? h('div', { class: 'note small ins-caveat' }, s.caveat) : null)))));
}
