#!/usr/bin/env python3
"""
First-party funnel analytics.

Why this exists alongside the Meta Pixel: Pixel data lives in Ads Manager, is
shaped for ad attribution rather than diagnosis, and silently loses everyone
running a blocker. This answers a different question — how many people reached
the site, and where they dropped out — from the site's own records.

Deliberately small: SQLite from the stdlib, on the same Railway volume as
store.json. The service runs a single replica (a volume pins it to one) and
server.py is a plain HTTPServer that handles one request at a time, so there is
no write contention to design around. The write path is one INSERT.

Privacy: no IP address and no user agent are ever stored. The UA is read once to
drop bots and then discarded. The visitor id is a random value minted in the
browser and means nothing outside this database.
"""
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

# ── Funnel ────────────────────────────────────────────────────────────────────
# Order matters: the report walks this list to compute step-to-step drop-off.
STAGES = [
    'visit',
    'view_product',
    'add_to_cart',
    'details',
    'summary',
    'checkout_created',
    'purchase',
]

STAGE_LABELS = {
    'visit':            'ביקורים',
    'view_product':     'צפייה במוצר',
    'add_to_cart':      'הוספה לעגלה',
    'details':          'פרטים אישיים',
    'summary':          'סיכום הזמנה',
    'checkout_created': 'מעבר לתשלום',
    'purchase':         'רכישה',
}

# Recorded by server.py only. A browser claiming one of these is ignored —
# otherwise anyone could POST themselves a purchase and corrupt the numbers.
SERVER_ONLY_STAGES = {'checkout_created', 'purchase'}
BROWSER_STAGES     = [s for s in STAGES if s not in SERVER_ONLY_STAGES]

SOURCES = ['paid_meta', 'paid_other', 'organic_search', 'referral', 'direct']

SOURCE_LABELS = {
    'paid_meta':      'ממומן — מטה',
    'paid_other':     'ממומן — אחר',
    'organic_search': 'חיפוש אורגני',
    'referral':       'הפניה מאתר',
    'direct':         'ישיר',
}

_BOT_RE = re.compile(
    r'bot|crawl|spider|slurp|facebookexternalhit|preview|monitor|uptime|'
    r'headless|curl|wget|python-requests|axios|postman|railway|health',
    re.I,
)


def is_bot(user_agent):
    """Cheap UA filter. Most crawlers never run JS and so never reach the beacon
    at all; this catches the ones that do, plus Railway's own health checks."""
    return bool(_BOT_RE.search(user_agent or ''))


# ── Israel-time buckets ───────────────────────────────────────────────────────
def _il_now():
    """Now, in Israel. The container runs on UTC, and the owner reads these
    numbers in local time — an event at 00:30 Tel Aviv belongs to that day, not
    to the previous one."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Asia/Jerusalem'))
    except Exception:
        return datetime.now(timezone(timedelta(hours=3)))


def _buckets(when=None):
    """('2026-08-16 14', '2026-08-16') for one event.

    Computed at insert time rather than by offsetting UTC in the report query:
    Israel switches between UTC+2 and UTC+3, and a fixed offset in SQL would
    quietly file events into the wrong hour for half the year.
    """
    dt = when or _il_now()
    return dt.strftime('%Y-%m-%d %H'), dt.strftime('%Y-%m-%d')


# ── Connection ────────────────────────────────────────────────────────────────
_db_path = None
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id       INTEGER PRIMARY KEY,
  ts       INTEGER NOT NULL,
  il_hour  TEXT NOT NULL,
  il_day   TEXT NOT NULL,
  visitor  TEXT NOT NULL,
  session  TEXT NOT NULL,
  stage    TEXT NOT NULL,
  source   TEXT NOT NULL,
  campaign TEXT,
  order_id TEXT,
  value    REAL
);
CREATE INDEX IF NOT EXISTS ix_events_day   ON events(il_day);
CREATE INDEX IF NOT EXISTS ix_events_stage ON events(stage, il_day);
CREATE INDEX IF NOT EXISTS ix_events_vis   ON events(visitor);

CREATE TABLE IF NOT EXISTS visitors (
  visitor    TEXT PRIMARY KEY,
  first_seen INTEGER NOT NULL,
  source     TEXT NOT NULL,
  campaign   TEXT,
  excluded   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_visitors_excl ON visitors(excluded);

-- A ledger of every event sent to Meta, from both channels, so event_id
-- coverage and deduplication can be measured from what we actually sent rather
-- than inferred from Events Manager's own reporting window.
CREATE TABLE IF NOT EXISTS meta_events (
  id         INTEGER PRIMARY KEY,
  ts         INTEGER NOT NULL,
  il_day     TEXT NOT NULL,
  event_name TEXT NOT NULL,
  event_id   TEXT NOT NULL,
  channel    TEXT NOT NULL,   -- 'browser' | 'server'
  status     TEXT,
  value      REAL             -- the event's value parameter; NULL when it has none
);
CREATE INDEX IF NOT EXISTS ix_meta_day ON meta_events(il_day);
CREATE INDEX IF NOT EXISTS ix_meta_eid ON meta_events(event_id);
"""


