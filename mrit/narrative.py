"""Narrative generation: why rates moved, morning brief, EOD review, audience registers.

Every generated sentence is assembled from measured values and traced causal paths.
Nothing is asserted that the data does not support, and every explanation carries a
confidence level.
"""

import datetime

from . import analytics, causal, registry, store


def _sign(v, unit='bp', dp=0):
    if v is None:
        return 'n/a'
    fmt = '%+.' + str(dp) + 'f'
    return (fmt % v) + (' ' + unit if unit else '')


def _dir_word(bp, up='higher', down='lower', flat='unchanged'):
    if bp is None:
        return flat
    if bp > 0.5:
        return up
    if bp < -0.5:
        return down
    return flat


# ---------------------------------------------------------------- why rates moved

def why(con=None):
    """Primary driver, secondary driver, counterforce, and a confidence level."""
    press = analytics.pressure(con=con)
    daily = analytics.daily_move(con=con)
    weekly = analytics.weekly_decomposition(con=con)
    spread = analytics.spread_state(con=con)

    shocks = {}
    for r in analytics.scored_releases(con=con):
        if r['surprise_z'] is None or (r['stale_days'] or 999) > analytics.STALE_RELEASE_DAYS:
            continue
        node = _release_node(r['id'])
        if node:
            shocks[node] = r['surprise_z']
    for sid in ('OIL', 'BRENT'):
        _, _, d_oil = analytics.change(sid, 1, con=con)
        if d_oil:
            shocks[sid] = d_oil / 3.0

    prop = causal.propagate(shocks, con=con)
    conf, conf_reason = causal.confidence_for(prop)

    contribs = press['contributors']
    up = [c for c in contribs if c['bp'] > 0.5]
    down = [c for c in contribs if c['bp'] < -0.5]
    primary = contribs[0] if contribs else None
    secondary = contribs[1] if len(contribs) > 1 else None

    counterforce = None
    if primary:
        opposing = [c for c in contribs[1:] if (c['bp'] > 0) != (primary['bp'] > 0)]
        counterforce = opposing[0] if opposing else None

    net = press['net_bp']
    lines = []
    if daily.get('ust10_bp') is not None:
        lines.append(
            'The 10-year Treasury is at %.2f%%, %s on the day. Mortgage rates take their '
            'direction from the 10-year first.'
            % (daily['ust10'], _sign(daily['ust10_bp'], 'bp')))
    if weekly:
        lines.append(
            'Between the last two published mortgage surveys the 30-year moved %s. That '
            'breaks down exactly: %s from Treasuries and %s from the mortgage spread.'
            % (_sign(weekly['mortgage_bp'], 'bp'), _sign(weekly['treasury_bp'], 'bp'),
               _sign(weekly['spread_bp'], 'bp')))
    if spread:
        lines.append(
            'The mortgage/10-year spread is %.0f bp, which is %s and sits at the %.0fth '
            'percentile of the last %d years. The long-run average is %.0f bp, so roughly '
            '%.0f bp of the current mortgage rate is spread rather than Treasury yield.'
            % (spread['spread_bp'], spread['band'].lower(), spread['percentile'] or 0,
               spread['years'], spread['avg_bp'] or 0, spread['excess_vs_avg_bp'] or 0))
    if daily.get('spread_leg') == 'UNOBSERVED':
        lines.append(
            'Intraday spread movement is not observable here. Without a live MBS feed the '
            'daily read assumes the spread held and moves the rate with the 10-year only.')

    return {
        'headline': _headline(net, daily, weekly),
        'summary': ' '.join(lines),
        'primary': primary, 'secondary': secondary, 'counterforce': counterforce,
        'upward_drivers': up, 'downward_drivers': down,
        'net_bp': net, 'band': press['band'], 'band_label': press['band_label'],
        'confidence': conf, 'confidence_reason': conf_reason,
        'causal': prop,
        'method': press['method'],
        'generated_at': store.utcnow(),
    }


def _headline(net_bp, daily, weekly):
    d = _dir_word(net_bp, 'under upward pressure', 'improving', 'roughly flat')
    if daily.get('ust10') is None:
        return 'Rate pressure is %s.' % d
    return ('Mortgage rates are %s. The 10-year Treasury is %.2f%% (%s on the day) and the '
            'modeled 30-year sits near %.2f%%.'
            % (d, daily['ust10'], _sign(daily.get('ust10_bp'), 'bp'),
               daily.get('mortgage_est') or 0))


