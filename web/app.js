// MRIT shell: routing, command bar, keyboard, polling.
import { h, tickerItem, panel, unavailable } from './components.js';
import * as S from './screens.js';
import * as Inspector from './inspector.js';

const COMMANDS = [
  { cmd: 'DASH', alt: ['RATES', 'HOME'], api: 'dash', title: 'Dashboard', render: S.renderDash,
    desc: 'Rate pressure, why rates moved, drivers, brief, calendar' },
  { cmd: 'WHY', alt: ['CAUSE'], api: 'why', title: 'Why rates are moving', render: S.renderWhy,
    desc: 'Primary, secondary, counterforce and the full causal trace' },
  { cmd: 'UST', alt: ['TREASURY', 'CURVE'], api: 'ust', title: 'Treasuries', render: S.renderUST,
    desc: 'Full curve 1M to 30Y, yield curve chart, 2s10s / 5s10s / 10s30s' },
  { cmd: 'MBS', alt: ['TBA'], api: 'mbs', title: 'Mortgage-backed securities', render: S.renderMBS,
    desc: 'FNMA coupon stack, production coupon, price and ticks (MODELED)' },
  { cmd: 'SPREAD', alt: ['OAS'], api: 'spread', title: 'Mortgage / Treasury spread', render: S.renderSpread,
    desc: 'Level, percentile, band, and the exact Treasury vs spread decomposition' },
  { cmd: 'FED', alt: ['FOMC'], api: 'fed', title: 'Federal Reserve', render: S.renderFed,
    desc: 'Stance gauge, balance sheet, FOMC calendar, transmission mechanism' },
  { cmd: 'CPI', alt: ['INFLATION', 'PCE'], api: 'tier/3', title: 'Inflation', render: S.renderTier,
    desc: 'CPI, core CPI, PPI, shelter with surprise scoring' },
  { cmd: 'LABOR', alt: ['JOBS', 'NFP'], api: 'tier/4', title: 'Labor market', render: S.renderTier,
    desc: 'Payrolls, unemployment, earnings, claims with surprise scoring' },
  { cmd: 'GROWTH', alt: ['GDP'], api: 'tier/5', title: 'Economic growth', render: S.renderTier,
    desc: 'GDP, retail sales, ISM, industrial production' },
  { cmd: 'VOL', alt: ['MARKET', 'RISK'], api: 'tier/6', title: 'Market conditions', render: S.renderTier,
    desc: 'VIX, MOVE, credit spreads, equities, dollar, oil' },
  { cmd: 'HOUSING', alt: ['HOMES'], api: 'tier/8', title: 'Housing market', render: S.renderTier,
    desc: 'Sales, starts, permits, inventory, prices' },
  { cmd: 'CALENDAR', alt: ['CAL', 'EVENTS'], api: 'calendar', title: 'Event calendar', render: S.renderCalendar,
    desc: 'Rate-relevant releases with countdowns and last-print impact' },
  { cmd: 'HISTORY', alt: ['CHART', 'HIST', 'GRAPH'], api: 'chart', title: 'Interactive rate history', render: S.renderHistory,
    desc: 'TradingView-style chart: crosshair, zoom, pan, overlays, event markers' },
  { cmd: 'PRICING', alt: ['LLPA', 'LAB'], api: 'pricing', title: 'Rate pricing lab', render: S.renderPricing,
    desc: 'Borrower-level adjustments. Market rate is not borrower rate' },
  { cmd: 'BRIEF', alt: ['EOD', 'EXPLAIN'], api: 'brief', title: 'Briefs and translations', render: S.renderBrief,
    desc: 'Morning brief, EOD review, borrower / realtor / LO / exec registers' },
  { cmd: 'STATUS', alt: ['DATA', 'SOURCES'], api: 'status', title: 'Data status', render: S.renderStatus,
    desc: 'Source health, freshness, what is missing and why' },
];
const TABS = ['DASH', 'WHY', 'UST', 'MBS', 'SPREAD', 'FED', 'CPI', 'LABOR', 'CALENDAR', 'HISTORY', 'PRICING', 'BRIEF', 'STATUS'];

