"""Analytics: surprise scoring, percentiles, move decomposition, pressure meter.

Design rule enforced here: the top-level decomposition of a mortgage-rate move is an
arithmetic identity, not a model. Only the attribution of each leg is inferred, and
inferred pieces are labeled and ranked rather than collapsed into one score.
"""

import datetime
import math

from . import registry, store

# ---------------------------------------------------------------- helpers


def _mean(xs):
    return sum(xs) / float(len(xs)) if xs else None


def _stdev(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / float(len(xs) - 1))


def pct_rank(series, value):
    """Percentile of value within series, 0-100."""
    vals = [v for v in series if v is not None]
    if not vals or value is None:
        return None
    below = sum(1 for v in vals if v < value)
    return round(100.0 * below / len(vals), 1)


def change(sid, periods=1, con=None):
    """Change over N observations back. Returns (current, prior, delta) or Nones."""
    rows = store.history(sid, limit=periods + 1, con=con)
    if len(rows) < periods + 1:
        return (rows[-1]['value'] if rows else None), None, None
    cur, prv = rows[-1]['value'], rows[-1 - periods]['value']
    return cur, prv, cur - prv


def change_over_days(sid, days, con=None):
    """Change versus the most recent observation at or before today-N days."""
    rows = store.history(sid, con=con)
    if not rows:
        return None, None, None
    cur = rows[-1]
    target = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    prior = None
    for r in rows:
        if r['obs_date'] <= target:
            prior = r
    if not prior:
        return cur['value'], None, None
    return cur['value'], prior['value'], cur['value'] - prior['value']


# ---------------------------------------------------------------- surprises

STALE_RELEASE_DAYS = 70   # latest monthly print stays actionable until the next one

CLASSES = ['VERY_BULLISH', 'BULLISH', 'NEUTRAL', 'BEARISH', 'VERY_BEARISH']
CLASS_LABEL = {
    'VERY_BULLISH': 'Very bullish for rates',
    'BULLISH': 'Bullish for rates',
    'NEUTRAL': 'Neutral',
    'BEARISH': 'Bearish for rates',
    'VERY_BEARISH': 'Very bearish for rates',
}
# "Bullish for rates" = bond-friendly = mortgage rates lower.
CLASS_NOTE = 'Bullish means bond-friendly, which pushes mortgage rates DOWN.'


def classify_surprise(z, direction):
    """z = standardised surprise. direction=+1 if a HIGH print pushes rates UP."""
    if z is None:
        return 'NEUTRAL'
    eff = z * direction          # positive eff = upward pressure on rates = bearish
    if eff >= 1.5:
        return 'VERY_BEARISH'
    if eff >= 0.5:
        return 'BEARISH'
    if eff <= -1.5:
        return 'VERY_BULLISH'
    if eff <= -0.5:
        return 'BULLISH'
    return 'NEUTRAL'


def score_release(rel, con=None, lookback=24):
    """Build a scored release row.

    No free consensus feed exists, so absent a manually entered consensus the
    benchmark is the trailing mean of the series. That is a TREND surprise, not a
    CONSENSUS surprise, and it is labeled that way everywhere it surfaces.
    """
    sid = rel['series_id']
    rows = store.history(sid, con=con)
    if not rows:
        return None
    actual = rows[-1]['value']
    previous = rows[-2]['value'] if len(rows) > 1 else None
    hist = [r['value'] for r in rows[-(lookback + 1):-1]]

    consensus = rel.get('consensus')
    benchmark = 'consensus'
    if consensus is None:
        consensus = _mean(hist)
        benchmark = 'trailing %dm mean' % min(lookback, len(hist))

    sd = _stdev(hist)
    surprise = (actual - consensus) if consensus is not None else None
    z = (surprise / sd) if (surprise is not None and sd) else None
    cls = classify_surprise(z, rel['direction'])

    return {
        'id': rel['id'], 'name': rel['name'], 'series_id': sid, 'tier': rel['tier'],
        'impact': rel['impact'], 'direction': rel['direction'], 'notes': rel.get('notes', ''),
        'period': rows[-1]['obs_date'], 'unit': registry.get(sid)['unit'] if registry.get(sid) else '',
        'previous': previous, 'consensus': (round(consensus, 3) if consensus is not None else None),
        'actual': actual,
        'surprise': (round(surprise, 3) if surprise is not None else None),
        'surprise_z': (round(z, 2) if z is not None else None),
        'benchmark': benchmark,
        'classification': cls, 'classification_label': CLASS_LABEL[cls],
        'quality': rows[-1]['quality'],
        'stale_days': _age_days(rows[-1]['obs_date']),
    }


