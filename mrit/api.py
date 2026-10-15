"""View assembly. The only layer the UI talks to."""

import datetime

from . import alerts, analytics, causal, narrative, pricing, registry, sources, store
from . import events as mrit_events


def _cell(sid, con=None, dp=2, days_1w=7):
    """One data cell: value, changes, provenance, freshness. The UI never builds these."""
    meta = registry.get(sid)
    cur = store.latest(sid, con=con)
    if not cur:
        return {'series_id': sid, 'name': meta['name'] if meta else sid,
                'value': None, 'quality': registry.UNAVAILABLE,
                'unit': meta['unit'] if meta else '', 'available': False,
                'reason': _unavailable_reason(meta)}
    _, _, d1 = analytics.change(sid, 1, con=con)
    _, _, dw = analytics.change_over_days(sid, days_1w, con=con)
    _, _, dm = analytics.change_over_days(sid, 30, con=con)
    age = analytics._age_days(cur['obs_date'])
    return {
        'series_id': sid, 'name': meta['name'] if meta else sid,
        'ticker': meta['ticker'] if meta else sid,
        'value': round(cur['value'], dp) if cur['value'] is not None else None,
        'unit': meta['unit'] if meta else '', 'tier': meta['tier'] if meta else None,
        'change_1d': round(d1, 4) if d1 is not None else None,
        'change_1w': round(dw, 4) if dw is not None else None,
        'change_1m': round(dm, 4) if dm is not None else None,
        'obs_date': cur['obs_date'], 'quality': cur['quality'],
        'source_id': cur['source_id'], 'fetched_at': cur['fetched_at'],
        'age_days': age, 'available': True,
        'invert_for_rates': meta['invert_for_rates'] if meta else 0,
        'notes': meta['notes'] if meta else '',
    }


def _unavailable_reason(meta):
    if not meta:
        return 'Unknown series.'
    src = meta['source_id']
    return {
        'fred': 'Needs a free FRED API key in config.json.',
        'eia': 'Needs a free EIA API key in config.json (eia.gov/opendata/register.php). A FRED key also works as a fallback for the two crude benchmarks.',
        'fedprob': 'Requires a licensed CME fed funds futures feed. No free source exists.',
        'movefeed': 'MOVE is a licensed ICE index with no free daily feed.',
        'mbsfeed': 'Real FNMA TBA prices are licensed.',
        'manual': 'Awaiting manual entry in data/manual.json.',
    }.get(src, 'Not yet ingested. Run a refresh.')


def _cells(ids, con=None, dp=2):
    return [_cell(s, con=con, dp=dp) for s in ids]


# ---------------------------------------------------------------- screens

def ticker(con=None):
    return {
        'items': _cells(['MORT30Y', 'MORT30Y_D', 'UST10Y', 'UST2Y', 'MBS_CC',
                         'MTG_UST_SPREAD'], con=con, dp=3),
        'fed': analytics.fed_stance(con=con),
        'next_event': (narrative.calendar_ahead(con=con, days=21) or [None])[0],
    }


def dash(con=None):
    press = analytics.pressure(con=con)
    press['bullets'] = analytics.pressure_bullets(con=con)
    press['provenance'] = analytics.meter_provenance(con=con)
    return {
        'screen': 'DASH',
        'ticker': ticker(con=con),
        'pressure': press,
        'why': narrative.why(con=con),
        'brief': narrative.morning_brief(con=con),
        'calendar': narrative.calendar_ahead(con=con, days=10)[:6],
        'alerts': alerts.evaluate(con=con),
        'spread': _slim_spread(analytics.spread_state(con=con)),
        'significance': analytics.move_significance(con=con),
        'tier1': _cells(['UST2Y', 'UST5Y', 'UST10Y', 'MBS_CC', 'MBS_SPREAD',
                         'CURVE_2S10S'], con=con, dp=3),
    }


def _slim_spread(s):
    if not s:
        return None
    out = dict(s)
    out.pop('history', None)
    return out


def screen_why(con=None):
    w = narrative.why(con=con)
    w['screen'] = 'WHY'
    w['graph'] = causal.graph_json()
    w['significance'] = analytics.move_significance(con=con)
    return w


