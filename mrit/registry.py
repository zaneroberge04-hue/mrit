"""Series and release registry. The data contract every other layer reads.

Adding a data point to the terminal means adding a row here and teaching one
adapter to produce it. Nothing else changes.
"""

# quality levels, worst to best. Drives the badge on every rendered number.
UNAVAILABLE = 'UNAVAILABLE'
STALE = 'STALE'
SEED = 'SEED'
MODELED = 'MODELED'
DERIVED = 'DERIVED'
LIVE = 'LIVE'

QUALITY_RANK = {UNAVAILABLE: 0, STALE: 1, SEED: 2, MODELED: 3, DERIVED: 4, LIVE: 5}

# Derived series that are EXACT arithmetic on live observations, not models: a spread,
# a slope, a year-over-year or month-over-month change. They carry the reliability of
# their inputs, so they get their own badge (DERIVED) instead of being lumped in with
# MODELED, which is reserved for genuine constructions like the MBS stack. native_quality
# consults this set so the staleness pass restores DERIVED, not MODELED, for them.
DERIVED_SERIES = {
    'CURVE_2S10S', 'CURVE_5S10S', 'CURVE_10S30S', 'BRENT_WTI',
    'NFP', 'CPI_YOY', 'CORECPI_YOY', 'CORECPI_MOM', 'AHE_YOY',
    'MOVE', 'FED_PROB_CUT',
}

# Observation frequency, kept separate from refresh cadence. The chart uses this to
# decide which time ranges are honest: a weekly survey cannot answer a 1-day range,
# and the fix is to disable the button, never to interpolate a value.
FREQUENCY = {
    'realtime': 'REAL-TIME', 'daily': 'DAILY', 'weekly': 'WEEKLY',
    'monthly': 'MONTHLY', 'quarterly': 'QUARTERLY', 'event': 'EVENT-DRIVEN',
}
MIN_RANGE_DAYS = {'realtime': 1, 'daily': 5, 'weekly': 30, 'monthly': 180,
                  'quarterly': 550, 'event': 365}


def publication_lag(sid):
    """Business days the ORIGINATING source runs behind real time.

    A feed can be perfectly healthy and still be days old: EIA posts petroleum spot
    with a multi-day lag, BLS stamps observations with the reference month. Staleness
    has to be measured against that expected lag, or normal behaviour gets flagged as
    a broken feed and the badge stops meaning anything.
    """
    m = BY_ID.get(sid)
    if not m:
        return 0
    return SOURCE_META.get(m['source_id'], {}).get('publication_lag_days', 0)


def frequency_of(sid):
    m = BY_ID.get(sid)
    return m['refresh'] if m else 'daily'

# Tiers mirror the causal hierarchy in ARCHITECTURE.md
T1_RATES, T2_FED, T3_INFL, T4_LABOR, T5_GROWTH, T6_MKT, T7_GLOBAL, T8_HOUSING = 1, 2, 3, 4, 5, 6, 7, 8

TIER_NAMES = {
    T1_RATES: 'Direct rate drivers',
    T2_FED: 'Federal Reserve',
    T3_INFL: 'Inflation',
    T4_LABOR: 'Labor market',
    T5_GROWTH: 'Economic growth',
    T6_MKT: 'Market conditions',
    T7_GLOBAL: 'Global macro',
    T8_HOUSING: 'Housing market',
}


def S(sid, name, source, tier, unit, refresh, ticker='', invert=0, notes=''):
    """invert=1 means a RISE in this series pushes mortgage rates DOWN."""
    return dict(id=sid, name=name, source_id=source, tier=tier, unit=unit,
                refresh=refresh, ticker=ticker or sid, invert_for_rates=invert,
                notes=notes)