def _age_days(date_str):
    try:
        d = datetime.date(*[int(x) for x in date_str[:10].split('-')])
        return (datetime.date.today() - d).days
    except Exception:
        return None


def scored_releases(tier=None, con=None):
    out = []
    for rel in registry.RELEASES:
        if tier and rel['tier'] != tier:
            continue
        r = score_release(rel, con=con)
        if r:
            out.append(r)
    return out


# ---------------------------------------------------------------- spread bands

SPREAD_BANDS = [
    (0, 10, 'VERY TIGHT'), (10, 30, 'TIGHT'), (30, 70, 'NORMAL'),
    (70, 90, 'WIDE'), (90, 101, 'EXTREMELY WIDE'),
]


def spread_state(con=None, years=10):
    """Mortgage/10Y spread level, percentile, band, and rate decomposition."""
    since = (datetime.date.today() - datetime.timedelta(days=365 * years)).isoformat()
    rows = store.history('MTG_UST_SPREAD', since=since, con=con)
    if not rows:
        return None
    cur = rows[-1]
    vals = [r['value'] for r in rows]
    p = pct_rank(vals, cur['value'])
    band = 'NORMAL'
    for lo, hi, nm in SPREAD_BANDS:
        if p is not None and lo <= p < hi:
            band = nm
            break

    mort = store.latest('MORT30Y', con=con)
    ust = store.value_on_or_before('UST10Y', cur['obs_date'], con=con)
    avg = _mean(vals)

    excess_bp = (cur['value'] - avg) if avg is not None else None
    return {
        'spread_bp': cur['value'], 'obs_date': cur['obs_date'], 'quality': cur['quality'],
        'percentile': p, 'band': band,
        'avg_bp': round(avg, 1) if avg is not None else None,
        'min_bp': round(min(vals), 1), 'max_bp': round(max(vals), 1),
        'n_obs': len(vals), 'years': years,
        'mortgage_rate': mort['value'] if mort else None,
        'ust10': ust['value'] if ust else None,
        'excess_vs_avg_bp': round(excess_bp, 1) if excess_bp is not None else None,
        'decomposition': {
            'treasury_pct': round(100.0 * (ust['value'] / mort['value']), 1)
            if (ust and mort and mort['value']) else None,
            'spread_pct': round(100.0 * ((cur['value'] / 100.0) / mort['value']), 1)
            if (mort and mort['value']) else None,
        },
        'history': rows,
    }


# ---------------------------------------------------------------- MBS stack

COUPONS = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0]


def mbs_stack(con=None):
    """MODELED FNMA 30Y coupon stack derived from the current-coupon yield."""
    from .sources import tba_price, MBS_EFF_DURATION
    cc = store.latest('MBS_CC', con=con)
    cc_prev = store.prior('MBS_CC', con=con)
    ust10 = store.latest('UST10Y', con=con)
    ust5 = store.latest('UST5Y', con=con)
    if not cc:
        return None
    bench = None
    if ust10 and ust5:
        bench = 0.5 * ust5['value'] + 0.5 * ust10['value']

    prod = round(cc['value'] * 2) / 2.0
    rows = []
    for c in COUPONS:
        price = tba_price(cc['value'], c)
        prev = tba_price(cc_prev['value'], c) if cc_prev else None
        # a discount coupon extends, a premium coupon shortens
        dur = MBS_EFF_DURATION * (1.0 + 0.18 * (c - cc['value']))
        dur = max(1.2, min(7.5, dur))
        yld = c + (cc['value'] - c) * 0.55       # crude yield-to-price consistency
        rows.append({
            'coupon': c,
            'price': round(price, 3),
            'price_32': to_32nds(price),
            'ticks': round((price - prev) * 32, 1) if prev is not None else None,
            'yield': round(yld, 3),
            'duration': round(dur, 2),
            'spread_bp': round((yld - bench) * 100, 1) if bench is not None else None,
            'is_production': abs(c - prod) < 1e-6,
            'moneyness': 'DISCOUNT' if c < cc['value'] - 0.05 else
                         ('PREMIUM' if c > cc['value'] + 0.05 else 'AT MARKET'),
        })
    return {
        'current_coupon': cc['value'], 'production_coupon': prod,
        'obs_date': cc['obs_date'], 'quality': registry.MODELED,
        'benchmark_yield': round(bench, 3) if bench is not None else None,
        'rows': rows,
        'model': ('current coupon = PMMS 30Y less 50bp primary/secondary spread; '
                  'per-coupon yield and spread are modeled off that; '
                  'benchmark = 50/50 blend of the 5Y and 10Y Treasury'),
    }