def init(data_dir):
    """Point the module at a directory and make sure the schema is there."""
    global _db_path
    with _lock:
        _db_path = os.path.join(data_dir, 'analytics.db')
        try:
            with _connect() as db:
                db.executescript(SCHEMA)
                _migrate(db)
            return True
        except Exception as e:
            # Analytics must never stop the store from serving. If the DB can't
            # be opened, every call below turns into a no-op.
            print(f'  [Analytics] Could not open {_db_path}: {e}')
            _db_path = None
            return False


# Columns added after the table first shipped. CREATE TABLE IF NOT EXISTS will
# not add them to the database already on the Railway volume, so each is applied
# separately and a duplicate-column error is the expected no-op.
_MIGRATIONS = (
    ('meta_events', 'value', 'REAL'),
)


def _migrate(db):
    for table, column, coltype in _MIGRATIONS:
        try:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {coltype}')
            print(f'  [Analytics] migrated: {table}.{column} added')
        except sqlite3.OperationalError as e:
            if 'duplicate column' not in str(e).lower():
                raise


def _connect():
    db = sqlite3.connect(_db_path, timeout=5)
    # WAL so a reporting read can never block the write path.
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=NORMAL')
    db.row_factory = sqlite3.Row
    return db


def ready():
    return _db_path is not None


# ── Writing ───────────────────────────────────────────────────────────────────
def _clean(value, limit=64):
    """Everything here arrives from the open internet. Truncate hard and keep
    only characters that could appear in an id, a source or a campaign name."""
    return re.sub(r'[^\w.\- ]', '', str(value or ''))[:limit]


def record(stage, visitor, session='', source='direct', campaign='',
           order_id='', value=None):
    """Append one funnel event. Never raises — a failure here must not surface
    in a page request, let alone in checkout."""
    if not ready():
        return False
    stage   = _clean(stage, 32)
    visitor = _clean(visitor, 64)
    if stage not in STAGES or not visitor:
        return False
    source = source if source in SOURCES else 'direct'
    hour, day = _buckets()
    try:
        with _lock, _connect() as db:
            # First touch wins: the source recorded against a visitor is where
            # they originally came from, which is the useful answer to "did the
            # ad bring me this customer". The per-event source is last touch.
            db.execute(
                'INSERT OR IGNORE INTO visitors (visitor, first_seen, source, campaign)'
                ' VALUES (?, ?, ?, ?)',
                (visitor, int(time.time()), source, _clean(campaign, 120)),
            )
            db.execute(
                'INSERT INTO events (ts, il_hour, il_day, visitor, session, stage,'
                ' source, campaign, order_id, value) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (int(time.time()), hour, day, visitor, _clean(session, 64), stage,
                 source, _clean(campaign, 120), _clean(order_id, 40),
                 float(value) if value is not None else None),
            )
        return True
    except Exception as e:
        print(f'  [Analytics] record({stage}) failed: {e}')
        return False


def set_excluded(visitor, excluded=True):
    """Flag a visitor's own device so it drops out of every report, past events
    included. Reversible — the rows stay, they are just filtered."""
    if not ready():
        return False
    visitor = _clean(visitor, 64)
    if not visitor:
        return False
    try:
        with _lock, _connect() as db:
            # The device may be flagged before it has ever sent an event, so
            # make sure there is a row to flag.
            db.execute(
                'INSERT OR IGNORE INTO visitors (visitor, first_seen, source)'
                ' VALUES (?, ?, ?)',
                (visitor, int(time.time()), 'direct'),
            )
            db.execute('UPDATE visitors SET excluded=? WHERE visitor=?',
                       (1 if excluded else 0, visitor))
        return True
    except Exception as e:
        print(f'  [Analytics] set_excluded failed: {e}')
        return False


def is_excluded(visitor):
    if not ready() or not visitor:
        return False
    try:
        with _connect() as db:
            row = db.execute('SELECT excluded FROM visitors WHERE visitor=?',
                             (_clean(visitor, 64),)).fetchone()
        return bool(row and row['excluded'])
    except Exception:
        return False