const state = {
  screen: 'DASH',
  chartSeries: 'MORT30Y',
  chartCompare: [],
  chartEvents: [],
  chartRange: '1Y',
  chartMode: 'rate',
  pricing: {},
  busy: false,
};

const $ = (id) => document.getElementById(id);
const findCmd = (name) => COMMANDS.find(c => c.cmd === name)
  || COMMANDS.find(c => (c.alt || []).includes(name));

// In static mode (the deployed site) there is no Python server: every screen is
// read from a JSON file baked by build_static.py, and the two interactive screens
// recompute in the browser. In local dev (python3 server.py) MRIT_STATIC is unset
// and these fall through to the live /api routes unchanged.
const STATIC = !!window.MRIT_STATIC;
const SERIES_COLORS = ['#e8a33d', '#4aa3df', '#3ecf8e', '#c77dff', '#ef5350', '#8d9aa8'];

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

async function get(path) {
  if (!STATIC) return fetchJSON('/api/' + path);

  const [name, qs] = path.split('?');
  const q = new URLSearchParams(qs || '');

  // HISTORY: load the primary series' baked chart, then splice in any comparison
  // series from their own baked files and recolor them by position. The chart
  // already windows the full history client-side, so range/mode switches are free.
  if (name === 'chart') {
    const primary = q.get('series') || 'MORT30Y';
    const compare = (q.get('compare') || '').split(',').filter(Boolean)
      .filter((c) => c !== primary).slice(0, 5);
    const events = (q.get('events') || '').split(',').filter(Boolean);
    const data = await fetchJSON('data/chart/' + primary + '.json');
    data.series[0].color = SERIES_COLORS[0];
    for (let i = 0; i < compare.length; i++) {
      try {
        const cd = await fetchJSON('data/chart/' + compare[i] + '.json');
        const line = cd.series[0];
        line.color = SERIES_COLORS[(i + 1) % SERIES_COLORS.length];
        data.series.push(line);
      } catch (e) { /* a series with no data is simply skipped, as on the server */ }
    }
    data.events = events.length
      ? (data.events || []).filter((m) => events.includes(m.kind)) : [];
    return data;
  }

  // PRICING: the lab is pure arithmetic ported to pricing.js. Seed inputs (today's
  // market rate, option lists, disclaimer) come from the baked file; the result and
  // buydowns are computed here so every slider still responds instantly.
  if (name === 'pricing') {
    const seed = await fetchJSON('data/pricing.json');
    const { priceScenario } = await import('./pricing.js');
    return priceScenario(seed, Object.fromEntries(q.entries()));
  }

  // Everything else maps straight to a file: dash, tier/5, screen-meta/DASH,
  // series/UST10Y, etc. Query params (e.g. calendar?days=) are pre-baked at defaults.
  return fetchJSON('data/' + name + '.json');
}