def to_32nds(price):
    whole = int(price)
    frac = price - whole
    t = frac * 32.0
    return '%d-%02d' % (whole, int(round(t))) if t < 31.5 else '%d-00' % (whole + 1)


# ---------------------------------------------------------------- decomposition

def weekly_decomposition(con=None):
    """EXACT identity on real data: d(mortgage) = d(10Y) + d(spread).

    Both legs come from published series (PMMS and Treasury), so this carries no
    model risk. It is the anchor of the pressure meter.
    """
    m = store.history('MORT30Y', limit=2, con=con)
    if len(m) < 2:
        return None
    d_now, d_prev = m[-1]['obs_date'], m[-2]['obs_date']
    u_now = store.value_on_or_before('UST10Y', d_now, con=con)
    u_prev = store.value_on_or_before('UST10Y', d_prev, con=con)
    if not (u_now and u_prev):
        return None
    d_mort = (m[-1]['value'] - m[-2]['value']) * 100
    d_ust = (u_now['value'] - u_prev['value']) * 100
    d_spread = d_mort - d_ust
    return {
        'from_date': d_prev, 'to_date': d_now,
        'mortgage_bp': round(d_mort, 1),
        'treasury_bp': round(d_ust, 1),
        'spread_bp': round(d_spread, 1),
        'treasury_share': round(100.0 * abs(d_ust) / (abs(d_ust) + abs(d_spread)), 0)
        if (abs(d_ust) + abs(d_spread)) > 0.01 else None,
        'exact': True,
        'note': 'Arithmetic identity on published PMMS and Treasury data. No model.',
    }


def daily_move(con=None):
    """Daily Treasury move plus the MODELED mortgage read.

    The daily spread leg is UNOBSERVED without an MBS feed. Saying so is the point:
    it is exactly the information a paid MBS subscription buys.
    """
    u_now, u_prev, d_ust = change('UST10Y', 1, con=con)
    m = store.latest('MORT30Y_D', con=con)
    mp = store.prior('MORT30Y_D', con=con)
    ticks = store.latest('MBS_TICKS', con=con)
    return {
        'obs_date': m['obs_date'] if m else None,
        'ust10': u_now, 'ust10_prev': u_prev,
        'ust10_bp': round(d_ust * 100, 1) if d_ust is not None else None,
        'mortgage_est': m['value'] if m else None,
        'mortgage_est_bp': round((m['value'] - mp['value']) * 100, 1) if (m and mp) else None,
        'mbs_ticks': ticks['value'] if ticks else None,
        'spread_leg': 'UNOBSERVED',
        'note': ('Daily spread change cannot be observed without a live MBS feed. '
                 'The modeled daily mortgage rate moves with the 10Y at a 0.95 beta '
                 'and holds the last published spread constant.'),
    }


# ---------------------------------------------------------------- pressure meter

BANDS = [
    (-1e9, -12, 'STRONG DOWNWARD', 'Strong downward rate pressure'),
    (-12, -4, 'MODERATE DOWNWARD', 'Moderate downward rate pressure'),
    (-4, 4, 'NEUTRAL', 'Neutral'),
    (4, 12, 'MODERATE UPWARD', 'Moderate upward rate pressure'),
    (12, 1e9, 'STRONG UPWARD', 'Strong upward rate pressure'),
]


def band_for(bp):
    for lo, hi, code, label in BANDS:
        if lo <= bp < hi:
            return code, label
    return 'NEUTRAL', 'Neutral'


