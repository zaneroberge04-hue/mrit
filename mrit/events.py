"""Economic event markers for the chart timeline.

Honesty rule carried through from the rest of the terminal: a marker's DATE may be
projected from the agency's published monthly rhythm, but the rate move measured
around it is real, read off actual observations. Each marker says which it is.
"""

import datetime

from . import analytics, registry, store

# Confirmed FOMC decision dates. 2026 is the published schedule; earlier years are
# left to manual entry rather than recited from memory, because a wrong marker date
# silently corrupts every before/after move computed against it.
FOMC_DATES = [
    '2026-01-28', '2026-03-18', '2026-04-29', '2026-06-17',
    '2026-07-29', '2026-09-16', '2026-11-04', '2026-12-16',
]

# (rule, label, series behind it, impact). Rules mirror narrative._MONTHLY_RULES.
EVENT_KINDS = {
    'CPI': (('day', 12), 'CPI', 'CPI_YOY', 'HIGH'),
    'CORECPI': (('day', 12), 'Core CPI', 'CORECPI_MOM', 'HIGH'),
    'PCE': (('day', 28), 'Core PCE', 'PCE_CORE_YOY', 'HIGH'),
    'NFP': (('nth_weekday', 1, 4), 'Jobs Report', 'NFP', 'HIGH'),
    'FOMC': (('fixed',), 'FOMC', 'FED_TARGET_HIGH', 'HIGH'),
    'GDP': (('day', 27), 'GDP', 'GDP', 'MEDIUM'),
    'RETAIL': (('day', 16), 'Retail Sales', 'RETAIL', 'MEDIUM'),
    'PPI': (('day', 15), 'PPI', 'PPI', 'MEDIUM'),
}

KIND_ORDER = ['CPI', 'CORECPI', 'PCE', 'NFP', 'FOMC', 'GDP', 'RETAIL', 'PPI']


def _iter_months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _rule_dates(rule, start, end):
    """Expand a monthly rhythm rule into concrete dates in [start, end]."""
    if rule[0] == 'fixed':
        out = []
        for d in FOMC_DATES:
            dt = datetime.date(*[int(x) for x in d.split('-')])
            if start <= dt <= end:
                out.append(dt)
        return out

    out = []
    for y, m in _iter_months(start, end):
        if rule[0] == 'day':
            try:
                d = datetime.date(y, m, rule[1])
            except ValueError:
                continue
        else:                                   # ('nth_weekday', n, weekday)
            n, wd = rule[1], rule[2]
            d, count = datetime.date(y, m, 1), 0
            while d.month == m:
                if d.weekday() == wd:
                    count += 1
                    if count == n:
                        break
                d += datetime.timedelta(days=1)
            if d.month != m:
                continue
        if start <= d <= end:
            out.append(d)
    return out


def _around(sid, date_str, con=None):
    """Observation on or before the event, and the first one strictly after."""
    before = store.value_on_or_before(sid, date_str, con=con)
    rows = store.history(sid, since=date_str, con=con)
    after = None
    for r in rows:
        if r['obs_date'] > date_str:
            after = r
            break
    return before, after


def markers(from_date, to_date, kinds=None, rate_series='MORT30Y', con=None):
    """Event markers in a window, each with the measured move around it."""
    try:
        start = datetime.date(*[int(x) for x in from_date[:10].split('-')])
        end = datetime.date(*[int(x) for x in to_date[:10].split('-')])
    except Exception:
        return []

    kinds = [k for k in (kinds or KIND_ORDER) if k in EVENT_KINDS]
    scored = dict((r['id'], r) for r in analytics.scored_releases(con=con))
    out = []

    for kind in kinds:
        rule, label, sid, impact = EVENT_KINDS[kind]
        confirmed = (rule[0] == 'fixed')
        for d in _rule_dates(rule, start, end):
            ds = d.isoformat()
            before, after = _around(rate_series, ds, con=con)
            move_bp = None
            if before and after:
                move_bp = round((after['value'] - before['value']) * 100, 1)

            # Actual and forecast are only meaningful for the newest print, which is
            # the one the surprise engine scored. Older markers carry the level that
            # was published for that reference month and no forecast at all.
            sc = scored.get(kind)
            actual = forecast = None
            classification = None
            if sc and sc['period'][:7] == ds[:7]:
                actual, forecast = sc['actual'], sc['consensus']
                classification = sc['classification_label']
            else:
                ref = store.value_on_or_before(sid, ds, con=con) if sid else None
                actual = ref['value'] if ref else None

            out.append({
                'date': ds,
                'kind': kind,
                'label': label,
                'impact': impact,
                'series_id': sid,
                'date_confidence': 'CONFIRMED' if confirmed else 'PROJECTED',
                'date_note': ('Published FOMC schedule.' if confirmed else
                              'Date projected from the agency\'s usual monthly rhythm, '
                              'not a scraped release calendar. The rate move below is '
                              'measured from real observations either side of it.'),
                'actual': actual,
                'forecast': forecast,
                'classification': classification,
                'rate_before': before['value'] if before else None,
                'rate_before_date': before['obs_date'] if before else None,
                'rate_after': after['value'] if after else None,
                'rate_after_date': after['obs_date'] if after else None,
                'move_bp': move_bp,
            })

    out.sort(key=lambda e: e['date'])
    return out


def kind_catalog():
    return [{'kind': k, 'label': EVENT_KINDS[k][1], 'impact': EVENT_KINDS[k][3],
             'confirmed_dates': EVENT_KINDS[k][0][0] == 'fixed'}
            for k in KIND_ORDER]
