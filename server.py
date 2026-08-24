#!/usr/bin/env python3
"""
Steelo dev server — serves static files + handles admin save + order endpoints.
Run: python3 server.py
"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json, os, re, hashlib, time, smtplib, threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import meta_capi
import analytics

# Railway injects PORT; fall back to 8891 for local dev
PORT     = int(os.environ.get('PORT', 8891))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JS  = os.path.join(BASE_DIR, 'js', 'data.js')

# ── Admin auth ────────────────────────────────────────────────────────────────
# Set ADMIN_PASSWORD env var before deploying. Default is for local dev only.
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'steelo-admin')
# The token is the SHA-256 hash of the password. Stateless — no session store needed.
ADMIN_TOKEN = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()

# ── Rate limiting (payment endpoint) ─────────────────────────────────────────
_rate: dict = {}          # ip → [timestamp, ...]
RATE_WINDOW  = 60         # seconds
RATE_LIMIT   = 5          # max attempts per window
ANALYTICS_LIMIT = 120     # funnel beacons per window — a real session sends a
                          # handful; this only sheds a flood
META_EVENT_LIMIT = 60     # Pixel-event reports per window
# Events whose CAPI twin this public endpoint may send. Strictly an allow-list:
# Purchase and InitiateCheckout are sent from the payment path instead, where the
# order is known to be real, so a browser cannot conjure a conversion.
# InitiateCheckout is here so its CAPI copy goes out at the same instant as the
# Pixel call. It used to be sent from /payment/init, which only fires for people
# who reach the payment step — so every abandoned checkout was a browser event
# with no server twin, which is the coverage gap Meta reported.
META_SERVER_TWIN = {'AddToCart', 'InitiateCheckout'}
# Names the ledger will record at all. /meta/event is public, and without this
# anyone could fill the diagnostics table with noise — which matters, because
# that table is what we use to judge whether deduplication is working.
META_KNOWN_EVENTS = {'PageView', 'ViewContent', 'AddToCart',
                     'InitiateCheckout', 'AddPaymentInfo', 'Purchase'}
COUPON_LIMIT = 15         # coupon tries per window — enough for honest typos,
                          # not enough to enumerate codes

# ── Google Sheets config ──────────────────────────────────────────────────────
# 1. Create a Google Sheet, share it with the service account email (Editor).
# 2. Paste the Sheet ID from the URL below (the long string between /d/ and /edit).
# 3. Save your service account credentials JSON as credentials.json in this folder.
SHEET_ID        = os.environ.get('STEELO_SHEET_ID', '1DsV1E82jfN_X-QXnSrFPerhOY_xCRQ08ezG85m6BGnc')
CREDENTIALS_FILE = os.path.join(BASE_DIR, 'credentials.json')

SHEET_COLUMNS = [
    'Order ID', 'Date', 'Name', 'Email', 'Phone',
    'Address', 'Apartment', 'City', 'Postal Code', 'Country',
    'Notes', 'Items', 'Total (₪)', 'Status',
    'Floor', 'Delivery', 'Delivery Fee (₪)',
    'Coupon', 'Coupon Discount (₪)',
]

# Marketing-list tab header (one row per customer who reaches payment).
MARKETING_COLUMNS = [
    'Date', 'Name', 'Email', 'Phone', 'Email Opt-in', 'WhatsApp Opt-in', 'Order ID',
]

# Delivery fee (₪) by lowercased product category — server-authoritative;
# mirror of the map in build.py. Pickup is always free.
DELIVERY_FEE = {
    'dining table': 300,
    'coffee table': 100,
    'living room table': 100,
    'side table': 70,
    'nesting tables': 70,
    'stool': 50,
}

def get_sheets_service():
    """Return an authenticated Google Sheets service, or None if not configured.
    Credentials can come from:
      1. GOOGLE_CREDENTIALS_JSON env var (JSON string) — used on Railway
      2. credentials.json file in the project directory — used locally
    """
    if not SHEET_ID:
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON', '')
        if creds_json:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
        elif os.path.exists(CREDENTIALS_FILE):
            creds = service_account.Credentials.from_service_account_file(
                CREDENTIALS_FILE,
                scopes=['https://www.googleapis.com/auth/spreadsheets'],
            )
        else:
            return None

        return build('sheets', 'v4', credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f'  [Sheets] Could not build service: {e}')
        return None


def ensure_sheet_tab(service, tab):
    """Create the tab if it doesn't exist (used for the auto test tabs)."""
    try:
        meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
        titles = [s['properties']['title'] for s in meta.get('sheets', [])]
        if tab not in titles:
            service.spreadsheets().batchUpdate(
                spreadsheetId=SHEET_ID,
                body={'requests': [{'addSheet': {'properties': {'title': tab}}}]},
            ).execute()
            print(f'  [Sheets] Created tab "{tab}"')
    except Exception as e:
        print(f'  [Sheets] ensure_sheet_tab({tab}) error: {e}')


def ensure_header_row(service, tab='orders'):
    """Keep the orders/orders_test header row in sync with SHEET_COLUMNS."""
    try:
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=f'{tab}!A1',
            valueInputOption='RAW',
            body={'values': [SHEET_COLUMNS]},
        ).execute()
    except Exception as e:
        print(f'  [Sheets] Header row error: {e}')


def append_marketing_row(service, order, tab='marketing'):
    """Append the customer's contact + consent to the marketing tab."""
    yes_no = lambda v: 'TRUE' if v else 'FALSE'
    row = [
        order.get('date', ''),
        order.get('name', ''),
        order.get('email', ''),
        order.get('phone', ''),
        yes_no(order.get('optin_email')),
        yes_no(order.get('optin_wa')),
        order.get('order_id', ''),
    ]
    try:
        ensure_sheet_tab(service, tab)
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID, range=f'{tab}!A1',
            valueInputOption='RAW', body={'values': [MARKETING_COLUMNS]},
        ).execute()
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID, range=f'{tab}!A1',
            valueInputOption='RAW', insertDataOption='INSERT_ROWS',
            body={'values': [row]},
        ).execute()
        print(f'  [Sheets] Marketing row for {order.get("email","")} → {tab} ✓')
        return True
    except Exception as e:
        print(f'  [Sheets] Marketing append error: {e}')
        return False


def mark_order_paid(service, order_id):
    """Find the row with this order_id and set its Status column to Paid."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range='orders!A:A'
        ).execute()
        rows = result.get('values', [])
        for i, row in enumerate(rows):
            if row and row[0] == order_id:
                row_num = i + 1  # 1-indexed
                service.spreadsheets().values().update(
                    spreadsheetId=SHEET_ID,
                    range=f'orders!N{row_num}',
                    valueInputOption='RAW',
                    body={'values': [['Paid']]},
                ).execute()
                print(f'  [Sheets] Order {order_id} marked Paid (row {row_num}) ✓')
                return True
        print(f'  [Sheets] Order {order_id} not found in sheet to mark Paid')
        return False
    except Exception as e:
        print(f'  [Sheets] mark_order_paid error: {e}')
        return False


def append_order_to_sheet(service, order, tab='orders'):
    """Append one order row to the orders (or orders_test) tab."""
    items_summary = '; '.join(
        f"{i['name']} ×{i['qty']} (₪{i['price']})"
        for i in order.get('items', [])
    )
    row = [
        order.get('order_id', ''),
        order.get('date', ''),
        order.get('name', ''),
        order.get('email', ''),
        order.get('phone', ''),
        order.get('address', ''),
        order.get('apartment', ''),
        order.get('city', ''),
        order.get('postal_code', ''),
        order.get('country', 'Israel'),
        order.get('notes', ''),
        items_summary,
        order.get('total', 0),
        order.get('status_override', 'New'),
        order.get('floor', ''),
        'איסוף עצמי' if order.get('delivery_method') == 'pickup' else 'משלוח',
        order.get('delivery_fee', 0),
        order.get('coupon_code', ''),
        order.get('coupon_discount', 0),
    ]
    try:
        ensure_sheet_tab(service, tab)
        ensure_header_row(service, tab)
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f'{tab}!A1',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body={'values': [row]},
        ).execute()
        print(f'  [Sheets] Order {order["order_id"]} appended → {tab} ✓')
        return True
    except Exception as e:
        print(f'  [Sheets] Append error: {e}')
        return False


# ── Email receipts ───────────────────────────────────────────────────────────
GMAIL_USER     = 'steelo.designers@gmail.com'
GMAIL_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')

def send_receipt_email(order):
    if not GMAIL_PASSWORD:
        print('  [Email] GMAIL_APP_PASSWORD not set — skipping receipt email')
        return False
    to_email = order.get('email', '')
    if not to_email:
        print('  [Email] No customer email in order — skipping')
        return False

    order_id  = order.get('order_id', '')
    name      = order.get('name', 'Valued Customer')
    items     = order.get('items', [])
    total     = order.get('total', 0)
    date      = order.get('date', '')
    address_parts = [
        order.get('address', ''), order.get('apartment', ''),
        order.get('city', ''), order.get('postal_code', ''),
        order.get('country', ''),
    ]
    address = ', '.join(p for p in address_parts if p)

    items_html = ''.join(
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #e8e2da;">{i.get("name","")}</td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #e8e2da;text-align:center;">×{i.get("qty",1)}</td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #e8e2da;text-align:right;">₪{i.get("price",0)}</td></tr>'
        for i in items
    )

    html = f"""
<html><body style="margin:0;padding:0;background:#f5f0eb;font-family:Georgia,serif;">
<div style="max-width:560px;margin:40px auto;background:#faf7f4;border:1px solid #e8e2da;">
  <div style="background:#1a1714;padding:32px 40px;">
    <p style="font-family:Helvetica,sans-serif;font-size:10px;letter-spacing:4px;text-transform:uppercase;color:#c8b89a;margin:0;">STEELO</p>
  </div>
  <div style="padding:40px;">
    <h1 style="font-weight:300;font-size:28px;color:#1a1714;margin:0 0 8px;">Thank you, {name}.</h1>
    <p style="font-family:Helvetica,sans-serif;font-size:13px;color:#6b6560;margin:0 0 32px;">Your order has been received and is being processed.</p>

    <table width="100%" cellpadding="0" cellspacing="0" style="font-family:Helvetica,sans-serif;font-size:13px;color:#1a1714;">
      <tr>
        <th style="text-align:left;padding-bottom:12px;border-bottom:2px solid #1a1714;font-size:10px;letter-spacing:2px;text-transform:uppercase;font-weight:500;">Item</th>
        <th style="text-align:center;padding-bottom:12px;border-bottom:2px solid #1a1714;font-size:10px;letter-spacing:2px;text-transform:uppercase;font-weight:500;">Qty</th>
        <th style="text-align:right;padding-bottom:12px;border-bottom:2px solid #1a1714;font-size:10px;letter-spacing:2px;text-transform:uppercase;font-weight:500;">Price</th>
      </tr>
      {items_html}
      <tr>
        <td colspan="2" style="padding:16px 0 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;font-weight:500;">Total</td>
        <td style="padding:16px 0 0;text-align:right;font-size:18px;font-family:Georgia,serif;">₪{total}</td>
      </tr>
    </table>

    <div style="margin-top:32px;padding-top:24px;border-top:1px solid #e8e2da;font-family:Helvetica,sans-serif;font-size:12px;color:#6b6560;line-height:1.8;">
      <p style="margin:0 0 4px;"><strong style="color:#1a1714;">Order</strong> {order_id}</p>
      <p style="margin:0 0 4px;"><strong style="color:#1a1714;">Date</strong> {date}</p>
      {'<p style="margin:0;"><strong style="color:#1a1714;">Delivery to</strong> ' + address + '</p>' if address else ''}
    </div>

    <p style="margin:32px 0 0;font-family:Helvetica,sans-serif;font-size:12px;color:#6b6560;line-height:1.8;">
      Each piece is made to order. Lead time is 5-10 business days.<br>
      We will be in touch with delivery details.<br><br>
      <a href="mailto:steelo.designers@gmail.com" style="color:#1a1714;">steelo.designers@gmail.com</a>
    </p>
  </div>
  <div style="background:#1a1714;padding:20px 40px;">
      <p style="font-family:Helvetica,sans-serif;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#6b6560;margin:0;">ריהיאי נירוסטה על-זמניים · Made in Israel</p>
  </div>