def screen_ust(con=None):
    tenors = [t[0] for t in registry.TREASURY_TENORS]
    cells = _cells(tenors, con=con, dp=3)
    curve_hist = {}
    for label, days in (('current', 0), ('week', 7), ('month', 30), ('quarter', 90)):
        target = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        pts = []
        for sid, name, _c, yrs in registry.TREASURY_TENORS:
            r = store.value_on_or_before(sid, target, con=con) if days else \
                store.latest(sid, con=con)
            if r:
                pts.append({'tenor': name, 'series_id': sid, 'years': yrs, 'yield': r['value']})
        curve_hist[label] = pts
    return {
        'screen': 'UST', 'cells': cells, 'curve': curve_hist,
        'slopes': _cells(['CURVE_2S10S', 'CURVE_5S10S', 'CURVE_10S30S'], con=con, dp=1),
        'interpretation': _curve_note(con=con),
        'source': 'U.S. Treasury daily par yield curve. Free, no key, updated each business day.',
    }


def _curve_note(con=None):
    s = store.latest('CURVE_2S10S', con=con)
    _, _, d = analytics.change('CURVE_2S10S', 1, con=con)
    if not s:
        return 'Curve data unavailable.'
    shape = ('inverted' if s['value'] < 0 else
             ('flat' if s['value'] < 25 else 'positively sloped'))
    move = ('steepening' if (d or 0) > 1 else ('flattening' if (d or 0) < -1 else 'stable'))
    why_txt = {
        'steepening': ('The long end is selling off faster than the front end, or the front '
                       'end is rallying faster. Bull steepening (front end leading) is good '
                       'for mortgage rates. Bear steepening (long end leading) is not, '
                       'because mortgages track the long end.'),
        'flattening': ('The gap is closing. If the front end is selling off, the market is '
                       'pricing a firmer Fed. Mortgage rates care more about where the 10Y '
                       'ends up than about the slope itself.'),
        'stable': 'No meaningful change in curve shape today.',
    }[move]
    return {'shape': shape, 'slope_bp': s['value'], 'motion': move, 'explanation': why_txt}


def screen_mbs(con=None):
    stack = analytics.mbs_stack(con=con)
    return {
        'screen': 'MBS', 'stack': stack,
        'cells': _cells(['MTG_UST_SPREAD', 'MBS_CC', 'MBS_SPREAD'], con=con, dp=3),
        'data_status': registry.MODELED,
        'banner': ('Real FNMA TBA prices are licensed (Tradeweb, MBS Live, Bloomberg) and '
                   'have no free feed, so this screen does not invent one. It leads with the '
                   'mortgage/Treasury spread, which is a LIVE read on whether MBS are rich or '
                   'cheap, and shows the current-coupon yield DERIVED from the published '
                   'mortgage rate and the Treasury curve. The coupon stack below is modeled '
                   'for shape and direction only. Never lock or trade off it.'),
        'teaching': ['The mortgage/Treasury spread is the number to watch here. It is live, '
                     'and it is what actually tells you whether MBS are cheap or rich.',
                     'A wider spread means investors demand more yield to hold mortgages, '
                     'which pushes your rate up even if the 10-year has not moved.',
                     'Current coupon is the yield on the coupon your loans are being pooled '
                     'into. It tracks the mortgage rate less the primary/secondary spread.',
                     'Prices in 32nds are deliberately absent: without a licensed TBA feed, '
                     'any price here would be a guess dressed up as a quote.'],
    }


def screen_spread(con=None):
    s = analytics.spread_state(con=con)
    if not s:
        return {'screen': 'SPREAD', 'available': False}
    hist = s.pop('history')
    s.update({
        'screen': 'SPREAD', 'available': True,
        'series': [{'d': r['obs_date'], 'v': r['value']} for r in hist],
        'weekly_decomposition': analytics.weekly_decomposition(con=con),
        'daily': analytics.daily_move(con=con),
        'explanation': (
            'Your borrower rate is the 10-year Treasury plus the mortgage spread. The Fed '
            'moves the front end, which pulls the 10-year. Nobody controls the spread. It is '
            'set by rate volatility, prepayment risk, and who is buying mortgage bonds. '
            'When the spread is wide, a Treasury rally does not reach your borrower.'),
        'bands': [{'range': '%d-%dth pct' % (lo, hi), 'label': nm}
                  for lo, hi, nm in analytics.SPREAD_BANDS],
    })
    return s