# ── Meta event ledger ─────────────────────────────────────────────────────────
# Meta's own diagnostics report over a 7-28 day window, so a fix made today can
# read as 0% for weeks. This records what we sent, when, and with which id, so
# "is deduplication working" becomes a question about our own data.
META_CHANNELS = ('browser', 'server')


def log_meta_event(event_name, event_id, channel, status='', value=None):
    """Record one Pixel or CAPI send. Never raises."""
    if not ready():
        return False
    event_name = _clean(event_name, 40)
    event_id   = _clean(event_id, 100)
    if not event_name or not event_id or channel not in META_CHANNELS:
        return False
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        value = None
    _, day = _buckets()
    try:
        with _lock, _connect() as db:
            db.execute(
                'INSERT INTO meta_events'
                ' (ts, il_day, event_name, event_id, channel, status, value)'
                ' VALUES (?,?,?,?,?,?,?)',
                (int(time.time()), day, event_name, event_id, channel,
                 _clean(status, 200), value),
            )
        return True
    except Exception as e:
        print(f'  [Meta] ledger write failed: {e}')
        return False


def meta_coverage(days=7):
    """Per event name: how many went out on each channel, how many ids appear on
    BOTH — which is what Meta calls deduplication — and the last raw rows.

    `matched` is deliberately not expected to equal the totals. A server event
    with no browser twin is ad-blocked traffic being counted, which is the whole
    point of CAPI; the number to watch is that every event has an id at all.
    """
    if not ready():
        return {'ok': False, 'error': 'analytics not initialised'}
    since = _since_day(days)
    with _lock, _connect() as db:
        rows = db.execute("""
            SELECT event_name,
                   SUM(channel='browser') AS browser,
                   SUM(channel='server')  AS server,
                   COUNT(DISTINCT event_id) AS ids,
                   -- distinct_values is the local answer to Meta's "prices in
                   -- value parameter are the same for all web Purchase events".
                   -- 1 across a week of Purchases is that warning, visible
                   -- immediately instead of after their 7-28 day window.
                   COUNT(DISTINCT value) AS distinct_values,
                   MIN(value) AS min_value,
                   MAX(value) AS max_value
            FROM meta_events WHERE il_day >= ?
            GROUP BY event_name ORDER BY event_name
        """, (since,)).fetchall()

        matched = {r['event_name']: r['n'] for r in db.execute("""
            SELECT event_name, COUNT(*) AS n FROM (
              SELECT event_name, event_id FROM meta_events WHERE il_day >= ?
              GROUP BY event_name, event_id
              HAVING COUNT(DISTINCT channel) = 2
            ) GROUP BY event_name
        """, (since,)).fetchall()}

        recent = [dict(r) for r in db.execute("""
            SELECT ts, event_name, event_id, channel, status, value
            FROM meta_events ORDER BY id DESC LIMIT 30
        """).fetchall()]

    events = []
    for r in rows:
        name = r['event_name']
        both = matched.get(name, 0)
        # Both channels fired for this action, so it is a candidate for
        # deduplication — measured against whichever channel sent fewer.
        pairable = min(r['browser'] or 0, r['server'] or 0)
        events.append({
            'event_name': name,
            'browser':    r['browser'] or 0,
            'server':     r['server'] or 0,
            'ids':        r['ids'] or 0,
            'matched':    both,
            'dedup_pct':  round(both / pairable * 100, 1) if pairable else None,
            'distinct_values': r['distinct_values'] or 0,
            'min_value':  r['min_value'],
            'max_value':  r['max_value'],
        })
    total = sum(e['browser'] + e['server'] for e in events)
    return {'ok': True, 'days': days, 'events': events, 'recent': recent,
            # Every row in this table carried an id by construction — the ledger
            # refuses a write without one — so this is 100% whenever anything
            # was sent. It is here to be compared against Events Manager: if
            # ours says 100% and Meta says less, Meta's window is catching up.
            'id_coverage_pct': 100.0 if total else None,
            'total_events': total}


# ── Reporting ─────────────────────────────────────────────────────────────────
# Every query joins visitors and drops excluded ones, so the owner's own device
# and anything else flagged never reaches a number on screen.
_EXCLUDE = ('AND e.visitor NOT IN (SELECT visitor FROM visitors WHERE excluded=1)')