# --------------------------------------------------------------------------
# TIER 1 - direct mortgage rate drivers
# --------------------------------------------------------------------------
TREASURY_TENORS = [
    ('UST1M', '1-Month Treasury', 'BC_1MONTH', 1 / 12.0),
    ('UST3M', '3-Month Treasury', 'BC_3MONTH', 0.25),
    ('UST6M', '6-Month Treasury', 'BC_6MONTH', 0.5),
    ('UST1Y', '1-Year Treasury', 'BC_1YEAR', 1.0),
    ('UST2Y', '2-Year Treasury', 'BC_2YEAR', 2.0),
    ('UST3Y', '3-Year Treasury', 'BC_3YEAR', 3.0),
    ('UST5Y', '5-Year Treasury', 'BC_5YEAR', 5.0),
    ('UST7Y', '7-Year Treasury', 'BC_7YEAR', 7.0),
    ('UST10Y', '10-Year Treasury', 'BC_10YEAR', 10.0),
    ('UST20Y', '20-Year Treasury', 'BC_20YEAR', 20.0),
    ('UST30Y', '30-Year Treasury', 'BC_30YEAR', 30.0),
]

SERIES = []
for _sid, _nm, _code, _yrs in TREASURY_TENORS:
    SERIES.append(S(_sid, _nm, 'treasury', T1_RATES, 'percent', 'daily', notes='UST par yield'))

