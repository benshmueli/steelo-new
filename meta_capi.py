#!/usr/bin/env python3
"""
Meta Conversions API — server-side event reporting.

The browser Pixel is the primary signal; this is the redundant server copy that
survives ad blockers and Safari ITP, and carries the customer details the
browser never sees (email, phone, address). Meta collapses the two into one
event when they share event_name + event_id — see send_event().

Nothing here is required for the site to work. With META_PIXEL_ID or
META_CAPI_ACCESS_TOKEN unset, every call is a logged no-op, so a dev machine
behaves exactly as it did before this file existed.
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

PIXEL_ID     = os.environ.get('META_PIXEL_ID', '').strip()
ACCESS_TOKEN = os.environ.get('META_CAPI_ACCESS_TOKEN', '').strip()
# Graph API versions are supported for roughly two years. Check the current one
# in Events Manager → Settings and override here if it has moved on.
API_VERSION  = os.environ.get('META_API_VERSION', 'v21.0').strip()
# Set only while testing. Events carrying it appear in Test Events and are
# EXCLUDED from real reporting — it must be removed before running a campaign.
TEST_EVENT_CODE = os.environ.get('META_TEST_EVENT_CODE', '').strip()

CURRENCY = 'ILS'
SITE     = 'https://www.steelo-design.com'
TIMEOUT  = 10

enabled = bool(PIXEL_ID and ACCESS_TOKEN)
_warned = False

# Optional sink for a local record of what was sent, set by server.py to
# analytics.log_meta_event. Injected rather than imported so this module keeps
# working on its own, with no dependency on the analytics database.
_ledger = None


def set_ledger(fn):
    """fn(event_name, event_id, channel, status) — called after each send."""
    global _ledger
    _ledger = fn


def _record(event_name, event_id, status):
    if not _ledger:
        return
    try:
        _ledger(event_name, event_id, 'server', status)
    except Exception as e:
        print(f'  [Meta] ledger hook failed: {e}')


def _hash(value):
    """SHA-256 of a normalised string, or None if there is nothing to hash.

    Meta's normalisation rules for every hashed field: trim, lowercase, then
    hash. Sending an unnormalised value doesn't error — it just silently fails
    to match, which is worse.
    """
    if not value:
        return None
    norm = str(value).strip().lower()
    if not norm:
        return None
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()


def _hash_phone(value):
    """Israeli phone → E.164 digits (no +), then hashed.

    Customers type '050-123-4567', '+972 50 123 4567' and '972501234567'
    interchangeably. All three have to hash identically or the same person
    counts as three, so everything is reduced to digits and forced to a 972
    country code before hashing.
    """
    if not value:
        return None
    digits = re.sub(r'\D', '', str(value))
    if not digits:
        return None
    if digits.startswith('972'):
        pass
    elif digits.startswith('0'):
        digits = '972' + digits[1:]
    elif len(digits) == 9:          # already stripped of its leading zero
        digits = '972' + digits
    return hashlib.sha256(digits.encode('utf-8')).hexdigest()


def _split_name(full):
    """'ישראל ישראלי' → ('ישראל', 'ישראלי'). Single-word names give no surname."""
    parts = [p for p in str(full or '').strip().split() if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def build_user_data(order, fbp=None, fbc=None, ip=None, ua=None):
    """Assemble Meta's user_data block from an order dict.

    Everything identifying is hashed. fbp/fbc/IP/user-agent are the documented
    exceptions — Meta requires those raw, and they carry no PII on their own.
    Absent fields are omitted rather than sent empty; an empty string hashes to
    a real digest that matches nobody and drags the match quality score down.
    """
    first, last = _split_name(order.get('name'))
    fields = {
        'em': _hash(order.get('email')),
        'ph': _hash_phone(order.get('phone')),
        'fn': _hash(first),
        'ln': _hash(last),
        'ct': _hash(order.get('city')),
        'zp': _hash(order.get('postal_code')),
        'country': _hash('il'),
        'client_ip_address': ip,
        'client_user_agent': ua,
        'fbp': fbp,
        'fbc': fbc,
    }
    return {k: v for k, v in fields.items() if v}


def contents_from_items(items):
    """Order items → Meta's contents[] plus the matching content_ids[].

    'qty' is the key checkout.js sends; 'quantity' is accepted too so this can
    be handed a cart-shaped dict without a surprise.
    """
    contents, ids = [], []
    for it in items or []:
        pid = str(it.get('id') or it.get('name') or '').strip()
        if not pid:
            continue
        qty = int(it.get('qty') or it.get('quantity') or 1)
        contents.append({
            'id': pid,
            'quantity': qty,
            'item_price': float(it.get('price') or 0),
        })
        ids.append(pid)
    return contents, ids


def send_event(event_name, event_id, user_data, custom_data=None,
               event_source_url=None, event_time=None):
    """Queue one event for the Conversions API. Returns immediately.

    server.py runs on a plain HTTPServer, which is single-threaded: a blocking
    POST to Meta would stall the customer's post-payment redirect and every
    other request on the box behind it. So the request goes out on a daemon
    thread and the caller never waits, never sees an exception, and never
    depends on the result.
    """
    global _warned
    if not enabled:
        if not _warned:
            missing = []
            if not PIXEL_ID:
                missing.append('META_PIXEL_ID')
            if not ACCESS_TOKEN:
                missing.append('META_CAPI_ACCESS_TOKEN')
            print(f'  [Meta] CAPI disabled — {" and ".join(missing)} not set')
            _warned = True
        # Still recorded: the id the server *would* have used is what makes the
        # deduplication wiring testable on a dev machine with no credentials.
        _record(event_name, event_id, 'skipped: CAPI disabled')
        return

    event = {
        'event_name':       event_name,
        'event_time':       int(event_time or time.time()),
        'event_id':         event_id,
        'action_source':    'website',
        'event_source_url': event_source_url or SITE,
        'user_data':        user_data or {},
    }
    if custom_data:
        event['custom_data'] = custom_data

    payload = {'data': [event], 'access_token': ACCESS_TOKEN}
    if TEST_EVENT_CODE:
        payload['test_event_code'] = TEST_EVENT_CODE

    url = f'https://graph.facebook.com/{API_VERSION}/{PIXEL_ID}/events'
    threading.Thread(
        target=_post, args=(url, payload, event_name, event_id), daemon=True
    ).start()


def _post(url, payload, event_name, event_id):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=body, headers={'Content-Type': 'application/json'}, method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            received = json.loads(resp.read().decode()).get('events_received')
            print(f'  [Meta] {event_name} {event_id} → OK (received={received})')
            _record(event_name, event_id, f'ok received={received}')
    except urllib.error.HTTPError as e:
        # Meta puts the actual reason in the body, not the status line — an
        # expired token and a malformed payload are both plain 400s.
        detail = e.read().decode(errors='replace')[:400]
        print(f'  [Meta] {event_name} {event_id} → HTTP {e.code}: {detail}')
        _record(event_name, event_id, f'HTTP {e.code}: {detail[:120]}')
    except Exception as e:
        print(f'  [Meta] {event_name} {event_id} → failed: {e}')
        _record(event_name, event_id, f'failed: {e}')