def pressure(con=None):
    """Ranked contributors in mortgage-rate-equivalent basis points.

    Deliberately NOT a single blended score. The observed legs are separated from
    the inferred ones, each carries its own confidence, and the net is shown
    alongside the components rather than instead of them.
    """
    contribs = []

    # --- observed leg 1: today's Treasury move, passed through at beta 0.95
    _, _, d_ust = change('UST10Y', 1, con=con)
    if d_ust is not None:
        bp = d_ust * 100 * 0.95
        contribs.append(_c('10Y Treasury', bp, 'OBSERVED', 'HIGH',
                           '10Y %s%.0f bp, passed through at a 0.95 beta'
                           % ('+' if d_ust >= 0 else '', d_ust * 100),
                           'UST10Y'))

    # --- observed leg 2: front-end repricing as a Fed-expectations proxy
    _, _, d_2y = change('UST2Y', 1, con=con)
    if d_2y is not None:
        bp = d_2y * 100 * 0.25
        contribs.append(_c('Fed expectations (2Y)', bp, 'OBSERVED', 'MEDIUM',
                           '2Y %s%.0f bp. The front end is the cleanest free read on '
                           'Fed repricing while futures probabilities are unavailable.'
                           % ('+' if d_2y >= 0 else '', d_2y * 100),
                           'UST2Y'))

    # --- observed leg 3: published spread move, week over week
    wk = weekly_decomposition(con=con)
    if wk and wk['spread_bp'] is not None:
        contribs.append(_c('Mortgage spread (w/w)', wk['spread_bp'], 'OBSERVED', 'HIGH',
                           'Published spread moved %s%.0f bp between PMMS prints'
                           % ('+' if wk['spread_bp'] >= 0 else '', wk['spread_bp']),
                           'MTG_UST_SPREAD'))

    # --- inferred legs: latest macro releases, scaled by impact and surprise
    weight = {'HIGH': 6.0, 'MEDIUM': 3.0, 'LOW': 1.0}
    for r in scored_releases(con=con):
        if r['surprise_z'] is None or abs(r['surprise_z']) < 0.4:
            continue
        # Monthly observations are stamped with the reference-period start, so July data
        # is already 60+ days old by early September even when it is the latest print.
        if (r['stale_days'] or 999) > STALE_RELEASE_DAYS:
            continue
        bp = r['surprise_z'] * r['direction'] * weight.get(r['impact'], 1.0)
        bp = max(-10.0, min(10.0, bp))   # a single stale monthly print cannot dominate
        contribs.append(_c(r['name'], bp, 'INFERRED',
                           'MEDIUM' if r['impact'] == 'HIGH' else 'LOW',
                           '%s %s vs %s (%.1f sigma). %s'
                           % (r['name'], _fmt(r['actual']), r['benchmark'],
                              r['surprise_z'], r['classification_label']),
                           r['series_id']))

    # --- inferred legs: both crude benchmarks, scored in SIGMA like every other
    # inferred driver. Scoring them in dollars made a 3-sigma crude shock rank
    # below a 1-sigma payroll surprise, which is nonsense.
    for sid, nm, w, why in (
            ('BRENT', 'Brent crude (global)', 5.0,
             'Brent %s$%.2f (%.1f sigma). The global benchmark, so it moves world inflation '
             'expectations and therefore demand for US duration. It also cuts the other way '
             'through recession risk, and the engine nets both channels.'),
            ('OIL', 'WTI crude (US)', 3.5,
             'WTI %s$%.2f (%.1f sigma). The US refinery input, so it drives the gasoline line '
             'in headline CPI within a few weeks.')):
        m = move_context(sid, 1, con=con)
        if not m or m.get('z') is None:
            continue
        bp = max(-10.0, min(10.0, m['z'] * w))
        contribs.append(_c(nm, bp, 'INFERRED',
                           'MEDIUM' if abs(m['z']) >= 1.5 else 'LOW',
                           why % ('+' if m['move_bp'] >= 0 else '', m['move_bp'], m['z'])
                           + ('  %s move: bigger than %.0f%% of history.'
                              % (m['verdict'].lower(), m['abs_percentile'])),
                           sid))

    # Observed legs rank above inferred ones. They are different kinds of evidence
    # and mixing them in one magnitude sort would imply they are interchangeable.
    contribs.sort(key=lambda c: (0 if c['basis'] == 'OBSERVED' else 1, -abs(c['bp'])))
    observed = [c for c in contribs if c['basis'] == 'OBSERVED']
    # The 2Y leg is a Fed-expectations READ, not an independent driver: its effect on
    # mortgages already runs through the 10Y. Summing both would double count it.
    net_obs = 0.0
    if d_ust is not None:
        net_obs += d_ust * 100 * 0.95
    if wk and wk['spread_bp'] is not None:
        net_obs += wk['spread_bp'] * 0.2           # weekly spread, damped to a daily view
    code, label = band_for(net_obs)

    return {
        'net_bp': round(net_obs, 1), 'band': code, 'band_label': label,
        'contributors': contribs[:8],
        'observed_count': len(observed),
        'inferred_count': len(contribs) - len(observed),
        'method': ('Observed legs come from published Treasury and PMMS data. Inferred legs '
                   'are macro releases scaled by impact and surprise size. The net uses the '
                   'observed legs only; inferred legs are shown for direction, not summed in.'),
    }


