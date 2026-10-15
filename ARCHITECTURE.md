# MRIT — Mortgage Rate Intelligence Terminal
### Architecture and build plan · v0.1 · 2026-09-02

---

## 0. The constraint that shapes everything

Before design, I probed every candidate data source from this machine. The result reorders the whole plan:

| Source | Status | Auth | What it gives |
|---|---|---|---|
| **Treasury.gov daily yield curve (XML)** | **LIVE, verified** | none | Full curve 1M–30Y, daily, 168 obs YTD 2026 |
| **Freddie Mac PMMS (CSV)** | **LIVE, verified** | none | 30Y and 15Y mortgage rate, weekly, full history |
| **BLS Public API v2** | **LIVE, verified** | none (key raises limits) | CPI, Core CPI, PPI, Shelter, NFP, U-3, AHE |
| FRED API | blocked from this host | free key | VIX, breakevens, credit spreads, Fed balance sheet, PCE |
| **FNMA TBA / MBS pricing** | **NOT FREELY AVAILABLE** | licensed | Real MBS prices, coupon stack, OAS |
| CME FedWatch probabilities | licensed / ToS-restricted | licensed | Fed funds futures implied probabilities |

**Two of your Tier-1 requirements have no free feed: FNMA MBS pricing and Fed funds futures probabilities.** Every product that shows them either licenses the data (MBS Live, Bloomberg, Tradeweb, CME) or scrapes it.

I am not going to fabricate them. The architecture handles this three ways:

1. **`MODELED` series.** MBS current-coupon yield, TBA price, and tick moves are *derived* from the mortgage rate and the Treasury curve using a documented model. Every one is stamped `MODELED` in the UI with the formula visible on hover. They are directionally correct and internally consistent, and they are not a price feed.
2. **`DATA UNAVAILABLE`.** Fed funds futures probabilities render as an explicit unavailable state, not a guess. A `FedProbabilitySource` adapter slot exists for the day you license CME or expense MBS Live.
3. **Adapter swap.** Every series resolves through a source adapter. Adding a real MBS feed is one new file plus one registry line. Zero changes to analytics, causal engine, or UI.

This is your own stated principle ("Never display stale data as real-time. Do not fabricate values"), applied to the hardest case.

---

## 1. Screen architecture

Twelve screens, each addressable by a terminal command. Tab bar plus command bar plus `Ctrl+K` palette.

```
DASH     Home. 30-sec scan. Ticker strip, Rate Pressure Meter,
         Why Rates Moved, Driver Contribution, next events, brief.
WHY      Full causal explanation: primary / secondary / counterforce,
         confidence, propagation trace through the causal graph.
UST      Treasury screen. Full curve 1M-30Y, yield curve chart,
         1D/1W/1M changes, 2s10s / 5s10s / 10s30s slopes.
MBS      MBS screen. Coupon stack 2.0-7.0, price/yield/duration/
         spread, production coupon highlighted. MODELED banner.
SPREAD   Mortgage/Treasury spread. Level, history, percentile,
         tight/normal/wide band, and the decomposition:
         how much of the mortgage rate is Treasury vs spread.
FED      Fed stance gauge, funds rate, balance sheet, QT runoff,
         FOMC calendar. Probabilities render UNAVAILABLE by design.
CPI      Inflation tier. Release table with prev/consensus/actual/
         surprise/classification. Core, headline, PPI, shelter.
LABOR    Labor tier. NFP, U-3, AHE, claims, JOLTS. Same table shape.
GROWTH   Tier 5. GDP, retail sales, ISM, durable goods.
CALENDAR Event calendar filtered to rate-relevant releases, with
         countdown timers, impact rating, historical reaction.
HISTORY  Interactive rate chart. 1D-10Y ranges, overlay series.
PRICING  Rate Pricing Lab. LLPA-style borrower adjustments.
BRIEF    Morning brief / EOD review / audience translations.
```

Global: `?` help, `Esc` command bar, `[`/`]` cycle screens, `r` refresh.

---

## 2. Data architecture

Five layers, hard boundaries. Each layer only knows the one below it.