_RELEASE_NODE = {
    'CORECPI': 'CORE_CPI', 'CPI': 'HEADLINE_CPI', 'PPI': 'PPI', 'PCE': 'CORE_CPI',
    'NFP': 'NFP', 'UNRATE': 'UNRATE', 'AHE': 'AHE', 'CLAIMS': 'CLAIMS', 'JOLTS': 'JOLTS',
    'RETAIL': 'RETAIL', 'GDP': 'GROWTH',
}


def _release_node(rid):
    return _RELEASE_NODE.get(rid)


# ---------------------------------------------------------------- morning brief

def morning_brief(con=None):
    """Max 150 words. Hard-truncated, not aspirationally short."""
    mort = store.latest('MORT30Y', con=con)
    mort_d = store.latest('MORT30Y_D', con=con)
    ust = store.latest('UST10Y', con=con)
    _, _, d_ust = analytics.change('UST10Y', 1, con=con)
    ticks = store.latest('MBS_TICKS', con=con)
    press = analytics.pressure(con=con)
    spread = analytics.spread_state(con=con)
    upcoming = calendar_ahead(con=con, days=7)

    bias = _dir_word(press['net_bp'], 'Worsening', 'Improving', 'Flat')
    risk = _biggest_risk(upcoming, spread)

    body = (
        'Mortgage rates: %s%% published %s, modeled %s%% today. '
        '10-year Treasury: %.2f%% (%s). MBS: %s ticks. Rate bias: %s. '
        'The mortgage spread is %.0f bp, %s versus its %.0f bp long-run average. '
        'Ahead: %s. Biggest risk: %s. '
        'What LOs should know: %s'
        % (
            _fmt(mort['value']) if mort else 'n/a',
            mort['obs_date'] if mort else 'n/a',
            _fmt(mort_d['value']) if mort_d else 'n/a',
            ust['value'] if ust else 0,
            _sign(d_ust * 100 if d_ust is not None else None, 'bp'),
            _fmt(ticks['value']) if ticks else 'n/a',
            bias,
            spread['spread_bp'] if spread else 0,
            (spread['band'].lower() if spread else 'n/a'),
            (spread['avg_bp'] or 0) if spread else 0,
            _events_phrase(upcoming),
            risk,
            _lo_takeaway(press, spread),
        )
    )
    words = body.split()
    truncated = len(words) > 150
    if truncated:
        body = ' '.join(words[:150]).rstrip(',.') + '.'
    return {
        'title': 'MORTGAGE MARKET MORNING BRIEF',
        'date': datetime.date.today().isoformat(),
        'body': body, 'word_count': min(len(words), 150), 'truncated': truncated,
        'bias': bias,
        'generated_at': store.utcnow(),
    }


def _fmt(v):
    return ('%.2f' % v) if v is not None else 'n/a'


def _events_phrase(events):
    if not events:
        return 'no high-impact releases scheduled in the next week'
    hi = [e for e in events if e['impact'] == 'HIGH'][:2]
    src = hi or events[:2]
    return ', '.join('%s on %s' % (e['name'], e['date'][5:]) for e in src)


def _biggest_risk(events, spread):
    hi = [e for e in events if e['impact'] == 'HIGH']
    if hi:
        return '%s. A hot print reverses any Treasury rally' % hi[0]['name']
    if spread and spread['band'] in ('WIDE', 'EXTREMELY WIDE'):
        return ('the spread is %s, so a Treasury rally may not reach borrowers'
                % spread['band'].lower())
    return 'no single dominant catalyst'


def _lo_takeaway(press, spread):
    if press['band'] in ('STRONG DOWNWARD', 'MODERATE DOWNWARD'):
        return ('pull your float list and re-price. Improvements reach rate sheets with a '
                'one to two day lag')
    if press['band'] in ('STRONG UPWARD', 'MODERATE UPWARD'):
        return 'protect anything closing inside 30 days and expect reprice risk intraday'
    if spread and spread['band'] in ('WIDE', 'EXTREMELY WIDE'):
        return ('quote the spread, not the Fed. A wide spread is why borrower rates are not '
                'following Treasuries down')
    return 'no action. Rates are inside the daily noise band'


# ---------------------------------------------------------------- EOD review