def screen_fed(con=None):
    return {
        'screen': 'FED',
        'stance': analytics.fed_stance(con=con),
        'cells': _cells(['FED_TARGET_LOW', 'FED_TARGET_HIGH', 'FEDFUNDS', 'UST2Y',
                         'WALCL', 'FED_MBS_HOLD', 'FED_PROB_CUT'], con=con, dp=3),
        'fomc_dates': [{'date': d, 'days_out': _days_out(d)} for d in narrative.FOMC_2026],
        'transmission_note': (
            'The Fed does not set mortgage rates. It sets the overnight rate. That moves '
            'expectations for growth and inflation, which move Treasury yields, which move '
            'MBS yields, which move mortgage rates. The chain can break at any link. In '
            'September through December 2024 the Fed cut 100 bp and the 30-year mortgage '
            'rate rose roughly 100 bp, because the 10-year sold off.'),
    }


def _days_out(d):
    try:
        dt = datetime.date(*[int(x) for x in d.split('-')])
        return (dt - datetime.date.today()).days
    except Exception:
        return None


def screen_tier(tier, con=None):
    """Generic tier screen: series cells plus scored releases."""
    ids = [s['id'] for s in registry.by_tier(tier)]
    return {
        'screen': 'TIER%d' % tier,
        'tier': tier, 'tier_name': registry.TIER_NAMES.get(tier, ''),
        'cells': _cells(ids, con=con, dp=3),
        'releases': analytics.scored_releases(tier=tier, con=con),
        'class_note': analytics.CLASS_NOTE,
    }


def screen_calendar(con=None, days=45):
    events = narrative.calendar_ahead(con=con, days=days)
    scored = dict((r['id'], r) for r in analytics.scored_releases(con=con))
    for e in events:
        for rid, rel in registry.RELEASE_BY_ID.items():
            if rel['name'] == e['name']:
                sc = scored.get(rid)
                if sc:
                    e['last_actual'] = sc['actual']
                    e['last_period'] = sc['period']
                    e['previous'] = sc['previous']
                    e['consensus'] = sc['consensus']
                    e['benchmark'] = sc['benchmark']
                    e['last_classification'] = sc['classification_label']
                break
    return {
        'screen': 'CALENDAR', 'events': events,
        'note': ('Dates for BLS and Census releases are projected from their published '
                 'monthly rhythm and marked PROJECTED. FOMC dates are the confirmed 2026 '
                 'schedule. Consensus forecasts require a paid feed, so surprise is measured '
                 'against the trailing mean and labeled as such.'),
        'alerts': alerts.evaluate(con=con),
    }


def screen_history(con=None, series_ids=None, days=365):
    series_ids = series_ids or ['MORT30Y', 'UST10Y']
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    out = []
    for sid in series_ids:
        meta = registry.get(sid)
        rows = store.history(sid, since=since, con=con)
        if not rows:
            continue
        out.append({
            'series_id': sid, 'name': meta['name'] if meta else sid,
            'unit': meta['unit'] if meta else '',
            'quality': rows[-1]['quality'],
            'points': [{'d': r['obs_date'], 'v': r['value']} for r in rows],
        })
    return {'screen': 'HISTORY', 'days': days, 'series': out,
            'available_overlays': [
                {'id': s['id'], 'name': s['name'], 'unit': s['unit'], 'tier': s['tier']}
                for s in registry.SERIES
                if store.latest(s['id'], con=con)]}