```
                    ┌──────────────────────────────┐
   web/             │  UI  (vanilla ES modules)    │
                    └──────────────┬───────────────┘
                                   │ JSON over /api/*
                    ┌──────────────┴───────────────┐
   mrit/api.py      │  API / VIEW ASSEMBLY         │
                    └──────────────┬───────────────┘
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
  ┌───────┴────────┐  ┌────────────┴────────┐  ┌────────────┴───────┐
  │ analytics.py   │  │ causal.py           │  │ narrative.py       │
  │ surprise, z,   │  │ relationship graph, │  │ why-moved, brief,  │
  │ percentile,    │  │ propagation,        │  │ EOD, audience      │
  │ decomposition, │  │ competing forces    │  │ translation        │
  │ pressure meter │  │                     │  │ + alerts.py        │
  └───────┬────────┘  └────────────┬────────┘  └────────────┬───────┘
          └────────────────────────┼────────────────────────┘
                    ┌──────────────┴───────────────┐
   mrit/store.py    │  STORE  (SQLite)             │
                    └──────────────┬───────────────┘
                    ┌──────────────┴───────────────┐
   mrit/sources.py  │  INGESTION  (adapters)       │
                    │  Treasury · PMMS · BLS ·     │
                    │  FRED · Derived · <slots>    │
                    └──────────────────────────────┘
```

**Every observation carries:** `series_id, date, value, source_id, fetched_at, quality`.
`quality ∈ {LIVE, MODELED, SEED, STALE, UNAVAILABLE}` and drives a visible badge on every number.

---

## 3. Technical stack

| Layer | Choice | Why |
|---|---|---|
| Server | **Python 3.9 stdlib only** (`http.server`, `sqlite3`, `urllib`, `xml.etree`, `csv`) | Your machine has Python 3.9.6 and no `requests`. Zero pip installs, zero venv, zero dependency rot. Matches `serve.py`. |
| Store | **SQLite** (stdlib) | Single file. Gives you the historical event-impact database Phase 3 needs, for free. |
| Frontend | **Vanilla ES modules, no build step** | Matches `echo-os.html`. No npm, no bundler, no CDN. Works offline. |
| Charts | **Hand-rolled SVG** | No CDN means no Chart.js. Full control over terminal aesthetics. ~200 lines. |
| Port | **5200** | `echo-os` owns 5199. |

**Why not React/Next/FastAPI:** you are one person who will maintain this between loan files. Every dependency is a future breakage you have to debug instead of originating. The moment this needs a team, the layer boundaries above make the port mechanical.

---

## 4. Component hierarchy (frontend)

```
app.js                    bootstrap, state, router, keyboard, command bar
├─ CommandBar             ":" / Ctrl+K, fuzzy match over command registry
├─ TickerStrip            always-visible Tier-1 strip
├─ StatusBar              data freshness, source count, clock, last refresh
└─ ScreenHost
   ├─ screens.js          one render fn per screen, pure (state) -> DOM
   │  ├─ renderDash        ├─ renderUST       ├─ renderCPI
   │  ├─ renderWhy         ├─ renderMBS       ├─ renderLabor
   │  ├─ renderSpread      ├─ renderFed       ├─ renderGrowth
   │  ├─ renderCalendar    ├─ renderHistory   ├─ renderPricing
   │  └─ renderBrief
   └─ charts.js           SVG primitives
      ├─ lineChart        multi-series, overlays, range selection
      ├─ curveChart       yield curve with prior-period ghost
      ├─ pressureGauge    5-band meter with contributor bars
      └─ sparkline        inline micro-chart for tables
components.js             tile, dataCell(value+quality badge), table,
                          arrowLabel(dir+text, never color-only), pill
```

**Accessibility rule enforced in one place:** `arrowLabel()` is the only function permitted to express direction. It always emits arrow glyph + text label + color. Nothing else may use color alone.

---

## 5. Database schema

