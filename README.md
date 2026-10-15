# MRIT — Mortgage Rate Intelligence Terminal

A market terminal for a mortgage loan officer. Answers, in under 30 seconds: what rates are
doing, what changed, why, which factor drove it, whether it came from Treasuries or the
spread, what could move rates next, and what to tell a borrower.

```bash
python3 server.py --refresh
```

Then open **http://127.0.0.1:5200**. No pip install, no venv, no build step, no npm.
Python 3.9 stdlib only. Port 5200 (echo-os keeps 5199).

| Flag | Effect |
|---|---|
| *(none)* | serve using whatever is already in the database |
| `--refresh` | ingest every source, then serve |
| `--once` | ingest and exit (for cron) |
| `--verbose` | log requests |

## What is real and what is modeled

This is the part that matters. **Three Tier-1 sources are live and free. Two are not
available at any price below a market-data subscription, and the terminal says so on
screen rather than inventing numbers.**

| Data | Status | Source |
|---|---|---|
| Treasury curve, 1M–30Y, daily, 10-year history | **LIVE** | Treasury.gov XML, no key |
| 30Y / 15Y mortgage rate, weekly | **LIVE** | Freddie Mac PMMS CSV, no key |
| CPI, core CPI, PPI, shelter, payrolls, U-3, earnings | **LIVE** | BLS Public API v2, no key |
| Mortgage / 10Y spread | **LIVE** (derived from two live series) | computed |
| FNMA MBS prices, coupon stack, ticks | **MODELED** | derived, formula shown in the UI |
| Fed funds futures probabilities | **UNAVAILABLE** | licensed CME feed |
| MOVE index | **UNAVAILABLE** | licensed ICE index |
| WTI and Brent crude spot | needs a free EIA key (or FRED) | EIA, the originator |
| VIX, breakevens, credit spreads, Fed balance sheet, housing | needs a free FRED key | FRED |

Every number on every screen carries a badge: `LIVE`, `MODELED`, `SEED`, `STALE`, or
`UNAVAILABLE`. Hover any badge for the source, the observation date, and the fetch time.
Nothing stale is ever painted as current, and nothing missing is ever filled in with a guess.

### Optional: unlock the FRED-backed tiers

```bash
cp config.json.example config.json
# paste a free key from https://fredaccount.stlouisfed.org/apikeys
python3 server.py --refresh
```

That fills Tier 5, 6, and 8 (growth, market conditions, housing) plus PCE and breakevens.
A free BLS key raises BLS limits from 25 to 500 requests a day.

For crude, add an `eia_api_key` (free at eia.gov/opendata/register.php). EIA is the
originator of both benchmarks; FRED just republishes them as `DCOILWTICO` and
`DCOILBRENTEU`, so a FRED key alone will also pick them up as a fallback.

### The two crude benchmarks

`OIL` is **WTI**, Cushing OK spot: light, sweet, landlocked, the US refinery input, so it
drives the gasoline line in headline CPI. `BRENT` is **Brent Europe** spot: waterborne,
prices roughly two thirds of the world's traded crude, and therefore the better read on
global inflation. `BRENT_WTI` is the spread between them, which is the global-versus-domestic
dislocation gauge: it widens on supply shocks or shipping risk abroad, and collapses on a US
glut or an export bottleneck.

Oil is the only input in the terminal that pushes mortgage rates **both ways at once**, and
the causal engine shows both legs rather than netting them:

```
Brent ↑ → inflation expectations ↑ → 10Y ↑ → MBS yield ↑ → mortgage rate ↑   (strength 33%)
Brent ↑ → recession risk ↑       → 10Y ↓ → MBS yield ↓ → mortgage rate ↓   (strength 16%)
```

A modest crude rise is an inflation story. A violent one becomes a demand story, and the
two channels trade places.

## Commands

Press `:` or `Ctrl-K` anywhere.

```
DASH      pressure meter, why rates moved, drivers, brief, calendar
WHY       primary / secondary / counterforce with the full causal trace
UST       full curve, yield curve chart, 2s10s / 5s10s / 10s30s
MBS       FNMA coupon stack, production coupon highlighted   (MODELED)
SPREAD    level, percentile, band, exact Treasury-vs-spread decomposition
FED       stance gauge, balance sheet, FOMC calendar, transmission chain
CPI       inflation releases with surprise scoring
LABOR     employment releases with surprise scoring
GROWTH    GDP, retail, ISM            VOL      VIX, credit, MOVE
HOUSING   sales, starts, permits      CALENDAR events with countdowns
HISTORY   interactive chart, 1M-10Y, overlays
PRICING   rate pricing lab: market rate is not borrower rate
BRIEF     morning brief, EOD review, four audience registers
STATUS    source health and what is missing and why
```

