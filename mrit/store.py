"""SQLite persistence. Every read returns quality and provenance with the value."""

import os
import sqlite3
import datetime

from . import registry

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'mrit.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
  id TEXT PRIMARY KEY, name TEXT, ticker TEXT, source_id TEXT, category TEXT,
  tier INTEGER, unit TEXT, refresh TEXT, invert_for_rates INTEGER, notes TEXT
);
CREATE TABLE IF NOT EXISTS observation (
  series_id TEXT NOT NULL, obs_date TEXT NOT NULL, value REAL,
  quality TEXT NOT NULL, source_id TEXT, fetched_at TEXT,
  PRIMARY KEY (series_id, obs_date)
);
CREATE INDEX IF NOT EXISTS ix_obs_series_date ON observation(series_id, obs_date DESC);

CREATE TABLE IF NOT EXISTS release (
  id TEXT PRIMARY KEY, name TEXT, series_id TEXT, tier INTEGER, impact TEXT,
  scheduled_utc TEXT, period TEXT, previous REAL, consensus REAL, actual REAL,
  surprise REAL, surprise_z REAL, classification TEXT, source_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_release_sched ON release(scheduled_utc);

CREATE TABLE IF NOT EXISTS event_reaction (
  release_id TEXT, horizon TEXT, ust10_bp REAL, mbs_ticks REAL,
  mortgage_bp REAL, spread_bp REAL,
  PRIMARY KEY (release_id, horizon)
);
CREATE TABLE IF NOT EXISTS causal_edge (
  src TEXT, dst TEXT, sign INTEGER, weight REAL, lag_days INTEGER,
  confidence REAL, rationale TEXT, PRIMARY KEY (src, dst)
);
CREATE TABLE IF NOT EXISTS alert_rule (
  id TEXT PRIMARY KEY, kind TEXT, threshold REAL, enabled INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS alert_fired (
  id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT, fired_at TEXT, payload_json TEXT
);
CREATE TABLE IF NOT EXISTS fetch_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, started_at TEXT,
  finished_at TEXT, status TEXT, detail TEXT
);
"""


def utcnow():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def connect():
    d = os.path.dirname(DB_PATH)
    if not os.path.isdir(d):
        os.makedirs(d)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con


def init():
    con = connect()
    try:
        con.executescript(SCHEMA)
        for s in registry.SERIES:
            con.execute(
                'INSERT OR REPLACE INTO series'
                '(id,name,ticker,source_id,category,tier,unit,refresh,invert_for_rates,notes)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?)',
                (s['id'], s['name'], s['ticker'], s['source_id'],
                 registry.TIER_NAMES.get(s['tier'], ''), s['tier'], s['unit'],
                 s['refresh'], s['invert_for_rates'], s['notes']))
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- observations

def upsert(obs, con=None):
    """obs: iterable of dicts with series_id, obs_date, value, quality, source_id."""
    own = con is None
    con = con or connect()
    try:
        now = utcnow()
        rows = [(o['series_id'], o['obs_date'], o.get('value'),
                 o.get('quality', registry.LIVE), o.get('source_id', ''),
                 o.get('fetched_at', now)) for o in obs]
        con.executemany(
            'INSERT OR REPLACE INTO observation'
            '(series_id,obs_date,value,quality,source_id,fetched_at) VALUES (?,?,?,?,?,?)', rows)
        if own:
            con.commit()
        return len(rows)
    finally:
        if own:
            con.close()


def history(series_id, limit=None, since=None, con=None):
    """Ascending by date."""
    own = con is None
    con = con or connect()
    try:
        q = 'SELECT obs_date,value,quality,source_id,fetched_at FROM observation ' \
            'WHERE series_id=? AND value IS NOT NULL'
        args = [series_id]
        if since:
            q += ' AND obs_date>=?'
            args.append(since)
        q += ' ORDER BY obs_date DESC'
        if limit:
            q += ' LIMIT %d' % int(limit)
        rows = [dict(r) for r in con.execute(q, args)]
        rows.reverse()
        return rows
    finally:
        if own:
            con.close()


def latest(series_id, con=None, before=None):
    own = con is None
    con = con or connect()
    try:
        q = ('SELECT obs_date,value,quality,source_id,fetched_at FROM observation '
             'WHERE series_id=? AND value IS NOT NULL')
        args = [series_id]
        if before:
            q += ' AND obs_date<?'
            args.append(before)
        q += ' ORDER BY obs_date DESC LIMIT 1'
        r = con.execute(q, args).fetchone()
        return dict(r) if r else None
    finally:
        if own:
            con.close()


def prior(series_id, con=None):
    """The observation immediately before the latest one."""
    cur = latest(series_id, con=con)
    if not cur:
        return None
    return latest(series_id, con=con, before=cur['obs_date'])


def value_on_or_before(series_id, date_str, con=None):
    own = con is None
    con = con or connect()
    try:
        r = con.execute(
            'SELECT obs_date,value,quality FROM observation WHERE series_id=? '
            'AND value IS NOT NULL AND obs_date<=? ORDER BY obs_date DESC LIMIT 1',
            (series_id, date_str)).fetchone()
        return dict(r) if r else None
    finally:
        if own:
            con.close()


def all_latest(con=None):
    """Latest observation for every series, keyed by series_id."""
    own = con is None
    con = con or connect()
    try:
        rows = con.execute(
            'SELECT o.series_id, o.obs_date, o.value, o.quality, o.source_id, o.fetched_at '
            'FROM observation o JOIN ('
            '  SELECT series_id, MAX(obs_date) md FROM observation '
            '  WHERE value IS NOT NULL GROUP BY series_id) m '
            'ON o.series_id=m.series_id AND o.obs_date=m.md').fetchall()
        return dict((r['series_id'], dict(r)) for r in rows)
    finally:
        if own:
            con.close()


# ---------------------------------------------------------------- releases

def upsert_releases(rows, con=None):
    own = con is None
    con = con or connect()
    try:
        con.executemany(
            'INSERT OR REPLACE INTO release(id,name,series_id,tier,impact,scheduled_utc,'
            'period,previous,consensus,actual,surprise,surprise_z,classification,source_id)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [(r['id'], r['name'], r.get('series_id'), r.get('tier'), r.get('impact'),
              r.get('scheduled_utc'), r.get('period'), r.get('previous'), r.get('consensus'),
              r.get('actual'), r.get('surprise'), r.get('surprise_z'),
              r.get('classification'), r.get('source_id', '')) for r in rows])
        if own:
            con.commit()
    finally:
        if own:
            con.close()


def releases(since=None, until=None, con=None):
    own = con is None
    con = con or connect()
    try:
        q, args = 'SELECT * FROM release WHERE 1=1', []
        if since:
            q += ' AND scheduled_utc>=?'
            args.append(since)
        if until:
            q += ' AND scheduled_utc<=?'
            args.append(until)
        q += ' ORDER BY scheduled_utc'
        return [dict(r) for r in con.execute(q, args)]
    finally:
        if own:
            con.close()


# ---------------------------------------------------------------- fetch log

def log_fetch(source_id, started, status, detail='', con=None):
    own = con is None
    con = con or connect()
    try:
        con.execute('INSERT INTO fetch_log(source_id,started_at,finished_at,status,detail)'
                    ' VALUES (?,?,?,?,?)', (source_id, started, utcnow(), status, detail[:500]))
        if own:
            con.commit()
    finally:
        if own:
            con.close()


def fetch_status(con=None):
    own = con is None
    con = con or connect()
    try:
        rows = con.execute(
            'SELECT f.source_id, f.finished_at, f.status, f.detail FROM fetch_log f '
            'JOIN (SELECT source_id, MAX(id) mi FROM fetch_log GROUP BY source_id) m '
            'ON f.id=m.mi ORDER BY f.source_id').fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            con.close()