def _c(name, bp, basis, conf, detail, series_id):
    return {'name': name, 'bp': round(bp, 1),
            'direction': 'UP' if bp > 0.5 else ('DOWN' if bp < -0.5 else 'FLAT'),
            'arrow': '↑' if bp > 0.5 else ('↓' if bp < -0.5 else '→'),
            'pressure_label': 'pushes rates up' if bp > 0.5 else
                              ('pushes rates down' if bp < -0.5 else 'neutral'),
            'basis': basis, 'confidence': conf, 'detail': detail, 'series_id': series_id}


def _fmt(v):
    if v is None:
        return 'n/a'
    return ('%.2f' % v).rstrip('0').rstrip('.')


# ---------------------------------------------------------------- fed stance

def fed_stance(con=None):
    """Stance read off the front end and inflation, since futures data is unavailable."""
    cur2 = store.latest('UST2Y', con=con)
    _, _, d2_30 = change_over_days('UST2Y', 30, con=con)
    core = store.latest('CORECPI_YOY', con=con)
    unrate = store.latest('UNRATE', con=con)
    ff_hi = store.latest('FED_TARGET_HIGH', con=con)

    score = 0.0
    parts = []
    if cur2 and ff_hi:
        gap = cur2['value'] - (ff_hi['value'] - 0.125)
        score += gap * 2.0
        parts.append('2Y sits %+.2f pp vs the midpoint of the target range' % gap)
    if d2_30 is not None:
        score += d2_30 * 3.0
        parts.append('2Y %+.0f bp over 30 days' % (d2_30 * 100))
    if core:
        score += (core['value'] - 2.0) * 0.8
        parts.append('core CPI %.2f%% y/y vs the 2%% target' % core['value'])
    if unrate:
        score -= (unrate['value'] - 4.0) * 1.2
        parts.append('unemployment %.1f%%' % unrate['value'])

    if score <= -1.5:
        stance, rate_impact = 'VERY DOVISH', 'BULLISH'
    elif score <= -0.5:
        stance, rate_impact = 'DOVISH', 'BULLISH'
    elif score < 0.5:
        stance, rate_impact = 'NEUTRAL', 'NEUTRAL'
    elif score < 1.5:
        stance, rate_impact = 'HAWKISH', 'BEARISH'
    else:
        stance, rate_impact = 'VERY HAWKISH', 'BEARISH'

    return {
        'stance': stance, 'score': round(score, 2),
        'rate_impact': rate_impact,
        'rate_impact_label': {'BULLISH': 'Bullish for mortgage rates (pressure down)',
                              'NEUTRAL': 'Neutral for mortgage rates',
                              'BEARISH': 'Bearish for mortgage rates (pressure up)'}[rate_impact],
        'inputs': parts,
        'probabilities': None,
        'probabilities_status': registry.DERIVED,
        'probabilities_note': ('Market-implied Fed path, read from the curve instead of the '
                               'licensed CME futures feed: the gap between the 1-year Treasury '
                               'and the current target midpoint. Positive = easing priced, '
                               'negative = tightening priced. A real signal, not an option-implied '
                               'probability.'),
        'transmission': ['Fed policy', 'growth and inflation expectations',
                         'Treasury yields', 'MBS yields', 'mortgage rates'],
        'caveat': 'The Fed does not set mortgage rates. It moves the front end; '
                  'mortgage rates follow the 10Y and the MBS spread.',
    }


# ---------------------------------------------------------------- risk regime