```sql
series(
  id TEXT PRIMARY KEY,        -- 'UST10Y'
  name TEXT, ticker TEXT, source_id TEXT, category TEXT, tier INTEGER,
  unit TEXT,                  -- 'percent'|'index'|'bps'|'thousands'|'price32'
  refresh TEXT,               -- 'daily'|'weekly'|'monthly'|'realtime'
  invert_for_rates INTEGER,   -- 1 if a rise in this series pushes rates DOWN
  notes TEXT
)

observation(
  series_id TEXT, obs_date TEXT, value REAL,
  quality TEXT,               -- LIVE|MODELED|SEED|STALE|UNAVAILABLE
  source_id TEXT, fetched_at TEXT,
  PRIMARY KEY (series_id, obs_date)
)

release(                      -- scheduled economic events
  id TEXT PRIMARY KEY, name TEXT, series_id TEXT, tier INTEGER,
  impact TEXT,                -- HIGH|MEDIUM|LOW
  scheduled_utc TEXT, period TEXT,
  previous REAL, consensus REAL, actual REAL,
  surprise REAL, surprise_z REAL,
  classification TEXT,        -- VERY_BULLISH..VERY_BEARISH (for rates)
  source_id TEXT
)

event_reaction(               -- Phase 3 learning substrate
  release_id TEXT, horizon TEXT,     -- '1d'|'1w'
  ust10_bp REAL, mbs_ticks REAL, mortgage_bp REAL, spread_bp REAL
)

causal_edge(                  -- persisted so weights can be re-fit from data
  src TEXT, dst TEXT, sign INTEGER, weight REAL,
  lag_days INTEGER, confidence REAL, rationale TEXT
)

alert_rule(id, kind, threshold, enabled, note)
alert_fired(id, rule_id, fired_at, payload_json)
fetch_log(source_id, started_at, finished_at, status, detail)
```

---

## 6. Data-source strategy

**Adapter contract** (`sources.py`): every adapter implements `fetch() -> List[Obs]` and declares `source_id`, `requires_key`, `cadence`. Failure is caught, logged to `fetch_log`, and leaves prior observations in place marked `STALE`. A failed source never blanks the screen and never silently serves old data as new.

| Adapter | Series | Auth | Cadence |
|---|---|---|---|
| `TreasuryCurveSource` | UST1M…UST30Y (11 tenors) | none | daily |
| `PMMSSource` | MORT30Y, MORT15Y | none | weekly (Thu) |
| `BLSSource` | CPI, CORECPI, PPI, SHELTER, NFP, UNRATE, AHE | none | monthly |
| `DerivedSource` | MBS current coupon, TBA price/ticks, MTG/UST spread, curve slopes, y/y and m/m transforms | n/a | on read |
| `FREDSource` | VIX, T10YIE, BAMLH0A0HYM2, WALCL, PCE, DFF | free key | daily |
| `MBSFeedSource` | **slot** — real TBA stack | licensed | — |
| `FedProbSource` | **slot** — CME implied probabilities | licensed | — |

**The MBS model, stated openly** (rendered in the UI on hover):

```
current_coupon_yield  = MORT30Y − primary_secondary_spread(0.50%)
mbs_benchmark         = 0.5 × UST5Y + 0.5 × UST10Y     # duration-matched
mbs_spread_bp         = (current_coupon_yield − mbs_benchmark) × 100
tba_price_change_pts  = −effective_duration(4.5) × Δcurrent_coupon_yield
ticks_32nds           = tba_price_change_pts × 32
```

---

## 7. Causal model

A directed graph of signed, weighted, lagged edges. Not a black box: every explanation the terminal produces is a **traced path through this graph**, printed for the user.

**Nodes** (38): the eight tiers plus latent nodes `RECESSION_RISK`, `INFL_EXPECT`, `RISK_APPETITE`, `TERM_PREMIUM`, `TSY_SUPPLY`, `FOREIGN_DEMAND`.

**Terminal node:** `MORTGAGE_30Y`. Every path resolves there.

**Core transmission chain (the one the UI teaches):**

```
Fed policy ─→ growth/inflation expectations ─→ Treasury yields ─→ MBS yields ─→ mortgage rates
```

The Fed node has **no direct edge to `MORTGAGE_30Y`.** It is structurally impossible for this engine to say the Fed sets mortgage rates.

**Representative edges** `(src → dst, sign, weight, confidence)`:

```
CORE_CPI      → INFL_EXPECT   +0.80  HIGH      NFP        → RECESSION_RISK −0.70 HIGH
INFL_EXPECT   → UST_10Y       +0.70  HIGH      UNRATE     → RECESSION_RISK +0.70 HIGH
CORE_CPI      → FED_STANCE    +0.90  HIGH      RECESSION_RISK → UST_10Y    −0.75 HIGH
FED_STANCE    → UST_2Y        +0.85  HIGH      UST_10Y    → MBS_YIELD      +0.90 HIGH
UST_2Y        → UST_10Y       +0.50  MEDIUM    MBS_YIELD  → MORTGAGE_30Y   +0.95 HIGH
AHE           → INFL_EXPECT   +0.50  MEDIUM    MBS_SPREAD → MORTGAGE_30Y   +0.90 HIGH
OIL           → INFL_EXPECT   +0.50  MEDIUM    MOVE_VOL   → MBS_SPREAD     +0.80 HIGH
RISK_APPETITE → UST_10Y       +0.40  MEDIUM    HY_SPREAD  → MBS_SPREAD     +0.50 MEDIUM
FOREIGN_DEMAND→ UST_10Y       −0.60  MEDIUM    QT_RUNOFF  → MBS_SPREAD     +0.60 MEDIUM
TSY_SUPPLY    → UST_10Y       +0.50  MEDIUM    MBS_PRICE  → MBS_YIELD      −1.00 HIGH
```

**Competing forces are first-class.** Propagation returns *all* paths with their signed contributions, so the engine naturally produces:

```
10Y −7bp        → mortgage −6.3bp   (path: NFP → RECESSION_RISK → UST_10Y → MBS_YIELD → MORTGAGE_30Y)
MOVE +8         → spread +4bp       (path: MOVE_VOL → MBS_SPREAD → MORTGAGE_30Y)
NET             → mortgage −2.3bp   CONFIDENCE: MEDIUM (offsetting forces)
```

**Confidence rule:** `HIGH` when one path carries >60% of absolute contribution and its edges are all high-confidence. `MEDIUM` when contributions are split or a medium edge is load-bearing. `LOW` when net magnitude is under the noise floor, or when top contributors offset within 25%.

**Rate Pressure Meter is an exact identity first, attribution second:**

```
Δmortgage ≡ Δ(10Y) + Δ(spread)          # arithmetically exact, no model
   then Δ(10Y)     is attributed to data surprises, Fed repricing, oil, risk, supply
   then Δ(spread)  is attributed to volatility, credit, Fed balance sheet
```

The top-level split is arithmetic, not an algorithm. Only the second stage is modeled, and it is shown as ranked contributors with individual confidence, never collapsed to a single score. This is exactly your "do not reduce everything to one simplistic algorithm" requirement.

---

## 8. MVP implementation sequence

| # | Step | Output |
|---|---|---|
| 1 | Registry + store | Series contract, SQLite schema |
| 2 | Live adapters | Treasury, PMMS, BLS ingesting real data |
| 3 | Derived adapter | Spread, curve slopes, MBS model, transforms |
| 4 | Analytics | Surprise z-scores, percentiles, decomposition, pressure |
| 5 | Causal engine | Graph, propagation, competing forces, confidence |
| 6 | Narrative | Why-moved, brief, EOD, four audience registers |
| 7 | API | `/api/dash`, `/api/screen/<id>`, `/api/series/<id>`, `/api/refresh` |
| 8 | Terminal shell | Command bar, router, ticker, status bar, keyboard |
| 9 | Screens | 12 renderers |
| 10 | Charts | line, curve, gauge, sparkline |
| 11 | Verify | Fetch live, assert real values, screenshot |

**Phase 2:** FRED key wiring (VIX/MOVE/breakevens/credit/balance sheet), event-reaction backfill, alerts engine, news ingestion.
**Phase 3:** learned edge weights re-fit from `event_reaction`, licensed MBS feed, CME probabilities, full LLPA engine with real rate sheets, mobile.

---

## 9. What this will and will not do

**Will:** show real Treasury, mortgage, and BLS data with sourcing and timestamps; decompose today's move arithmetically; trace causation through an inspectable graph; state confidence; refuse to display stale data as live.

**Will not:** price a live lock, quote a real borrower rate, show real MBS prices, predict rates, or replace your lender's rate sheet. The Pricing Lab is an *illustrative* LLPA model, labeled as such, for teaching `MARKET RATE ≠ BORROWER RATE`. It is not a pricing engine and must never be shown to a borrower as one.