def screen_pricing(con=None, params=None):
    p = params or {}
    mort = store.latest('MORT30Y_D', con=con) or store.latest('MORT30Y', con=con)
    market = mort['value'] if mort else 6.66
    kw = dict(
        fico=int(p.get('fico', 740)), ltv=float(p.get('ltv', 80)),
        loan_amount=float(p.get('loan_amount', 285000)),
        product=p.get('product', 'CONVENTIONAL'), occupancy=p.get('occupancy', 'PRIMARY'),
        property_type=p.get('property_type', 'SFR'), dti=float(p.get('dti', 38)),
        points=float(p.get('points', 0)), term=int(p.get('term', 30)),
    )
    dm = analytics.daily_move(con=con)
    res = pricing.price(market, daily_move_bp=dm.get('ust10_bp'), **kw)
    return {
        'screen': 'PRICING', 'market_rate': market,
        'market_rate_quality': mort['quality'] if mort else registry.UNAVAILABLE,
        'result': res,
        'buydowns': [pricing.buydown(kw['loan_amount'], res['borrower_rate'], s)
                     for s in ('2-1', '3-2-1', '1-0')],
        'options': {
            'products': list(pricing.PRODUCT_BASE.keys()),
            'occupancies': list(pricing.OCCUPANCY_ADJ.keys()),
            'property_types': list(pricing.PROPERTY_ADJ.keys()),
            'terms': sorted(pricing.TERM_ADJ.keys(), reverse=True),
        },
        'disclaimer': pricing.DISCLAIMER,
    }


def screen_brief(con=None):
    return {
        'screen': 'BRIEF',
        'morning': narrative.morning_brief(con=con),
        'eod': narrative.eod_review(con=con),
        'translations': dict((a, narrative.translate(a, con=con))
                             for a in ('BORROWER', 'REALTOR', 'LO', 'EXEC')),
    }


def status(con=None):
    fetches = store.fetch_status(con=con)
    latest = store.all_latest(con=con)
    counts = {}
    for sid, row in latest.items():
        counts[row['quality']] = counts.get(row['quality'], 0) + 1
    missing = [s['id'] for s in registry.SERIES if s['id'] not in latest]
    return {
        'fetches': fetches, 'quality_counts': counts,
        'series_total': len(registry.SERIES), 'series_with_data': len(latest),
        'missing': missing,
        'server_time': store.utcnow(),
        'sources': [{'id': s.source_id, 'name': getattr(s, 'name', s.source_id),
                     'requires_key': s.requires_key} for s in sources.SOURCES],
    }


def series_detail(sid, days=1825, con=None):
    """Full provenance inspector for one series.

    Answers, for any number on any screen: where did this come from, how do I get
    to it myself, what does the level mean, and how does it reach a mortgage rate.
    """
    meta = registry.get(sid)
    if not meta:
        return {'error': 'unknown series %s' % sid}
    cell = _cell(sid, con=con, dp=4)
    src = registry.SOURCE_META.get(meta['source_id'], {})

    deep = None
    if src.get('deep_link') and meta.get('ticker'):
        deep = src['deep_link'] % meta['ticker']

    deriv = registry.DERIVATION.get(sid)
    provenance = {
        'source_id': meta['source_id'],
        'source_name': src.get('name', meta['source_id']),
        'dataset': src.get('dataset'),
        'url': src.get('url'),
        'deep_link': deep,
        'endpoint': src.get('endpoint'),
        'ticker': meta.get('ticker'),
        'auth': src.get('auth'),
        'cadence': src.get('cadence'),
        'reliability': src.get('reliability'),
        'caveat': src.get('caveat'),
        'refresh_window': meta['refresh'],
        'publication_lag_days': registry.publication_lag(sid),
        'lag_note': (
            'This source publishes about %d days behind real time, so an observation '
            'that old is normal, not a broken feed. For same-session crude you would '
            'need a front-month futures feed, which is licensed.'
            % registry.publication_lag(sid)) if registry.publication_lag(sid) >= 3 else None,
        'obs_date': cell.get('obs_date'),
        'fetched_at': cell.get('fetched_at'),
        'age_days': cell.get('age_days'),
        'quality': cell.get('quality', registry.UNAVAILABLE),
        'quality_meaning': registry.QUALITY_MEANING.get(
            cell.get('quality', registry.UNAVAILABLE), ''),
        'registry_note': meta.get('notes'),
        'derivation': ({'formula': deriv[0], 'inputs': deriv[1], 'note': deriv[2]}
                       if deriv else None),
    }

    insights = _insights(sid, meta, con=con)
    impact = _impact(sid, meta, con=con)

    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = store.history(sid, since=since, con=con)
    return {
        'meta': meta, 'cell': cell,
        'provenance': provenance, 'insights': insights, 'impact': impact,
        'points': [{'d': r['obs_date'], 'v': r['value'], 'q': r['quality']} for r in rows],
        'related': _related(sid, meta, deriv),
    }


