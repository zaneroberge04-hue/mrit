"""RATE PRICING LAB.

Purpose: demonstrate visually that MARKET RATE != BORROWER RATE.

This is an ILLUSTRATIVE teaching model, not a pricing engine. The adjustment values
are representative of how agency LLPAs and product overlays are structured, not any
lender's live matrix. Nothing here may be quoted to a borrower.
"""

DISCLAIMER = ('ILLUSTRATIVE MODEL. Representative structure only, not a rate sheet and not '
              'any lender matrix. Never quote these numbers to a borrower. Price live '
              'scenarios in your lender system.')

# Points of cost. Positive = worse for the borrower. Converted to rate at the ratio below.
POINTS_TO_RATE = 0.25 / 1.0     # 1.00 point of cost is roughly 0.25% in rate

FICO_BUCKETS = [(780, 850), (760, 779), (740, 759), (720, 739), (700, 719),
                (680, 699), (660, 679), (640, 659), (620, 639)]
LTV_BUCKETS = [(0, 60), (60.01, 70), (70.01, 75), (75.01, 80),
               (80.01, 85), (85.01, 90), (90.01, 95), (95.01, 97)]

# Conventional purchase LLPA, points of cost. Structure mirrors the agency grid shape:
# cost rises as FICO falls and as LTV rises, with the 80.01-95 band worst at low FICO.
CONV_LLPA = {
    (780, 850): [0.000, 0.000, 0.000, 0.000, 0.125, 0.125, 0.250, 0.250],
    (760, 779): [0.000, 0.000, 0.000, 0.125, 0.250, 0.250, 0.375, 0.375],
    (740, 759): [0.000, 0.000, 0.125, 0.250, 0.375, 0.500, 0.625, 0.625],
    (720, 739): [0.000, 0.125, 0.250, 0.500, 0.625, 0.750, 0.875, 0.875],
    (700, 719): [0.000, 0.250, 0.500, 0.750, 1.000, 1.125, 1.250, 1.250],
    (680, 699): [0.000, 0.375, 0.750, 1.000, 1.375, 1.500, 1.625, 1.625],
    (660, 679): [0.125, 0.625, 1.125, 1.500, 1.875, 2.000, 2.250, 2.250],
    (640, 659): [0.250, 1.000, 1.500, 2.000, 2.500, 2.750, 3.000, 3.000],
    (620, 639): [0.500, 1.375, 2.125, 2.750, 3.250, 3.500, 3.750, 3.750],
}

# Product spread to the conventional 30-year par rate, in rate points.
PRODUCT_BASE = {
    'CONVENTIONAL': 0.000,
    'FHA': -0.375,      # lower note rate, but MIP is the real cost
    'VA': -0.375,
    'USDA': -0.250,
    'JUMBO': 0.125,
    'NONQM': 1.750,
}
PRODUCT_NOTE = {
    'FHA': 'FHA usually prices below conventional on note rate, then charges 1.75% UFMIP '
           'plus annual MIP that generally cannot be removed. Compare total cost, not rate.',
    'VA': 'VA prices well and has no monthly MI, but carries a funding fee unless exempt.',
    'USDA': 'Geographic and income limits apply. Guarantee fee plus annual fee.',
    'JUMBO': 'Above the conforming limit. Pricing is investor-specific and reserves matter '
             'more than on agency.',
    'NONQM': 'Bank statement, DSCR, and similar. Priced for documentation risk, not credit '
             'alone. Expect a wide dispersion between investors.',
    'CONVENTIONAL': 'Agency execution through DU or LPA. LLPAs are the dominant adjustment.',
}

OCCUPANCY_ADJ = {'PRIMARY': 0.000, 'SECOND_HOME': 1.125, 'INVESTMENT': 2.125}
PROPERTY_ADJ = {'SFR': 0.000, 'CONDO': 0.750, 'MANUFACTURED': 0.500, 'TWO_TO_FOUR': 1.000}
TERM_ADJ = {30: 0.000, 25: -0.125, 20: -0.250, 15: -0.500, 10: -0.500}


