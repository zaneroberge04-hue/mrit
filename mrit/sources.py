"""Ingestion adapters.

Contract: every adapter exposes source_id, requires_key, and run(con) -> (n_written, detail).
A failing adapter is logged and leaves prior observations in place. Prior observations
that are past their expected refresh window are re-flagged STALE by mark_stale(), so a
dead feed degrades visibly instead of silently serving old numbers as current.
"""

import csv
import datetime
import io
import json
import os
import ssl
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from . import registry, store

UA = 'MRIT/0.1 (mortgage rate intelligence terminal; local research tool)'
_CTX = ssl.create_default_context()

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')


def config():
    # Local dev reads config.json. CI (the scheduled build) has no file and instead
    # passes the optional keys as environment variables, so nothing secret is ever
    # committed. A present config.json key wins over the environment.
    cfg = {}
    for name in ('fred_api_key', 'bls_api_key', 'eia_api_key', 'tenure_start'):
        val = os.environ.get(name.upper()) or os.environ.get('MRIT_' + name.upper())
        if val:
            cfg[name] = val
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update({k: v for k, v in json.load(f).items() if v})
        except Exception:
            pass
    return cfg


def http_get(url, data=None, headers=None, timeout=45):
    h = {'User-Agent': UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read()


def obs(series_id, date, value, quality, source_id):
    return dict(series_id=series_id, obs_date=date, value=value,
                quality=quality, source_id=source_id)


# =========================================================================
# TIER 1 - Treasury curve. Free, no key, full 1M-30Y daily.
# =========================================================================
class TreasuryCurveSource(object):
    source_id = 'treasury'
    requires_key = False
    name = 'U.S. Treasury daily par yield curve'
    url = ('https://home.treasury.gov/resource-center/data-chart-center/interest-rates/'
           'pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=%s')
    NS = {'a': 'http://www.w3.org/2005/Atom',
          'm': 'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata',
          'd': 'http://schemas.microsoft.com/ado/2007/08/dataservices'}

    def run(self, con, years=None):
        # A ten-year window is what makes the spread percentile meaningful. Without it
        # the SPREAD screen ranks today against an 18-month sample and calls a 199bp
        # spread "tight" because 2024-25 was wider.
        if years is None:
            now = datetime.date.today().year
            years = list(range(now - 10, now + 1))
        out = []
        for yr in years:
            raw = http_get(self.url % yr)
            root = ET.fromstring(raw)
            for entry in root.findall('a:entry', self.NS):
                props = entry.find('a:content/m:properties', self.NS)
                if props is None:
                    continue
                vals = {}
                for child in props:
                    vals[child.tag.split('}')[-1]] = child.text
                d = (vals.get('NEW_DATE') or '')[:10]
                if not d:
                    continue
                for sid, _n, code, _y in registry.TREASURY_TENORS:
                    v = vals.get(code)
                    if v not in (None, '', 'N/A'):
                        try:
                            out.append(obs(sid, d, float(v), registry.LIVE, self.source_id))
                        except ValueError:
                            pass
        store.upsert(out, con=con)
        return len(out), '%d obs across %s' % (len(out), years)


# =========================================================================
# TIER 1 - Freddie Mac PMMS. Free, no key, weekly, history to 1971.
# =========================================================================
class PMMSSource(object):
    source_id = 'pmms'
    requires_key = False
    name = 'Freddie Mac Primary Mortgage Market Survey'
    url = 'https://www.freddiemac.com/pmms/docs/PMMS_history.csv'

    # Full history. PMMS runs to 1971 and MAX should mean MAX; ~2.9k weekly
    # observations is nothing for the store and makes the long ranges real.
    def run(self, con, since_year=1971):
        raw = http_get(self.url).decode('utf-8', 'replace')
        rdr = csv.DictReader(io.StringIO(raw))
        out = []
        for row in rdr:
            ds = (row.get('date') or '').strip()
            if not ds:
                continue
            try:
                m, d, y = [int(x) for x in ds.split('/')]
            except ValueError:
                continue
            if y < since_year:
                continue
            iso = '%04d-%02d-%02d' % (y, m, d)
            for sid, col in (('MORT30Y', 'pmms30'), ('MORT15Y', 'pmms15')):
                v = (row.get(col) or '').strip()
                if v:
                    try:
                        out.append(obs(sid, iso, float(v), registry.LIVE, self.source_id))
                    except ValueError:
                        pass
        store.upsert(out, con=con)
        return len(out), '%d obs since %d' % (len(out), since_year)


# =========================================================================
# TIER 3/4 - BLS. Free without a key (25 series, 10yr, 25 req/day).
# =========================================================================
class BLSSource(object):
    source_id = 'bls'
    requires_key = False
    name = 'Bureau of Labor Statistics Public API v2'
    url = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'

    def run(self, con, start_year=None):
        series = registry.by_source('bls')
        tickers = [s['ticker'] for s in series]
        by_ticker = dict((s['ticker'], s['id']) for s in series)
        this_year = datetime.date.today().year
        start_year = start_year or (this_year - 4)

        payload = {'seriesid': tickers, 'startyear': str(start_year), 'endyear': str(this_year)}
        key = config().get('bls_api_key')
        if key:
            payload['registrationkey'] = key
        body = json.dumps(payload).encode()
        raw = http_get(self.url, data=body, headers={'Content-Type': 'application/json'})
        j = json.loads(raw.decode('utf-8', 'replace'))
        if j.get('status') != 'REQUEST_SUCCEEDED':
            raise RuntimeError('BLS: %s %s' % (j.get('status'), j.get('message')))

        out = []
        for ser in j.get('Results', {}).get('series', []):
            sid = by_ticker.get(ser.get('seriesID'))
            if not sid:
                continue
            for pt in ser.get('data', []):
                per = pt.get('period', '')
                if not per.startswith('M') or per == 'M13':
                    continue
                try:
                    d = '%s-%02d-01' % (pt['year'], int(per[1:]))
                    out.append(obs(sid, d, float(pt['value']), registry.LIVE, self.source_id))
                except (ValueError, KeyError):
                    pass
        store.upsert(out, con=con)
        return len(out), '%d obs, %d series' % (len(out), len(tickers))


# =========================================================================
# TIER 6 - EIA petroleum spot prices. Free key. The originator of both crude
# benchmarks; FRED republishes these same series.
# =========================================================================
class EIASource(object):
    source_id = 'eia'
    requires_key = True
    name = 'U.S. Energy Information Administration'
    url = 'https://api.eia.gov/v2/petroleum/pri/spt/data/'

    def run(self, con, start='2018-01-01'):
        key = config().get('eia_api_key')
        if not key:
            raise RuntimeError(
                'No eia_api_key in config.json. Free at eia.gov/opendata/register.php. '
                'Without it, WTI and Brent fall back to FRED if a FRED key is present, '
                'and otherwise render DATA UNAVAILABLE rather than guessing.')
        series = registry.by_source('eia')
        by_ticker = dict((s['ticker'], s['id']) for s in series)
        q = [
            'api_key=' + urllib.parse.quote(key),
            'frequency=daily', 'data[0]=value',
            'start=' + start,
            'sort[0][column]=period', 'sort[0][direction]=desc',
            'length=5000',
        ] + ['facets[series][]=' + t for t in by_ticker]
        raw = http_get(self.url + '?' + '&'.join(q), timeout=40)
        j = json.loads(raw.decode('utf-8', 'replace'))
        rows = (j.get('response') or {}).get('data') or []
        if not rows:
            raise RuntimeError('EIA returned no rows: %s' % str(j)[:180])

        out = []
        for r in rows:
            sid = by_ticker.get(r.get('series'))
            v = r.get('value')
            if not sid or v in (None, ''):
                continue
            try:
                out.append(obs(sid, str(r['period'])[:10], float(v),
                               registry.LIVE, self.source_id))
            except (ValueError, KeyError):
                pass
        store.upsert(out, con=con)
        return len(out), '%d obs, %d series (%s)' % (
            len(out), len(by_ticker), ', '.join(sorted(by_ticker)))


# =========================================================================
# TIER 2/5/6/8 - FRED. Needs a free key in config.json. Optional for MVP.
# =========================================================================
class FREDSource(object):
    source_id = 'fred'
    requires_key = True
    name = 'FRED (St. Louis Fed)'
    url = ('https://api.stlouisfed.org/fred/series/observations'
           '?series_id=%s&api_key=%s&file_type=json&observation_start=%s')

    # FRED republishes the EIA crude series. If EIA has no key but FRED does,
    # pick them up here so the oil tier is not dark for want of a second key.
    FALLBACK = {'OIL': 'DCOILWTICO', 'BRENT': 'DCOILBRENTEU'}

    def run(self, con, start='2018-01-01'):
        key = config().get('fred_api_key')
        if not key:
            raise RuntimeError('No fred_api_key in config.json. This is the one gap you can close yourself: get a free key at fredaccount.stlouisfed.org/apikeys, copy config.json.example to config.json, paste it in. Unlocks Tiers 5, 6 and 8.')
        targets = list(registry.by_source('fred'))
        if not config().get('eia_api_key'):
            for sid, tk in self.FALLBACK.items():
                m = registry.get(sid)
                if m and not store.latest(sid, con=con):
                    targets.append(dict(m, ticker=tk))

        out, ok, bad = [], 0, []
        for s in targets:
            try:
                raw = http_get(self.url % (s['ticker'], key, start), timeout=30)
                j = json.loads(raw.decode('utf-8', 'replace'))
                for o in j.get('observations', []):
                    if o.get('value') in (None, '', '.'):
                        continue
                    out.append(obs(s['id'], o['date'], float(o['value']),
                                   registry.LIVE, self.source_id))
                ok += 1
            except Exception as e:
                bad.append('%s:%s' % (s['id'], type(e).__name__))
        store.upsert(out, con=con)
        if not ok:
            raise RuntimeError('all FRED series failed: %s' % ', '.join(bad[:6]))
        return len(out), '%d obs, %d/%d series ok' % (len(out), ok, ok + len(bad))


# =========================================================================
# Derived series. Reads the store, writes computed series back.
# Everything here is MODELED and is labeled as such in the UI.
# =========================================================================
PRIMARY_SECONDARY_SPREAD = 0.50   # pct, gross of g-fee, servicing, origination
MBS_EFF_DURATION = 4.5            # yrs, current-coupon TBA
MORTGAGE_BETA_TO_10Y = 0.95       # historical pass-through of a 10Y move


def _asof_index(rows):
    """(sorted dates, {date: value}) for as-of lookups."""
    dates = [r['obs_date'] for r in rows]
    return dates, dict((r['obs_date'], r['value']) for r in rows)


def tba_price(cc_yield, coupon):
    """MODELED TBA dollar price for a coupon given the current-coupon yield.

    Discount to par by duration, with a mild convexity haircut on the wings so
    deep discounts and premiums do not extrapolate linearly the way real TBAs
    never do. Directionally right, not a price feed.
    """
    dy = cc_yield - coupon
    return 100.0 - MBS_EFF_DURATION * dy - 0.5 * 0.35 * (dy ** 2) * 100 * 0.01


def _asof(dates, values, target):
    """Most recent value at or before target. Linear scan is fine at this size."""
    best = None
    for d in dates:
        if d <= target:
            best = d
        else:
            break
    return (best, values[best]) if best else (None, None)


class DerivedSource(object):
    source_id = 'derived'
    requires_key = False
    name = 'Derived analytics (MODELED)'

    def run(self, con):
        out = []
        H = lambda sid: store.history(sid, con=con)

        ust10, ust5, ust2, ust30 = H('UST10Y'), H('UST5Y'), H('UST2Y'), H('UST30Y')
        pmms = H('MORT30Y')

        d10, v10 = _asof_index(ust10)
        d5, v5 = _asof_index(ust5)
        dp, vp = _asof_index(pmms)

        # ---- curve slopes (bps), on Treasury dates
        for a, b, sid in (('UST10Y', 'UST2Y', 'CURVE_2S10S'),
                          ('UST10Y', 'UST5Y', 'CURVE_5S10S'),
                          ('UST30Y', 'UST10Y', 'CURVE_10S30S')):
            ra, rb = H(a), H(b)
            mb = dict((r['obs_date'], r['value']) for r in rb)
            for r in ra:
                if r['obs_date'] in mb:
                    out.append(obs(sid, r['obs_date'],
                                   round((r['value'] - mb[r['obs_date']]) * 100, 1),
                                   registry.DERIVED, self.source_id))

        # ---- weekly mortgage/10Y spread on PMMS print dates (near-exact, not modeled)
        for r in pmms:
            dd, tv = _asof(d10, v10, r['obs_date'])
            if tv is not None:
                out.append(obs('MTG_UST_SPREAD', r['obs_date'],
                               round((r['value'] - tv) * 100, 1),
                               registry.LIVE, self.source_id))

        # ---- daily modeled mortgage rate, MBS current coupon, TBA price, MBS spread
        #
        # The production coupon is pinned to TODAY's current coupon and held constant
        # across history. Re-deriving it each day would make the coupon jump half a
        # point at rounding boundaries and print a fake 72-tick move.
        prod_coupon = None
        if dp and d10:
            _, last_pv = _asof(dp, vp, d10[-1])
            _, anchor_last = _asof(d10, v10, _asof(dp, vp, d10[-1])[0] or d10[-1])
            if last_pv is not None:
                cc_now = last_pv - PRIMARY_SECONDARY_SPREAD
                prod_coupon = round(cc_now * 2) / 2.0

        prev_price = None
        for d in d10:
            pd_, pv = _asof(dp, vp, d)
            if pv is None:
                continue
            _, anchor10 = _asof(d10, v10, pd_)
            if anchor10 is None:
                continue
            mort = pv + (v10[d] - anchor10) * MORTGAGE_BETA_TO_10Y
            out.append(obs('MORT30Y_D', d, round(mort, 3), registry.MODELED, self.source_id))

            cc = mort - PRIMARY_SECONDARY_SPREAD
            out.append(obs('MBS_CC', d, round(cc, 3), registry.MODELED, self.source_id))

            _, t5 = _asof(d5, v5, d)
            if t5 is not None:
                bench = 0.5 * t5 + 0.5 * v10[d]
                out.append(obs('MBS_SPREAD', d, round((cc - bench) * 100, 1),
                               registry.MODELED, self.source_id))

            if prod_coupon is not None:
                price = tba_price(cc, prod_coupon)
                out.append(obs('MBS_PRICE', d, round(price, 4), registry.MODELED, self.source_id))
                if prev_price is not None:
                    out.append(obs('MBS_TICKS', d, round((price - prev_price) * 32, 1),
                                   registry.MODELED, self.source_id))
                prev_price = price

        # ---- Brent minus WTI, on dates where both benchmarks printed
        brent = dict((r['obs_date'], r['value']) for r in H('BRENT'))
        for r in H('OIL'):
            b = brent.get(r['obs_date'])
            if b is not None:
                out.append(obs('BRENT_WTI', r['obs_date'], round(b - r['value'], 3),
                               registry.DERIVED, self.source_id))

        # ---- 10Y realized volatility (free proxy for the licensed MOVE index)
        # Trailing-20-session stdev of daily 10Y yield changes, in bp, annualized by
        # root-252. Realized rather than implied vol, so it confirms a shock instead of
        # forecasting one, but it moves on the same events and needs no feed.
        import math
        win = 20
        changes = []  # (date, daily change in bp)
        for i in range(1, len(ust10)):
            changes.append((ust10[i]['obs_date'],
                            (ust10[i]['value'] - ust10[i - 1]['value']) * 100.0))
        for i in range(win - 1, len(changes)):
            window = [c[1] for c in changes[i - win + 1:i + 1]]
            mean = sum(window) / win
            var = sum((x - mean) ** 2 for x in window) / (win - 1)
            vol = (var ** 0.5) * math.sqrt(252)
            out.append(obs('MOVE', changes[i][0], round(vol, 1),
                           registry.DERIVED, self.source_id))

        # ---- Fed easing priced into the 1Y vs the target midpoint (free proxy for
        # CME FedWatch). Positive = cuts priced. Needs the 1Y and the live target range.
        ust1 = H('UST1Y')
        tlo, thi = H('FED_TARGET_LOW'), H('FED_TARGET_HIGH')
        dlo, vlo = _asof_index(tlo)
        dhi, vhi = _asof_index(thi)
        for r in ust1:
            _, lo = _asof(dlo, vlo, r['obs_date'])
            _, hi = _asof(dhi, vhi, r['obs_date'])
            if lo is not None and hi is not None:
                mid = (lo + hi) / 2.0
                out.append(obs('FED_PROB_CUT', r['obs_date'],
                               round((mid - r['value']) * 100.0, 1),
                               registry.DERIVED, self.source_id))

        # ---- BLS transforms
        out += self._mom('NFP_LEVEL', 'NFP', diff=True)
        out += self._yoy('CPI', 'CPI_YOY')
        out += self._yoy('CORECPI', 'CORECPI_YOY')
        out += self._mom('CORECPI', 'CORECPI_MOM', pct=True)
        out += self._yoy('AHE_LEVEL', 'AHE_YOY')

        store.upsert(out, con=con)
        return len(out), '%d derived obs' % len(out)

    def _mom(self, src, dst, diff=False, pct=False):
        rows = store.history(src)
        out, prev = [], None
        for r in rows:
            if prev is not None:
                if diff:
                    v = round(r['value'] - prev, 1)
                elif pct:
                    v = round((r['value'] / prev - 1.0) * 100, 3) if prev else None
                else:
                    v = r['value'] - prev
                if v is not None:
                    out.append(obs(dst, r['obs_date'], v, registry.DERIVED, self.source_id))
            prev = r['value']
        return out

    def _yoy(self, src, dst):
        rows = store.history(src)
        m = dict((r['obs_date'], r['value']) for r in rows)
        out = []
        for r in rows:
            y, mo = int(r['obs_date'][:4]), int(r['obs_date'][5:7])
            key = '%04d-%02d-01' % (y - 1, mo)
            if key in m and m[key]:
                out.append(obs(dst, r['obs_date'], round((r['value'] / m[key] - 1) * 100, 3),
                               registry.DERIVED, self.source_id))
        return out


# =========================================================================
# Slots for licensed feeds. These fail loudly and render UNAVAILABLE.
# =========================================================================
class UnavailableSource(object):
    """A slot for a feed that has no free source. Not a failure: a known gap."""
    requires_key = True
    licensed = True

    def __init__(self, source_id, name, why):
        self.source_id, self.name, self.why = source_id, name, why

    def run(self, con):
        raise Unavailable(self.why)


class Unavailable(Exception):
    """Raised by a source that cannot run because the data is not obtainable,
    as distinct from a source that broke."""


SOURCES = [
    TreasuryCurveSource(),
    PMMSSource(),
    BLSSource(),
    EIASource(),
    FREDSource(),
    DerivedSource(),                       # must run last: reads what the others wrote
    UnavailableSource('mbsfeed', 'FNMA TBA pricing',
                      'Real FNMA TBA prices are licensed (Tradeweb / MBS Live / Bloomberg). '
                      'MBS_* series are MODELED from the mortgage rate and Treasury curve.'),
]

# derived must run after ingestion
ORDER = ['treasury', 'pmms', 'bls', 'eia', 'fred', 'derived',
         'fedprob', 'movefeed', 'mbsfeed']


def refresh(only=None):
    """Run every adapter. Never raises: failures land in fetch_log and the UI."""
    con = store.connect()
    results = []
    try:
        byid = dict((s.source_id, s) for s in SOURCES)
        for sid in ORDER:
            if only and sid not in only:
                continue
            src = byid.get(sid)
            if not src:
                continue
            started = store.utcnow()
            try:
                n, detail = src.run(con)
                store.log_fetch(sid, started, 'OK', detail, con=con)
                results.append({'source': sid, 'status': 'OK', 'n': n, 'detail': detail})
            except Unavailable as e:
                store.log_fetch(sid, started, 'UNAVAILABLE', str(e), con=con)
                results.append({'source': sid, 'status': 'UNAVAILABLE', 'n': 0,
                                'detail': str(e), 'actionable': False})
            except Exception as e:
                msg = '%s: %s' % (type(e).__name__, e)
                actionable = 'api_key' in msg or 'config.json' in msg
                store.log_fetch(sid, started, 'FAIL', msg, con=con)
                results.append({'source': sid, 'status': 'FAIL', 'n': 0, 'detail': msg,
                                'actionable': actionable})
            con.commit()
        mark_stale(con)
        con.commit()
    finally:
        con.close()
    return results


# Observations are stamped with their REFERENCE period, not their release date.
# July CPI carries 2026-07-01 but does not publish until mid-August, so the window
# has to cover reference-period start through the next scheduled release.
MAX_AGE_DAYS = {'daily': 5, 'weekly': 12, 'monthly': 75, 'quarterly': 160,
                'event': 400, 'realtime': 1}


def native_quality(source_id, series_id=None):
    """The quality an observation should carry when it is inside its freshness window.

    Derived series split two ways: exact arithmetic (a spread, a y/y change) is DERIVED,
    everything else from the derived adapter is a genuine MODELED construction.
    """
    if series_id in registry.DERIVED_SERIES:
        return registry.DERIVED
    return {'derived': registry.MODELED, 'manual': registry.SEED}.get(
        source_id, registry.LIVE)


def mark_stale(con):
    """Re-evaluate freshness in BOTH directions.

    This used to only downgrade, which meant a series marked STALE once could never
    recover even after fresh data landed: the badge latched on and stayed wrong. It
    now restores the native quality when an observation is back inside its window.
    """
    today = datetime.date.today()
    downgraded = restored = 0
    for s in registry.SERIES:
        cur = store.latest(s['id'], con=con)
        if not cur:
            continue
        try:
            d = datetime.date(*[int(x) for x in cur['obs_date'][:10].split('-')])
        except Exception:
            continue
        age = (today - d).days
        allowance = MAX_AGE_DAYS.get(s['refresh'], 30) + registry.publication_lag(s['id'])
        native = native_quality(cur['source_id'], s['id'])

        if age > allowance and cur['quality'] != registry.STALE:
            con.execute('UPDATE observation SET quality=? WHERE series_id=? AND obs_date=?',
                        (registry.STALE, s['id'], cur['obs_date']))
            downgraded += 1
        elif age <= allowance and cur['quality'] == registry.STALE:
            con.execute('UPDATE observation SET quality=? WHERE series_id=? AND obs_date=?',
                        (native, s['id'], cur['obs_date']))
            restored += 1
    return {'downgraded': downgraded, 'restored': restored}