def _insights(sid, meta, con=None):
    """Where this level sits, how it is moving, and whether the move is notable."""
    cell = _cell(sid, con=con, dp=4)
    if not cell.get('available'):
        return {'available': False, 'reason': cell.get('reason')}

    out = {'available': True, 'value': cell['value'], 'unit': meta['unit'],
           'change_1d': cell['change_1d'], 'change_1w': cell['change_1w'],
           'change_1m': cell['change_1m']}

    for label, yrs in (('1y', 1), ('5y', 5)):
        since = (datetime.date.today() - datetime.timedelta(days=365 * yrs)).isoformat()
        rows = store.history(sid, since=since, con=con)
        vals = [r['value'] for r in rows]
        if len(vals) > 10:
            out['range_' + label] = {
                'min': round(min(vals), 4), 'max': round(max(vals), 4),
                'percentile': analytics.pct_rank(vals, cell['value']),
                'n': len(vals),
            }

    step = 1
    sig = analytics.move_context(sid, step, con=con,
                                 tenure_start=sources.config().get('tenure_start'))
    if sig:
        out['move'] = {'move_bp': sig['move_bp'], 'z': sig['z'],
                       'percentile': sig['abs_percentile'], 'verdict': sig['verdict'],
                       'detail': sig['verdict_detail'],
                       'largest_up': sig['largest_up'], 'largest_down': sig['largest_down']}

    p1 = out.get('range_1y', {}).get('percentile')
    if p1 is not None:
        where = ('the top of' if p1 >= 80 else 'the bottom of' if p1 <= 20 else 'the middle of')
        out['stat_line'] = ('Sitting in %s its 1-year range, at the %.0fth percentile.'
                            % (where, p1))
    return out


def _impact(sid, meta, con=None):
    """How a move in this series reaches a mortgage rate, traced through the graph."""
    node = None
    for n, (label, series_id, tier) in causal.NODES.items():
        if series_id == sid:
            node = n
            break

    invert = bool(meta.get('invert_for_rates'))
    all_paths = causal.paths_to_terminal(node) if node else []
    signs = set(p['sign'] for p in all_paths)

    if sid == 'MORT30Y':
        meaning = ('This IS the mortgage rate. Everything else in the terminal exists to '
                   'explain why this number is where it is.')
    elif len(signs) > 1:
        # Never flatten a two-sided driver into a one-line rule. Telling someone "a rise
        # pushes rates up" about a series that also pushes them down is exactly the kind
        # of confident wrongness this terminal exists to avoid.
        up = max((p for p in all_paths if p['sign'] > 0), key=lambda p: p['weight'])
        dn = max((p for p in all_paths if p['sign'] < 0), key=lambda p: p['weight'])
        net = 'UP' if up['weight'] > dn['weight'] else 'DOWN'
        meaning = ('This series cuts BOTH WAYS. A rise pushes mortgage rates UP through %s '
                   '(path strength %.0f%%) and DOWN through %s (path strength %.0f%%). On '
                   'current weights the %s channel dominates, so the net effect of a rise is '
                   '%s. The two can trade places depending on how far and how fast it moves: '
                   'a modest rise is an inflation story, a violent one becomes a demand story.'
                   % (causal.NODES[up['edges'][0]['dst']][0].lower(), up['weight'] * 100,
                      causal.NODES[dn['edges'][0]['dst']][0].lower(), dn['weight'] * 100,
                      'inflation' if net == 'UP' else 'growth', net))
    elif invert:
        meaning = 'A RISE in this series pushes mortgage rates DOWN. A fall pushes them UP.'
    else:
        meaning = 'A RISE in this series pushes mortgage rates UP. A fall pushes them DOWN.'

    chains = []
    if node:
        for p in all_paths[:4]:
            chains.append({
                'chain': causal.describe_path(p),
                'weight': p['weight'], 'sign': p['sign'],
                'confidence': p['confidence'],
                'rationales': [e['rationale'] for e in p['edges'] if e['rationale']],
            })

    return {
        'node': node, 'meaning': meaning, 'invert_for_rates': invert,
        'chains': chains,
        'no_chain_note': (None if chains else
                          'This series is not a node in the causal graph. It is context, '
                          'not a modeled driver of mortgage rates.'),
        'tier': meta['tier'], 'tier_name': registry.TIER_NAMES.get(meta['tier'], ''),
    }