def _fico_bucket(fico):
    for lo, hi in FICO_BUCKETS:
        if lo <= fico <= hi:
            return (lo, hi)
    return FICO_BUCKETS[-1] if fico < 620 else FICO_BUCKETS[0]


def _ltv_index(ltv):
    for i, (lo, hi) in enumerate(LTV_BUCKETS):
        if lo <= ltv <= hi:
            return i
    return len(LTV_BUCKETS) - 1 if ltv > 97 else 0


def price(market_rate, fico=740, ltv=80.0, loan_amount=285000, product='CONVENTIONAL',
          occupancy='PRIMARY', property_type='SFR', dti=38.0, points=0.0, term=30,
          conforming_limit=806500, daily_move_bp=None):
    """Return a full adjustment stack from market rate to illustrative borrower rate."""
    product = (product or 'CONVENTIONAL').upper()
    occupancy = (occupancy or 'PRIMARY').upper()
    property_type = (property_type or 'SFR').upper()
    adjustments = []

    def add(name, pts, why, kind='LLPA'):
        adjustments.append({'name': name, 'points': round(pts, 3),
                            'rate_effect': round(pts * POINTS_TO_RATE, 4),
                            'why': why, 'kind': kind})

    base = PRODUCT_BASE.get(product, 0.0)
    if abs(base) > 1e-9:
        adjustments.append({'name': 'Product base (%s)' % product, 'points': None,
                            'rate_effect': base, 'kind': 'BASE',
                            'why': PRODUCT_NOTE.get(product, '')})

    if product in ('CONVENTIONAL', 'JUMBO'):
        fb = _fico_bucket(fico)
        li = _ltv_index(ltv)
        llpa = CONV_LLPA[fb][li]
        add('Credit / LTV grid (%d-%d FICO, %.0f%% LTV)' % (fb[0], fb[1], ltv), llpa,
            'The agency grid charges for the joint risk of credit and equity. This is the '
            'single largest borrower-level adjustment on most files.')
    elif product in ('FHA', 'VA', 'USDA'):
        add('Government product: no FICO/LTV grid', 0.0,
            'Government loans do not use agency LLPAs. That is why a 660 FICO borrower at '
            '96.5% LTV often prices better on FHA than on conventional, even though the '
            'MIP makes the total cost higher.')

    if OCCUPANCY_ADJ.get(occupancy):
        add('Occupancy: %s' % occupancy.replace('_', ' ').title(), OCCUPANCY_ADJ[occupancy],
            'Investment and second-home borrowers default at higher rates, so the agencies '
            'charge for it up front.')
    if PROPERTY_ADJ.get(property_type):
        add('Property type: %s' % property_type.replace('_', ' ').title(),
            PROPERTY_ADJ[property_type],
            'Condo above 75% LTV and 2-4 unit properties carry their own adjustments.')
    if dti and dti > 40 and product in ('CONVENTIONAL', 'JUMBO'):
        add('DTI above 40%%(%.0f%%)' % dti, 0.375,
            'High-DTI conventional loans above 40% carry an adjustment at most LTVs.')
    if loan_amount and loan_amount > conforming_limit and product == 'CONVENTIONAL':
        add('Above conforming limit', 0.375,
            'Loan exceeds the conforming limit of $%s. This should be priced as jumbo.'
            % format(conforming_limit, ','))
    if TERM_ADJ.get(term):
        adjustments.append({'name': 'Term: %d year' % term, 'points': None,
                            'rate_effect': TERM_ADJ[term], 'kind': 'BASE',
                            'why': 'Shorter terms carry lower rates because the lender takes '
                                   'less duration risk.'})
    if points:
        adjustments.append({'name': 'Discount points paid', 'points': -abs(points),
                            'rate_effect': -abs(points) * POINTS_TO_RATE, 'kind': 'BUYDOWN',
                            'why': 'Borrower-paid discount. Roughly 1 point buys 0.25% in '
                                   'rate, though the real ratio moves with the MBS coupon '
                                   'stack.'})

    total_points = sum(a['points'] for a in adjustments if a.get('points') is not None)
    total_rate = sum(a['rate_effect'] for a in adjustments)
    borrower_rate = (market_rate or 0) + total_rate

    return {
        'market_rate': market_rate,
        'borrower_rate': round(borrower_rate, 3),
        'delta': round(borrower_rate - (market_rate or 0), 3),
        'total_points': round(total_points, 3),
        'cost_dollars': round(total_points / 100.0 * (loan_amount or 0), 0),
        'adjustments': adjustments,
        'inputs': {'fico': fico, 'ltv': ltv, 'loan_amount': loan_amount, 'product': product,
                   'occupancy': occupancy, 'property_type': property_type, 'dti': dti,
                   'points': points, 'term': term},
        'payment': payment(loan_amount, borrower_rate, term),
        'disclaimer': DISCLAIMER,
        'teaching_point': _teaching(total_rate, daily_move_bp),
    }


