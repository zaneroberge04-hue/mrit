"""Causal relationship graph.

Every explanation the terminal emits is a traced path through this graph, printed
for the user. Nothing here is a black box.

Structural guarantee: FED_STANCE has NO edge to MORTGAGE_30Y. It is not possible for
this engine to claim the Fed sets mortgage rates. It can only route through
expectations, then Treasuries, then MBS.
"""

from . import store

HIGH, MEDIUM, LOW = 0.9, 0.6, 0.35

NODES = {
    'CORE_CPI': ('Core CPI', 'CORECPI_MOM', 3),
    'HEADLINE_CPI': ('Headline CPI', 'CPI_YOY', 3),
    'PPI': ('Producer prices', 'PPI', 3),
    'SHELTER': ('Shelter inflation', 'SHELTER', 3),
    'AHE': ('Wage growth', 'AHE_YOY', 4),
    'INFL_EXPECT': ('Inflation expectations', 'BREAKEVEN10', 3),
    'NFP': ('Payrolls', 'NFP', 4),
    'UNRATE': ('Unemployment rate', 'UNRATE', 4),
    'CLAIMS': ('Jobless claims', 'CLAIMS', 4),
    'JOLTS': ('Job openings', 'JOLTS', 4),
    'GROWTH': ('Growth expectations', 'GDP', 5),
    'RETAIL': ('Retail sales', 'RETAIL', 5),
    'RECESSION_RISK': ('Recession risk', None, 5),
    'FED_STANCE': ('Fed policy stance', None, 2),
    'FED_BS': ('Fed balance sheet', 'WALCL', 2),
    'QT_RUNOFF': ('QT / MBS runoff', 'FED_MBS_HOLD', 2),
    'UST_2Y': ('2Y Treasury', 'UST2Y', 1),
    'UST_10Y': ('10Y Treasury', 'UST10Y', 1),
    'TERM_PREMIUM': ('Term premium', None, 1),
    'TSY_SUPPLY': ('Treasury supply', None, 7),
    'FOREIGN_DEMAND': ('Foreign demand for Treasuries', None, 7),
    'MOVE_VOL': ('Rate volatility (10Y realized)', 'MOVE', 6),
    'VIX': ('Equity volatility', 'VIX', 6),
    'HY_SPREAD': ('High yield spreads', 'HY_SPREAD', 6),
    'RISK_APPETITE': ('Risk appetite', 'SPX', 6),
    'OIL': ('WTI crude (US benchmark)', 'OIL', 6),
    'BRENT': ('Brent crude (global benchmark)', 'BRENT', 6),
    'DXY': ('Dollar', 'DXY', 7),
    'MBS_YIELD': ('MBS yield', 'MBS_CC', 1),
    'MBS_PRICE': ('MBS price', 'MBS_PRICE', 1),
    'MBS_SPREAD': ('MBS spread', 'MBS_SPREAD', 1),
    'MORTGAGE_30Y': ('30Y mortgage rate', 'MORT30Y', 1),
    'HOUSING_DEMAND': ('Housing demand', 'EHS', 8),
    'MTG_APPS': ('Mortgage applications', None, 8),
}