def _related(sid, meta, deriv):
    """Inputs to this series, series it feeds, and its tier siblings."""
    feeds = [k for k, v in registry.DERIVATION.items() if sid in v[1]]
    out = []
    for r, rel in [(deriv[1] if deriv else [], 'INPUT'), (feeds, 'FEEDS')]:
        for other in r:
            m = registry.get(other)
            if m:
                out.append({'id': other, 'name': m['name'], 'relation': rel})
    for m in registry.by_tier(meta['tier']):
        if m['id'] != sid and len(out) < 14:
            out.append({'id': m['id'], 'name': m['name'], 'relation': 'TIER'})
    return out


def screen_meta(screen, con=None):
    """Panel/tab level explainer: what a screen is for and which sources feed it."""
    info = SCREEN_INFO.get(screen.upper())
    if not info:
        return {'error': 'unknown screen %s' % screen}
    srcs = []
    for s in info['series']:
        m = registry.get(s)
        if not m:
            continue
        if m['source_id'] not in [x['source_id'] for x in srcs]:
            sm = registry.SOURCE_META.get(m['source_id'], {})
            srcs.append({'source_id': m['source_id'], 'name': sm.get('name', m['source_id']),
                         'url': sm.get('url'), 'caveat': sm.get('caveat'),
                         'auth': sm.get('auth')})
    return {'screen': screen.upper(), 'title': info['title'], 'purpose': info['purpose'],
            'question': info['question'], 'how_to_read': info['how_to_read'],
            'series': [{'id': s, 'name': (registry.get(s) or {}).get('name', s)}
                       for s in info['series']],
            'sources': srcs}


SCREEN_INFO = {
    'DASH': {'title': 'Dashboard', 'question': 'What are rates doing right now?',
             'purpose': 'A 30-second read before you pick up the phone.',
             'how_to_read': 'Pressure meter first, then the driver panel. If the top driver '
                            'is OBSERVED you can trust the direction. If everything is '
                            'INFERRED, the market has not actually moved today.',
             'series': ['MORT30Y', 'MORT30Y_D', 'UST10Y', 'UST2Y', 'MBS_PRICE',
                        'MTG_UST_SPREAD']},
    'WHY': {'title': 'Why rates are moving', 'question': 'Why did rates move?',
            'purpose': 'Separate the cause from the correlation, with confidence attached.',
            'how_to_read': 'Read the counterforce before the primary driver. When forces '
                           'offset, a small net move can hide two large opposing ones.',
            'series': ['UST10Y', 'MTG_UST_SPREAD', 'CORECPI_MOM', 'NFP']},
    'UST': {'title': 'Treasuries', 'question': 'What is the bond market doing?',
            'purpose': 'The 10-year is the primary input to every mortgage rate.',
            'how_to_read': 'Watch the 10Y for your rate and the 2Y for Fed expectations. '
                           'Curve shape matters less to you than where the 10Y lands.',
            'series': ['UST2Y', 'UST5Y', 'UST10Y', 'UST30Y', 'CURVE_2S10S']},
    'MBS': {'title': 'Mortgage-backed securities',
            'question': 'What is the bond your loans get pooled into doing?',
            'purpose': 'Rate sheets are priced off MBS execution, not off Treasuries.',
            'how_to_read': 'Everything here is MODELED. Use it to understand the mechanism, '
                           'never to lock.',
            'series': ['MBS_CC', 'MBS_PRICE', 'MBS_TICKS', 'MBS_SPREAD']},
    'SPREAD': {'title': 'Mortgage / Treasury spread',
               'question': 'Is the move coming from Treasuries or from the spread?',
               'purpose': 'The most useful screen here. It is the only one that tells you '
                          'whether a Treasury rally will actually reach your borrower.',
               'how_to_read': 'The weekly decomposition is an exact identity on published '
                              'data. When the spread is wide, stop explaining rates with the '
                              'Fed and start explaining them with the spread.',
               'series': ['MORT30Y', 'UST10Y', 'MTG_UST_SPREAD']},
    'FED': {'title': 'Federal Reserve', 'question': 'What is the Fed doing to rates?',
            'purpose': 'To show the transmission mechanism, and to stop you saying the Fed '
                       'sets mortgage rates.',
            'how_to_read': 'The Fed moves the front end. Your rate follows the 10-year and '
                           'the spread. The chain breaks often.',
            'series': ['FED_TARGET_HIGH', 'UST2Y', 'WALCL']},
    'VOL': {'title': 'Market conditions', 'question': 'Is the market calm or stressed?',
            'purpose': 'Risk appetite, volatility and energy set the mortgage SPREAD, which '
                       'is the half of your rate that Treasuries do not explain.',
            'how_to_read': 'Watch the two crude benchmarks together. Brent is the global '
                           'read and WTI the domestic one. When they diverge, the story is '
                           'supply or shipping abroad, not US demand. Oil is the one input '
                           'here that pushes mortgage rates BOTH ways at once: up through '
                           'inflation expectations, down through recession risk.',
            'series': ['BRENT', 'OIL', 'BRENT_WTI', 'VIX', 'HY_SPREAD', 'MOVE']},
    'PRICING': {'title': 'Rate pricing lab',
                'question': 'Why is my borrower not getting the rate on the news?',
                'purpose': 'To show that borrower profile usually beats market timing.',
                'how_to_read': 'Illustrative structure only. Never quote it.',
                'series': ['MORT30Y_D']},
}