</div>
</body></html>"""

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Your STEELO order — {order_id}'
        msg['From']    = f'STEELO <{GMAIL_USER}>'
        msg['To']      = to_email
        msg['Reply-To'] = GMAIL_USER
        msg.attach(MIMEText(html, 'html', 'utf-8'))

        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.starttls()
            smtp.login(GMAIL_USER, GMAIL_PASSWORD)
            smtp.sendmail(GMAIL_USER, to_email, msg.as_string())

        print(f'  [Email] Receipt sent to {to_email} ✓')
        return True
    except Exception as e:
        print(f'  [Email] Failed to send to {to_email}: {e}')
        return False


# ── Tranzila hosted payment page ──────────────────────────────────────────────
TRANZILA_TERMINAL    = os.environ.get('TRANZILA_TERMINAL', 'fxpsteelo')
TRANZILA_PASSWORD    = os.environ.get('TRANZILA_PASSWORD', '')
TRANZILA_HANDSHAKE_URL = 'https://api.tranzila.com/v1/handshake/create'
TRANZILA_IFRAME_BASE   = f'https://direct.tranzila.com/{TRANZILA_TERMINAL}/iframenew.php'

# In-memory pending orders (order_id → order dict).
# Tranzila redirects back to us after payment; we look up the order then save it.
_pending_orders: dict = {}


# ── Internal orders ──────────────────────────────────────────────────────────
# The hidden 'test' product is priced at ₪1 and its category carries no delivery
# fee, so every internal test order totals exactly ₪1.00. Those orders used to be
# reported to Meta like any other, which is why Events Manager warned that every
# web Purchase carried the same value — and why the ad account was optimising
# toward ₪1 conversions.

TEST_PRODUCT_ID = 'test'


def is_test_order(order):
    """An internal test order — the hidden 'test' product. Decides which Sheets
    tab the order lands in."""
    if not order:
        return False
    return any(str(it.get('id')) == TEST_PRODUCT_ID
               for it in order.get('items', []))


def is_internal_order(order):
    """True when this order must not reach Meta at all.

    Wider than is_test_order: it also covers a device the admin flagged with
    "Ignore this device", which may well be buying a real product to test the
    payment flow. That order is a genuine sale for the sheet and the receipt —
    it just must not teach the ad account anything.
    """
    if not order:
        return False
    if is_test_order(order):
        return True
    return analytics.is_excluded(order.get('visitor_id', ''))


# ── Meta Purchase de-duplication ─────────────────────────────────────────────
# A single payment can reach us down several different paths: Tranzila's GET
# redirect to /payment-success, the Apple Pay bridge POSTing to the same URL,
# /?payment=success, the browser's own /payment/confirm call, and the legacy
# /payment-result. Each of them legitimately confirms the order — but Meta must
# see exactly one Purchase, so the first one through claims the order_id here
# and the rest are no-ops.
#
# Bounded because this process is long-lived: order IDs are only needed for the
# few seconds in which the duplicate paths fire.
_purchase_sent: dict = {}          # order_id → timestamp
_purchase_lock = threading.Lock()
PURCHASE_TTL = 3600


def claim_purchase(order_id):
    """Reserve this order for reporting. True for the first caller only."""
    if not order_id:
        return False
    now = time.time()
    with _purchase_lock:
        for oid, ts in list(_purchase_sent.items()):
            if now - ts > PURCHASE_TTL:
                del _purchase_sent[oid]
        if order_id in _purchase_sent:
            return False
        _purchase_sent[order_id] = now
        return True


# ── Auth helpers ─────────────────────────────────────────────────────────────
def check_admin_token(handler):
    """Return True if the request carries the correct admin token."""
    auth = handler.headers.get('Authorization', '')
    return auth == f'Bearer {ADMIN_TOKEN}'

def rate_check(ip, bucket='payment', limit=RATE_LIMIT):
    """Return True if the IP is within the allowed rate. Prunes old entries.

    Bucketed so that trying a few coupon codes cannot use up the payment
    allowance — a shopper who mistypes a code twice must still be able to pay.
    """
    now = time.time()
    key = (bucket, ip)
    timestamps = [t for t in _rate.get(key, []) if now - t < RATE_WINDOW]
    _rate[key] = timestamps
    if len(timestamps) >= limit:
        return False
    _rate[key].append(now)
    return True

# ── Validation helpers ────────────────────────────────────────────────────────
import re as _re

def validate_order(order):
    """
    Validate required order fields server-side.
    Returns (ok: bool, error: str)
    """
    required = ['name', 'email', 'phone']
    # Shipping address is only required when the order is delivered (not pickup).
    if order.get('delivery_method') != 'pickup':
        required += ['address', 'city', 'postal_code']
    for field in required:
        val = str(order.get(field, '')).strip()
        if not val:
            return False, f'Missing required field: {field}'
        if len(val) > 200:
            return False, f'Field too long: {field}'

    email = str(order.get('email', '')).strip()
    if not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return False, 'Invalid email address'

    phone = str(order.get('phone', '')).strip()
    if not _re.match(r'^[\d\s\+\-\(\)]{7,20}$', phone):
        return False, 'Invalid phone number'

    items = order.get('items', [])
    if not items or not isinstance(items, list):
        return False, 'Order must have at least one item'

    return True, ''

# ── Persistent store ──────────────────────────────────────────────────────────
# Railway's container filesystem is ephemeral: anything written next to
# server.py is gone on the next restart or deploy. That is why admin discounts
# kept vanishing from the live site — /admin/save rewrote js/data.js inside the
# container and the next restart restored the git copy. Everything the admin can
# change, plus the coupon redemption counters, lives in one JSON file on a
# mounted volume instead. STEELO_DATA_DIR points at that volume in production;
# locally it falls back to the repo directory.
#
# The store holds *overrides*, not a copy of the catalogue: js/data.js in git
# stays the source of truth for products, and the store records only the fields
# the admin actually edited. So a product added or re-photographed through a PR
# still appears, and a save cannot silently drop fields the admin panel doesn't
# model — it has no idea `material` or CATEGORY_ORDER exist.
#
# RAILWAY_VOLUME_MOUNT_PATH is set by Railway itself the moment a volume is
# attached, so attaching one is the only step needed — there is no second
# setting to forget. STEELO_DATA_DIR stays as an override for anything else.
STORE_DIR  = (os.environ.get('STEELO_DATA_DIR')
              or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
              or BASE_DIR)
STORE_PATH = os.path.join(STORE_DIR, 'store.json')

_store_lock = threading.RLock()
_store: dict = {}
_store_rev  = 0        # bumped on every write; keys the rendered-page caches


def _empty_store():
    return {'version': 1, 'overrides': {}, 'extra_products': [],
            'coupons': [], 'redemptions': []}


def load_store():
    """The store, read from disk once and then kept in memory."""
    global _store
    with _store_lock:
        if _store:
            return _store
        data = _empty_store()
        try:
            with open(STORE_PATH, encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for key in data:
                    if key in loaded and isinstance(loaded[key], type(data[key])):
                        data[key] = loaded[key]
            print(f'  [Store] Loaded {STORE_PATH} '
                  f'({len(data["overrides"])} overrides, {len(data["coupons"])} coupons)')
        except FileNotFoundError:
            print(f'  [Store] No store at {STORE_PATH} yet — starting empty')
        except Exception as e:
            print(f'  [Store] Could not read {STORE_PATH}: {e} — starting empty')
        _store = data
        return _store


def save_store():
    """Write the store out atomically — a crash mid-write must not truncate it."""
    global _store_rev
    with _store_lock:
        os.makedirs(STORE_DIR, exist_ok=True)
        tmp = STORE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_store, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STORE_PATH)
        _store_rev += 1
        return _store


def store_rev():
    with _store_lock:
        return _store_rev


# ── Catalogue ─────────────────────────────────────────────────────────────────
# Fields the admin may override. `material`, and anything else added to data.js
# later, is deliberately not here: it stays whatever git says.
OVERRIDABLE = ('name', 'category', 'price', 'discount', 'dimensions',
               'description', 'images')


def _js_str(block, field):
    """Read a single-quoted JS string field out of one product block."""
    m = _re.search(field + r":\s*'((?:[^'\\]|\\.)*)'", block)
    if not m:
        return ''
    return m.group(1).replace("\\'", "'").replace('\\\\', '\\')


def _js_int(block, field, default=0):
    m = _re.search(field + r':\s*(\d+)', block)
    return int(m.group(1)) if m else default


def _parse_products_js(src):
    """Products from a data.js source as {id: {...}}.

    Regex rather than a real JS parse: the file is machine-regular, and the
    server must not depend on node the way build.py can — build.py runs on a
    laptop, this runs in the container.
    """
    out = {}
    starts = [m.start() for m in _re.finditer(r"\bid:\s*'", src)]
    for i, start in enumerate(starts):
        end   = starts[i + 1] if i + 1 < len(starts) else len(src)
        block = src[start:end]
        pid   = _js_str(block, 'id')
        if not pid:
            continue
        images = _re.search(r'images:\s*\[(.*?)\]', block, _re.DOTALL)
        out[pid] = {
            'id':          pid,
            'name':        _js_str(block, 'name'),
            'category':    _js_str(block, 'category'),
            'dimensions':  _js_str(block, 'dimensions'),
            'description': _js_str(block, 'description'),
            'price':       _js_int(block, 'price'),
            'discount':    _js_int(block, 'discount'),
            'images':      _re.findall(r"'([^']*)'", images.group(1)) if images else [],
        }
    return out


_repo_src_cache = (None, '')     # (mtime, source)


def _repo_data_js():
    """The git copy of data.js, cached on its mtime so a deploy that changes the
    catalogue is picked up without a restart."""
    global _repo_src_cache
    try:
        stamp = os.path.getmtime(DATA_JS)
    except OSError:
        return ''
    if _repo_src_cache[0] == stamp:
        return _repo_src_cache[1]
    with open(DATA_JS, encoding='utf-8') as f:
        src = f.read()
    _repo_src_cache = (stamp, src)
    return src


def products_by_id():
    """The catalogue as the storefront sees it: git's data.js with the admin's
    overrides applied. The single place the server reads product data, so
    delivery fees, order totals and invoice lines can never drift apart."""
    store    = load_store()
    override = store.get('overrides', {})
    catalog  = _parse_products_js(_repo_data_js())
    for extra in store.get('extra_products', []):
        pid = str(extra.get('id', '')).strip()
        if pid:
            catalog[pid] = {
                'id': pid, 'name': extra.get('name', ''),
                'category': extra.get('category', ''),
                'dimensions': extra.get('dimensions', ''),
                'price': int(extra.get('price', 0) or 0),
                'discount': int(extra.get('discount', 0) or 0),
            }
    for pid, fields in override.items():
        if pid not in catalog:
            continue
        if fields.get('_deleted'):
            del catalog[pid]
            continue
        for key, value in fields.items():
            if key not in OVERRIDABLE:
                continue
            catalog[pid][key] = int(value or 0) if key in ('price', 'discount') else value
    return catalog


def save_product_overrides(products):
    """Diff what the admin panel posted against git's data.js and keep only the
    fields that actually differ.

    Storing a diff rather than a snapshot is the whole point: a later PR can
    change a photo, a price or a description and the change shows up, instead of
    being shadowed forever by whatever the admin last had on screen. It also
    makes it impossible to lose a field the panel doesn't model — the old
    full-file save silently stripped `material` from every product."""
    repo = _parse_products_js(_repo_data_js())
    with _store_lock:
        store, overrides, extra, posted = load_store(), {}, [], set()
        for p in products:
            pid = str(p.get('id', '')).strip()
            if not pid:
                continue
            posted.add(pid)
            base = repo.get(pid)
            if base is None:      # added in the panel, not in git
                extra.append({k: p[k] for k in ('id',) + OVERRIDABLE if k in p})
                continue
            diff = {}
            for key in OVERRIDABLE:
                if key not in p:
                    continue
                value = int(p[key] or 0) if key in ('price', 'discount') else p[key]
                if value != base.get(key):
                    diff[key] = value
            if diff:
                overrides[pid] = diff
        for pid in repo:
            if pid not in posted:
                overrides[pid] = {'_deleted': True}
        store['overrides']      = overrides
        store['extra_products'] = extra
        save_store()
    _page_cache.clear()
    return len(overrides) + len(extra)


def sale_price(price, discount):
    """Mirror of salePrice() in js/cart.js — the two must round identically or
    the storefront and the charge disagree by a shekel."""
    price = int(price or 0)
    discount = int(discount or 0)
    if discount <= 0:
        return price
    return round(price * (1 - discount / 100))


def render_data_js():
    """js/data.js as served: the repo file verbatim, plus a patch block applying
    the admin's overrides.

    Appending rather than regenerating is deliberate. The admin panel models six
    fields; data.js also carries CATEGORY_ORDER, per-product `material` and the
    comments explaining both. Rewriting the file from the panel's model silently
    destroyed all of it."""
    src   = _repo_data_js()
    store = load_store()
    over  = {pid: {k: v for k, v in f.items() if k in OVERRIDABLE or k == '_deleted'}
             for pid, f in store.get('overrides', {}).items()}
    over  = {pid: f for pid, f in over.items() if f}
    extra = store.get('extra_products', [])
    if not over and not extra:
        return src
    patch = json.dumps(over, ensure_ascii=False)
    added = json.dumps(extra, ensure_ascii=False)
    return src + f'''
/* ── Admin overrides ──────────────────────────────────────────────────────────
   Applied by server.py from the persistent store (see STORE_PATH). Edited in
   /admin.html, never by hand — anything written here is regenerated on save. */
(function () {{
  var O = {patch};
  var EXTRA = {added};
  for (var i = PRODUCTS.length - 1; i >= 0; i--) {{
    var o = O[PRODUCTS[i].id];
    if (!o) continue;
    if (o._deleted) {{ PRODUCTS.splice(i, 1); continue; }}
    for (var k in o) if (k.charAt(0) !== '_') PRODUCTS[i][k] = o[k];
  }}
  for (var j = 0; j < EXTRA.length; j++) PRODUCTS.push(EXTRA[j]);
}})();
'''


# ── Generated product pages ───────────────────────────────────────────────────
_PRODUCT_ROUTE = _re.compile(r'^/products/([A-Za-z0-9_-]+)/$')
_page_cache: dict = {}     # pid → ((pid, store_rev, mtime), html)


def rewrite_product_prices(html, product):
    """Refresh the three machine-readable prices build.py baked into a product
    page: the OG price meta, the Product JSON-LD offer, and STEELO_PRODUCT (which
    is what the Meta ViewContent event reports). All three must be the price
    actually being asked, not the pre-discount list price."""
    price = sale_price(product['price'], product['discount'])
    subs = (
        (r'(<meta property="product:price:amount" content=")\d+(")', rf'\g<1>{price}\g<2>'),
        (r'("priceCurrency":\s*"ILS",\s*"price":\s*)\d+',            rf'\g<1>{price}'),
        (r'(window\.STEELO_PRODUCT\s*=\s*\{[^\n]*?"price":\s*)\d+',   rf'\g<1>{price}'),
    )
    for pattern, repl in subs:
        html = _re.sub(pattern, repl, html)
    return html


# ── Order pricing ─────────────────────────────────────────────────────────────
def compute_delivery_fee(order, lines=None):
    """Server-authoritative delivery fee. Pickup is free; shipping sums each
    item's category fee × quantity. Never trusts the client's number."""
    if order.get('delivery_method') == 'pickup':
        return 0
    if lines is None:
        lines = order_lines(order)
    fee = 0
    for line in lines:
        fee += DELIVERY_FEE.get((line['category'] or '').lower(), 0) * line['qty']
    return fee


def order_lines(order):
    """The cart resolved against the catalogue: unit prices are the current sale
    prices from the store, not whatever the browser put in localStorage."""
    catalog = products_by_id()
    lines   = []
    for item in order.get('items', []):
        pid = str(item.get('id') or '')
        qty = max(1, min(int(item.get('qty', 1) or 1), 99))
        p   = catalog.get(pid)
        if p:
            # `list_unit` is the pre-sale price. A non-stacking coupon is
            # measured against it, so "25% off" means 25% off the ticket price
            # rather than 25% off an already-reduced one.
            list_unit = int(p['price'])
            unit      = sale_price(list_unit, p['discount'])
            name, cat, dims = p['name'], p['category'], p['dimensions']
        else:
            # Unknown id (a product deleted mid-checkout): fall back to what the
            # browser sent rather than dropping a paid-for line from the order.
            unit = list_unit = int(item.get('price', 0) or 0)
            name, cat, dims = item.get('name', ''), item.get('category', ''), ''
        lines.append({'id': pid, 'qty': qty, 'unit': unit, 'list_unit': list_unit,
                      'name': name, 'category': cat, 'dimensions': dims})
    return lines


def price_order(order, coupon_code=None):
    """The one authority on what an order costs.

    Returns subtotal / coupon discount / delivery / total, all computed here from
    the catalogue and the coupon store. /payment/init and /coupon/validate both
    go through it, so the number shown in the summary is the number charged.
    """
    lines    = order_lines(order)
    subtotal = sum(l['unit'] * l['qty'] for l in lines)
    delivery = compute_delivery_fee(order, lines)

    code = (coupon_code or '').strip().upper()
    # `subtotal` and `coupon_discount` are the sale-price basis and the real
    # reduction — build_purchase_data() divides by them to spread the coupon
    # across invoice lines, so their meaning must not drift. The display_* pair
    # is what the summary screen shows, and it only differs for a non-stacking
    # coupon, which prices against the ticket price instead.
    result = {
        'lines': lines, 'subtotal': subtotal, 'delivery_fee': delivery,
        'coupon': '', 'coupon_discount': 0, 'coupon_label': '',
        'free_shipping': False, 'coupon_error': '',
        'display_subtotal': subtotal, 'display_discount': 0, 'list_price_ids': [],
        'scope_note': '',
        'total': subtotal + delivery,
    }
    if not code:
        return result

    ok, discount, free_shipping, message, list_ids = evaluate_coupon(
        code, lines, subtotal, delivery, order,
    )
    if not ok:
        result['coupon_error'] = message
        return result

    result['coupon']          = code
    result['coupon_discount'] = discount
    result['scope_note']      = coupon_scope_note(find_coupon(code) or {})
    result['coupon_label']    = message
    result['free_shipping']   = free_shipping
    result['list_price_ids']  = list_ids
    result['delivery_fee']    = 0 if free_shipping else delivery
    result['total']           = max(subtotal - discount, 0) + result['delivery_fee']

    # Re-express the same reduction against whatever the rows will be priced at,
    # so the summary always reconciles:
    #   display_subtotal − display_discount == subtotal − coupon_discount
    display_subtotal = sum((l['list_unit'] if l['id'] in list_ids else l['unit']) * l['qty']
                           for l in lines)
    result['display_subtotal'] = display_subtotal
    result['display_discount'] = display_subtotal - (subtotal - discount)
    return result


def recalculate_total(order):
    """Kept for callers that only need the number. Prefer price_order()."""
    return price_order(order, order.get('coupon_code')).get('total', 0)


# ── Tranzila invoice lines ────────────────────────────────────────────────────
VAT_RATE = 1.18  # 18% Israeli VAT; listed prices are VAT-inclusive


def _invoice_line_name(line):
    """A meaningful invoice description: product name (+ dimensions when known),
    resolved server-side so it never depends on what the browser cart stored."""
    name  = (line.get('name') or line.get('id') or 'מוצר').strip()
    dims  = (line.get('dimensions') or '').strip()
    label = f'{name} · {dims}' if dims else name
    return label[:118]


def build_purchase_data(order, pricing=None):
    """Tranzila json_purchase_data (invoice line items) as a compact JSON string.

    product_price is sent PRE-VAT (price / 1.18) because the account applies VAT;
    a rounding delta is absorbed on the last line so the post-VAT total matches
    the charged sum exactly (otherwise the invoice omits per-line amounts).

    A coupon is spread proportionally across the product lines rather than added
    as a negative line — Tranzila's invoicing rejects those, and the lines still
    have to reconcile to the charge. '' if there is nothing to invoice."""
    if pricing is None:
        pricing = price_order(order, order.get('coupon_code'))
    subtotal = pricing['subtotal']
    discount = pricing['coupon_discount']
    ratio    = (subtotal - discount) / subtotal if subtotal > 0 else 1

    lines = []
    for line in pricing['lines']:
        lines.append({
            'product_name':     _invoice_line_name(line),
            'product_quantity': line['qty'],
            'product_price':    round(line['unit'] * ratio / VAT_RATE, 2),
        })
    fee = pricing['delivery_fee']
    if fee > 0:
        lines.append({
            'product_name':     'משלוח',
            'product_quantity': 1,
            'product_price':    round(fee / VAT_RATE, 2),
        })
    if not lines:
        return ''
    # Reconcile on the displayed (post-VAT) total the way an Israeli invoice
    # does: VAT is re-added per line and rounded per line, then summed. Adjust
    # the last line's pre-VAT price so Σ(round(price×qty×VAT)) equals the charge
    # exactly — otherwise Tranzila prints the products without per-line amounts.
    charged   = round(pricing.get('total', 0) or 0, 2)
    line_post = lambda l: round(l['product_price'] * l['product_quantity'] * VAT_RATE, 2)
    others    = round(sum(line_post(l) for l in lines[:-1]), 2)
    last      = lines[-1]
    last_post = round(charged - others, 2)
    last['product_price'] = round(last_post / VAT_RATE / last['product_quantity'], 2)
    return json.dumps(lines, separators=(',', ':'), ensure_ascii=False)


# ── Coupons ───────────────────────────────────────────────────────────────────
# One coupon per order, always. `order['coupon_code']` is a single string rather
# than a list, so a second code can only ever replace the first — stacking is
# impossible by construction, not by a rule somebody has to remember.
#
# Every message here is customer-facing Hebrew and deliberately specific: a
# shopper who is told "code expired" stops retyping, a shopper told "invalid"
# tries four more times and then leaves.
COUPON_TYPES = ('percent', 'fixed', 'free_shipping')

# Hebrew category labels for the customer-facing scope note. Mirror of
# CATEGORY_HE in build.py — kept in step by hand, the same way DELIVERY_FEE is
# mirrored across build.py, server.py and js/checkout.js. Several English
# categories deliberately share one Hebrew label, which is how the storefront
# already presents them.
CATEGORY_HE = {
    'coffee table':      'שולחנות סלון',
    'living room table': 'שולחנות סלון',
    'dining table':      'שולחנות אוכל',
    'side table':        'שידות צד',
    'nesting tables':    'שידות צד',
    'stool':             'מעמדי מגזינים',
}

_MSG = {
    'unknown':   'קוד קופון לא קיים',
    'inactive':  'הקופון אינו פעיל',
    'expired':   'פג תוקף הקופון',
    'early':     'הקופון עדיין לא פעיל',
    'exhausted': 'הקופון מוצה',
    'per_cust':  'כבר מימשת את הקופון הזה',
    'min':       'הקופון תקף מהזמנה של ₪{}',
    'items':     'הקופון לא תקף למוצרים שבעגלה',
    'zero':      'לא ניתן להשלים הזמנה בסכום 0 — צרו קשר',
    'worse':     'המבצע הקיים משתלם יותר מהקופון',
}


def _il_today():
    """Today's date in Israel. The container runs on UTC, and an expiry of
    "30/09" has to mean end of the 30th in Tel Aviv, not in Greenwich."""
    from datetime import datetime, timezone, timedelta
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Asia/Jerusalem')).date()
    except Exception:
        return datetime.now(timezone(timedelta(hours=3))).date()


def _as_date(value):
    """'2026-09-30' → date, or None. Anything unparseable is treated as unset,
    so a typo in the admin form can't silently disable a coupon."""
    if not value:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except Exception:
        return None