def eod_review(con=None):
    daily = analytics.daily_move(con=con)
    weekly = analytics.weekly_decomposition(con=con)
    spread = analytics.spread_state(con=con)
    w = why(con=con)
    ahead = calendar_ahead(con=con, days=3)

    reprice = 'UNOBSERVABLE'
    if daily.get('mbs_ticks') is not None:
        t = daily['mbs_ticks']
        if t <= -20:
            reprice = 'LIKELY WORSE (modeled MBS off %s ticks)' % _fmt(t)
        elif t >= 20:
            reprice = 'LIKELY BETTER (modeled MBS up %s ticks)' % _fmt(t)
        else:
            reprice = 'UNLIKELY (modeled MBS move inside 20 ticks)'

    return {
        'title': 'END OF DAY REVIEW',
        'date': datetime.date.today().isoformat(),
        'what_moved': w['headline'],
        'why': w['summary'],
        'treasury_move_bp': daily.get('ust10_bp'),
        'mbs_move_ticks': daily.get('mbs_ticks'),
        'spread_direction': ('widened' if weekly and weekly['spread_bp'] > 0
                             else ('tightened' if weekly and weekly['spread_bp'] < 0
                                   else 'unchanged')) if weekly else 'unknown',
        'spread_bp': spread['spread_bp'] if spread else None,
        'spread_band': spread['band'] if spread else None,
        'lender_reprice': reprice,
        'reprice_caveat': ('Real reprice detection needs a live MBS feed. This is inferred '
                           'from the modeled tick move.'),
        'expectations_change': _expectations_change(con=con),
        'tomorrow': [e['name'] + ' (' + e['impact'] + ')' for e in ahead] or
                    ['No scheduled rate-relevant releases'],
        'confidence': w['confidence'],
        'generated_at': store.utcnow(),
    }


def _expectations_change(con=None):
    _, _, d2 = analytics.change('UST2Y', 1, con=con)
    if d2 is None:
        return 'Front-end data unavailable.'
    bp = d2 * 100
    if abs(bp) < 2:
        return 'The 2-year barely moved, so Fed expectations are unchanged.'
    return ('The 2-year moved %s, which means the market %s its expected path for Fed policy.'
            % (_sign(bp, 'bp'), 'firmed' if bp > 0 else 'softened'))


# ---------------------------------------------------------------- calendar

FOMC_2026 = ['2026-01-28', '2026-03-18', '2026-04-29', '2026-06-17',
             '2026-07-29', '2026-09-16', '2026-11-04', '2026-12-16']


def calendar_ahead(con=None, days=14):
    """Projected release calendar. BLS and Census publish on a stable monthly rhythm,
    so dates are derived from that rhythm and flagged PROJECTED, not scraped."""
    today = datetime.date.today()
    out = []
    for d in FOMC_2026:
        dt = datetime.date(*[int(x) for x in d.split('-')])
        if today <= dt <= today + datetime.timedelta(days=days):
            out.append({'date': d, 'time': '14:00 ET', 'name': 'FOMC Rate Decision',
                        'impact': 'HIGH', 'tier': 2, 'scheduled': 'CONFIRMED',
                        'days_out': (dt - today).days,
                        'why': 'The statement and any dot plot revision move the 2Y, which '
                               'pulls the 10Y and then mortgage rates.'})
    for rel, rule in _MONTHLY_RULES.items():
        for dt in _next_occurrences(rule, today, days):
            r = registry.RELEASE_BY_ID.get(rel)
            if not r:
                continue
            out.append({'date': dt.isoformat(), 'time': r['typical_time'] + ' ET',
                        'name': r['name'], 'impact': r['impact'], 'tier': r['tier'],
                        'scheduled': 'PROJECTED', 'days_out': (dt - today).days,
                        'why': r['notes'] or _default_why(r)})
    out.sort(key=lambda e: (e['date'], e['time']))
    return out


def _default_why(r):
    d = 'up' if r['direction'] > 0 else 'down'
    return 'A hotter than expected print pushes mortgage rates %s.' % d


# (weekday-of-month rule) 0=Mon. ('nth_weekday', n, weekday) or ('day', day_of_month)
_MONTHLY_RULES = {
    'NFP': ('nth_weekday', 1, 4),        # first Friday
    'UNRATE': ('nth_weekday', 1, 4),
    'AHE': ('nth_weekday', 1, 4),
    'CPI': ('day', 12), 'CORECPI': ('day', 12),
    'PPI': ('day', 15),
    'PCE': ('day', 28),
    'RETAIL': ('day', 16),
    'JOLTS': ('day', 9),
    'CLAIMS': ('weekly', 3),             # every Thursday
    'EHS': ('day', 22), 'NHS': ('day', 25), 'STARTS': ('day', 18),
}


def _next_occurrences(rule, today, days):
    end = today + datetime.timedelta(days=days)
    out = []
    kind = rule[0]
    if kind == 'weekly':
        d = today
        while d <= end:
            if d.weekday() == rule[1]:
                out.append(d)
            d += datetime.timedelta(days=1)
        return out
    for month_offset in (0, 1, 2):
        y, m = today.year, today.month + month_offset
        while m > 12:
            m -= 12
            y += 1
        if kind == 'day':
            try:
                d = datetime.date(y, m, rule[1])
            except ValueError:
                continue
        else:
            n, wd = rule[1], rule[2]
            d = datetime.date(y, m, 1)
            count = 0
            while True:
                if d.weekday() == wd:
                    count += 1
                    if count == n:
                        break
                d += datetime.timedelta(days=1)
                if d.month != m:
                    break
        if today <= d <= end:
            out.append(d)
    return out