async function post(path, body) {
  if (!STATIC) {
    const r = await fetch('/api/' + path, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    return r.json();
  }
  if (path === 'refresh') {
    // No server to hit; data is rebuilt by the scheduled job. Re-read the manifest
    // so the UI can report when the live snapshot was last baked.
    try { return await fetchJSON('data/manifest.json'); } catch (e) { return {}; }
  }
  if (path === 'pricing') return get('pricing?' + new URLSearchParams(body || {}).toString());
  return {};
}

function toast(msg, ms = 3200) {
  const t = $('toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

const ctx = {
  state,
  go: (name) => go(name),
  ytdDays: () => Math.max(1, Math.round((Date.now() - new Date(new Date().getFullYear(), 0, 1)) / 86400000)),
  setChart: (patch) => {
    if (patch.compare) state.chartCompare = patch.compare;
    if (patch.removeCompare) {
      state.chartCompare = state.chartCompare.filter(x => x !== patch.removeCompare);
    }
    if (patch.events) state.chartEvents = patch.events;
    if (patch.series) state.chartSeries = patch.series;
    go('HISTORY');
  },
  modal: (title, body, onApply) => openModal(title, body, onApply),
  setPricing: (patch) => { Object.assign(state.pricing, patch); go('PRICING'); },
};

function apiPathFor(c) {
  if (c.cmd === 'HISTORY') {
    return `chart?series=${state.chartSeries}`
      + `&compare=${state.chartCompare.join(',')}`
      + `&events=${state.chartEvents.join(',')}`;
  }
  if (c.cmd === 'PRICING') {
    const q = new URLSearchParams(state.pricing).toString();
    return 'pricing' + (q ? '?' + q : '');
  }
  return c.api;
}

async function go(name) {
  const c = findCmd(name);
  if (!c) { toast('Unknown command: ' + name); return; }
  // Release any chart's window listeners before the screen is torn down.
  if (ctx.activeChart && ctx.activeChart.destroy) {
    ctx.activeChart.destroy();
    ctx.activeChart = null;
  }
  state.screen = c.cmd;
  renderTabs();
  const main = $('screen');
  main.setAttribute('aria-busy', 'true');
  try {
    const data = await get(apiPathFor(c));
    main.innerHTML = '';
    if (data.error) main.appendChild(panel('ERROR', unavailable(data.error)));
    else main.appendChild(c.render(data, ctx));
    $('statusMid').textContent = c.title.toUpperCase();
  } catch (e) {
    main.innerHTML = '';
    main.appendChild(panel('ERROR', unavailable(String(e.message || e))));
  }
  // DASH is sized to the viewport; every other screen scrolls normally.
  main.classList.toggle('fit', c.cmd === 'DASH');
  main.setAttribute('aria-busy', 'false');
  main.scrollTop = 0;
  location.hash = c.cmd;
}

// Grouped top nav. The deep screens live under RATES and ECONOMY so the bar is
// seven items instead of thirteen; everything is still one keystroke away in Ctrl+K.
const NAV = [
  { cmd: 'DASH' },
  { label: 'RATES', children: ['WHY', 'UST', 'MBS', 'SPREAD'] },
  { label: 'ECONOMY', children: ['FED', 'CPI', 'LABOR', 'GROWTH'] },
  { cmd: 'CALENDAR' },
  { cmd: 'HISTORY' },
  { cmd: 'PRICING' },
  { cmd: 'BRIEF' },
  { cmd: 'STATUS' },
];
const NAV_LABEL = { WHY: 'Why rates moved', UST: 'Treasuries', MBS: 'MBS', SPREAD: 'Spread',
  FED: 'Fed', CPI: 'Inflation', LABOR: 'Labor', GROWTH: 'Growth' };

function closeMenus() {
  document.querySelectorAll('#tabs .tab-menu').forEach(m => { m.hidden = true; });
  document.querySelectorAll('#tabs .tab-group').forEach(b => b.setAttribute('aria-expanded', 'false'));
}
document.addEventListener('click', closeMenus);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenus(); });

function renderTabs() {
  const nav = $('tabs');
  nav.innerHTML = '';
  NAV.forEach(item => {
    if (item.children) {
      const active = item.children.includes(state.screen);
      const menu = h('div', { class: 'tab-menu', role: 'menu', hidden: true },
        item.children.map(cmd => h('button', {
          class: 'tab-menu-item' + (state.screen === cmd ? ' on' : ''), role: 'menuitem',
          onclick: (e) => { e.stopPropagation(); closeMenus(); go(cmd); },
        }, h('span', { class: 'tm-code' }, cmd),
          h('span', { class: 'tm-name' }, NAV_LABEL[cmd] || cmd))));
      const btn = h('button', {
        class: 'tab-group', 'aria-haspopup': 'true', 'aria-expanded': 'false',
        'aria-selected': active ? 'true' : null,
        onclick: (e) => {
          e.stopPropagation();
          const wasOpen = !menu.hidden;
          closeMenus();
          if (!wasOpen) { menu.hidden = false; btn.setAttribute('aria-expanded', 'true'); }
        },
      }, item.label, h('span', { class: 'caret', 'aria-hidden': 'true' }, '▾'));
      nav.appendChild(h('div', { class: 'tab-wrap' }, btn, menu));
    } else {
      nav.appendChild(h('button', {
        role: 'tab', 'aria-selected': state.screen === item.cmd ? 'true' : null,
        onclick: () => go(item.cmd),
      }, item.cmd));
    }
  });
}

async function refreshTicker() {
  try {
    const t = await get('ticker');
    const bar = $('ticker');
    bar.innerHTML = '';
    t.items.forEach(c => bar.appendChild(tickerItem(c)));
    const f = t.fed;
    bar.appendChild(h('div', { class: 'tick', title: f.probabilities_note },
      h('span', { class: 'k' }, 'FED STANCE'),
      h('span', { class: 'v', style: 'font-size:12px' }, f.stance),
      h('span', { class: 'c', style: 'color:var(--dim)' }, f.rate_impact + ' FOR RATES')));
    if (t.next_event) {
      const e = t.next_event;
      bar.appendChild(h('div', { class: 'tick', title: e.why },
        h('span', { class: 'k' }, 'NEXT EVENT'),
        h('span', { class: 'v', style: 'font-size:12px' }, e.name),
        h('span', { class: 'c', style: 'color:var(--dim)' },
          (e.days_out === 0 ? 'TODAY' : 'T+' + e.days_out + 'd') + ' · ' + e.impact)));
    }
    const stale = t.items.filter(i => !i.available || i.quality === 'STALE').length;
    const modeled = t.items.filter(i => i.quality === 'MODELED').length;
    $('statusLeft').textContent =
      `${t.items.length - stale} live · ${modeled} modeled · ${stale} stale or unavailable`;
  } catch (e) {
    $('statusLeft').textContent = 'ticker error: ' + e.message;
  }
}

/* ---------------------------------------------------------------- modal */
// Small apply/cancel dialog reusing the inspector's chrome so the picker looks
// native rather than like a second design language bolted on.
function openModal(title, body, onApply) {
  const close = () => host.remove();
  const host = h('div', { class: 'inspector', style: 'display:flex',
    role: 'dialog', 'aria-modal': 'true', 'aria-label': title,
    onclick: (e) => { if (e.target === host) close(); } },
  h('div', { class: 'ins-card', style: 'max-width:640px' },
    h('header', {}, h('div', {}, h('h2', {}, title)),
      h('button', { class: 'btn', onclick: close }, 'ESC')),
    h('div', { class: 'ins-body' }, body),
    h('div', { class: 'ins-actions' },
      h('button', { class: 'btn', onclick: close }, 'CANCEL'),
      h('button', { class: 'btn primary',
        onclick: () => { close(); onApply && onApply(); } }, 'APPLY'))));
  document.body.appendChild(host);
  const esc = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); } };
  document.addEventListener('keydown', esc);
}