def norm_code(code):
    return _re.sub(r'\s+', '', str(code or '')).upper()


def norm_phone(phone):
    """Last 9 digits — matches 054-442-4206, +972554424206 and 0554424206."""
    digits = _re.sub(r'\D', '', str(phone or ''))
    return digits[-9:] if len(digits) >= 9 else digits


def norm_email(email):
    return str(email or '').strip().lower()


def find_coupon(code):
    code = norm_code(code)
    if not code:
        return None
    for c in load_store().get('coupons', []):
        if norm_code(c.get('code')) == code:
            return c
    return None


def coupon_used_count(code):
    """Counted from the redemption log rather than a stored counter, so the two
    can never disagree after a partial write."""
    code = norm_code(code)
    return sum(1 for r in load_store().get('redemptions', [])
               if norm_code(r.get('code')) == code)


def coupon_customer_uses(code, email, phone):
    code, email, phone = norm_code(code), norm_email(email), norm_phone(phone)
    uses = 0
    for r in load_store().get('redemptions', []):
        if norm_code(r.get('code')) != code:
            continue
        if (email and norm_email(r.get('email')) == email) or \
           (phone and norm_phone(r.get('phone')) == phone):
            uses += 1
    return uses


def coupon_scope_note(coupon):
    """Hebrew description of what a scoped coupon covers, for the checkout
    summary. Without it a shopper whose cart is only partly eligible sees a
    discount smaller than the headline percentage and no reason why."""
    ids  = coupon.get('applies_to') or []
    cats = coupon.get('applies_to_categories') or []
    if not ids and not cats:
        return ''
    if cats:
        # dict.fromkeys keeps declaration order while removing the duplicates
        # that arise because several categories share one Hebrew label.
        labels = list(dict.fromkeys(
            CATEGORY_HE.get(str(c).lower(), str(c)) for c in cats))
    else:
        catalog = products_by_id()
        labels = [catalog[i]['name'] for i in ids if i in catalog]
    if not labels:
        return ''
    return 'ההנחה חלה על ' + ', '.join(labels) + ' בלבד'