def risk_regime(con=None):
    signals, score = [], 0.0
    _, _, d_spx = change('SPX', 1, con=con)
    _, _, d_vix = change('VIX', 1, con=con)
    _, _, d_hy = change('HY_SPREAD', 1, con=con)
    if d_spx is not None:
        score += 1 if d_spx > 0 else -1
        signals.append('S&P %+.2f' % d_spx)
    if d_vix is not None:
        score += -1 if d_vix > 0 else 1
        signals.append('VIX %+.2f' % d_vix)
    if d_hy is not None:
        score += -1 if d_hy > 0 else 1
        signals.append('HY OAS %+.0f bp' % d_hy)
    if not signals:
        return {'regime': registry.UNAVAILABLE, 'signals': [],
                'note': 'Requires a FRED key for VIX, credit spreads and equities.',
                'rate_impact': None}
    regime = 'RISK-ON' if score > 0.5 else ('RISK-OFF' if score < -0.5 else 'NEUTRAL')
    return {
        'regime': regime, 'signals': signals, 'score': score,
        'rate_impact': {'RISK-ON': 'Bearish for mortgage rates. Money leaves bonds.',
                        'RISK-OFF': 'Bullish for mortgage rates, but only if the MBS spread '
                                    'holds. Stress usually widens spreads and eats the rally.',
                        'NEUTRAL': 'Neutral'}[regime],
    }


# ---------------------------------------------------------------- move significance
#
# Spec question 7: "How significant is today's move compared with historical moves?"
# This exists because an LO's felt sense of a big move is calibrated to their own
# tenure, which is usually a few weeks or months. The job here is to say plainly
# whether a move is large in history or only large in the window you have watched.

def _changes(sid, step=1, con=None):
    """[(date, change_in_bp)] over `step` observations.

    Series carrying `percent` are scaled to bp; series already stored in bp
    (the spread, the curve slopes) are not, or a 7 bp move prints as 700.
    """
    rows = store.history(sid, con=con)
    meta = registry.get(sid) or {}
    scale = 100.0 if meta.get('unit') == 'percent' else 1.0
    return [(rows[i]['obs_date'], (rows[i]['value'] - rows[i - step]['value']) * scale)
            for i in range(step, len(rows))]


def move_context(sid, step=1, con=None, tenure_start=None, label=None):
    ch = _changes(sid, step, con=con)
    if len(ch) < 30:
        return None
    date, cur = ch[-1]
    # A gap across a holiday weekend packs several days of news into one observation.
    # Scoring that against a distribution of single-day moves overstates the z.
    gap_days = None
    try:
        rows = store.history(sid, limit=step + 1, con=con)
        d0 = datetime.date(*[int(x) for x in rows[0]['obs_date'].split('-')])
        d1 = datetime.date(*[int(x) for x in rows[-1]['obs_date'].split('-')])
        gap_days = (d1 - d0).days
    except Exception:
        pass
    vals = [v for _, v in ch]
    absv = [abs(v) for v in vals]
    sd = _stdev(vals)

    bigger = sorted((c for c in ch if abs(c[1]) >= abs(cur)), key=lambda c: -abs(c[1]))
    up, down = max(ch, key=lambda c: c[1]), min(ch, key=lambda c: c[1])

    meta = registry.get(sid) or {}
    unit = meta.get('unit')
    # Crude is in dollars, the spread is in bp, payrolls in thousands. Printing them
    # all as "bp" was wrong and made a $6 oil move read as 6 basis points.
    disp = {'usd': ('$', ''), 'usd_mm': ('$', 'mm'), 'thousands': ('', 'k'),
            'index': ('', ' pts')}.get(unit, ('', ' bp'))

    out = {
        'series_id': sid, 'label': label or meta.get('name', sid),
        'unit': unit, 'unit_prefix': disp[0], 'unit_suffix': disp[1],
        'step': step, 'obs_date': date,
        'move_bp': round(cur, 1),
        'direction': 'UP' if cur > 0 else ('DOWN' if cur < 0 else 'FLAT'),
        'z': round(cur / sd, 2) if sd else None,
        'abs_percentile': round(100.0 * sum(1 for a in absv if a < abs(cur)) / len(absv), 1),
        'signed_percentile': round(100.0 * sum(1 for v in vals if v < cur) / len(vals), 1),
        'mean_abs_move': round(_mean(absv), 1),
        'stdev': round(sd, 1) if sd else None,
        'n': len(ch),
        'history_from': ch[0][0],
        'rank_by_magnitude': len(bigger),
        'gap_days': gap_days,
        # Only flag a gap that is unusual FOR THIS SERIES. A weekly survey spanning
        # seven days is not a holiday gap, it is Thursday.
        'gap_note': ('This observation spans %d calendar days, not one session, so it carries '
                     'more news than a normal daily move and the sigma above overstates it.'
                     % gap_days) if (gap_days and step == 1 and gap_days > 3
                                     and meta.get('refresh') == 'daily') else None,
        'largest_up': {'bp': round(up[1], 1), 'date': up[0]},
        'largest_down': {'bp': round(down[1], 1), 'date': down[0]},
    }

    if tenure_start:
        ten = [c for c in ch if c[0] >= tenure_start]
        if ten:
            tv = [v for _, v in ten]
            biggest_up = max(ten, key=lambda c: c[1])
            biggest_abs = max(ten, key=lambda c: abs(c[1]))
            out['tenure'] = {
                'start': tenure_start, 'n': len(ten),
                'largest_up_bp': round(biggest_up[1], 1), 'largest_up_date': biggest_up[0],
                'largest_abs_bp': round(biggest_abs[1], 1), 'largest_abs_date': biggest_abs[0],
                'is_largest_up_in_tenure': abs(cur - biggest_up[1]) < 1e-6,
                'is_largest_abs_in_tenure': abs(cur - biggest_abs[1]) < 1e-6,
                'mean_abs_move': round(_mean([abs(v) for v in tv]), 1),
            }
    out['verdict'], out['verdict_detail'] = _verdict(out)
    return out