Keys: `[` `]` cycle screens · `r` refresh · `?` help · `Esc` close.

## The inspector — click any number

Every number in the terminal is clickable (and keyboard reachable: Tab to it, press Enter).
The inspector answers four things:

1. **Where it came from.** Source, dataset, ticker, observation date, fetch time, update
   cadence, whether it needs a key, and the exact endpoint MRIT calls. Plus a **deep link
   straight to that series at the source** — a BLS number opens
   `data.bls.gov/timeseries/CUSR0000SA0L1E`, a FRED number opens its FRED page.
2. **How it was computed**, if it is derived. The literal formula, the reasoning behind the
   constants, and clickable chips for every input series so you can drill all the way down
   to a raw observation.
3. **What the level means.** Position in the 1-year and 5-year range, percentile, whether
   the latest move is ordinary or notable, and the largest moves on record.
4. **How it reaches a mortgage rate.** The traced causal chain, path strength, and
   confidence. Or, when there is no chain, it says plainly that the series is context
   rather than a driver.

Every source carries a **caveat** in orange. The PMMS one is the important one: it is a
survey average, Thursday to Wednesday, conforming / 80% LTV / strong credit / ~0.6 points.
It will always look calmer and later than your rate sheet. Never quote it as a borrower rate.

Panel headers on the main screens carry a small **ⓘ** button: what the screen is for, what
question it answers, how to read it, and every source feeding it.

## The two design rules

**1. The decomposition is arithmetic before it is a model.**

```
Δ mortgage rate  ≡  Δ 10Y Treasury  +  Δ spread
```

Both legs come from published data, so the top-level split on the SPREAD screen carries
zero model risk. Only the *attribution* of each leg is inferred, and inferred contributors
are labeled `INFERRED`, ranked below `OBSERVED` ones, and never summed into the headline
number. That is why the pressure meter shows components rather than a single score.

**2. The Fed cannot reach mortgage rates directly.**

The causal graph has no edge from `FED_STANCE` to `MORTGAGE_30Y`. `causal.assert_invariants()`
runs at boot and refuses to start the server if anyone ever adds one. Fed influence can only
travel:

```
Fed policy → growth and inflation expectations → Treasury yields → MBS yields → mortgage rates
```

Every explanation the terminal writes is a traced path through that graph, printed for you,
with a confidence level that drops to MEDIUM or LOW when forces offset.

## Layout

```
server.py            HTTP, routing, static files
mrit/registry.py     series and release definitions  (the data contract)
mrit/store.py        SQLite: observations, releases, edges, alerts, fetch log
mrit/sources.py      ingestion adapters + the MBS model
mrit/analytics.py    surprise z-scores, percentiles, decomposition, pressure meter
mrit/causal.py       relationship graph, propagation, competing forces, confidence
mrit/narrative.py    why-moved, briefs, EOD, four audience registers
mrit/pricing.py      LLPA teaching model and buydown math
mrit/alerts.py       threshold rules, each with a why-it-matters
mrit/api.py          view assembly (the only layer the UI talks to)
web/                 index.html, terminal.css, app.js, screens.js, charts.js, components.js
data/mrit.db         SQLite store
data/manual.json     hand-entered values (FOMC target range), each with a cited source
```

Adding a data series is one row in `registry.py` plus one adapter. Replacing the modeled MBS
feed with a real one is one new class in `sources.py` and one registry edit. Analytics, the
causal engine, and the UI do not change.

## Accessibility

Color never carries meaning alone. `components.arrowLabel()` is the only function allowed to
express direction, and it always emits an arrow glyph plus a text label alongside the color.

## Limits

Not a rate quote. Not a lock recommendation. Not a rate sheet. The Pricing Lab is an
illustrative LLPA model that shows *how* borrower adjustments are structured, not any
lender's matrix; price real scenarios in your lender system. The modeled MBS values are
directionally useful for understanding, and are not tradeable prices.