def coupon_status(coupon):
    """The label the admin table shows. Order matters: an exhausted coupon that
    is also expired reads as expired, which is the more useful thing to know."""
    if not coupon.get('active', True):
        return 'paused'
    expires = _as_date(coupon.get('expires_at'))
    if expires and _il_today() > expires:
        return 'expired'
    starts = _as_date(coupon.get('starts_at'))
    if starts and _il_today() < starts:
        return 'scheduled'
    max_uses = coupon.get('max_uses')
    if max_uses and coupon_used_count(coupon.get('code')) >= int(max_uses):
        return 'exhausted'
    return 'active'


def evaluate_coupon(code, lines, subtotal, delivery, order):
    """Validate a coupon against this cart and customer.

    Returns (ok, discount_amount, free_shipping, message). On failure the
    message is the reason to show the shopper; on success it is the label for
    the summary row.
    """
    coupon = find_coupon(code)
    if not coupon:
        return False, 0, False, _MSG['unknown'], []
    if not coupon.get('active', True):
        return False, 0, False, _MSG['inactive'], []

    today = _il_today()
    starts, expires = _as_date(coupon.get('starts_at')), _as_date(coupon.get('expires_at'))
    if starts and today < starts:
        return False, 0, False, _MSG['early'], []
    if expires and today > expires:
        return False, 0, False, _MSG['expired'], []

    max_uses = coupon.get('max_uses')
    if max_uses and coupon_used_count(coupon['code']) >= int(max_uses):
        return False, 0, False, _MSG['exhausted'], []

    per_customer = coupon.get('per_customer')
    if per_customer:
        used = coupon_customer_uses(coupon['code'], order.get('email'), order.get('phone'))
        if used >= int(per_customer):
            return False, 0, False, _MSG['per_cust'], []

    min_subtotal = int(coupon.get('min_subtotal') or 0)
    if min_subtotal and subtotal < min_subtotal:
        return False, 0, False, _MSG['min'].format(f'{min_subtotal:,}'), []

    # Scope is the union of the two lists; both empty means the whole cart.
    # Category matching is case-insensitive because the catalogue holds both
    # 'Stool' and 'STOOL' — the same reason CATEGORY_ORDER and the delivery-fee
    # lookups fold case.
    ids    = set(coupon.get('applies_to') or [])
    cats   = {str(c).lower() for c in (coupon.get('applies_to_categories') or [])}
    scoped = bool(ids or cats)
    in_scope = [l for l in lines
                if not scoped
                or l['id'] in ids
                or (l['category'] or '').lower() in cats]
    eligible      = sum(l['unit']      * l['qty'] for l in in_scope)   # sale prices
    eligible_list = sum(l['list_unit'] * l['qty'] for l in in_scope)   # ticket prices
    if scoped and eligible <= 0:
        return False, 0, False, _MSG['items'], []

    ctype = coupon.get('type', 'percent')
    value = float(coupon.get('value') or 0)
    if ctype == 'free_shipping':
        # Shipping carries no sale price, so stacking is meaningless for it.
        return True, 0, True, norm_code(coupon['code']), []

    # Missing on coupons written before the flag existed. True keeps their
    # original behaviour rather than quietly making them stingier.
    stackable = coupon.get('stackable', True)

    # The two modes differ only in what the discount is measured from, so work
    # out the price the customer should land on and derive the discount:
    #
    #   stacks      → off what they'd otherwise pay, so 25% on top of a 10% sale
    #                 takes 32.5% off the ticket price.
    #   no stacking → the coupon *replaces* the sale. 25% means they pay 75% of
    #                 the ticket price, full stop; the sale they were already
    #                 getting is netted out of the discount.
    base   = eligible if stackable else eligible_list
    target = base - round(value) if ctype == 'fixed' else base * (1 - value / 100)
    discount = int(round(eligible - target))

    # A non-stacking coupon weaker than the running sale would otherwise *raise*
    # the price. Nobody may end up worse off for entering a code.
    if discount <= 0:
        return False, 0, False, _MSG['worse'], []

    # Never eats into shipping, and never leaves a total Tranzila cannot charge.
    discount = max(0, min(discount, subtotal))
    if subtotal - discount + delivery < 1:
        return False, 0, False, _MSG['zero'], []

    # Which rows the summary should price at the ticket rate — empty when the
    # coupon stacks, since then the sale prices still stand.
    list_ids = [] if stackable else [l['id'] for l in in_scope]
    return True, discount, False, norm_code(coupon['code']), list_ids


def redeem_coupon(order):
    """Record a redemption once the payment is confirmed.

    Deliberately not called at /payment/init: an abandoned checkout must not burn
    one of the "first 10 orders". Idempotent on order_id, because a single
    payment reaches us down several callback paths (see claim_purchase)."""
    code     = norm_code(order.get('coupon_code'))
    order_id = str(order.get('order_id') or '')
    if not code or not order_id:
        return False
    with _store_lock:
        store = load_store()
        for r in store['redemptions']:
            if str(r.get('order_id')) == order_id:
                return False
        store['redemptions'].append({
            'code':     code,
            'order_id': order_id,
            'email':    norm_email(order.get('email')),
            'phone':    norm_phone(order.get('phone')),
            'name':     order.get('name', ''),
            'amount':   order.get('coupon_discount', 0),
            'date':     order.get('date', ''),
        })
        save_store()
    print(f'  [Coupon] {code} redeemed on {order_id} '
          f'({coupon_used_count(code)} total)')
    return True


def coupons_for_admin():
    """Coupons plus the derived numbers the admin table needs. used_count is
    computed here rather than stored, so it is always the truth."""
    store = load_store()
    out   = []
    for c in store.get('coupons', []):
        code = norm_code(c.get('code'))
        out.append({
            **c,
            'code':        code,
            'used_count':  coupon_used_count(code),
            'status':      coupon_status(c),
            'redemptions': [r for r in store.get('redemptions', [])
                            if norm_code(r.get('code')) == code],
        })
    return out