SERIES += [
    S('MORT30Y', '30Y Fixed Mortgage Rate', 'pmms', T1_RATES, 'percent', 'weekly',
      notes='Freddie Mac PMMS, released Thursdays, survey week Thu-Wed'),
    S('MORT15Y', '15Y Fixed Mortgage Rate', 'pmms', T1_RATES, 'percent', 'weekly'),

    S('OBMMI30', 'Optimal Blue 30Y Conforming (daily, lock-based)', 'fred', T1_RATES,
      'percent', 'daily', ticker='OBMMIC30YF',
      notes='Daily rate built from ACTUAL RATE LOCKS across roughly a third of US '
            'originations, not a survey. This is the closest public series to what a rate '
            'sheet actually does, and it moves days before PMMS does.'),
    S('MORT30Y_D', 'Est. Daily 30Y Mortgage Rate', 'derived', T1_RATES, 'percent', 'daily',
      notes='MODELED: last PMMS print carried forward by the 10Y move since that print, beta 0.95. '
            'PMMS is a weekly Thursday survey; this is the daily read between prints.'),
    S('MBS_CC', 'FNMA Current Coupon Yield', 'derived', T1_RATES, 'percent', 'daily',
      notes='MODELED: MORT30Y minus 50bp primary/secondary spread'),
    S('MBS_PRICE', 'FNMA 30Y TBA Price (production coupon)', 'derived', T1_RATES, 'price32', 'daily',
      invert=1, notes='MODELED from current-coupon yield, duration 4.5'),
    S('MBS_TICKS', 'FNMA TBA Daily Move', 'derived', T1_RATES, 'ticks', 'daily',
      invert=1, notes='MODELED, 32nds'),
    S('MBS_SPREAD', 'MBS / Treasury Spread', 'derived', T1_RATES, 'bps', 'daily',
      notes='MODELED: current coupon less 5s10s duration-matched blend'),
    S('MTG_UST_SPREAD', 'Mortgage / 10Y Treasury Spread', 'derived', T1_RATES, 'bps', 'weekly',
      notes='MORT30Y minus UST10Y. The single most important spread on the screen.'),
    S('CURVE_2S10S', '2s10s Slope', 'derived', T1_RATES, 'bps', 'daily'),
    S('CURVE_5S10S', '5s10s Slope', 'derived', T1_RATES, 'bps', 'daily'),
    S('CURVE_10S30S', '10s30s Slope', 'derived', T1_RATES, 'bps', 'daily'),

    # ---------------- TIER 2 Fed ----------------
    S('FEDFUNDS', 'Effective Fed Funds Rate', 'fred', T2_FED, 'percent', 'daily', ticker='DFF'),
    S('FED_TARGET_LOW', 'Fed Funds Target Lower', 'fred', T2_FED, 'percent', 'daily',
      ticker='DFEDTARL', notes='FOMC target range lower bound, published daily by the Fed via '
                               'FRED. Steps only on decision days.'),
    S('FED_TARGET_HIGH', 'Fed Funds Target Upper', 'fred', T2_FED, 'percent', 'daily',
      ticker='DFEDTARU', notes='FOMC target range upper bound, published daily by the Fed via '
                               'FRED. Steps only on decision days.'),
    S('WALCL', 'Fed Balance Sheet (total assets)', 'fred', T2_FED, 'usd_mm', 'weekly', ticker='WALCL'),
    S('FED_MBS_HOLD', 'Fed MBS Holdings', 'fred', T2_FED, 'usd_mm', 'weekly', ticker='WSHOMCB'),
    S('FED_PROB_CUT', 'Easing Priced In, 1Y', 'derived', T2_FED, 'bps', 'daily',
      invert=1, notes='Basis points of cuts the 1-year Treasury is pricing versus the current '
                      'fed funds target midpoint. Positive = the market expects easing, negative '
                      '= hikes. A real read on Fed expectations straight from the curve, in place '
                      'of the licensed CME FedWatch probability.'),

    # ---------------- TIER 3 inflation ----------------
    S('CPI', 'CPI-U All Items (SA)', 'bls', T3_INFL, 'index', 'monthly', ticker='CUSR0000SA0'),
    S('CORECPI', 'Core CPI (ex food & energy, SA)', 'bls', T3_INFL, 'index', 'monthly', ticker='CUSR0000SA0L1E'),
    S('PPI', 'PPI Final Demand', 'bls', T3_INFL, 'index', 'monthly', ticker='WPSFD4'),
    S('SHELTER', 'CPI Shelter', 'bls', T3_INFL, 'index', 'monthly', ticker='CUSR0000SAH1'),
    S('CPI_YOY', 'CPI y/y', 'derived', T3_INFL, 'percent', 'monthly'),
    S('CORECPI_YOY', 'Core CPI y/y', 'derived', T3_INFL, 'percent', 'monthly'),
    S('CORECPI_MOM', 'Core CPI m/m', 'derived', T3_INFL, 'percent', 'monthly'),
    S('PCE_CORE_YOY', 'Core PCE y/y', 'fred', T3_INFL, 'percent', 'monthly', ticker='PCEPILFE'),
    S('BREAKEVEN10', '10Y Breakeven Inflation', 'fred', T3_INFL, 'percent', 'daily', ticker='T10YIE'),
    S('BREAKEVEN5', '5Y Breakeven Inflation', 'fred', T3_INFL, 'percent', 'daily', ticker='T5YIE'),

    # ---------------- TIER 4 labor ----------------
    S('NFP_LEVEL', 'Total Nonfarm Payrolls (level)', 'bls', T4_LABOR, 'thousands', 'monthly', ticker='CES0000000001'),
    S('NFP', 'Nonfarm Payrolls (m/m change)', 'derived', T4_LABOR, 'thousands', 'monthly'),
    S('UNRATE', 'Unemployment Rate', 'bls', T4_LABOR, 'percent', 'monthly', ticker='LNS14000000', invert=1),
    S('AHE_LEVEL', 'Average Hourly Earnings', 'bls', T4_LABOR, 'usd', 'monthly', ticker='CES0500000003'),
    S('AHE_YOY', 'Average Hourly Earnings y/y', 'derived', T4_LABOR, 'percent', 'monthly'),
    S('CLAIMS', 'Initial Jobless Claims', 'fred', T4_LABOR, 'thousands', 'weekly', ticker='ICSA', invert=1),
    S('CCLAIMS', 'Continuing Claims', 'fred', T4_LABOR, 'thousands', 'weekly', ticker='CCSA', invert=1),
    S('JOLTS', 'Job Openings (JOLTS)', 'fred', T4_LABOR, 'thousands', 'monthly', ticker='JTSJOL'),
    S('PARTRATE', 'Labor Force Participation', 'bls', T4_LABOR, 'percent', 'monthly', ticker='LNS11300000'),

    # ---------------- TIER 5 growth ----------------
    S('GDP', 'Real GDP q/q SAAR', 'fred', T5_GROWTH, 'percent', 'quarterly', ticker='A191RL1Q225SBEA'),
    S('RETAIL', 'Retail Sales', 'fred', T5_GROWTH, 'usd_mm', 'monthly', ticker='RSAFS'),
    S('CONFIDENCE', 'Consumer Sentiment', 'fred', T5_GROWTH, 'index', 'monthly', ticker='UMCSENT'),
    S('DURABLES', 'Durable Goods Orders', 'fred', T5_GROWTH, 'usd_mm', 'monthly', ticker='DGORDER'),
    S('INDPRO', 'Industrial Production', 'fred', T5_GROWTH, 'index', 'monthly', ticker='INDPRO'),

    # ---------------- TIER 6 market conditions ----------------
    S('VIX', 'CBOE Volatility Index', 'fred', T6_MKT, 'index', 'daily', ticker='VIXCLS'),
    S('MOVE', '10Y Realized Volatility (20d, ann.)', 'derived', T6_MKT, 'bps', 'daily',
      notes='Annualized realized volatility of daily 10-year Treasury yield changes over the '
            'trailing 20 sessions, in basis points. A real, free stand-in for the licensed ICE '
            'MOVE index: MOVE is option-implied (forward-looking) vol, this is realized '
            '(backward-looking) vol, so it confirms rather than leads, but both spike on the '
            'same shocks.'),
    S('HY_SPREAD', 'High Yield OAS', 'fred', T6_MKT, 'bps', 'daily', ticker='BAMLH0A0HYM2'),
    S('IG_SPREAD', 'Investment Grade OAS', 'fred', T6_MKT, 'bps', 'daily', ticker='BAMLC0A0CM'),
    S('SPX', 'S&P 500', 'fred', T6_MKT, 'index', 'daily', ticker='SP500'),
    S('DXY', 'Dollar Index (broad)', 'fred', T6_MKT, 'index', 'daily', ticker='DTWEXBGS'),
    S('OIL', 'WTI Crude (US benchmark)', 'eia', T6_MKT, 'usd', 'daily', ticker='RWTC',
      notes='West Texas Intermediate, Cushing OK spot FOB. The US benchmark: light, sweet, '
            'landlocked. Prices domestic refinery input and therefore US gasoline.'),
    S('BRENT', 'Brent Crude (global benchmark)', 'eia', T6_MKT, 'usd', 'daily', ticker='RBRTE',
      notes='Brent Europe spot FOB. The global benchmark: prices roughly two thirds of the '
            'world’s traded crude, and it is waterborne, so it carries geopolitical and '
            'freight risk that WTI does not.'),
    S('BRENT_WTI', 'Brent minus WTI Spread', 'derived', T6_MKT, 'usd', 'daily',
      notes='The global-versus-domestic dislocation gauge. Widens on supply shocks abroad, '
            'US export bottlenecks, or Cushing storage builds.'),
    S('GOLD', 'Gold', 'fred', T6_MKT, 'usd', 'daily', ticker='IQ12260'),

    # ---------------- TIER 8 housing ----------------
    S('EHS', 'Existing Home Sales', 'fred', T8_HOUSING, 'thousands', 'monthly', ticker='EXHOSLUSM495S'),
    S('NHS', 'New Home Sales', 'fred', T8_HOUSING, 'thousands', 'monthly', ticker='HSN1F'),
    S('STARTS', 'Housing Starts', 'fred', T8_HOUSING, 'thousands', 'monthly', ticker='HOUST'),
    S('PERMITS', 'Building Permits', 'fred', T8_HOUSING, 'thousands', 'monthly', ticker='PERMIT'),
    S('NEWSUPPLY', 'New Home Months Supply', 'fred', T8_HOUSING, 'months', 'monthly', ticker='MSACSR'),
    S('MEDNEW', 'Median New Home Price', 'fred', T8_HOUSING, 'usd', 'monthly', ticker='MSPNHSUS'),
]