def _fmt_move(m, v):
    return '%s%s%s' % (m.get('unit_prefix', ''),
                       ('%+.2f' if m.get('unit_prefix') == '$' else '%+.0f') % v,
                       m.get('unit_suffix', ' bp'))


def _fmt_mag(m, v):
    return '%s%s%s' % (m.get('unit_prefix', ''),
                       ('%.2f' if m.get('unit_prefix') == '$' else '%.1f') % v,
                       m.get('unit_suffix', ' bp'))


def _verdict(m):
    """Plain-language significance, with the tenure trap called out explicitly."""
    p = m['abs_percentile']
    if p >= 95:
        band = 'EXTREME'
    elif p >= 85:
        band = 'LARGE'
    elif p >= 60:
        band = 'ABOVE AVERAGE'
    elif p >= 30:
        band = 'ORDINARY'
    else:
        band = 'QUIET'

    detail = ('%s. Bigger in magnitude than %.0f%% of the %d moves since %s. '
              'The typical move is %s; this is %.1f sigma.'
              % (_fmt_move(m, m['move_bp']), p, m['n'], m['history_from'],
                 _fmt_mag(m, m['mean_abs_move']), abs(m['z'] or 0)))

    if m.get('gap_note'):
        detail += ' ' + m['gap_note']
    t = m.get('tenure')
    if t:
        if t['is_largest_abs_in_tenure'] and p < 70:
            detail += (' It is the largest move you have seen since %s, but your window is '
                       'only %d observations. That says more about how new you are than '
                       'about the market.' % (t['start'], t['n']))
        elif t['is_largest_abs_in_tenure']:
            detail += (' It is also the largest move since %s, and it is genuinely large '
                       'by historical standards.' % t['start'])
        else:
            detail += (' Not even the largest in your own window: %s on %s was bigger.'
                       % (_fmt_move(m, t['largest_abs_bp']), t['largest_abs_date']))
    return band, detail


def move_significance(con=None, tenure_start=None):
    """Multi-horizon significance for the two series that actually drive rate sheets."""
    from .sources import config
    tenure_start = tenure_start or config().get('tenure_start')
    out = []
    for sid, step, label in (
            ('MORT30Y', 1, '30Y mortgage rate, week over week (published survey)'),
            ('UST10Y', 1, '10Y Treasury, day over day'),
            ('UST10Y', 6, '10Y Treasury, over 6 sessions'),
            ('MTG_UST_SPREAD', 1, 'Mortgage spread, week over week'),
            ('BRENT', 1, 'Brent crude, session over session'),
            ('OIL', 1, 'WTI crude, session over session')):
        m = move_context(sid, step, con=con, tenure_start=tenure_start, label=label)
        if m:
            out.append(m)
    return {
        'moves': out, 'tenure_start': tenure_start,
        'note': ('A rate sheet moves in price, not rate, and it moves same-day. The PMMS '
                 'survey below is a Thursday-to-Wednesday average published weekly, so it '
                 'will always look calmer than what landed in your inbox this morning. '
                 'Compare the Treasury rows to judge whether the market actually moved.'),
    }


# ---------------------------------------------------------------- meter bullets

