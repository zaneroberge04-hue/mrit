// Client-side port of mrit/pricing.py, used only in static mode so the Rate Pricing
// Lab keeps recomputing with no server. It is a faithful line-for-line translation:
// the adjustment grids, the constants, and the output shape all match the Python, so
// renderPricing() in screens.js consumes it unchanged. ILLUSTRATIVE teaching model
// only, never a rate sheet. See pricing.py for the authoritative version.

const DISCLAIMER = 'ILLUSTRATIVE MODEL. Representative structure only, not a rate sheet and not '
  + 'any lender matrix. Never quote these numbers to a borrower. Price live '
  + 'scenarios in your lender system.';

const POINTS_TO_RATE = 0.25;

const FICO_BUCKETS = [[780, 850], [760, 779], [740, 759], [720, 739], [700, 719],
  [680, 699], [660, 679], [640, 659], [620, 639]];
const LTV_BUCKETS = [[0, 60], [60.01, 70], [70.01, 75], [75.01, 80],
  [80.01, 85], [85.01, 90], [90.01, 95], [95.01, 97]];

const CONV_LLPA = {
  '780,850': [0.000, 0.000, 0.000, 0.000, 0.125, 0.125, 0.250, 0.250],
  '760,779': [0.000, 0.000, 0.000, 0.125, 0.250, 0.250, 0.375, 0.375],
  '740,759': [0.000, 0.000, 0.125, 0.250, 0.375, 0.500, 0.625, 0.625],
  '720,739': [0.000, 0.125, 0.250, 0.500, 0.625, 0.750, 0.875, 0.875],
  '700,719': [0.000, 0.250, 0.500, 0.750, 1.000, 1.125, 1.250, 1.250],
  '680,699': [0.000, 0.375, 0.750, 1.000, 1.375, 1.500, 1.625, 1.625],
  '660,679': [0.125, 0.625, 1.125, 1.500, 1.875, 2.000, 2.250, 2.250],
  '640,659': [0.250, 1.000, 1.500, 2.000, 2.500, 2.750, 3.000, 3.000],
  '620,639': [0.500, 1.375, 2.125, 2.750, 3.250, 3.500, 3.750, 3.750],
};

const PRODUCT_BASE = {
  CONVENTIONAL: 0.000, FHA: -0.375, VA: -0.375, USDA: -0.250, JUMBO: 0.125, NONQM: 1.750,
};
const PRODUCT_NOTE = {
  FHA: 'FHA usually prices below conventional on note rate, then charges 1.75% UFMIP '
    + 'plus annual MIP that generally cannot be removed. Compare total cost, not rate.',
  VA: 'VA prices well and has no monthly MI, but carries a funding fee unless exempt.',
  USDA: 'Geographic and income limits apply. Guarantee fee plus annual fee.',
  JUMBO: 'Above the conforming limit. Pricing is investor-specific and reserves matter '
    + 'more than on agency.',
  NONQM: 'Bank statement, DSCR, and similar. Priced for documentation risk, not credit '
    + 'alone. Expect a wide dispersion between investors.',
  CONVENTIONAL: 'Agency execution through DU or LPA. LLPAs are the dominant adjustment.',
};
const OCCUPANCY_ADJ = { PRIMARY: 0.000, SECOND_HOME: 1.125, INVESTMENT: 2.125 };
const PROPERTY_ADJ = { SFR: 0.000, CONDO: 0.750, MANUFACTURED: 0.500, TWO_TO_FOUR: 1.000 };
const TERM_ADJ = { 30: 0.000, 25: -0.125, 20: -0.250, 15: -0.500, 10: -0.500 };

const r3 = (v) => Math.round(v * 1000) / 1000;
const r4 = (v) => Math.round(v * 10000) / 10000;

function ficoBucket(fico) {
  for (const [lo, hi] of FICO_BUCKETS) if (lo <= fico && fico <= hi) return [lo, hi];
  return fico < 620 ? FICO_BUCKETS[FICO_BUCKETS.length - 1] : FICO_BUCKETS[0];
}
function ltvIndex(ltv) {
  for (let i = 0; i < LTV_BUCKETS.length; i++) {
    const [lo, hi] = LTV_BUCKETS[i];
    if (lo <= ltv && ltv <= hi) return i;
  }
  return ltv > 97 ? LTV_BUCKETS.length - 1 : 0;
}