# (src, dst, sign, weight, lag_days, confidence, rationale)
EDGES = [
    ('CORE_CPI', 'INFL_EXPECT', +1, 0.80, 0, HIGH,
     'Realised core inflation is the largest single input to forward inflation pricing.'),
    ('HEADLINE_CPI', 'INFL_EXPECT', +1, 0.45, 0, MEDIUM,
     'Headline feeds expectations but is discounted for energy noise.'),
    ('PPI', 'CORE_CPI', +1, 0.35, 30, MEDIUM, 'Producer prices lead consumer prices with a lag.'),
    ('SHELTER', 'CORE_CPI', +1, 0.60, 0, HIGH, 'Shelter is roughly a third of core CPI.'),
    ('AHE', 'INFL_EXPECT', +1, 0.50, 0, MEDIUM, 'Wages drive services inflation.'),
    ('OIL', 'INFL_EXPECT', +1, 0.45, 0, MEDIUM,
     'WTI is the US refinery input, so it drives the gasoline line in headline CPI within '
     'two to four weeks.'),
    ('BRENT', 'INFL_EXPECT', +1, 0.55, 0, MEDIUM,
     'Brent prices roughly two thirds of the world’s traded crude, so it is the better read '
     'on GLOBAL inflation. Foreign inflation feeds foreign policy rates, which feeds the '
     'demand for US duration.'),
    ('BRENT', 'RECESSION_RISK', +1, 0.25, 0, LOW,
     'A sustained crude spike is a tax on the consumer. This is the offsetting channel: the '
     'same oil move that lifts inflation expectations also raises recession risk, and those '
     'two push mortgage rates in opposite directions.'),
    ('INFL_EXPECT', 'UST_10Y', +1, 0.70, 0, HIGH,
     'The 10Y is a real yield plus an inflation expectation. Expectations move the nominal.'),

    ('CORE_CPI', 'FED_STANCE', +1, 0.90, 0, HIGH, 'Inflation is the Fed reaction function.'),
    ('AHE', 'FED_STANCE', +1, 0.40, 0, MEDIUM, 'Wage pressure hardens the Fed.'),
    ('UNRATE', 'FED_STANCE', -1, 0.70, 0, HIGH, 'The employment half of the dual mandate.'),
    ('NFP', 'FED_STANCE', +1, 0.60, 0, HIGH, 'Strong hiring removes the case for easing.'),
    ('FED_STANCE', 'UST_2Y', +1, 0.85, 0, HIGH,
     'The front end prices the expected path of policy.'),
    ('FED_STANCE', 'QT_RUNOFF', +1, 0.50, 0, MEDIUM, 'A hawkish Fed keeps runoff going.'),
    ('UST_2Y', 'UST_10Y', +1, 0.50, 0, MEDIUM,
     'Front-end repricing pulls the belly and the long end, but only partly.'),

    ('NFP', 'GROWTH', +1, 0.70, 0, HIGH, 'Payrolls are the highest-frequency growth read.'),
    ('RETAIL', 'GROWTH', +1, 0.50, 0, MEDIUM, ''),
    ('GROWTH', 'UST_10Y', +1, 0.60, 0, HIGH, 'Stronger growth lifts real yields.'),
    ('NFP', 'RECESSION_RISK', -1, 0.70, 0, HIGH, ''),
    ('UNRATE', 'RECESSION_RISK', +1, 0.70, 0, HIGH, ''),
    ('CLAIMS', 'RECESSION_RISK', +1, 0.55, 0, MEDIUM, ''),
    ('JOLTS', 'RECESSION_RISK', -1, 0.40, 0, MEDIUM, ''),
    ('RECESSION_RISK', 'UST_10Y', -1, 0.75, 0, HIGH,
     'Recession fear is the classic bid for duration. Yields fall.'),

    ('TSY_SUPPLY', 'TERM_PREMIUM', +1, 0.55, 0, MEDIUM, 'More issuance demands more premium.'),
    ('FOREIGN_DEMAND', 'TERM_PREMIUM', -1, 0.55, 0, MEDIUM, ''),
    ('TERM_PREMIUM', 'UST_10Y', +1, 0.80, 0, HIGH, ''),
    ('RISK_APPETITE', 'UST_10Y', +1, 0.40, 0, MEDIUM,
     'Risk-on rotates out of Treasuries. Risk-off rotates in.'),
    ('DXY', 'FOREIGN_DEMAND', +1, 0.30, 0, LOW, ''),

    ('UST_10Y', 'MBS_YIELD', +1, 0.90, 0, HIGH,
     'MBS are priced off the Treasury curve. This is the main channel.'),
    ('MOVE_VOL', 'MBS_SPREAD', +1, 0.80, 0, HIGH,
     'MBS are short an embedded prepayment option. Rate volatility makes that option '
     'more expensive, so investors demand more spread.'),
    ('VIX', 'MBS_SPREAD', +1, 0.35, 0, LOW, ''),
    ('HY_SPREAD', 'MBS_SPREAD', +1, 0.50, 0, MEDIUM, 'General credit stress widens all spreads.'),
    ('QT_RUNOFF', 'MBS_SPREAD', +1, 0.60, 0, MEDIUM,
     'Fed MBS runoff removes the largest price-insensitive buyer from the market.'),
    ('RISK_APPETITE', 'HY_SPREAD', -1, 0.70, 0, HIGH, ''),
    ('MBS_PRICE', 'MBS_YIELD', -1, 1.00, 0, HIGH,
     'Price and yield are two views of the same number. Prices up means yields down.'),

    ('MBS_YIELD', 'MORTGAGE_30Y', +1, 0.95, 2, HIGH,
     'Lenders price off MBS execution, with a short lag for rate sheets.'),
    ('MBS_SPREAD', 'MORTGAGE_30Y', +1, 0.90, 2, HIGH,
     'A wider spread raises the borrower rate even when Treasuries are unchanged.'),

    ('MORTGAGE_30Y', 'MTG_APPS', -1, 0.75, 7, HIGH, ''),
    ('MORTGAGE_30Y', 'HOUSING_DEMAND', -1, 0.65, 30, HIGH, ''),
]

