// Shared DOM primitives.
//
// ACCESSIBILITY INVARIANT: arrowLabel() is the ONLY function permitted to express
// direction. It always emits an arrow glyph AND a text label alongside the colour,
// so meaning never depends on colour alone. Nothing else in this app may colour a
// value without routing through here.

export const h = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const k in attrs) {
    const v = attrs[k];
    if (v == null || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    n.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return n;
};

/**
 * Wrap a node so clicking it opens the provenance inspector for `sid`.
 * Dispatches on document so any screen gets the behaviour for free, and stays
 * keyboard reachable (Enter / Space) rather than being a click-only affordance.
 */
export function inspectable(node, sid, label) {
  if (!sid) return node;
  node.classList.add('inspectable');
  node.setAttribute('role', 'button');
  node.setAttribute('tabindex', '0');
  node.setAttribute('aria-label', 'Inspect ' + (label || sid) + ': source, meaning, impact');
  const open = (e) => {
    e.preventDefault(); e.stopPropagation();
    document.dispatchEvent(new CustomEvent('mrit:inspect', { detail: { sid } }));
  };
  node.addEventListener('click', open);
  node.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') open(e);
  });
  return node;
}

export const fmt = (v, dp = 2, suffix = '') =>
  (v == null || Number.isNaN(v)) ? '—' : v.toFixed(dp) + suffix;

export const signed = (v, dp = 2, suffix = '') =>
  (v == null || Number.isNaN(v)) ? '—' : (v > 0 ? '+' : '') + v.toFixed(dp) + suffix;

/**
 * Direction chip. `bp` is signed pressure on MORTGAGE RATES: positive pushes rates up.
 * `invert` flips the semantics for series where a rise is good for borrowers
 * (MBS price, unemployment).
 */
export function arrowLabel(value, { dp = 2, suffix = '', invert = false, words = true,
  upWord = 'rates up', downWord = 'rates down', flatWord = 'flat', threshold = 0 } = {}) {
  if (value == null || Number.isNaN(value)) {
    return h('span', { class: 'dir flat' }, h('span', { class: 'arrow' }, '·'), '—');
  }
  const eff = invert ? -value : value;
  const dir = eff > threshold ? 'up' : eff < -threshold ? 'down' : 'flat';
  const arrow = dir === 'up' ? '▲' : dir === 'down' ? '▼' : '►';
  const word = dir === 'up' ? upWord : dir === 'down' ? downWord : flatWord;
  return h('span', { class: 'dir ' + dir, title: word },
    h('span', { class: 'arrow' }, arrow),
    signed(value, dp, suffix),
    words ? h('span', { class: 'word' }, word) : null);
}

/** Data-quality badge. Every rendered number gets one. */
export const qualityBadge = (q, title) =>
  h('span', { class: 'badge q-' + (q || 'UNAVAILABLE'), title: title || '' }, q || 'UNAVAILABLE');

export const pill = (text, cls = '') => h('span', { class: 'pill ' + cls }, text);

export function panel(title, bodyNodes, { hint, tight, info } = {}) {
  const right = h('span', { class: 'hint' },
    hint || '',
    info ? h('button', {
      class: 'infobtn', title: 'What is this screen for, and where does it come from?',
      'aria-label': 'About the ' + info + ' screen',
      onclick: (e) => {
        e.stopPropagation();
        document.dispatchEvent(new CustomEvent('mrit:screeninfo', { detail: { screen: info } }));
      },
    }, 'i') : null);
  return h('section', { class: 'panel' },
    h('h2', {}, h('span', {}, title), right),
    h('div', { class: 'body' + (tight ? ' tight' : '') }, ...[].concat(bodyNodes).filter(Boolean)));
}

export function unavailable(reason) {
  return h('div', { class: 'unavail' }, 'DATA UNAVAILABLE', h('br'),
    h('span', { style: 'color:var(--fg2);font-size:10.5px' }, reason || ''));
}

export function table(headers, rows, { align = [] } = {}) {
  return h('table', {},
    h('thead', {}, h('tr', {}, headers.map((x, i) =>
      h('th', { class: align[i] === 'r' ? 'num' : '' }, x)))),
    h('tbody', {}, rows.map(r =>
      h('tr', { class: r._hi ? 'hi' : '' }, (r.cells || r).map((c, i) =>
        h('td', { class: align[i] === 'r' ? 'num' : '' }, c))))));
}

export const kv = (pairs) => h('dl', { class: 'kv' },
  pairs.filter(Boolean).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));

/** Cell renderer for an api._cell() payload. */
export function cellRow(c, { dp = 2 } = {}) {
  if (!c.available) {
    return { cells: [
      inspectable(h('span', {}, c.name), c.series_id, c.name),
      h('span', { class: 'note small' }, 'DATA UNAVAILABLE'),
      '—', '—', qualityBadge('UNAVAILABLE', c.reason)], _reason: c.reason };
  }
  const inv = !!c.invert_for_rates;
  return {
    cells: [
      inspectable(h('span', { title: 'Click to inspect source and impact' }, c.name),
        c.series_id, c.name),
      h('span', { class: 'val mono' }, fmt(c.value, dp)),
      arrowLabel(c.change_1d, { dp, invert: inv, words: false }),
      arrowLabel(c.change_1w, { dp, invert: inv, words: false }),
      h('span', { title: `${c.source_id} · observed ${c.obs_date} · fetched ${c.fetched_at} · ${c.age_days}d old` },
        qualityBadge(c.quality, c.notes)),
    ],
  };
}

export function tickerItem(c) {
  if (!c.available) {
    return inspectable(h('div', { class: 'tick', title: c.reason },
      h('span', { class: 'k' }, c.name),
      h('span', { class: 'v', style: 'color:var(--unavail);font-size:12px' }, 'N/A'),
      h('span', { class: 'c' }, qualityBadge('UNAVAILABLE'))), c.series_id, c.name);
  }
  const dp = c.unit === 'bps' || c.unit === 'ticks' ? 1 : c.unit === 'price32' ? 3 : 2;
  return inspectable(h('div', { class: 'tick',
    title: `${c.name} · ${c.obs_date} · ${c.source_id} · click to inspect` },
    h('span', { class: 'k' }, c.ticker || c.name),
    h('span', { class: 'v' }, fmt(c.value, dp)),
    h('span', { class: 'c' }, arrowLabel(c.change_1d, { dp, invert: !!c.invert_for_rates, words: false }),
      ' ', qualityBadge(c.quality))), c.series_id, c.name);
}