export function payment(principal, annualRate, years = 30) {
  if (!principal || annualRate === null || annualRate === undefined) return null;
  const r = annualRate / 100.0 / 12.0;
  const n = years * 12;
  if (r <= 0) return Math.round((principal / n) * 100) / 100;
  const f = (1 + r) ** n;
  return Math.round((principal * r * f / (f - 1)) * 100) / 100;
}

function teaching(totalRate, dailyMoveBp) {
  const adjBp = Math.abs(totalRate) * 100;
  const sign = (totalRate >= 0 ? '+' : '') + totalRate.toFixed(3);
  const base = `Borrower-level adjustments on this scenario are worth ${sign}% in rate, `
    + `or ${adjBp.toFixed(0)} bp.`;
  if (!dailyMoveBp || Math.abs(dailyMoveBp) < 0.1) {
    return base + ' The market barely moved today, so on this file the borrower '
      + 'profile is the entire story.';
  }
  const ratio = adjBp / Math.abs(dailyMoveBp);
  return base + ` The market moved ${Math.abs(dailyMoveBp).toFixed(1)} bp today, so the `
    + `borrower profile is worth ${ratio.toFixed(0)}x the daily market move. `
    + 'Profile beats market timing on almost every file.';
}

export function price(marketRate, opts = {}) {
  const fico = opts.fico === undefined ? 740 : opts.fico;
  const ltv = opts.ltv === undefined ? 80.0 : opts.ltv;
  const loanAmount = opts.loan_amount === undefined ? 285000 : opts.loan_amount;
  const product = (opts.product || 'CONVENTIONAL').toUpperCase();
  const occupancy = (opts.occupancy || 'PRIMARY').toUpperCase();
  const propertyType = (opts.property_type || 'SFR').toUpperCase();
  const dti = opts.dti === undefined ? 38.0 : opts.dti;
  const points = opts.points === undefined ? 0.0 : opts.points;
  const term = opts.term === undefined ? 30 : opts.term;
  const conformingLimit = opts.conforming_limit === undefined ? 806500 : opts.conforming_limit;
  const dailyMoveBp = opts.daily_move_bp;

  const adjustments = [];
  const add = (name, pts, why, kind = 'LLPA') => {
    adjustments.push({ name, points: r3(pts), rate_effect: r4(pts * POINTS_TO_RATE), why, kind });
  };

  const base = PRODUCT_BASE[product] || 0.0;
  if (Math.abs(base) > 1e-9) {
    adjustments.push({ name: `Product base (${product})`, points: null, rate_effect: base,
      kind: 'BASE', why: PRODUCT_NOTE[product] || '' });
  }

  if (product === 'CONVENTIONAL' || product === 'JUMBO') {
    const fb = ficoBucket(fico);
    const li = ltvIndex(ltv);
    const llpa = CONV_LLPA[fb[0] + ',' + fb[1]][li];
    add(`Credit / LTV grid (${fb[0]}-${fb[1]} FICO, ${ltv.toFixed(0)}% LTV)`, llpa,
      'The agency grid charges for the joint risk of credit and equity. This is the '
      + 'single largest borrower-level adjustment on most files.');
  } else if (product === 'FHA' || product === 'VA' || product === 'USDA') {
    add('Government product: no FICO/LTV grid', 0.0,
      'Government loans do not use agency LLPAs. That is why a 660 FICO borrower at '
      + '96.5% LTV often prices better on FHA than on conventional, even though the '
      + 'MIP makes the total cost higher.');
  }

  if (OCCUPANCY_ADJ[occupancy]) {
    add(`Occupancy: ${titleCase(occupancy)}`, OCCUPANCY_ADJ[occupancy],
      'Investment and second-home borrowers default at higher rates, so the agencies '
      + 'charge for it up front.');
  }
  if (PROPERTY_ADJ[propertyType]) {
    add(`Property type: ${titleCase(propertyType)}`, PROPERTY_ADJ[propertyType],
      'Condo above 75% LTV and 2-4 unit properties carry their own adjustments.');
  }
  if (dti && dti > 40 && (product === 'CONVENTIONAL' || product === 'JUMBO')) {
    add(`DTI above 40% (${dti.toFixed(0)}%)`, 0.375,
      'High-DTI conventional loans above 40% carry an adjustment at most LTVs.');
  }
  if (loanAmount && loanAmount > conformingLimit && product === 'CONVENTIONAL') {
    add('Above conforming limit', 0.375,
      `Loan exceeds the conforming limit of $${conformingLimit.toLocaleString('en-US')}. `
      + 'This should be priced as jumbo.');
  }
  if (TERM_ADJ[term]) {
    adjustments.push({ name: `Term: ${term} year`, points: null, rate_effect: TERM_ADJ[term],
      kind: 'BASE', why: 'Shorter terms carry lower rates because the lender takes less '
        + 'duration risk.' });
  }
  if (points) {
    adjustments.push({ name: 'Discount points paid', points: -Math.abs(points),
      rate_effect: -Math.abs(points) * POINTS_TO_RATE, kind: 'BUYDOWN',
      why: 'Borrower-paid discount. Roughly 1 point buys 0.25% in rate, though the real '
        + 'ratio moves with the MBS coupon stack.' });
  }

  const totalPoints = adjustments.reduce((s, a) => s + (a.points != null ? a.points : 0), 0);
  const totalRate = adjustments.reduce((s, a) => s + a.rate_effect, 0);
  const borrowerRate = (marketRate || 0) + totalRate;

  return {
    market_rate: marketRate,
    borrower_rate: r3(borrowerRate),
    delta: r3(borrowerRate - (marketRate || 0)),
    total_points: r3(totalPoints),
    cost_dollars: Math.round(totalPoints / 100.0 * (loanAmount || 0)),
    adjustments,
    inputs: { fico, ltv, loan_amount: loanAmount, product, occupancy,
      property_type: propertyType, dti, points, term },
    payment: payment(loanAmount, borrowerRate, term),
    disclaimer: DISCLAIMER,
    teaching_point: teaching(totalRate, dailyMoveBp),
  };
}