BY_ID = dict((s['id'], s) for s in SERIES)


def get(sid):
    return BY_ID.get(sid)


def by_tier(tier):
    return [s for s in SERIES if s['tier'] == tier]


def by_source(source_id):
    return [s for s in SERIES if s['source_id'] == source_id]


# --------------------------------------------------------------------------
# Release calendar. `direction` describes what a HIGHER-THAN-CONSENSUS print
# does to mortgage rates: +1 pushes rates UP, -1 pushes rates DOWN.
# --------------------------------------------------------------------------
def R(rid, name, series_id, tier, impact, direction, typical_time, notes=''):
    return dict(id=rid, name=name, series_id=series_id, tier=tier, impact=impact,
                direction=direction, typical_time=typical_time, notes=notes)


RELEASES = [
    R('NFP', 'Nonfarm Payrolls', 'NFP', T4_LABOR, 'HIGH', +1, '08:30',
      'Strong jobs means stronger growth, less Fed easing, higher yields.'),
    R('UNRATE', 'Unemployment Rate', 'UNRATE', T4_LABOR, 'HIGH', -1, '08:30',
      'Higher unemployment is bond-friendly, pushing rates down.'),
    R('AHE', 'Average Hourly Earnings', 'AHE_YOY', T4_LABOR, 'HIGH', +1, '08:30',
      'Wage growth feeds services inflation.'),
    R('CPI', 'Consumer Price Index', 'CPI_YOY', T3_INFL, 'HIGH', +1, '08:30', ''),
    R('CORECPI', 'Core CPI', 'CORECPI_MOM', T3_INFL, 'HIGH', +1, '08:30',
      'The single highest-variance monthly release for mortgage rates.'),
    R('PPI', 'Producer Price Index', 'PPI', T3_INFL, 'MEDIUM', +1, '08:30', ''),
    R('PCE', 'Core PCE Price Index', 'PCE_CORE_YOY', T3_INFL, 'HIGH', +1, '08:30',
      "The Fed's preferred inflation gauge."),
    R('CLAIMS', 'Initial Jobless Claims', 'CLAIMS', T4_LABOR, 'MEDIUM', -1, '08:30', ''),
    R('JOLTS', 'JOLTS Job Openings', 'JOLTS', T4_LABOR, 'MEDIUM', +1, '10:00', ''),
    R('RETAIL', 'Retail Sales', 'RETAIL', T5_GROWTH, 'MEDIUM', +1, '08:30', ''),
    R('GDP', 'GDP', 'GDP', T5_GROWTH, 'MEDIUM', +1, '08:30', ''),
    R('FOMC', 'FOMC Rate Decision', 'FED_TARGET_HIGH', T2_FED, 'HIGH', +1, '14:00',
      'Statement language and the dot plot move rates more than the decision itself.'),
    R('EHS', 'Existing Home Sales', 'EHS', T8_HOUSING, 'LOW', +1, '10:00', ''),
    R('NHS', 'New Home Sales', 'NHS', T8_HOUSING, 'LOW', +1, '10:00', ''),
    R('STARTS', 'Housing Starts & Permits', 'STARTS', T8_HOUSING, 'LOW', +1, '08:30', ''),
]