OUT = {}
for e in EDGES:
    OUT.setdefault(e[0], []).append(e)

TERMINAL = 'MORTGAGE_30Y'


def paths_to_terminal(src, max_depth=6):
    """All acyclic paths from src to MORTGAGE_30Y with net sign, weight, confidence."""
    results = []

    def walk(node, chain, sign, weight, conf, seen):
        if node == TERMINAL:
            results.append({
                'path': list(chain), 'sign': sign, 'weight': round(weight, 4),
                'confidence': round(conf, 3),
                'edges': [{'src': a, 'dst': b, 'sign': s, 'weight': w, 'rationale': r}
                          for (a, b, s, w, _l, _c, r) in chain],
            })
            return
        if len(chain) >= max_depth:
            return
        for (a, b, s, w, lag, c, r) in OUT.get(node, []):
            if b in seen:
                continue
            walk(b, chain + [(a, b, s, w, lag, c, r)], sign * s, weight * w,
                 min(conf, c), seen | set([b]))

    walk(src, [], 1, 1.0, 1.0, set([src]))
    results.sort(key=lambda p: -p['weight'])
    return results


def best_path(src):
    p = paths_to_terminal(src)
    return p[0] if p else None


def describe_path(path):
    """Render a path as a readable chain with directional arrows."""
    if not path:
        return ''
    parts = []
    running = 1
    for e in path['edges']:
        if not parts:
            parts.append(NODES.get(e['src'], (e['src'],))[0])
        running *= e['sign']
        parts.append('%s %s' % ('↑' if running > 0 else '↓', NODES.get(e['dst'], (e['dst'],))[0]))
    return ' → '.join(parts)