# ---------------------------------------------------------------- chart

# Series offered in ADD COMPARISON, grouped so the picker reads sensibly.
COMPARE_CATALOG = [
    ('Rates', ['MORT30Y', 'MORT15Y', 'MORT30Y_D', 'OBMMI30']),
    ('Treasuries', ['UST2Y', 'UST5Y', 'UST10Y', 'UST30Y']),
    ('MBS & spreads', ['MBS_CC', 'MBS_SPREAD', 'MTG_UST_SPREAD', 'CURVE_2S10S']),
    ('Fed', ['FED_TARGET_HIGH', 'FEDFUNDS', 'WALCL']),
    ('Inflation', ['CPI_YOY', 'CORECPI_YOY', 'PCE_CORE_YOY', 'BREAKEVEN10']),
    ('Market', ['BRENT', 'OIL', 'VIX', 'MOVE', 'HY_SPREAD', 'SPX', 'DXY']),
]

SERIES_COLORS = ['#e8a33d', '#4aa3df', '#3ecf8e', '#c77dff', '#ef5350', '#8d9aa8']

# Ranges the selector offers. `min_freq` is the coarsest observation frequency that
# can honestly answer the range: a weekly survey cannot show you a single day.
RANGES = [
    ('1D', 1, 'realtime'), ('5D', 5, 'daily'), ('1M', 30, 'daily'),
    ('3M', 91, 'weekly'), ('6M', 182, 'weekly'), ('YTD', None, 'weekly'),
    ('1Y', 365, 'weekly'), ('2Y', 730, 'weekly'), ('5Y', 1825, 'monthly'),
    ('10Y', 3650, 'monthly'), ('MAX', None, 'quarterly'),
]
_FREQ_RANK = {'realtime': 0, 'daily': 1, 'weekly': 2, 'monthly': 3,
              'quarterly': 4, 'event': 5}


