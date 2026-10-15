"""Alert engine. Every alert explains WHY the event matters, not just that it fired."""

import json

from . import analytics, registry, store

RULES = [
    {'id': 'UST10_5BP', 'kind': 'series_move', 'series': 'UST10Y', 'threshold': 0.05,
     'unit': 'pct', 'label': '10Y Treasury moved 5 bp or more',
     'why': 'The 10-year is the primary input to mortgage pricing. A 5 bp move is roughly '
            '5 bp of eventual mortgage rate, arriving with a one to two day lag.'},
    {'id': 'MORT_125', 'kind': 'series_move', 'series': 'MORT30Y', 'threshold': 0.125,
     'unit': 'pct', 'label': 'Published mortgage rate moved more than 0.125%',
     'why': 'An eighth of a point changes payment and qualification enough to matter on a '
            'live pre-approval. Re-run any borrower who was tight on DTI.'},
    {'id': 'SPREAD_BREAK', 'kind': 'spread_band', 'threshold': 85.0,
     'label': 'Mortgage spread at an extreme percentile',
     'why': 'A wide spread means Treasury rallies are not reaching borrowers. Stop explaining '
            'rates with the Fed and start explaining them with the spread.'},
    {'id': 'CPI_SURPRISE', 'kind': 'release_surprise', 'release': 'CORECPI', 'threshold': 1.0,
     'label': 'Core CPI surprise beyond 1 sigma',
     'why': 'Core CPI is the highest-variance monthly release for mortgage rates. A hot print '
            'reprices the entire curve within minutes.'},
    {'id': 'NFP_SURPRISE', 'kind': 'release_surprise', 'release': 'NFP', 'threshold': 1.0,
     'label': 'Payrolls surprise beyond 1 sigma',
     'why': 'Payrolls drive both growth and Fed expectations at once, which is why it is the '
            'single largest source of rate volatility on the calendar.'},
    {'id': 'CRUDE_SHOCK', 'kind': 'move_percentile', 'series': ['BRENT', 'OIL'],
     'threshold': 95.0, 'label': 'Crude benchmark moved at an extreme percentile',
     'why': 'An energy shock hits mortgage rates through two channels at once. It lifts '
            'inflation expectations, which pushes the 10Y and your rate UP, and it raises '
            'recession risk, which pushes them DOWN. Watch which one the bond market picks. '
            'If the 10Y sells off with crude, the market is trading inflation and you should '
            'protect float positions.'},
    {'id': 'CURVE_INVERT', 'kind': 'level_below', 'series': 'CURVE_2S10S', 'threshold': 0.0,
     'unit': 'bp', 'label': '2s10s inverted',
     'why': 'An inverted curve has preceded every modern recession. It is bullish for '
            'mortgage rates over quarters, not days.'},
]


def evaluate(con=None):
    fired = []
    for r in RULES:
        try:
            hit = _eval_rule(r, con)
        except Exception:
            hit = None
        if hit:
            fired.append(hit)
    fired.sort(key=lambda a: {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}.get(a['severity'], 3))
    return fired


def _eval_rule(r, con):
    if r['kind'] == 'series_move':
        cur, prev, d = analytics.change(r['series'], 1, con=con)
        if d is None or abs(d) < r['threshold']:
            return None
        return _mk(r, '%s moved %+.3f %s (from %s to %s)'
                   % (r['series'], d, r['unit'], prev, cur),
                   'HIGH' if abs(d) >= r['threshold'] * 2 else 'MEDIUM', d)

    if r['kind'] == 'level_below':
        cur = store.latest(r['series'], con=con)
        if not cur or cur['value'] >= r['threshold']:
            return None
        return _mk(r, '%s is %.1f %s' % (r['series'], cur['value'], r['unit']),
                   'MEDIUM', cur['value'])

    if r['kind'] == 'spread_band':
        s = analytics.spread_state(con=con)
        if not s or s['percentile'] is None:
            return None
        if s['percentile'] < r['threshold'] and s['percentile'] > (100 - r['threshold']):
            return None
        return _mk(r, 'Spread %.0f bp, %sth percentile, band %s'
                   % (s['spread_bp'], s['percentile'], s['band']),
                   'HIGH' if s['band'] == 'EXTREMELY WIDE' else 'MEDIUM', s['spread_bp'])

    if r['kind'] == 'move_percentile':
        hits = []
        for sid in r['series']:
            m = analytics.move_context(sid, 1, con=con)
            if m and m['abs_percentile'] >= r['threshold']:
                hits.append('%s %+.2f (%.0fth pctile, %.1f sigma)'
                            % (sid, m['move_bp'], m['abs_percentile'], m['z'] or 0))
        if not hits:
            return None
        return _mk(r, '; '.join(hits), 'HIGH', len(hits))

    if r['kind'] == 'release_surprise':
        rel = registry.RELEASE_BY_ID.get(r['release'])
        if not rel:
            return None
        sc = analytics.score_release(rel, con=con)
        if not sc or sc['surprise_z'] is None or abs(sc['surprise_z']) < r['threshold']:
            return None
        if (sc['stale_days'] or 999) > 45:
            return None
        return _mk(r, '%s came in at %s versus %s, a %.1f sigma surprise. %s'
                   % (sc['name'], sc['actual'], sc['benchmark'], sc['surprise_z'],
                      sc['classification_label']),
                   'HIGH', sc['surprise_z'])
    return None


def _mk(rule, detail, severity, value):
    return {'id': rule['id'], 'label': rule['label'], 'detail': detail,
            'why': rule['why'], 'severity': severity, 'value': value}


def persist(fired, con=None):
    own = con is None
    con = con or store.connect()
    try:
        for a in fired:
            con.execute('INSERT INTO alert_fired(rule_id,fired_at,payload_json) VALUES (?,?,?)',
                        (a['id'], store.utcnow(), json.dumps(a)))
        if own:
            con.commit()
    finally:
        if own:
            con.close()