def propagate(shocks, con=None):
    """Given {node: signed magnitude}, return contributions to MORTGAGE_30Y.

    Returns every path, so offsetting forces survive instead of netting to a
    single number the user cannot interrogate.
    """
    out = []
    for node, mag in shocks.items():
        if mag is None or node not in NODES:
            continue
        paths = paths_to_terminal(node)
        if not paths:
            continue

        # Sum EVERY path, not just the strongest. A node like Brent reaches the
        # mortgage rate twice with opposite signs (inflation expectations up,
        # recession risk down). Taking only the best path would silently discard
        # the offsetting channel, which is the exact thing this graph exists to show.
        legs = []
        for p in paths:
            legs.append({
                'contribution': round(mag * p['sign'] * p['weight'], 3),
                'chain': describe_path(p), 'weight': p['weight'], 'sign': p['sign'],
                'confidence': p['confidence'],
                'rationale': next((e['rationale'] for e in p['edges'] if e['rationale']), ''),
            })
        contrib = sum(l['contribution'] for l in legs)
        gross = sum(abs(l['contribution']) for l in legs)
        self_offset = (1.0 - abs(contrib) / gross) if gross else 0.0
        primary = paths[0]

        out.append({
            'node': node, 'label': NODES[node][0], 'shock': round(mag, 3),
            'contribution': round(contrib, 3),
            'direction': 'UP' if contrib > 0 else ('DOWN' if contrib < 0 else 'FLAT'),
            'arrow': '↑' if contrib > 0 else ('↓' if contrib < 0 else '→'),
            'chain': describe_path(primary),
            'path_weight': primary['weight'], 'confidence': primary['confidence'],
            'rationales': [e['rationale'] for e in primary['edges'] if e['rationale']],
            'legs': legs,
            'n_paths': len(legs),
            'self_offsetting': self_offset > 0.2,
            'self_offset_note': (
                '%s reaches mortgage rates through %d competing channels, so the net (%+.2f) '
                'is smaller than either leg. %s'
                % (NODES[node][0], len(legs), contrib,
                   ' vs '.join('%+.2f via %s' % (l['contribution'],
                                                 l['chain'].split(' → ')[1].lstrip('↑↓ '))
                               for l in legs[:2]))
                if self_offset > 0.2 else None),
        })
    out.sort(key=lambda x: -abs(x['contribution']))

    total = sum(x['contribution'] for x in out)
    up = sum(x['contribution'] for x in out if x['contribution'] > 0)
    down = sum(-x['contribution'] for x in out if x['contribution'] < 0)
    offset = min(up, down) / max(up, down, 1e-9)

    return {
        'contributions': out,
        'net': round(total, 3),
        'upward_force': round(up, 3), 'downward_force': round(down, 3),
        'offset_ratio': round(offset, 3),
        'competing': offset > 0.25,
    }


def confidence_for(prop):
    """HIGH when one path dominates and its edges are strong. LOW when forces offset."""
    c = prop['contributions']
    if not c:
        return 'LOW', 'No measurable drivers.'
    total = sum(abs(x['contribution']) for x in c)
    if total < 1e-6:
        return 'LOW', 'Net movement is inside the noise floor.'
    top = abs(c[0]['contribution']) / total
    if prop['competing']:
        return 'MEDIUM', ('Forces are offsetting. Upward %.2f versus downward %.2f, so the '
                          'net is small relative to the components.'
                          % (prop['upward_force'], prop['downward_force']))
    if top > 0.6 and c[0]['confidence'] >= HIGH:
        return 'HIGH', '%s carries %.0f%% of the move through a high-confidence chain.' \
                       % (c[0]['label'], top * 100)
    if top > 0.6:
        return 'MEDIUM', '%s dominates but the chain runs through a medium-confidence link.' \
                         % c[0]['label']
    return 'MEDIUM', 'The move is split across several drivers with no single dominant cause.'


def graph_json():
    return {
        'nodes': [{'id': k, 'label': v[0], 'series_id': v[1], 'tier': v[2]}
                  for k, v in NODES.items()],
        'edges': [{'src': a, 'dst': b, 'sign': s, 'weight': w, 'lag_days': l,
                   'confidence': c, 'rationale': r} for (a, b, s, w, l, c, r) in EDGES],
        'terminal': TERMINAL,
        'invariant': ('FED_STANCE has no direct edge to MORTGAGE_30Y. Fed influence can only '
                      'reach mortgage rates through expectations, Treasuries and MBS.'),
    }


def assert_invariants():
    """Fails loudly if someone ever wires the Fed straight to mortgage rates."""
    for (a, b, _s, _w, _l, _c, _r) in EDGES:
        if a == 'FED_STANCE' and b == TERMINAL:
            raise AssertionError('FED_STANCE must not link directly to MORTGAGE_30Y')
    assert paths_to_terminal('FED_STANCE'), 'Fed must still reach mortgage rates indirectly'
    return True