_GRAIN_SQL = {
    # Week starts Sunday, which is how an Israeli business week reads.
    'hour':  "e.il_hour",
    'day':   "e.il_day",
    'week':  "date(e.il_day, '-' || strftime('%w', e.il_day) || ' days')",
    'month': "substr(e.il_day, 1, 7)",
}


def _since_day(days):
    return (_il_now() - timedelta(days=days)).strftime('%Y-%m-%d')


def report(granularity='day', days=30):
    """Everything the admin dashboard renders, in one round trip."""
    if not ready():
        return {'ok': False, 'error': 'analytics not initialised'}
    grain = _GRAIN_SQL.get(granularity, _GRAIN_SQL['day'])
    since = _since_day(days)

    with _lock, _connect() as db:
        q = lambda sql, *a: db.execute(sql, a).fetchall()

        # Time series — unique people and raw pageviews per bucket.
        series = [
            {'bucket': r['bucket'], 'visitors': r['visitors'], 'pageviews': r['pageviews']}
            for r in q(f"""
                SELECT {grain} AS bucket,
                       COUNT(DISTINCT e.visitor) AS visitors,
                       SUM(CASE WHEN e.stage='visit' THEN 1 ELSE 0 END) AS pageviews
                FROM events e
                WHERE e.il_day >= ? {_EXCLUDE}
                GROUP BY bucket ORDER BY bucket
            """, since)
        ]

        # Funnel, as unique people per stage. Counting events instead would make
        # the drop-off percentages meaningless — one person adding three items
        # is not three people reaching that step.
        counts = {r['stage']: (r['people'], r['events']) for r in q(f"""
            SELECT e.stage, COUNT(DISTINCT e.visitor) AS people, COUNT(*) AS events
            FROM events e WHERE e.il_day >= ? {_EXCLUDE} GROUP BY e.stage
        """, since)}

        funnel, previous = [], None
        for stage in STAGES:
            people, events = counts.get(stage, (0, 0))
            funnel.append({
                'stage':     stage,
                'label':     STAGE_LABELS[stage],
                'people':    people,
                'events':    events,
                # Against the step before, so it reads as "of the people who got
                # this far, how many carried on".
                'step_pct':  round(people / previous * 100, 1) if previous else None,
            })
            previous = people

        top = funnel[0]['people'] or 0
        for row in funnel:
            row['of_visitors'] = round(row['people'] / top * 100, 1) if top else 0.0

        # By first-touch source: where the customer originally came from.
        by_source = {}
        for r in q(f"""
            SELECT v.source AS source, e.stage AS stage,
                   COUNT(DISTINCT e.visitor) AS people
            FROM events e JOIN visitors v ON v.visitor = e.visitor
            WHERE e.il_day >= ? AND v.excluded = 0
            GROUP BY v.source, e.stage
        """, since):
            by_source.setdefault(r['source'], {})[r['stage']] = r['people']

        sources = []
        for name in SOURCES:
            stages = by_source.get(name, {})
            visitors = stages.get('visit', 0)
            purchases = stages.get('purchase', 0)
            sources.append({
                'source':    name,
                'label':     SOURCE_LABELS[name],
                'visitors':  visitors,
                'add_to_cart': stages.get('add_to_cart', 0),
                'checkout':  stages.get('checkout_created', 0),
                'purchases': purchases,
                'cvr':       round(purchases / visitors * 100, 2) if visitors else 0.0,
            })
        total_visitors = sum(s['visitors'] for s in sources) or 0
        for s in sources:
            s['share'] = round(s['visitors'] / total_visitors * 100, 1) if total_visitors else 0.0

        rev = q(f"""
            SELECT COUNT(*) AS orders, COALESCE(SUM(e.value), 0) AS revenue
            FROM events e WHERE e.stage='purchase' AND e.il_day >= ? {_EXCLUDE}
        """, since)[0]

        totals = q(f"""
            SELECT COUNT(DISTINCT e.visitor) AS visitors,
                   SUM(CASE WHEN e.stage='visit' THEN 1 ELSE 0 END) AS pageviews
            FROM events e WHERE e.il_day >= ? {_EXCLUDE}
        """, since)[0]

    visitors = totals['visitors'] or 0
    return {
        'ok': True,
        'granularity': granularity,
        'days': days,
        'totals': {
            'visitors':  visitors,
            'pageviews': totals['pageviews'] or 0,
            'orders':    rev['orders'] or 0,
            'revenue':   round(rev['revenue'] or 0),
            'cvr':       round((rev['orders'] or 0) / visitors * 100, 2) if visitors else 0.0,
        },
        'series':  series,
        'funnel':  funnel,
        'sources': sources,
    }
