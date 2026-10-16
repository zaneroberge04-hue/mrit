#!/usr/bin/env python3
"""Bake MRIT into a fully static site.

Calls the exact same api.* view functions the live server calls, so the JSON a
browser reads from disk is byte-for-byte what the server would have returned.
There is no second implementation of any view to drift out of sync.

    python3 build_static.py            # bake using whatever is in the database
    python3 build_static.py --refresh  # ingest every source first, then bake

Output goes to dist/:

    dist/index.html  terminal.css  *.js      (a copy of web/, plus a static flag)
    dist/data/<screen>.json                  one file per parameterless screen
    dist/data/tier-<n>.json                  tiers 1..8
    dist/data/screen-meta/<name>.json        panel explainers
    dist/data/series/<id>.json               inspector detail, one per series
    dist/data/chart/<id>.json                full-history chart payload, one per series
    dist/data/pricing.json                   market rate + options for the client-side lab
    dist/data/manifest.json                  build time and what was baked

The deployed site never calls Python. The GitHub Action reruns this a few times a
day and Cloudflare serves the result. Visitors cost nothing: no AI, no per-request
compute, no market-data subscription.
"""

import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mrit import api, causal, events as mrit_events, registry, store  # noqa: E402

WEB = os.path.join(HERE, 'web')
DIST = os.path.join(HERE, 'dist')
DATA = os.path.join(DIST, 'data')

ALL_EVENT_KINDS = [k['kind'] for k in mrit_events.kind_catalog()]


def _write(relpath, obj):
    path = os.path.join(DATA, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(obj, f, separators=(',', ':'))
    return os.path.getsize(path)


def _copy_web():
    """Copy web/ into dist/ and flip the static-mode flag in index.html."""
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    shutil.copytree(WEB, DIST)
    idx = os.path.join(DIST, 'index.html')
    with open(idx) as f:
        html = f.read()
    flag = '<script>window.MRIT_STATIC=true;</script>'
    if flag not in html:
        # Inject just before the first module script so it runs first.
        html = html.replace('</head>', '  ' + flag + '\n</head>', 1)
    with open(idx, 'w') as f:
        f.write(html)


def main():
    # Create the schema if the database is new. On a developer machine the db already
    # exists from running server.py, but in CI it starts empty, so refreshing would
    # hit "no such table" without this. init() is CREATE TABLE IF NOT EXISTS, so it is
    # a no-op on an existing db.
    store.init()

    if '--refresh' in sys.argv:
        from mrit import sources
        print('refreshing sources ...')
        for r in sources.refresh():
            print('  ' + str(r))

    _copy_web()
    con = store.connect()
    total = 0
    n = 0

    # ---- parameterless screens -------------------------------------------------
    flat = {
        'dash': api.dash, 'ticker': api.ticker, 'why': api.screen_why,
        'ust': api.screen_ust, 'mbs': api.screen_mbs, 'spread': api.screen_spread,
        'fed': api.screen_fed, 'brief': api.screen_brief, 'status': api.status,
    }
    for name, fn in flat.items():
        total += _write(name + '.json', fn(con=con)); n += 1
    total += _write('graph.json', causal.graph_json()); n += 1
    total += _write('calendar.json', api.screen_calendar(con=con, days=45)); n += 1

    # ---- tiers -----------------------------------------------------------------
    # Written under tier/ so the api path "tier/5" maps straight to the file, the
    # same way "screen-meta/DASH" and "series/UST10Y" do.
    for tier in range(1, 9):
        total += _write('tier/%d.json' % tier, api.screen_tier(tier, con=con)); n += 1

    # ---- panel explainers ------------------------------------------------------
    for screen in api.SCREEN_INFO:
        total += _write('screen-meta/%s.json' % screen, api.screen_meta(screen, con=con)); n += 1

    # ---- inspector detail + chart payload, one file per series -----------------
    marker_floor = (datetime.date.today() - datetime.timedelta(days=1095)).isoformat()
    for s in registry.SERIES:
        sid = s['id']
        total += _write('series/%s.json' % sid, api.series_detail(sid, con=con)); n += 1
        # Base chart with no markers, then attach every event kind but only over the
        # last three years. Older markers are never useful on an overlay, and baking
        # 50+ years of them (MORT30Y starts in 1971) bloats the file 70x. The client
        # filters which kinds to show, so event toggles still need no network.
        chart = api.screen_chart(con=con, primary=sid, compare=[], events=[])
        pts = chart.get('series', [{}])[0].get('points') or []
        if pts:
            lo = max(pts[0][0], marker_floor)
            chart['events'] = mrit_events.markers(lo, pts[-1][0], kinds=ALL_EVENT_KINDS,
                                                  rate_series=sid, con=con)
        total += _write('chart/%s.json' % sid, chart); n += 1

    # ---- pricing lab inputs (the math itself runs client-side) -----------------
    from mrit import analytics
    pricing_seed = api.screen_pricing(con=con, params={})
    # The teaching line sizes borrower adjustments against today's market move, so
    # the client-side lab needs that number alongside the market rate.
    pricing_seed['daily_move_bp'] = analytics.daily_move(con=con).get('ust10_bp')
    total += _write('pricing.json', pricing_seed); n += 1

    # ---- manifest --------------------------------------------------------------
    manifest = {
        'built_at': store.utcnow(),
        'files': n,
        'bytes': total,
        'series': [s['id'] for s in registry.SERIES],
        'event_kinds': ALL_EVENT_KINDS,
    }
    _write('manifest.json', manifest)

    print('baked %d files, %.1f KB into %s' % (n + 1, total / 1024.0, DIST))


if __name__ == '__main__':
    main()