/* ---------------------------------------------------------------- palette */
let paletteIdx = 0;
function openPalette() {
  const p = $('palette');
  // Set display directly as well as the attribute: the .palette rule carries an
  // explicit display, which outranks the [hidden] UA rule on its own.
  p.hidden = false;
  p.style.display = 'flex';
  $('paletteInput').value = '';
  filterPalette('');
  $('paletteInput').focus();
}
const closePalette = () => {
  const p = $('palette');
  p.hidden = true;
  p.style.display = 'none';
  $('screen').focus();
};

function filterPalette(q) {
  const term = q.trim().toUpperCase();
  const hits = COMMANDS.filter(c => !term || c.cmd.includes(term)
    || (c.alt || []).some(a => a.includes(term)) || c.title.toUpperCase().includes(term));
  paletteIdx = 0;
  const ul = $('paletteList');
  ul.innerHTML = '';
  hits.forEach((c, i) => ul.appendChild(h('li', {
    role: 'option', 'aria-selected': i === 0, 'data-cmd': c.cmd,
    onclick: () => { closePalette(); go(c.cmd); },
  }, h('span', { class: 'cmd' }, c.cmd), h('span', { class: 'desc' }, c.desc))));
  return hits;
}

function movePalette(delta) {
  const items = [...$('paletteList').children];
  if (!items.length) return;
  items[paletteIdx].setAttribute('aria-selected', 'false');
  paletteIdx = (paletteIdx + delta + items.length) % items.length;
  const sel = items[paletteIdx];
  sel.setAttribute('aria-selected', 'true');
  sel.scrollIntoView({ block: 'nearest' });
}