def upsert_coupon(payload):
    """Create or update one coupon. Returns (ok, error)."""
    code = norm_code(payload.get('code'))
    if not code:
        return False, 'Coupon code is required'
    if not _re.match(r'^[A-Z0-9_-]{2,32}$', code):
        return False, 'Code must be 2-32 characters: A-Z, 0-9, - or _'

    ctype = payload.get('type', 'percent')
    if ctype not in COUPON_TYPES:
        return False, f'Unknown coupon type: {ctype}'

    value = float(payload.get('value') or 0)
    if ctype == 'percent' and not (0 < value <= 100):
        return False, 'Percentage must be between 1 and 100'
    if ctype == 'fixed' and value <= 0:
        return False, 'Fixed amount must be above 0'

    # Validated here rather than left to fail silently at checkout: an unknown id
    # or category would create a coupon that matches nothing and simply looks
    # broken to whoever was given it.
    catalog    = products_by_id()
    known_cats = {(p.get('category') or '').lower() for p in catalog.values()}
    ids  = [str(i).strip() for i in (payload.get('applies_to') or []) if str(i).strip()]
    cats = [str(c).strip().lower() for c in (payload.get('applies_to_categories') or [])
            if str(c).strip()]
    unknown = [i for i in ids if i not in catalog] + [c for c in cats if c not in known_cats]
    if unknown:
        return False, f'Unknown product or category: {", ".join(unknown[:3])}'

    n_or_none = lambda v: int(v) if str(v or '').strip() not in ('', '0', 'None') else None

    with _store_lock:
        store    = load_store()
        existing = next((c for c in store['coupons'] if norm_code(c.get('code')) == code), None)
        record   = existing or {'created_at': _il_today().isoformat()}
        record.update({
            'code':         code,
            'type':         ctype,
            'value':        value,
            'active':       bool(payload.get('active', True)),
            'max_uses':     n_or_none(payload.get('max_uses')),
            'per_customer': n_or_none(payload.get('per_customer')),
            'min_subtotal': int(payload.get('min_subtotal') or 0),
            # False = "ללא כפל מבצעים": the coupon replaces any running sale
            # rather than compounding with it.
            'stackable':    bool(payload.get('stackable', False)),
            'starts_at':    (payload.get('starts_at') or '')[:10] or None,
            'expires_at':   (payload.get('expires_at') or '')[:10] or None,
            'applies_to':            ids or None,
            'applies_to_categories': cats or None,
            'note':         str(payload.get('note') or '')[:200],
        })
        if not existing:
            store['coupons'].append(record)
        save_store()
    return True, ''


def set_coupon_active(code, active):
    """Pause or resume a coupon. Saves immediately — "cancel at any time" has to
    mean the next checkout, not the next time somebody presses Save."""
    with _store_lock:
        coupon = find_coupon(code)
        if not coupon:
            return False, 'Coupon not found'
        coupon['active'] = bool(active)
        save_store()
    return True, ''


def delete_coupon(code):
    """Remove a coupon. Its redemptions stay in the log — they are the record of
    real orders, and deleting them would rewrite history."""
    code = norm_code(code)
    with _store_lock:
        store  = load_store()
        before = len(store['coupons'])
        store['coupons'] = [c for c in store['coupons']
                            if norm_code(c.get('code')) != code]
        if len(store['coupons']) == before:
            return False, 'Coupon not found'
        save_store()
    return True, ''



# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):

    # ── Cache policy ─────────────────────────────────────────────────────────
    # Sending no Cache-Control at all makes browsers, proxies and the Railway
    # edge fall back to *heuristic* caching off Last-Modified — which is how a
    # stale homepage (old product count, missing product cards) can keep being
    # served, and crawled, long after a deploy. So be explicit:
    #   HTML           → always revalidate; 304s off Last-Modified keep it cheap
    #   ?v=… assets    → immutable for a year (the URL changes when they change)
    #   everything else→ short TTL, so a replaced image can't stick around
    def _cache_control_for(self, path):
        route, _, query = path.partition('?')
        route = route.partition('#')[0]
        last = route.rsplit('/', 1)[-1]
        # Generated from an env var, not a file on disk: short TTL so the pixel
        # ID can be changed in Railway and take effect without a deploy, and
        # without ever becoming immutable the way a ?v= asset would.
        if route == '/meta/pixel.js':
            return 'public, max-age=300'
        # Rendered from the store, so its contents change whenever the admin
        # sets a discount — it must never be treated as an immutable ?v= asset.
        # 11 KB, so revalidating on every page load costs a 304 and nothing else.
        if route == '/js/data.js':
            return 'no-cache, must-revalidate'
        if route.endswith('/') or last.endswith('.html') or '.' not in last:
            return 'no-cache, must-revalidate'
        if re.search(r'(^|&)v=', query):
            return 'public, max-age=31536000, immutable'
        return 'public, max-age=86400'

    def end_headers(self):
        if not getattr(self, '_cache_hdr_sent', False):
            self._cache_hdr_sent = True
            self.send_header('Cache-Control', self._cache_control_for(self.path))
        super().end_headers()

    def send_response(self, *args, **kwargs):
        # New response on this connection — allow a fresh Cache-Control header.
        self._cache_hdr_sent = False
        super().send_response(*args, **kwargs)

    def guess_type(self, path):
        """Tag text responses as UTF-8 — the storefront is Hebrew, and a bare
        `text/html` leaves the encoding to the client to guess."""
        ctype = super().guess_type(path)
        base = ctype.split(';', 1)[0].strip()
        if base in ('text/html', 'text/css', 'text/plain', 'text/javascript',
                    'application/javascript', 'application/xml', 'text/xml',
                    'application/json'):
            return base + '; charset=utf-8'
        return ctype

    def _client_ip(self):
        """The visitor's IP, not Railway's edge proxy.

        address_string() returns whatever opened the socket, which in
        production is always the proxy — sending that to Meta as
        client_ip_address would give every customer the same address and
        quietly wreck match quality.
        """
        fwd = self.headers.get('X-Forwarded-For', '')
        if fwd:
            return fwd.split(',')[0].strip()
        return self.address_string()

    def _serve_meta_pixel(self):
        """The Meta Pixel base snippet, with the ID injected from the env.

        Served rather than committed so META_PIXEL_ID lives in Railway instead
        of in the HTML — build.py runs on a laptop, so a build-time env var
        could never reach production. With the var unset this is an empty file
        and the site simply has no pixel.
        """
        if meta_capi.PIXEL_ID:
            body = (
                "!function(f,b,e,v,n,t,s)\n"
                "{if(f.fbq)return;n=f.fbq=function(){n.callMethod?\n"
                "n.callMethod.apply(n,arguments):n.queue.push(arguments)};\n"
                "if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';\n"
                "n.queue=[];t=b.createElement(e);t.async=!0;\n"
                "t.src=v;s=b.getElementsByTagName(e)[0];\n"
                "s.parentNode.insertBefore(t,s)}(window,document,'script',\n"
                "'https://connect.facebook.net/en_US/fbevents.js');\n"
                f"fbq('init', {json.dumps(meta_capi.PIXEL_ID)});\n"
                # PageView is the highest-volume event on the site, and without
                # an eventID every one of them counts against Meta's "browser
                # events with an Event ID" coverage. No server twin — CAPI
                # PageView is noise — the id exists so the event is well-formed.
                "window.STEELO_PV_ID = 'pv-' + Date.now().toString(36) + '-' +\n"
                "  Math.random().toString(36).slice(2, 10);\n"
                "if (window.STEELO_CONSENT !== false)\n"
                "  fbq('track', 'PageView', {}, { eventID: window.STEELO_PV_ID });\n"
            )
        else:
            body = '/* Meta Pixel disabled — META_PIXEL_ID not set */\n'
        raw = body.encode('utf-8')
        self._send_body(raw, 'application/javascript; charset=utf-8')

    def _send_body(self, raw, ctype, status=200):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _serve_data_js(self):
        """js/data.js, rendered from the store rather than read off disk — the
        disk copy is whatever git last deployed and knows nothing about the
        discounts the owner set in the admin."""
        raw = render_data_js().encode('utf-8')
        self._send_body(raw, 'application/javascript; charset=utf-8')

    def _serve_product_page(self, route):
        """A generated product page with its machine-readable prices refreshed.

        build.py bakes the price into <meta product:price:amount>, the Product
        JSON-LD and window.STEELO_PRODUCT at build time, on a laptop. Left alone,
        a sale would leave the pages Google actually indexes advertising a price
        the cart contradicts. The visible price needs no help here — it is
        rendered from PRODUCTS by fmtPrice(), same as the grid."""
        pid  = _PRODUCT_ROUTE.match(route).group(1)
        prod = products_by_id().get(pid)
        path = os.path.join(BASE_DIR, 'products', pid, 'index.html')
        if not prod or not os.path.exists(path):
            return super().do_GET()

        key    = (pid, store_rev(), os.path.getmtime(path))
        cached = _page_cache.get(pid)
        if cached and cached[0] == key:
            html = cached[1]
        else:
            with open(path, encoding='utf-8') as f:
                html = rewrite_product_prices(f.read(), prod)
            _page_cache[pid] = (key, html)
        self._send_body(html.encode('utf-8'), 'text/html; charset=utf-8')

    # ── Coupons ──────────────────────────────────────────────────────────────
    def _handle_admin_coupons_get(self):
        if not check_admin_token(self):
            self._json(401, {'ok': False, 'error': 'Unauthorised'})
            return
        self._json(200, {
            'ok': True,
            'coupons':  coupons_for_admin(),
            'products': [{'id': p['id'], 'name': p['name'],
                          'category': p.get('category', '')}
                         for p in products_by_id().values()],
        })

    def _handle_admin_coupons_post(self, raw):
        """Coupons save on their own, not behind the products "Save Changes"
        button: pausing a code has to take effect at the next checkout, not the
        next time somebody remembers to press Save."""
        try:
            data   = json.loads(raw or b'{}')
            action = data.get('action', 'save')
            if action == 'save':
                ok, err = upsert_coupon(data.get('coupon') or {})
            elif action == 'toggle':
                ok, err = set_coupon_active(data.get('code'), data.get('active'))
            elif action == 'delete':
                ok, err = delete_coupon(data.get('code'))
            else:
                ok, err = False, f'Unknown action: {action}'
            self._json(200 if ok else 400,
                       {'ok': ok, 'error': err, 'coupons': coupons_for_admin()})
        except Exception as e:
            self._json(500, {'ok': False, 'error': str(e)})

    def _handle_coupon_validate(self, raw, ip):
        """Live feedback for the checkout field. Advisory only — /payment/init
        re-validates from scratch, so a forged reply here changes nothing about
        what gets charged."""
        if not rate_check(ip, 'coupon', COUPON_LIMIT):
            self._json(429, {'ok': False, 'error': 'יותר מדי ניסיונות. נסו שוב בעוד דקה'})
            return
        try:
            data    = json.loads(raw or b'{}')
            pricing = price_order(data, data.get('coupon_code'))
            if pricing['coupon_error']:
                self._json(200, {'ok': False, 'error': pricing['coupon_error']})
                return
            self._json(200, {
                'ok':            True,
                'code':          pricing['coupon'],
                'discount':      pricing['coupon_discount'],
                'free_shipping': pricing['free_shipping'],
                'subtotal':      pricing['subtotal'],
                'delivery_fee':  pricing['delivery_fee'],
                'total':         pricing['total'],
                # What the summary renders. Equal to the pair above unless the
                # coupon replaces a sale, in which case rows price at the ticket
                # price so a "25% off" code visibly takes 25% off.
                'display_subtotal': pricing['display_subtotal'],
                'display_discount': pricing['display_discount'],
                'list_price_ids':   pricing['list_price_ids'],
                'scope_note':       pricing['scope_note'],
            })
        except Exception as e:
            print(f'  [Coupon] validate failed: {e}')
            self._json(400, {'ok': False, 'error': 'קוד קופון לא קיים'})

    # ── Meta events ──────────────────────────────────────────────────────────
    def _handle_meta_event(self, raw, ip):
        """POST /meta/event — the browser reporting a Pixel event it just fired.

        Two jobs. For every event it records the id in the local ledger, which is
        what lets us measure deduplication ourselves instead of waiting on
        Events Manager's 7-28 day window. For AddToCart it also sends the CAPI
        twin *with the same id*, so ad-blocked visitors stop being invisible for
        the event campaigns optimise on.

        The server-twin list is a strict allow-list: this endpoint is public, and
        without one it would be a way to inject arbitrary conversions into the
        ad account. Purchase and InitiateCheckout are absent on purpose — their
        server copies are sent from the payment path, where the order is real.
        """
        self.send_response(204)
        self.send_header('Content-Length', '0')
        self._cors()
        self.end_headers()

        if not rate_check(ip, 'meta', META_EVENT_LIMIT):
            return
        if analytics.is_bot(self.headers.get('User-Agent', '')):
            return
        try:
            data     = json.loads(raw or b'{}')
            name     = str(data.get('event', ''))[:40]
            event_id = str(data.get('event_id', ''))[:100]
            if not name or not event_id or name not in META_KNOWN_EVENTS:
                return

            # Item ids as the browser sent them, needed twice: once to reject
            # internal test beacons before anything is recorded, and again below
            # to price the CAPI twin from the catalogue.
            items = data.get('items')
            if not items:
                pid = str(data.get('content_id', ''))[:64]
                items = [{'id': pid, 'qty': 1}] if pid else []
            items = items[:50]
            if any(str(it.get('id')) == TEST_PRODUCT_ID for it in items):
                return

            # `fired` is false when the Pixel was blocked. The CAPI twin below
            # still goes out — that is the point — but the ledger must not claim
            # a browser event that never reached Meta, or the coverage figures
            # would flatter themselves.
            if data.get('fired'):
                analytics.log_meta_event(name, event_id, 'browser', 'fired',
                                         data.get('value'))
            elif data.get('note'):
                # A browser event that deliberately did not fire — today only
                # the Purchase value guard in tracking.js. Recorded so a broken
                # /payment/init shows up here instead of as a silent shortfall.
                analytics.log_meta_event(name, event_id, 'browser',
                                         f'not fired: {data["note"]}'[:200],
                                         data.get('value'))

            if name not in META_SERVER_TWIN:
                return

            # Priced from the catalogue, never from the beacon. The browser is
            # trusted for *which* products and how many, not for what they cost —
            # otherwise this public endpoint would let anyone report a
            # million-shekel conversion into the ad account. order_lines() is the
            # same helper checkout prices real orders with.
            lines = order_lines({'items': items})
            value = sum(l['unit'] * l['qty'] for l in lines) + float(data.get('fee') or 0)

            # No email or phone exists this early, so fbp/fbc plus IP and user
            # agent are the only matching signals. Lower match quality than
            # Purchase, which is expected for an anonymous browsing event.
            user_data = meta_capi.build_user_data(
                {}, fbp=str(data.get('fbp') or '')[:200],
                    fbc=str(data.get('fbc') or '')[:400],
                    ip=self._client_ip(),
                    ua=self.headers.get('User-Agent', '')[:500],
            )
            meta_capi.send_event(
                name,
                event_id=event_id,
                user_data=user_data,
                custom_data={
                    'currency':     meta_capi.CURRENCY,
                    'value':        value,
                    'content_type': 'product',
                    'content_ids':  [l['id'] for l in lines],
                    'contents':     [{'id': l['id'], 'quantity': l['qty'],
                                      'item_price': l['unit']} for l in lines],
                    'num_items':    sum(l['qty'] for l in lines),
                },
                event_source_url=str(data.get('url') or '')[:400] or None,
            )
        except Exception as e:
            print(f'  [Meta] /meta/event rejected: {e}')

    def _handle_meta_coverage(self):
        if not check_admin_token(self):
            self._json(401, {'ok': False, 'error': 'Unauthorised'})
            return
        import urllib.parse
        params = urllib.parse.parse_qs(self.path.partition('?')[2])
        try:
            days = max(1, min(int(params.get('days', ['7'])[0]), 90))
        except ValueError:
            days = 7
        self._json(200, analytics.meta_coverage(days))

    # ── Analytics ────────────────────────────────────────────────────────────
    def _handle_analytics_beacon(self, raw, ip):
        """POST /a — one funnel stage from the browser.

        Public by necessity, so it trusts nothing: stage names are allow-listed,
        the two server-recorded stages are refused outright (otherwise anyone
        could award themselves a purchase), every field is length-capped in
        analytics._clean, and bots are dropped on the user agent.

        Always answers 204, even on rejection. A beacon is fire-and-forget; there
        is nobody to tell, and an error status would only invite probing.
        """
        self.send_response(204)
        self.send_header('Content-Length', '0')
        self._cors()
        self.end_headers()

        if not rate_check(ip, 'analytics', ANALYTICS_LIMIT):
            return
        if analytics.is_bot(self.headers.get('User-Agent', '')):
            return
        try:
            data  = json.loads(raw or b'{}')
            stage = str(data.get('stage', ''))
            if stage not in analytics.BROWSER_STAGES:
                return
            analytics.record(
                stage,
                visitor=data.get('visitor', ''),
                session=data.get('session', ''),
                source=data.get('source', 'direct'),
                campaign=data.get('campaign', ''),
            )
        except Exception as e:
            print(f'  [Analytics] beacon rejected: {e}')

    def _handle_analytics_report(self):
        if not check_admin_token(self):
            self._json(401, {'ok': False, 'error': 'Unauthorised'})
            return
        import urllib.parse
        params = urllib.parse.parse_qs(self.path.partition('?')[2])
        grain  = (params.get('granularity', ['day'])[0] or 'day')
        try:
            days = max(1, min(int(params.get('days', ['30'])[0]), 730))
        except ValueError:
            days = 30
        self._json(200, analytics.report(grain, days))

    def _handle_analytics_exclude(self, raw):
        """Flag or unflag the owner's own device, so their browsing stops
        skewing a funnel that currently sees very little traffic."""
        if not check_admin_token(self):
            self._json(401, {'ok': False, 'error': 'Unauthorised'})
            return
        try:
            data = json.loads(raw or b'{}')
            ok = analytics.set_excluded(data.get('visitor', ''),
                                        bool(data.get('excluded', True)))
            self._json(200 if ok else 400, {'ok': ok})
        except Exception as e:
            self._json(500, {'ok': False, 'error': str(e)})

    def do_GET(self):
        route = self.path.partition('?')[0]
        if route == '/meta/pixel.js':
            self._serve_meta_pixel()
        elif route == '/js/data.js':
            self._serve_data_js()
        elif route == '/admin/coupons':
            self._handle_admin_coupons_get()
        elif route == '/admin/analytics':
            self._handle_analytics_report()
        elif route == '/admin/meta':
            self._handle_meta_coverage()
        elif _PRODUCT_ROUTE.match(route):
            self._serve_product_page(route)
        elif self.path.startswith('/payment/confirm'):
            self._handle_payment_confirm()
        elif self.path.startswith('/payment-result'):
            self._handle_payment_result()
        elif self.path.startswith('/payment-success'):
            self._handle_payment_success_redirect()
        elif self.path.startswith('/payment-fail'):
            self._handle_payment_fail_redirect()
        elif self.path.startswith('/debug/sheets'):
            self._debug_sheets()
        else:
            # Tranzila may redirect to /?payment=success via dashboard URL — save order here too
            if 'payment=success' in self.path:
                self._try_save_from_query()
            super().do_GET()

    def _try_save_from_query(self):
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        order_id = (params.get('order_id', ['']) or params.get('Order_ID', ['']))[0]
        # If Tranzila didn't include order_id in the redirect URL, use the pending order
        if not order_id and _pending_orders:
            order_id = list(_pending_orders.keys())[-1]
            print(f'  [PaymentQuery] No order_id in URL — using pending: {order_id}')
        print(f'  [PaymentQuery] order_id={order_id} path={self.path}')
        if order_id:
            self._save_order_from_params(params, order_id)

    def _debug_sheets(self):
        try:
            service = get_sheets_service()
            if not service:
                creds_set = bool(os.environ.get('GOOGLE_CREDENTIALS_JSON'))
                self._json(200, {'ok': False, 'sheets': False,
                    'GOOGLE_CREDENTIALS_JSON': creds_set,
                    'SHEET_ID': bool(SHEET_ID),
                    'pending_orders': list(_pending_orders.keys())})
                return
            result = service.spreadsheets().values().get(
                spreadsheetId=SHEET_ID, range='orders!A1:A3'
            ).execute()
            self._json(200, {'ok': True, 'sheets': True,
                'rows': result.get('values', []),
                'pending_orders': list(_pending_orders.keys())})
        except Exception as e:
            self._json(500, {'ok': False, 'error': str(e),
                'pending_orders': list(_pending_orders.keys())})

    def _handle_payment_confirm(self):
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        order_id   = params.get('order_id',  [''])[0]
        response   = params.get('Response',  [''])[0]
        conf_code  = params.get('ConfirmationCode', [''])[0]

        order = _pending_orders.pop(order_id, None)
        if not order:
            self._json(404, {'ok': False, 'error': 'Order not found or already processed'})
            return

        if response == '000' and conf_code:
            order['payment_ref'] = conf_code
            service = get_sheets_service()
            if service:
                append_order_to_sheet(service, order)
            else:
                print(f'  [Sheets] Not configured — order {order_id} logged to console only.')
                print(f'  [Order] {json.dumps(order, ensure_ascii=False, indent=2)}')
            print(f'  [Payment] Confirmed {order_id} — conf {conf_code}')
            redeem_coupon(order)
            self._fire_purchase(order_id, order)
            self._json(200, {'ok': True, 'order_id': order_id, 'conf': conf_code})
        else:
            print(f'  [Payment] Failed confirm for {order_id} — Response={response}')
            self._json(400, {'ok': False, 'error': f'Payment not confirmed (Response={response})'})

    def _handle_payment_result(self):
        """Legacy /payment-result handler — still live, not dead code: the
        Tranzila terminal's own dashboard is configured with this URL and uses
        it in preference to the success_url/fail_url we pass per transaction.

        Tranzila appends its whole result payload to that URL, which already
        ends in `?status=…`, so everything arrives double-encoded *inside* the
        `status` value. The old test — `'success' in status` — matched on any
        substring, and that blob always contains
        `success_url=…/payment-result?status=success`. A genuinely DECLINED
        card (Response=141, Amex on an acquirer that doesn't take it) was
        therefore treated as paid: marked Paid in the sheet, redirected to the
        thank-you page, and reported to Meta as a Purchase.

        So decide on Tranzila's numeric Response code, which is unambiguous:
        '000' is the only approval. The unpacked payload also carries the real
        Order_ID, so the order no longer has to be guessed from the pending
        list.
        """
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # Unpack the payload Tranzila buried inside `status`.
        status = (params.get('status') or [''])[0]
        if '=' in status:
            for key, val in urllib.parse.parse_qs(status).items():
                params.setdefault(key, val)
            status = status.split('&', 1)[0]

        response = (params.get('Response') or [''])[0].strip()
        order_id = (params.get('Order_ID') or params.get('order_id') or [''])[0]

        # A Response code, when present, is authoritative. Only fall back to
        # the `status` word when Tranzila sent no code at all.
        if response:
            approved = response == '000'
        else:
            approved = status.strip().lower() == 'success'

        print(f'  [PaymentResult/legacy] approved={approved} '
              f'Response={response or "(none)"} order={order_id or "(none)"}')

        if approved:
            self._save_order_from_params(params, order_id)
            redirect_url = f'/?payment=success&order_id={urllib.parse.quote(order_id)}'
        else:
            redirect_url = '/?payment=fail'
        self._redirect(redirect_url)

    def _handle_payment_success_redirect(self):
        """Tranzila GET-redirects here on successful payment."""
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        order_id  = (params.get('Order_ID', None) or params.get('order_id', ['']))[0]
        response  = params.get('Response',         [''])[0]
        conf_code = params.get('ConfirmationCode', [''])[0]
        print(f'  [PaymentSuccess] order={order_id} response={response} conf={conf_code} path={self.path}')
        self._save_order_from_params(params, order_id)
        self._frame_bust(f'/?payment=success&order_id={urllib.parse.quote(order_id)}')

    def _handle_payment_fail_redirect(self):
        """Tranzila GET-redirects here on failed/cancelled payment."""
        print(f'  [PaymentFail] path={self.path}')
        self._frame_bust('/?payment=fail')

    def _save_order_from_params(self, params, order_id):
        order = _pending_orders.pop(order_id, None)
        print(f'  [Sheets] Payment confirmed for {order_id} — marking Paid')
        service = get_sheets_service()
        if service:
            marked = mark_order_paid(service, order_id)
            if not marked:
                print(f'  [Sheets] Could not find row to mark Paid — row was already saved at init')
        # Counted here, not at /payment/init: an abandoned checkout must not burn
        # one of a "first 10 orders" coupon. Idempotent on order_id, because a
        # single payment reaches us down several of these callback paths.
        redeem_coupon(order or {})
        self._fire_purchase(order_id, order)
        if order:
            send_receipt_email(order)

    def _fire_purchase(self, order_id, order):
        """Report a completed purchase to Meta — at most once per order.

        Only ever called from a path where the payment actually succeeded;
        /payment-fail deliberately has no route here.

        `order` can be None when the in-memory entry has already been popped by
        an earlier path, or when a Railway restart (or a second instance — see
        the note in _handle_payment_init) lost it. There is then no value or
        item list to report, so the server stays quiet and the browser's own
        Purchase event carries the order on its own. That redundancy is the
        reason both sides send this event.
        """
        if not claim_purchase(order_id):
            return

        # The funnel's purchase step. Sitting behind claim_purchase means it is
        # counted exactly once no matter which callback path got here first.
        # When the in-memory order is gone the buyer can't be tied to their
        # earlier browsing, but the sale still happened and must still show up,
        # so it is recorded against a stand-in id.
        analytics.record(
            'purchase',
            visitor=(order or {}).get('visitor_id') or f'unknown-{order_id}',
            source=(order or {}).get('visitor_source', 'direct'),
            order_id=order_id,
            value=(order or {}).get('total') or 0,
        )

        if not order:
            print(f'  [Meta] Purchase {order_id} — no order in memory, '
                  f'leaving it to the browser pixel')
            return

        # A Purchase with no real amount is what Meta optimises on, so it is
        # worse than sending nothing. Record the skip rather than reporting ₪0.
        total = float(order.get('total') or 0)
        if total <= 0:
            print(f'  [Meta] Purchase {order_id} — total is {total}, not sent')
            analytics.log_meta_event('Purchase', order_id, 'server',
                                     'skipped: bad value', total)
            return

        contents, ids = meta_capi.contents_from_items(order.get('items'))
        user_data = meta_capi.build_user_data(
            order,
            fbp=order.get('meta_fbp'),
            fbc=order.get('meta_fbc'),
            ip=order.get('meta_ip'),
            ua=order.get('meta_ua'),
        )
        meta_capi.send_event(
            'Purchase',
            # The order ID is the event ID on both sides. Both arrive at it
            # independently — the browser reads it out of the redirect URL —
            # so nothing has to be handed between them for Meta to dedupe.
            event_id=order_id,
            user_data=user_data,
            custom_data={
                'currency':     meta_capi.CURRENCY,
                'value':        total,
                'content_type': 'product',
                'content_ids':  ids,
                'contents':     contents,
                'num_items':    sum(c['quantity'] for c in contents),
                'order_id':     order_id,
            },
            event_source_url=f'{meta_capi.SITE}/?payment=success&order_id={order_id}',
            internal=is_internal_order(order),
        )

    def _redirect(self, location):
        self.send_response(302)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self._cors()
        self.end_headers()

    def _frame_bust(self, location):
        """Navigate the TOP window to `location`.

        Tranzila redirects the embedded payment iframe to our success/fail URL,
        which is same-origin with the parent, so we can drive window.top to break
        out of the iframe. If this page is loaded top-level (redirect fallback),
        window.top === window and it just navigates normally.
        """
        js_url = json.dumps(location)  # safely quoted JS string literal
        safe   = location.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;')
        body = (
            '<!doctype html><html lang="he"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>...</title></head>'
            '<body style="margin:0;background:#F5F0EB;">'
            '<script>(function(){var u=' + js_url + ';'
            'try{(window.top||window).location.replace(u);}catch(e){window.location.replace(u);}})();</script>'
            '<noscript><a href="' + safe + '">המשך</a></noscript>'
            '</body></html>'
        ).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        raw    = self.rfile.read(length)
        ip     = self.address_string()

        # ── Admin login ──────────────────────────────────────────────────────
        if self.path == '/admin/login':
            try:
                data = json.loads(raw)
                pw   = data.get('password', '')
                if hashlib.sha256(pw.encode()).hexdigest() == ADMIN_TOKEN:
                    self._json(200, {'ok': True, 'token': ADMIN_TOKEN})
                else:
                    self._json(401, {'ok': False, 'error': 'Incorrect password'})
            except Exception as e:
                self._json(400, {'ok': False, 'error': str(e)})

        # ── Admin token check ────────────────────────────────────────────────
        # The admin page used to test its token by POSTing an empty array to
        # /admin/save, which happily serialised an empty catalogue over data.js.
        # Verifying deserves its own endpoint that cannot write anything.
        elif self.path == '/admin/verify':
            self._json(200 if check_admin_token(self) else 401,
                       {'ok': check_admin_token(self)})

        # ── Admin save (requires token) ───────────────────────────────────
        elif self.path == '/admin/save':
            if not check_admin_token(self):
                self._json(401, {'ok': False, 'error': 'Unauthorised'})
                return
            try:
                payload  = json.loads(raw)
                products = payload if isinstance(payload, list) else payload.get('products', [])
                if not products:
                    self._json(400, {'ok': False,
                                     'error': 'Refusing to save an empty catalogue'})
                    return
                count = save_product_overrides(products)
                self._json(200, {'ok': True, 'count': len(products), 'changed': count})
            except Exception as e:
                self._json(500, {'ok': False, 'error': str(e)})

        # ── Coupons (requires token) ─────────────────────────────────────────
        elif self.path == '/admin/coupons':
            if not check_admin_token(self):
                self._json(401, {'ok': False, 'error': 'Unauthorised'})
                return
            self._handle_admin_coupons_post(raw)

        # ── Coupon validation (public, for the checkout UI) ──────────────────
        elif self.path == '/coupon/validate':
            self._handle_coupon_validate(raw, ip)

        # ── Funnel analytics ─────────────────────────────────────────────────
        elif self.path == '/a':
            self._handle_analytics_beacon(raw, ip)

        elif self.path == '/admin/analytics/exclude':
            self._handle_analytics_exclude(raw)

        elif self.path == '/meta/event':
            self._handle_meta_event(raw, ip)

        elif self.path == '/payment/init':
            self._handle_payment_init(raw, ip)

        elif self.path == '/payment/charge':
            if not rate_check(ip):
                print(f'  [Rate] Payment blocked for {ip}')
                self._json(429, {'ok': False, 'error': 'Too many attempts. Please wait a minute.'})
                return
            try:
                data = json.loads(raw)
                # ⚠️  Never log card_number, cvv, or expiry
                amount     = float(data.get('amount', 0))
                order_ref  = data.get('order_id', '')
                print(f'  [Payment] Charging ₪{amount} for order {order_ref}')
                ok, tx_id, err = charge_tranzila(
                    amount_ils  = amount,
                    card_number = data.get('card_number', ''),
                    expiry_mmyy = data.get('expiry', ''),
                    cvv         = data.get('cvv', ''),
                    cardholder  = data.get('cardholder', ''),
                    email       = data.get('email', ''),
                    order_id    = order_ref,
                )
                if ok:
                    self._json(200, {'ok': True, 'transaction_id': tx_id})
                else:
                    self._json(402, {'ok': False, 'error': err or 'Payment declined'})
            except Exception as e:
                print(f'  [Payment] Error: {e}')
                self._json(500, {'ok': False, 'error': str(e)})

        elif self.path == '/order':
            try:
                order    = json.loads(raw)
                order_id = order.get('order_id', 'unknown')

                # Honeypot check — bots fill hidden fields
                if order.get('website', '').strip():
                    print(f'  [Order] Honeypot triggered from {ip} — rejected')
                    self._json(400, {'ok': False, 'error': 'Invalid submission'})
                    return

                # Server-side validation
                valid, err_msg = validate_order(order)
                if not valid:
                    print(f'  [Order] Validation failed: {err_msg}')
                    self._json(400, {'ok': False, 'error': err_msg})
                    return

                # Server-side total recalculation (prevents client price tampering)
                verified_total = recalculate_total(order)
                if verified_total != order.get('total', 0):
                    print(f'  [Order] Total mismatch — client: ₪{order.get("total")}, server: ₪{verified_total}. Using server total.')
                    order['total'] = verified_total

                print(f'  [Order] Received {order_id} — {order.get("name")} — ₪{order.get("total")}')

                sheet_ok = False
                service  = get_sheets_service()
                if service:
                    sheet_ok = append_order_to_sheet(service, order)
                else:
                    print('  [Sheets] Not configured — order logged to console only.')
                    print(f'  [Order] {json.dumps(order, ensure_ascii=False, indent=2)}')

                self._json(200, {'ok': True, 'order_id': order_id, 'sheet': sheet_ok})
            except Exception as e:
                print(f'  [Order] Error: {e}')
                self._json(500, {'ok': False, 'error': str(e)})

        # Apple Pay (Tranzila's bridge) POSTs to the success/fail URL instead of
        # GET-redirecting like the card flow — route it through the same handlers
        # so the customer lands on the confirmation screen (not a raw JSON page).
        elif self.path.startswith('/payment-success'):
            self._handle_payment_success_redirect()

        elif self.path.startswith('/payment-fail'):
            self._handle_payment_fail_redirect()

        else:
            # Return 200 for any unhandled POST (e.g. Tranzila server-to-server notification)
            print(f'  [POST] Unhandled: {self.path}')
            self._json(200, {'ok': True})

    def _handle_payment_init(self, raw, ip):
        if not rate_check(ip):
            self._json(429, {'ok': False, 'error': 'Too many attempts. Please wait a minute.'})
            return
        try:
            import urllib.parse
            order = json.loads(raw)

            if order.get('website', '').strip():
                self._json(400, {'ok': False, 'error': 'Invalid submission'})
                return

            valid, err = validate_order(order)
            if not valid:
                self._json(400, {'ok': False, 'error': err})
                return

            # Server-authoritative amount: sale prices from the store, delivery
            # fee by category, coupon re-validated from scratch. Whatever the
            # browser claimed the total was is discarded.
            claimed = order.get('coupon_code')
            pricing = price_order(order, claimed)
            order['delivery_fee']    = pricing['delivery_fee']
            order['coupon_code']     = pricing['coupon']
            order['coupon_discount'] = pricing['coupon_discount']
            order['total']           = pricing['total']

            # The coupon passed in the summary but not here — it was paused, or
            # someone else just took the last of a limited run. Send the customer
            # back rather than quietly charging a total they never agreed to.
            if claimed and pricing['coupon_error']:
                print(f'  [Coupon] {norm_code(claimed)} rejected at init: '
                      f'{pricing["coupon_error"]}')
                self._json(400, {'ok': False, 'coupon_removed': True,
                                 'error': pricing['coupon_error']})
                return

            now = __import__('datetime').datetime.now()
            order.setdefault('date', now.strftime('%d/%m/%Y %H:%M'))

            order_id = order.get('order_id', '')
            if not order_id:
                self._json(400, {'ok': False, 'error': 'Missing order_id'})
                return

            # Meta match signals, captured here because this is the last
            # request we know comes from the customer's own browser. The
            # post-payment callbacks can arrive from Tranzila's servers (the
            # Apple Pay bridge POSTs to us), where the IP and user agent would
            # be Tranzila's, not the buyer's.
            order['meta_fbp'] = str(order.get('meta_fbp') or '')[:200]
            order['meta_fbc'] = str(order.get('meta_fbc') or '')[:400]
            order['meta_ip']  = self._client_ip()
            order['meta_ua']  = self.headers.get('User-Agent', '')[:500]
            # Belong to the checkout events, not to the purchase, so neither is
            # kept on the order.
            order.pop('meta_event_id', None)
            api_event_id = str(order.pop('meta_api_event_id', '') or '')[:100]

            _pending_orders[order_id] = order

            # AddPaymentInfo — the customer has committed to paying. This is the
            # moment the server-side InitiateCheckout used to be sent from, which
            # was the coverage bug: the browser fires InitiateCheckout when the
            # modal opens, so everyone who abandoned before this point left a
            # browser event with no server twin. InitiateCheckout's CAPI copy now
            # goes out from /meta/event at modal-open time instead, and this
            # step reports what it actually is.
            #
            # Worth keeping as its own event because it is the best-matched one
            # on the site: by now the customer has typed name, email, phone, city
            # and postcode, so build_user_data sends a full set of hashed
            # identifiers rather than just cookies.
            #
            # Sent before the Tranzila handshake, because the customer has
            # already reached payment by this point. Reporting it after the
            # handshake would silently lose the signal whenever Tranzila is
            # down — exactly when the funnel data matters most.
            #
            # Sent whether or not the browser managed to fire its own copy, so
            # the ad-blocked case CAPI exists for is still counted. The fallback
            # id is derived from the order rather than random, so a retried
            # /payment/init can't produce two uncorrelated events.
            _contents, _ids = meta_capi.contents_from_items(order.get('items'))
            meta_capi.send_event(
                'AddPaymentInfo',
                event_id=api_event_id or f'api-{order_id}',
                user_data=meta_capi.build_user_data(
                    order, fbp=order['meta_fbp'], fbc=order['meta_fbc'],
                    ip=order['meta_ip'], ua=order['meta_ua'],
                ),
                custom_data={
                    'currency':     meta_capi.CURRENCY,
                    'value':        float(order['total']),
                    'content_type': 'product',
                    'content_ids':  _ids,
                    'contents':     _contents,
                    'num_items':    sum(c['quantity'] for c in _contents),
                },
                internal=is_internal_order(order),
            )

            # Internal test orders (the hidden 'test' product) go to separate
            # tabs so the real orders/marketing data stays clean. Deliberately
            # is_test_order and not is_internal_order: an excluded device buying
            # a real product is a real sale for the sheet, just not for Meta.
            is_test = is_test_order(order)
            orders_tab = 'orders_test' if is_test else 'orders'
            mkt_tab    = 'marketing_test' if is_test else 'marketing'

            # Save immediately to Sheets as "Pending Payment" so we never lose order data
            # (Railway may run multiple instances; _pending_orders is not shared across them)
            try:
                service = get_sheets_service()
                if service:
                    order['status_override'] = 'TEST' if is_test else 'Pending Payment'
                    append_order_to_sheet(service, order, tab=orders_tab)
                    del order['status_override']
                    print(f'  [Sheets] Order {order_id} saved → {orders_tab}')
                    # Add the customer to the marketing list (records consent flags).
                    try:
                        append_marketing_row(service, order, tab=mkt_tab)
                    except Exception as _me:
                        print(f'  [Sheets] Marketing save failed: {_me}')
            except Exception as _se:
                print(f'  [Sheets] Pre-save failed: {_se}')

            import urllib.request as _req, urllib.error as _uerr

            tranzila_pw = TRANZILA_PASSWORD
            if not tranzila_pw:
                raise Exception('TRANZILA_PASSWORD not configured in Railway')

            # Itemized-invoice data must be part of the transaction definition
            # (the handshake), not just the iframe display URL — otherwise the
            # invoicing module ignores it and prints a default, unnamed line.
            purchase_data = build_purchase_data(order, pricing)

            # Step 1: get handshake token from Tranzila
            hw_data = {
                'supplier':   TRANZILA_TERMINAL,
                'sum':        f"{order['total']:.2f}",
                'TranzilaPW': tranzila_pw,
            }
            if purchase_data:
                hw_data['u71'] = '1'                             # enable itemized invoice
                hw_data['json_purchase_data'] = purchase_data
            # quote_via=quote → spaces encode as %20 (not +), per Tranzila's spec
            hw_qs = urllib.parse.urlencode(hw_data, quote_via=urllib.parse.quote)
            try:
                hw_resp = _req.urlopen(
                    f'{TRANZILA_HANDSHAKE_URL}?{hw_qs}', timeout=10
                ).read().decode()
            except _uerr.HTTPError as e:
                hw_resp = e.read().decode()
                raise Exception(f'Tranzila handshake HTTP {e.code}: {hw_resp[:300]}')
            except Exception as e:
                raise Exception(f'Tranzila handshake request failed: {e}')
            print(f'  [Tranzila] Handshake raw response: {hw_resp[:200]}')
            # Response is plain text: "thtk=abc123" or JSON
            thtk = ''
            if hw_resp.startswith('{'):
                thtk = json.loads(hw_resp).get('thtk', '')
            else:
                for part in hw_resp.replace('\n', '&').split('&'):
                    if part.startswith('thtk='):
                        thtk = part.split('=', 1)[1].strip()
            if not thtk:
                raise Exception(f'No thtk in response: {hw_resp[:300]}')

            # Step 2: build iframe URL
            base_site = 'https://www.steelo-design.com'
            iframe_fields = {
                'sum':         f"{order['total']:.2f}",
                'thtk':        thtk,
                'new_process': '1',
                'cred_type':   '1',
                'currency':    '1',
                'contact':     order.get('name', ''),
                'email':       order.get('email', ''),
                'phone':       order.get('phone', ''),
                'Order_ID':    order_id,
                'success_url': f'{base_site}/payment-success?order_id={order_id}',
                'fail_url':    f'{base_site}/payment-fail',
            }
            if purchase_data:
                iframe_fields['u71'] = '1'                       # enable itemized invoice
                iframe_fields['json_purchase_data'] = purchase_data
            # quote_via=quote → spaces encode as %20 (not +), per Tranzila's spec
            iframe_params = urllib.parse.urlencode(iframe_fields, quote_via=urllib.parse.quote)
            iframe_url = f'{TRANZILA_IFRAME_BASE}?{iframe_params}'
            print(f'  [Payment] Init {order_id} — ₪{order["total"]} — handshake OK')
            # Recorded here rather than from the browser: this is the point the
            # payment page actually exists, and a server-side record survives ad
            # blockers, so the bottom of the funnel stays trustworthy even when
            # the top is undercounted.
            analytics.record('checkout_created', visitor=order.get('visitor_id', ''),
                             source=order.get('visitor_source', 'direct'),
                             order_id=order_id, value=order['total'])
            print(f'  [Payment] Invoice items (u71/json_purchase_data): {purchase_data or "(none)"}')

            # `total` is server-authoritative (items + delivery fee, recomputed
            # above). The browser needs it back so its Purchase event reports
            # the amount actually charged — the cart alone has no delivery fee.
            self._json(200, {'ok': True, 'iframe_url': iframe_url,
                             'order_id': order_id, 'total': order['total']})
        except Exception as e:
            print(f'  [Payment/init] Error: {e}')
            self._json(500, {'ok': False, 'error': str(e)})

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f'  {self.address_string()} — {args[0]} {args[1]}')