def _prov(sid, con=None):
    """Source name and observation date for a series, for inline attribution."""
    meta = registry.get(sid) or {}
    cur = store.latest(sid, con=con)
    src = registry.SOURCE_META.get(meta.get('source_id'), {})
    return {
        'series_id': sid,
        'source': src.get('name', meta.get('source_id', '?')),
        'obs_date': cur['obs_date'] if cur else None,
        'quality': cur['quality'] if cur else registry.UNAVAILABLE,
        'url': src.get('url'),
    }


def pressure_bullets(con=None):
    """Plain-language reads sitting under the meter, each stamped with where it
    came from and when. Written to be scannable in about ten seconds."""
    out = []

    def add(text, sid, direction='FLAT'):
        p = _prov(sid, con=con)
        if not p['obs_date']:
            return
        p.update({'text': text, 'direction': direction,
                  'arrow': '▲' if direction == 'UP' else '▼' if direction == 'DOWN' else '►'})
        out.append(p)

    # the 10Y, which is the primary input to every mortgage rate
    cur, _, d1 = change('UST10Y', 1, con=con)
    if cur is not None:
        bp = (d1 or 0) * 100
        add('10-year Treasury at %.2f%%, %s on the day. This is the single biggest '
            'input to your rate.' % (cur, _signed_bp(bp)),
            'UST10Y', 'UP' if bp > 0.5 else 'DOWN' if bp < -0.5 else 'FLAT')

    # the published mortgage rate
    m = store.latest('MORT30Y', con=con)
    mp = store.prior('MORT30Y', con=con)
    if m and mp:
        bp = (m['value'] - mp['value']) * 100
        add('Published 30-year survey at %.2f%%, %s week over week. It is a weekly '
            'average and always lags your rate sheet.' % (m['value'], _signed_bp(bp)),
            'MORT30Y', 'UP' if bp > 0.5 else 'DOWN' if bp < -0.5 else 'FLAT')

    # the spread, which is the half of the rate Treasuries do not explain
    s = spread_state(con=con)
    if s:
        add('Mortgage spread %.0f bp, %s at the %.0fth percentile of %d years. That is '
            '%.2f points of the %.2f%% rate coming from spread, not from Treasuries.'
            % (s['spread_bp'], s['band'].lower(), s['percentile'] or 0, s['years'],
               s['spread_bp'] / 100.0, s['mortgage_rate'] or 0),
            'MTG_UST_SPREAD',
            'UP' if (s['excess_vs_avg_bp'] or 0) > 5 else
            'DOWN' if (s['excess_vs_avg_bp'] or 0) < -5 else 'FLAT')

    # anything that just moved abnormally
    for sid in ('BRENT', 'OIL', 'UST10Y', 'MORT30Y'):
        mv = move_context(sid, 1, con=con)
        if not mv or mv['abs_percentile'] < 90:
            continue
        meta = registry.get(sid) or {}
        add('%s %s, bigger than %.0f%% of moves on record. %s'
            % (meta.get('name', sid).split('(')[0].strip(),
               _fmt_move(mv, mv['move_bp']), mv['abs_percentile'],
               'Watch whether the bond market trades this as inflation or as demand.'
               if sid in ('BRENT', 'OIL') else 'Expect rate sheets to follow.'),
            sid, 'UP' if mv['move_bp'] > 0 else 'DOWN')
        break

    # the freshest inflation print, since it is the Fed's reaction function
    for sid, lbl in (('CORECPI_MOM', 'Core CPI'), ('CPI_YOY', 'Headline CPI')):
        r = store.latest(sid, con=con)
        if r:
            add('%s %+.2f%% (%s reference month), the newest inflation read the market has.'
                % (lbl, r['value'], r['obs_date'][:7]), sid,
                'UP' if r['value'] > 0.25 else 'FLAT')
            break

    return out


def _signed_bp(bp):
    if abs(bp) < 0.5:
        return 'flat'
    return '%+.0f bp' % bp


def meter_provenance(con=None):
    """One line naming every source behind the meter and how fresh each one is."""
    seen, rows = set(), []
    for sid in ('UST10Y', 'MORT30Y', 'BRENT', 'CORECPI'):
        p = _prov(sid, con=con)
        if p['obs_date'] and p['source'] not in seen:
            seen.add(p['source'])
            rows.append(p)
    return {'sources': rows, 'generated_at': store.utcnow()}