export function buydown(loanAmount, noteRate, structure = '2-1', term = 30) {
  const steps = ({ '3-2-1': [3, 2, 1], '2-1': [2, 1], '1-0': [1] })[structure] || [2, 1];
  const full = payment(loanAmount, noteRate, term);
  const rows = [];
  let total = 0.0;
  steps.forEach((off, i) => {
    const r = noteRate - off;
    const p = payment(loanAmount, r, term);
    const sub = (full - p) * 12;
    total += sub;
    rows.push({ year: i + 1, rate: r3(r), payment: p,
      monthly_subsidy: Math.round((full - p) * 100) / 100,
      annual_subsidy: Math.round(sub * 100) / 100 });
  });
  rows.push({ year: `${steps.length + 1}+`, rate: r3(noteRate), payment: full,
    monthly_subsidy: 0.0, annual_subsidy: 0.0 });
  return { structure, note_rate: noteRate, note_payment: full, schedule: rows,
    total_cost: Math.round(total * 100) / 100, loan_amount: loanAmount,
    note: 'Seller or builder paid, escrowed at closing and released monthly. The borrower '
      + 'still qualifies at the note rate.' };
}

function titleCase(s) {
  return s.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

const NUMERIC = new Set(['fico', 'ltv', 'loan_amount', 'dti', 'points', 'term']);

// Mirrors api.screen_pricing: takes the baked seed (market rate, options, disclaimer,
// today's market move) plus the UI's param overrides, and returns the full screen shape.
export function priceScenario(seed, params = {}) {
  const kw = { fico: 740, ltv: 80, loan_amount: 285000, product: 'CONVENTIONAL',
    occupancy: 'PRIMARY', property_type: 'SFR', dti: 38, points: 0, term: 30 };
  for (const [k, v] of Object.entries(params)) {
    if (v === '' || v === undefined || v === null) continue;
    kw[k] = NUMERIC.has(k) ? Number(v) : v;
  }
  kw.daily_move_bp = seed.daily_move_bp;
  const market = seed.market_rate;
  const res = price(market, kw);
  return {
    screen: 'PRICING',
    market_rate: market,
    market_rate_quality: seed.market_rate_quality,
    result: res,
    buydowns: ['2-1', '3-2-1', '1-0'].map((s) => buydown(kw.loan_amount, res.borrower_rate, s)),
    options: seed.options,
    disclaimer: seed.disclaimer || DISCLAIMER,
  };
}