RELEASE_BY_ID = dict((r['id'], r) for r in RELEASES)


# --------------------------------------------------------------------------
# Source metadata for the provenance inspector.
# `deep_link` takes the series ticker so the inspector can send you straight to
# the exact page the number came from, not just the vendor's home page.
# --------------------------------------------------------------------------
SOURCE_META = {
    'treasury': {
        'name': 'U.S. Department of the Treasury',
        'publication_lag_days': 1,
        'dataset': 'Daily Treasury Par Yield Curve Rates',
        'url': 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/'
               'TextView?type=daily_treasury_yield_curve',
        'endpoint': 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/'
                    'pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=YYYY',
        'deep_link': None,
        'auth': 'None. Public XML feed.',
        'cadence': 'Each business day, published around 3:30 pm ET.',
        'reliability': 'Primary source. This IS the official curve, not a vendor copy.',
        'caveat': 'Par yields derived from the on-the-run bid side at roughly 3:30 pm ET. '
                  'Not intraday. A big afternoon move lands in tomorrow’s print.',
    },
    'pmms': {
        'name': 'Freddie Mac',
        'publication_lag_days': 1,
        'dataset': 'Primary Mortgage Market Survey (PMMS)',
        'url': 'https://www.freddiemac.com/pmms',
        'endpoint': 'https://www.freddiemac.com/pmms/docs/PMMS_history.csv',
        'deep_link': None,
        'auth': 'None. Public CSV, history to 1971.',
        'cadence': 'Weekly, published Thursdays at noon ET.',
        'reliability': 'The most-quoted mortgage rate in the country. It is what the press '
                       'means by "the average 30-year rate".',
        'caveat': 'THIS IS A SURVEY AVERAGE, not a rate sheet. It covers Thursday through '
                  'Wednesday, is conventional / conforming / 80% LTV / strong credit, and '
                  'assumes about 0.6 points paid. It will always look calmer and later than '
                  'your lender pricing. Never quote it as a borrower rate.',
    },
    'bls': {
        'name': 'U.S. Bureau of Labor Statistics',
        'publication_lag_days': 14,
        'dataset': 'BLS Public Data API v2',
        'url': 'https://www.bls.gov/data/',
        'endpoint': 'https://api.bls.gov/publicAPI/v2/timeseries/data/',
        'deep_link': 'https://data.bls.gov/timeseries/%s',
        'auth': 'None required. A free key raises limits from 25 to 500 requests a day.',
        'cadence': 'Monthly. CPI around the 12th, employment the first Friday.',
        'reliability': 'Primary source. The number the market trades.',
        'caveat': 'Observations are stamped with the REFERENCE month, not the release date. '
                  'July data carries 2026-07-01 but does not publish until mid-August, so a '
                  'current print always looks 40 to 60 days old here. Prior months get '
                  'revised, sometimes heavily.',
    },
    'eia': {
        'name': 'U.S. Energy Information Administration',
        'publication_lag_days': 6,
        'dataset': 'Petroleum spot prices (series RWTC and RBRTE)',
        'url': 'https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm',
        'endpoint': 'https://api.eia.gov/v2/petroleum/pri/spt/data/',
        'deep_link': 'https://www.eia.gov/opendata/browser/petroleum/pri/spt?frequency=daily'
                     '&data=value&facets=series%%3B&series=%s',
        'auth': 'Free API key. https://www.eia.gov/opendata/register.php',
        'cadence': 'Each business day, roughly a two business day publication lag.',
        'reliability': 'Primary source. EIA is the originator; FRED merely republishes these '
                       'same two series as DCOILWTICO and DCOILBRENTEU.',
        'caveat': 'These are SPOT prices, not front-month futures. Spot and the futures screen '
                  'you see on CNBC can differ by a dollar or more, and spot publishes with a '
                  'lag while futures are live. Do not use this to time anything intraday.',
    },
    'fred': {
        'name': 'Federal Reserve Bank of St. Louis',
        'publication_lag_days': 2,
        'dataset': 'FRED',
        'url': 'https://fred.stlouisfed.org/',
        'endpoint': 'https://api.stlouisfed.org/fred/series/observations',
        'deep_link': 'https://fred.stlouisfed.org/series/%s',
        'auth': 'Free API key required. https://fredaccount.stlouisfed.org/apikeys',
        'cadence': 'Varies by series, daily through quarterly.',
        'reliability': 'Aggregator, not originator. FRED republishes other agencies’ data.',
        'caveat': 'FRED mirrors a source with its own lag. For anything time-critical, check '
                  'the originating agency.',
    },
    'derived': {
        'name': 'MRIT derived',
        'dataset': 'Computed locally from other series in this terminal',
        'url': None, 'endpoint': None, 'deep_link': None,
        'auth': 'n/a',
        'cadence': 'Recomputed on every refresh.',
        'reliability': 'Only as good as its inputs. Each derived series lists its formula and '
                       'its input series so you can audit it.',
        'caveat': 'Anything stamped MODELED is a construction, not an observation.',
    },
    'manual': {
        'name': 'Hand entered',
        'dataset': 'data/manual.json',
        'url': None, 'endpoint': 'data/manual.json', 'deep_link': None,
        'auth': 'n/a',
        'cadence': 'Whenever you update the file.',
        'reliability': 'As good as your last edit. Every value carries a cited source in the '
                       'file.',
        'caveat': 'Goes stale silently unless you maintain it. Update the FOMC target range '
                  'the afternoon of each meeting.',
    },
    'fedprob': {
        'name': 'CME Group (not connected)',
        'dataset': 'Fed funds futures implied probabilities (FedWatch)',
        'url': 'https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html',
        'endpoint': None, 'deep_link': None,
        'auth': 'Licensed. No free programmatic source exists.',
        'cadence': 'n/a',
        'reliability': 'n/a',
        'caveat': 'The terminal infers Fed stance from the 2-year Treasury instead. That is a '
                  'proxy, not a market-implied probability, and it is labeled as such.',
    },
    'movefeed': {
        'name': 'ICE (not connected)',
        'dataset': 'ICE BofA MOVE Index',
        'url': 'https://indices.theice.com/',
        'endpoint': None, 'deep_link': None,
        'auth': 'Licensed index.',
        'cadence': 'n/a', 'reliability': 'n/a',
        'caveat': 'MOVE is the single best predictor of MBS spread widening. Its absence is '
                  'the biggest analytical gap in this build.',
    },
    'mbsfeed': {
        'name': 'TBA pricing vendor (not connected)',
        'dataset': 'FNMA 30Y TBA prices',
        'url': 'https://mbslive.net/',
        'endpoint': None, 'deep_link': None,
        'auth': 'Licensed. Tradeweb, MBS Live, or Bloomberg.',
        'cadence': 'n/a', 'reliability': 'n/a',
        'caveat': 'Every MBS_* series here is MODELED from the mortgage rate and the Treasury '
                  'curve. Directionally useful for understanding. Never lock or trade off it.',
    },
}

