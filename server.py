#!/usr/bin/env python3
"""MRIT server. Python 3 stdlib only. No pip, no venv, no build step.

    python3 server.py            # serve on 5200
    python3 server.py --refresh  # ingest, then serve
    python3 server.py --once     # ingest and exit
"""

import http.server
import json
import os
import socketserver
import sys
import threading
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mrit import api, causal, registry, sources, store   # noqa: E402

PORT = int(os.environ.get('MRIT_PORT', '5200'))
ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, 'web')
MANUAL = os.path.join(ROOT, 'data', 'manual.json')

MIME = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
        '.js': 'text/javascript; charset=utf-8', '.json': 'application/json',
        '.svg': 'image/svg+xml', '.ico': 'image/x-icon'}


def load_manual():
    """Hand-entered observations for series with no free feed (FOMC target range, ISM)."""
    if not os.path.exists(MANUAL):
        return 0
    try:
        with open(MANUAL) as f:
            data = json.load(f)
    except Exception:
        return 0
    obs = []
    for sid, points in (data.get('observations') or {}).items():
        for d, v in points.items():
            if v is not None:
                obs.append({'series_id': sid, 'obs_date': d, 'value': float(v),
                            'quality': registry.SEED, 'source_id': 'manual'})
    if obs:
        store.upsert(obs)
    return len(obs)


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = 'MRIT/0.1'

    def log_message(self, fmt, *args):
        if '--verbose' in sys.argv:
            sys.stderr.write('%s %s\n' % (self.address_string(), fmt % args))

    # ---------------------------------------------------------------- helpers
    def _json(self, payload, code=200):
        body = json.dumps(payload, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _static(self, relpath):
        if relpath in ('', '/'):
            relpath = 'index.html'
        path = os.path.normpath(os.path.join(WEB, relpath.lstrip('/')))
        if not path.startswith(WEB) or not os.path.isfile(path):
            self.send_error(404, 'not found')
            return
        ext = os.path.splitext(path)[1]
        with open(path, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', MIME.get(ext, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(body)))
        # no-store, not no-cache: this is a local tool that is edited live, and a
        # stale cached stylesheet is a confusing class of bug to chase.
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------------- routes
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        q = dict(urllib.parse.parse_qsl(parsed.query))
        if not path.startswith('/api/'):
            return self._static(path)
        try:
            return self._json(self.route(path[5:], q))
        except Exception as e:
            return self._json({'error': '%s: %s' % (type(e).__name__, e)}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        try:
            body = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        except Exception:
            body = {}
        try:
            if parsed.path == '/api/refresh':
                results = sources.refresh(only=body.get('only'))
                load_manual()
                return self._json({'results': results, 'status': api.status()})
            if parsed.path == '/api/pricing':
                return self._json(api.screen_pricing(params=body))
            return self._json({'error': 'unknown endpoint'}, 404)
        except Exception as e:
            return self._json({'error': '%s: %s' % (type(e).__name__, e)}, 500)

    def route(self, name, q):
        con = store.connect()
        try:
            if name == 'dash':
                return api.dash(con=con)
            if name == 'ticker':
                return api.ticker(con=con)
            if name == 'why':
                return api.screen_why(con=con)
            if name == 'ust':
                return api.screen_ust(con=con)
            if name == 'mbs':
                return api.screen_mbs(con=con)
            if name == 'spread':
                return api.screen_spread(con=con)
            if name == 'fed':
                return api.screen_fed(con=con)
            if name == 'calendar':
                return api.screen_calendar(con=con, days=int(q.get('days', 45)))
            if name == 'brief':
                return api.screen_brief(con=con)
            if name == 'pricing':
                return api.screen_pricing(con=con, params=q)
            if name == 'status':
                return api.status(con=con)
            if name == 'chart':
                return api.screen_chart(
                    con=con, primary=q.get('series', 'MORT30Y'),
                    compare=[x for x in (q.get('compare', '')).split(',') if x],
                    events=[x for x in (q.get('events', '')).split(',') if x])
            if name == 'graph':
                return causal.graph_json()
            if name == 'history':
                ids = [s for s in (q.get('series', 'MORT30Y,UST10Y')).split(',') if s]
                return api.screen_history(con=con, series_ids=ids,
                                          days=int(q.get('days', 365)))
            if name.startswith('tier/'):
                return api.screen_tier(int(name.split('/')[1]), con=con)
            if name.startswith('screen-meta/'):
                return api.screen_meta(name.split('/', 1)[1], con=con)
            if name.startswith('series/'):
                return api.series_detail(name.split('/', 1)[1], con=con,
                                         days=int(q.get('days', 1825)))
            return {'error': 'unknown endpoint /api/%s' % name}
        finally:
            con.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def boot(do_refresh):
    store.init()
    causal.assert_invariants()
    n = load_manual()
    if do_refresh:
        print('Ingesting...')
        for r in sources.refresh():
            print('  %-9s %-4s %6s  %s' % (r['source'], r['status'], r['n'], r['detail'][:70]))
    if n:
        print('  manual    OK   %6d  seeded observations' % n)


def main():
    boot('--refresh' in sys.argv or '--once' in sys.argv)
    if '--once' in sys.argv:
        return
    with Server(('127.0.0.1', PORT), Handler) as httpd:
        print('\nMRIT terminal  http://127.0.0.1:%d' % PORT)
        print('Ctrl-C to stop.\n')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nstopped')


if __name__ == '__main__':
    main()