if __name__ == '__main__':
    os.chdir(BASE_DIR)
    httpd = HTTPServer(('', PORT), Handler)

    sheets_ready = bool(SHEET_ID and os.path.exists(CREDENTIALS_FILE))
    store = load_store()
    analytics.init(STORE_DIR)
    # Gives meta_capi a local record of every CAPI send without it having to
    # know the analytics database exists.
    meta_capi.set_ledger(analytics.log_meta_event)
    # Loud, because a production container without STEELO_DATA_DIR pointed at a
    # mounted volume silently loses every discount and coupon on the next deploy.
    persistent = STORE_DIR != BASE_DIR
    print(f'\n  Steelo store  →  http://localhost:{PORT}')
    print(f'  Admin panel   →  http://localhost:{PORT}/admin.html')
    print(f'  Data store    →  {STORE_PATH} '
          f'{"✓ persistent" if persistent else "⚠ NOT persistent — set STEELO_DATA_DIR to a mounted volume"}')
    print(f'                   {len(store["overrides"])} product overrides · '
          f'{len(store["coupons"])} coupons · {len(store["redemptions"])} redemptions')
    print(f'  Analytics     →  {"✓ ready" if analytics.ready() else "⚠ disabled (could not open the database)"}')
    print(f'  Google Sheets →  {"✓ configured" if sheets_ready else "⚠ not configured (add SHEET_ID + credentials.json)"}')
    print(f'  Tranzila      →  {"✓ password set" if TRANZILA_PASSWORD else "⚠ TRANZILA_PASSWORD not set"}')
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n  Server stopped.')