# Formula and inputs for every computed series, surfaced in the inspector so a
# derived number can be audited rather than trusted.
DERIVATION = {
    'MORT30Y_D': ('last PMMS print + (UST10Y_today - UST10Y_on_PMMS_date) x 0.95',
                  ['MORT30Y', 'UST10Y'],
                  'PMMS is weekly. This carries the last print forward on the 10Y move so '
                  'there is a daily read between Thursdays. The 0.95 beta is the historical '
                  'pass-through of a 10Y move into the mortgage rate.'),
    'MBS_CC': ('MORT30Y_D - 0.50', ['MORT30Y_D'],
               'The 50 bp is the primary/secondary spread: g-fee, servicing, and origination '
               'margin between what a borrower pays and what the bond yields.'),
    'MBS_SPREAD': ('(MBS_CC - (0.5 x UST5Y + 0.5 x UST10Y)) x 100', ['MBS_CC', 'UST5Y', 'UST10Y'],
                   'Benchmarked to a 5s10s blend because MBS duration sits between the two, '
                   'not at 10 years.'),
    'MBS_PRICE': ('100 - 4.5 x (MBS_CC - coupon), with a convexity haircut on the wings',
                  ['MBS_CC'],
                  'Duration 4.5 is a current-coupon TBA approximation. The production coupon '
                  'is pinned to today and held constant across history so the series does not '
                  'print a fake 72-tick jump at a rounding boundary.'),
    'MBS_TICKS': ('(MBS_PRICE_today - MBS_PRICE_yesterday) x 32', ['MBS_PRICE'],
                  'One tick is 1/32 of a point. Around 20 ticks is where lenders reprice.'),
    'MTG_UST_SPREAD': ('(MORT30Y - UST10Y) x 100', ['MORT30Y', 'UST10Y'],
                       'Computed on PMMS print dates against the Treasury close on or before '
                       'that date. Both legs are published data, so this is measurement, not '
                       'a model.'),
    'BRENT_WTI': ('BRENT - OIL', ['BRENT', 'OIL'],
                  'Positive means waterborne global crude is dearer than landlocked US crude, '
                  'which is the normal state. A widening spread usually signals a supply '
                  'shock or shipping risk abroad rather than anything happening in the US. '
                  'A collapsing or negative spread signals a US glut or an export bottleneck.'),
    'CURVE_2S10S': ('(UST10Y - UST2Y) x 100', ['UST10Y', 'UST2Y'], ''),
    'CURVE_5S10S': ('(UST10Y - UST5Y) x 100', ['UST10Y', 'UST5Y'], ''),
    'CURVE_10S30S': ('(UST30Y - UST10Y) x 100', ['UST30Y', 'UST10Y'], ''),
    'NFP': ('NFP_LEVEL_t - NFP_LEVEL_t-1', ['NFP_LEVEL'],
            'BLS publishes the payroll LEVEL. The headline number the market reacts to is the '
            'month-over-month change, computed here.'),
    'CPI_YOY': ('(CPI_t / CPI_t-12 - 1) x 100', ['CPI'], ''),
    'CORECPI_YOY': ('(CORECPI_t / CORECPI_t-12 - 1) x 100', ['CORECPI'], ''),
    'CORECPI_MOM': ('(CORECPI_t / CORECPI_t-1 - 1) x 100', ['CORECPI'],
                    'The month-over-month core print is the highest-variance single number '
                    'for mortgage rates on the monthly calendar.'),
    'AHE_YOY': ('(AHE_LEVEL_t / AHE_LEVEL_t-12 - 1) x 100', ['AHE_LEVEL'], ''),
    'MOVE': ('stdev(daily ΔUST10Y in bp, trailing 20) x sqrt(252)', ['UST10Y'],
             'Realized 10Y yield volatility, annualized to bp. A free, backward-looking proxy '
             'for the licensed ICE MOVE index, which measures the same thing option-implied.'),
    'FED_PROB_CUT': ('((FED_TARGET_LOW + FED_TARGET_HIGH)/2 - UST1Y) x 100',
                     ['FED_TARGET_LOW', 'FED_TARGET_HIGH', 'UST1Y'],
                     'Basis points of easing the 1-year Treasury prices versus the current target '
                     'midpoint. Positive = cuts priced. A curve-based stand-in for CME FedWatch.'),
}

QUALITY_MEANING = {
    LIVE: 'Fetched from the originating source. This is a real observation.',
    DERIVED: 'Exact arithmetic on live observations: a spread, a slope, or a year-over-year '
             'change. Not a model. It is as reliable as the series it is computed from, and '
             'the formula is shown below so you can audit it.',
    MODELED: 'Computed by this terminal from other series. A construction, not an observation. '
             'The formula is shown below so you can audit it.',
    SEED: 'Hand entered in data/manual.json with a cited source. Accurate when entered, and it '
          'will not update itself.',
    STALE: 'The newest value on file is older than this series’ refresh window. The feed '
           'may be down. Treat it as a last known value, not a current one.',
    UNAVAILABLE: 'No data. Either the source needs a key or it has no free feed at all.',
}