/* -------------------------------------------------------------- keyboard */
function keydown(e) {
  if (Inspector.isOpen()) {
    if (e.key === 'Escape') { e.preventDefault(); Inspector.close(); }
    return;
  }
  const pal = !$('palette').hidden;
  if (pal) {
    if (e.key === 'Escape') { e.preventDefault(); closePalette(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); movePalette(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); movePalette(-1); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const sel = $('paletteList').children[paletteIdx];
      const typed = $('paletteInput').value.trim().toUpperCase();
      closePalette();
      go(sel ? sel.dataset.cmd : typed);
    }
    return;
  }
  const typing = /^(INPUT|SELECT|TEXTAREA)$/.test((e.target.tagName || ''));
  if (typing) return;
  if (e.key === ':' || (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey))) {
    e.preventDefault(); openPalette();
  } else if (e.key === '?') {
    e.preventDefault(); openPalette(); $('paletteInput').value = '';
  } else if (e.key === '[' || e.key === ']') {
    e.preventDefault();
    const i = TABS.indexOf(state.screen);
    go(TABS[(i + (e.key === ']' ? 1 : -1) + TABS.length) % TABS.length]);
  } else if (e.key.toLowerCase() === 'r' && !e.metaKey && !e.ctrlKey) {
    e.preventDefault(); doRefresh();
  }
}

async function doRefresh() {
  if (state.busy) return;
  state.busy = true;
  const btn = $('refreshBtn');
  btn.textContent = STATIC ? 'RELOADING…' : 'INGESTING…';
  btn.setAttribute('aria-pressed', 'true');
  try {
    const res = await post('refresh');
    if (STATIC) {
      const when = res.built_at ? res.built_at.replace('T', ' ').replace('Z', ' UTC') : 'unknown';
      toast(`Published snapshot. Data is baked on a schedule; last build ${when}. `
        + 'Observation dates and freshness badges are on STATUS.', 6000);
    } else {
      const ok = (res.results || []).filter(r => r.status === 'OK');
      const bad = (res.results || []).filter(r => r.status === 'FAIL');
      toast(`Ingest complete. ${ok.length} sources OK, ${bad.length} unavailable`
        + (bad.length ? ': ' + bad.map(b => b.source).join(', ') : '') + '. See STATUS for detail.', 6000);
    }
    await refreshTicker();
    await go(state.screen);
  } catch (e) {
    toast('Refresh failed: ' + e.message);
  }
  btn.textContent = 'REFRESH';
  btn.removeAttribute('aria-pressed');
  state.busy = false;
}

function tickClock() {
  const d = new Date();
  $('clock').textContent = d.toLocaleTimeString('en-US', { hour12: false }) + ' local';
}

/* ------------------------------------------------------------------ boot */
function init() {
  $('palette').style.display = 'none';
  renderTabs();
  $('paletteInput').addEventListener('input', (e) => filterPalette(e.target.value));
  // Any rendered value can ask for the inspector. Listening once on document means
  // new screens get the behaviour without wiring anything up.
  document.addEventListener('mrit:inspect', (e) => Inspector.inspect(e.detail.sid));
  document.addEventListener('mrit:screeninfo', (e) => Inspector.inspectScreen(e.detail.screen));
  $('refreshBtn').addEventListener('click', doRefresh);
  document.addEventListener('keydown', keydown);
  window.addEventListener('hashchange', () => {
    const t = location.hash.replace('#', '').toUpperCase();
    if (t && t !== state.screen) go(t);
  });
  tickClock();
  setInterval(tickClock, 1000);
  refreshTicker();
  setInterval(refreshTicker, 120000);
  go((location.hash.replace('#', '') || 'DASH').toUpperCase());
}

init();