# ---------------------------------------------------------------- audience registers

def translate(audience, con=None):
    """Same facts, four registers. Borrower language avoids jargon entirely."""
    w = why(con=con)
    daily = analytics.daily_move(con=con)
    spread = analytics.spread_state(con=con)
    mort = store.latest('MORT30Y', con=con)
    press_dir = _dir_word(w['net_bp'], 'higher', 'lower', 'about flat')

    if audience == 'BORROWER':
        text = _borrower(w, daily, spread, mort, press_dir)
    elif audience == 'REALTOR':
        text = _realtor(w, daily, spread, mort, press_dir)
    elif audience == 'LO':
        text = _lo(w, daily, spread, mort)
    else:
        text = _exec(w, daily, spread, mort)
    return {'audience': audience, 'text': text, 'confidence': w['confidence'],
            'generated_at': store.utcnow(),
            'disclaimer': ('Draft for the licensed loan officer to review. Not a rate quote, '
                           'not a lock recommendation, and not to be sent to a borrower '
                           'without review.')}


def _borrower(w, daily, spread, mort, d):
    bits = ['Here is where the market stands today.']
    if daily.get('ust10') is not None:
        bits.append(
            'Mortgage rates are %s. Home loan rates follow the bond market, and the main '
            'bond that matters is the 10-year Treasury. It is at %.2f percent today, %s '
            'than yesterday.'
            % (d, daily['ust10'],
               'higher' if (daily.get('ust10_bp') or 0) > 0 else 'lower'))
    if spread and spread['band'] in ('WIDE', 'EXTREMELY WIDE'):
        bits.append(
            'One thing worth knowing: there is currently an unusually large gap between '
            'government bond rates and mortgage rates. That gap is about %.0f percent of a '
            'point wider than normal. It means mortgage rates have room to improve if the '
            'market calms down, even without anything changing at the Federal Reserve.'
            % ((spread['excess_vs_avg_bp'] or 0) / 100.0))
    bits.append('Nothing here is a quote. When you are ready I will price your specific '
                'scenario, because your rate depends on your credit, your down payment and '
                'the property, not just the market.')
    return ' '.join(bits)


def _realtor(w, daily, spread, mort, d):
    bits = []
    if mort:
        bits.append('Quick market read: the published 30-year average is %.2f%% as of %s and '
                    'the trend today is %s.' % (mort['value'], mort['obs_date'], d))
    if daily.get('ust10_bp') is not None:
        bits.append('The 10-year Treasury moved %s today, and mortgage pricing follows it '
                    'with about a one day lag.' % _sign(daily['ust10_bp'], 'bp'))
    if spread and spread['band'] in ('WIDE', 'EXTREMELY WIDE'):
        bits.append('The mortgage spread is %s at %.0f bp against a %.0f bp average. For your '
                    'buyers that is roughly %.2f%% of extra rate that is not the Fed and not '
                    'the economy, just risk pricing in the mortgage bond market.'
                    % (spread['band'].lower(), spread['spread_bp'], spread['avg_bp'] or 0,
                       (spread['excess_vs_avg_bp'] or 0) / 100.0))
    bits.append('Happy to run payment scenarios on any active listing or buyer.')
    return ' '.join(bits)


def _lo(w, daily, spread, mort):
    parts = [w['headline'], w['summary']]
    if w['primary']:
        parts.append('Primary driver: %s (%s bp, %s, %s confidence). %s'
                     % (w['primary']['name'], _fmt(w['primary']['bp']),
                        w['primary']['pressure_label'], w['primary']['confidence'],
                        w['primary']['detail']))
    if w['counterforce']:
        parts.append('Counterforce: %s (%s bp). %s'
                     % (w['counterforce']['name'], _fmt(w['counterforce']['bp']),
                        w['counterforce']['detail']))
    parts.append('Overall confidence: %s. %s' % (w['confidence'], w['confidence_reason']))
    return ' '.join(parts)


def _exec(w, daily, spread, mort):
    return ('%s Net rate pressure reads %s. Spread is %s at the %sth percentile. '
            'Confidence %s.'
            % (w['headline'], w['band_label'].lower(),
               spread['band'].lower() if spread else 'n/a',
               int(spread['percentile']) if spread and spread['percentile'] else '?',
               w['confidence']))