def _teaching(total_rate, daily_move_bp):
    """Size the borrower adjustments against the actual observed market move."""
    adj_bp = abs(total_rate) * 100
    base = ('Borrower-level adjustments on this scenario are worth %+.3f%% in rate, '
            'or %.0f bp.' % (total_rate, adj_bp))
    if not daily_move_bp or abs(daily_move_bp) < 0.1:
        return base + (' The market barely moved today, so on this file the borrower '
                       'profile is the entire story.')
    ratio = adj_bp / abs(daily_move_bp)
    return base + (' The market moved %.1f bp today, so the borrower profile is worth %.0fx '
                   'the daily market move. Profile beats market timing on almost every file.'
                   % (abs(daily_move_bp), ratio))


def payment(principal, annual_rate, years=30):
    if not principal or annual_rate is None:
        return None
    r = annual_rate / 100.0 / 12.0
    n = years * 12
    if r <= 0:
        return round(principal / n, 2)
    f = (1 + r) ** n
    return round(principal * r * f / (f - 1), 2)


def buydown(loan_amount, note_rate, structure='2-1', term=30):
    """Temporary buydown schedule and total subsidy cost."""
    steps = {'3-2-1': [3, 2, 1], '2-1': [2, 1], '1-0': [1]}.get(structure, [2, 1])
    full = payment(loan_amount, note_rate, term)
    rows, total = [], 0.0
    for i, off in enumerate(steps):
        r = note_rate - off
        p = payment(loan_amount, r, term)
        sub = (full - p) * 12
        total += sub
        rows.append({'year': i + 1, 'rate': round(r, 3), 'payment': p,
                     'monthly_subsidy': round(full - p, 2), 'annual_subsidy': round(sub, 2)})
    rows.append({'year': '%d+' % (len(steps) + 1), 'rate': round(note_rate, 3),
                 'payment': full, 'monthly_subsidy': 0.0, 'annual_subsidy': 0.0})
    return {'structure': structure, 'note_rate': note_rate, 'note_payment': full,
            'schedule': rows, 'total_cost': round(total, 2),
            'loan_amount': loan_amount,
            'note': 'Seller or builder paid, escrowed at closing and released monthly. '
                    'The borrower still qualifies at the note rate.'}


def grid(market_rate, ltv=80.0, product='CONVENTIONAL', **kw):
    """Full FICO x LTV borrower-rate grid for the heat map."""
    rows = []
    for lo, hi in FICO_BUCKETS:
        cells = []
        for llo, lhi in LTV_BUCKETS:
            p = price(market_rate, fico=(lo + hi) // 2, ltv=lhi, product=product, **kw)
            cells.append({'ltv': lhi, 'rate': p['borrower_rate'], 'points': p['total_points']})
        rows.append({'fico_low': lo, 'fico_high': hi, 'cells': cells})
    return {'rows': rows, 'ltv_buckets': [b[1] for b in LTV_BUCKETS],
            'market_rate': market_rate, 'disclaimer': DISCLAIMER}