def _chart_series(sid, idx, con=None):
    """Full history for one series plus everything the chart needs to label it."""
    meta = registry.get(sid)
    if not meta:
        return None
    rows = store.history(sid, con=con)
    cur = store.latest(sid, con=con)
    src = registry.SOURCE_META.get(meta['source_id'], {})
    freq = meta['refresh']
    if not rows:
        return {
            'series_id': sid, 'name': meta['name'], 'unit': meta['unit'],
            'available': False, 'reason': _unavailable_reason(meta),
            'frequency': freq, 'frequency_label': registry.FREQUENCY.get(freq, freq.upper()),
            'source': src.get('name', meta['source_id']), 'quality': registry.UNAVAILABLE,
            'color': SERIES_COLORS[idx % len(SERIES_COLORS)], 'points': [],
        }
    vals = [r['value'] for r in rows]
    return {
        'series_id': sid, 'name': meta['name'], 'unit': meta['unit'],
        'available': True,
        'tier': meta['tier'], 'notes': meta['notes'],
        'frequency': freq,
        'frequency_label': registry.FREQUENCY.get(freq, freq.upper()),
        'source': src.get('name', meta['source_id']),
        'source_url': src.get('deep_link', '') % meta['ticker']
        if (src.get('deep_link') and meta.get('ticker')) else src.get('url'),
        'source_caveat': src.get('caveat'),
        'quality': cur['quality'], 'last_updated': cur['fetched_at'],
        'obs_date': cur['obs_date'],
        'color': SERIES_COLORS[idx % len(SERIES_COLORS)],
        'invert_for_rates': meta['invert_for_rates'],
        # [date, value] pairs keep the payload small and stay human-readable in
        # devtools, which matters more here than shaving a few more kilobytes.
        'points': [[r['obs_date'], r['value']] for r in rows],
        'full_stats': {
            'n': len(rows), 'first': rows[0]['obs_date'], 'last': rows[-1]['obs_date'],
            'high': round(max(vals), 4),
            'high_date': max(rows, key=lambda r: r['value'])['obs_date'],
            'low': round(min(vals), 4),
            'low_date': min(rows, key=lambda r: r['value'])['obs_date'],
        },
    }


def screen_chart(con=None, primary='MORT30Y', compare=None, events=None):
    """Everything the interactive chart needs, in one round trip.

    Full history ships once and the client windows it, so range and mode switching
    are instant with no network. Only adding a comparison series refetches.
    """
    compare = [c for c in (compare or []) if c and c != primary][:5]
    prim = _chart_series(primary, 0, con=con)
    if not prim:
        return {'error': 'unknown series %s' % primary}

    series = [prim] + [s for s in
                       (_chart_series(c, i + 1, con=con) for i, c in enumerate(compare))
                       if s]

    prim_rank = _FREQ_RANK.get(prim['frequency'], 2)
    ranges = []
    for label, days, min_freq in RANGES:
        need = _FREQ_RANK.get(min_freq, 2)
        ok = prim_rank <= need
        ranges.append({
            'id': label, 'days': days, 'enabled': ok,
            'reason': None if ok else
            ('%s is a %s series. A %s window would contain at most one observation, '
             'and this terminal will not interpolate one to fill the gap.'
             % (prim['name'], prim['frequency_label'].lower(), label)),
        })

    evt = []
    if events and prim.get('points'):
        evt = mrit_events.markers(prim['points'][0][0], prim['points'][-1][0],
                                  kinds=events, rate_series=primary, con=con)

    return {
        'screen': 'CHART',
        'series': series,
        # Context rail: the chart is the feature, not the whole screen.
        'context': {
            'movers': _cells(['UST10Y', 'UST2Y', 'MTG_UST_SPREAD', 'MBS_CC',
                              'BRENT', 'OIL'], con=con, dp=3),
            'drivers': analytics.pressure(con=con)['contributors'][:6],
            'bullets': analytics.pressure_bullets(con=con)[:4],
            'upcoming': narrative.calendar_ahead(con=con, days=14)[:5],
            'alerts': alerts.evaluate(con=con)[:3],
        },
        'events': evt,
        'ranges': ranges,
        'catalog': {
            'compare': [{'group': g,
                         'items': [{'id': s, 'name': (registry.get(s) or {}).get('name', s),
                                    'unit': (registry.get(s) or {}).get('unit', ''),
                                    'has_data': bool(store.latest(s, con=con))}
                                   for s in ids if registry.get(s)]}
                        for g, ids in COMPARE_CATALOG],
            'events': mrit_events.kind_catalog(),
            'modes': [
                {'id': 'rate', 'label': 'RATE', 'hint': 'Level, as published'},
                {'id': 'change', 'label': 'CHANGE', 'hint': 'Change vs the prior observation'},
                {'id': 'bp', 'label': 'BP FROM START', 'hint': 'Basis points from the window start'},
                {'id': 'norm', 'label': 'NORMALIZED', 'hint': 'Percent change from the window start, '
                                                              'the only mode that compares unlike units'},
            ],
        },
    }
