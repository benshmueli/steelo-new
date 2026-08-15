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

def rate_check(ip):
    """Return True if the IP is within the allowed rate. Prunes old entries."""
    now = time.time()
    timestamps = [t for t in _rate.get(ip, []) if now - t < RATE_WINDOW]
    _rate[ip] = timestamps
    if len(timestamps) >= RATE_LIMIT:
        return False
    _rate[ip].append(now)
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

def recalculate_total(order):
    """
    Recalculate the order total server-side from product IDs & quantities.
    Falls back to client total if product lookup fails (stub — replace with DB lookup).
    Returns the verified total.
    """
    # Load current product prices from data.js
    try:
        with open(DATA_JS, 'r', encoding='utf-8') as f:
            src = f.read()
        # Extract price values: price: NNNN
        price_map = {}
        for match in _re.finditer(r"id:\s*'([^']+)'.*?price:\s*(\d+)", src, _re.DOTALL):
            price_map[match.group(1)] = int(match.group(2))

        if not price_map:
            return order.get('total', 0)  # fallback if parse fails

        total = 0
        for item in order.get('items', []):
            pid   = item.get('id') or item.get('name', '')
            qty   = max(1, min(int(item.get('qty', 1)), 99))
            price = price_map.get(pid, item.get('price', 0))
            total += price * qty
        return total
    except Exception as e:
        print(f'  [Validate] Total recalc failed: {e} — using client total')
        return order.get('total', 0)

def _category_map():
    """Parse id → category from data.js (server-authoritative)."""
    try:
        with open(DATA_JS, 'r', encoding='utf-8') as f:
            src = f.read()
        m = {}
        for match in _re.finditer(r"id:\s*'([^']+)'.*?category:\s*'([^']+)'", src, _re.DOTALL):
            m[match.group(1)] = match.group(2)
        return m
    except Exception:
        return {}

def compute_delivery_fee(order):
    """Server-authoritative delivery fee. Pickup is free; shipping sums each
    item's category fee × quantity. Never trusts the client's number."""
    if order.get('delivery_method') == 'pickup':
        return 0
    cat_map = _category_map()
    fee = 0
    for item in order.get('items', []):
        pid = item.get('id') or ''
        qty = max(1, min(int(item.get('qty', 1)), 99))
        cat = (cat_map.get(pid) or item.get('category', '') or '').lower()
        fee += DELIVERY_FEE.get(cat, 0) * qty
    return fee

def _product_map():
    """Parse id → {name, price, dimensions} from data.js (server-authoritative,
    so the invoice never depends on whatever the browser cart happened to store)."""
    try:
        with open(DATA_JS, 'r', encoding='utf-8') as f:
            src = f.read()
        m = {}
        pat = (r"id:\s*'([^']+)'\s*,\s*name:\s*'([^']*)'.*?price:\s*(\d+)"
               r".*?dimensions:\s*'([^']*)'")
        for match in _re.finditer(pat, src, _re.DOTALL):
            m[match.group(1)] = {
                'name':       match.group(2).strip(),
                'price':      int(match.group(3)),
                'dimensions': match.group(4).strip(),
            }
        return m
    except Exception:
        return {}

VAT_RATE = 1.18  # 18% Israeli VAT; listed prices are VAT-inclusive

def _invoice_line_name(pid, item, pmap):
    """A meaningful invoice description: product name (+ dimensions when known),
    resolved server-side by id, falling back to the cart's own fields."""
    info = pmap.get(pid, {})
    name = (info.get('name') or item.get('name') or pid or 'מוצר').strip()
    dims = (info.get('dimensions') or '').strip()
    label = f"{name} · {dims}" if dims else name
    return label[:118]

def build_purchase_data(order):
    """Tranzila json_purchase_data (invoice line items) as a compact JSON string.
    product_price is sent PRE-VAT (price / 1.18) because the account applies VAT;
    a rounding delta is absorbed on the last line so the post-VAT total matches the
    charged sum exactly (else the invoice omits per-line amounts). '' if no items."""
    pmap = _product_map()
    lines = []
    for item in order.get('items', []):
        pid   = item.get('id') or ''
        qty   = max(1, min(int(item.get('qty', 1)), 99))
        gross = pmap.get(pid, {}).get('price', item.get('price', 0))  # VAT-inclusive unit price
        lines.append({
            'product_name':     _invoice_line_name(pid, item, pmap),
            'product_quantity': qty,
            'product_price':    round(gross / VAT_RATE, 2),
        })
    fee = order.get('delivery_fee', 0) or 0
    if fee > 0:
        lines.append({
            'product_name':     'משלוח',
            'product_quantity': 1,
            'product_price':    round(fee / VAT_RATE, 2),
        })
    if not lines:
        return ''
    # Reconcile on the displayed (post-VAT) total the way an Israeli invoice does:
    # VAT is re-added per line and rounded per line, then summed. Adjust the last
    # line's pre-VAT price so Σ(round(price×qty×VAT)) equals the charge exactly —
    # otherwise Tranzila prints the products without per-line amounts.
    charged = round(order.get('total', 0) or 0, 2)
    line_post = lambda l: round(l['product_price'] * l['product_quantity'] * VAT_RATE, 2)
    others = round(sum(line_post(l) for l in lines[:-1]), 2)
    last = lines[-1]
    last_post = round(charged - others, 2)
    last['product_price'] = round(last_post / VAT_RATE / last['product_quantity'], 2)
    return json.dumps(lines, separators=(',', ':'), ensure_ascii=False)

# ── Products helpers ──────────────────────────────────────────────────────────
def products_to_js(products):
    """Serialize the products list back to the data.js format."""
    lines = ['const PRODUCTS = [']
    for p in products:
        imgs = ', '.join(f"'{img}'" for img in p.get('images', []))
        desc = p.get('description', '').replace('\\', '\\\\').replace("'", "\\'")
        name = p.get('name', '').replace("'", "\\'")
        cat  = p.get('category', '').replace("'", "\\'")
        dims = p.get('dimensions', '').replace("'", "\\'")
        disc = max(0, min(99, int(p.get('discount', 0))))
        lines.append(f"""  {{
    id: '{p['id']}',
    name: '{name}',
    category: '{cat}',
    price: {int(p['price'])},
    discount: {disc},
    dimensions: '{dims}',
    description: '{desc}',
    images: [{imgs}],
  }},""")
    lines.append('];\n')
    return '\n'.join(lines)


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
                "if (window.STEELO_CONSENT !== false) fbq('track', 'PageView');\n"
            )
        else:
            body = '/* Meta Pixel disabled — META_PIXEL_ID not set */\n'
        raw = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.partition('?')[0] == '/meta/pixel.js':
            self._serve_meta_pixel()
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
            self._fire_purchase(order_id, order)
            self._json(200, {'ok': True, 'order_id': order_id, 'conf': conf_code})
        else:
            print(f'  [Payment] Failed confirm for {order_id} — Response={response}')
            self._json(400, {'ok': False, 'error': f'Payment not confirmed (Response={response})'})

    def _handle_payment_result(self):
        """Legacy /payment-result handler — kept for backwards compat."""
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        status   = params.get('status', ['fail'])[0]
        order_id = (params.get('Order_ID', None) or params.get('order_id', ['']))[0]
        print(f'  [PaymentResult/legacy] status={status} path={self.path}')
        if 'success' in status:
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
        if not order:
            print(f'  [Meta] Purchase {order_id} — no order in memory, '
                  f'leaving it to the browser pixel')
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
                'value':        float(order.get('total') or 0),
                'content_type': 'product',
                'content_ids':  ids,
                'contents':     contents,
                'num_items':    sum(c['quantity'] for c in contents),
                'order_id':     order_id,
            },
            event_source_url=f'{meta_capi.SITE}/?payment=success&order_id={order_id}',
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

        # ── Admin save (requires token) ───────────────────────────────────
        elif self.path == '/admin/save':
            if not check_admin_token(self):
                self._json(401, {'ok': False, 'error': 'Unauthorised'})
                return
            try:
                payload  = json.loads(raw)
                products = payload if isinstance(payload, list) else payload.get('products', [])
                js = products_to_js(products)
                with open(DATA_JS, 'w', encoding='utf-8') as f:
                    f.write(js)
                self._json(200, {'ok': True, 'count': len(products)})
            except Exception as e:
                self._json(500, {'ok': False, 'error': str(e)})

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

            # Server-authoritative amount: items total + delivery fee (pickup = 0).
            order['delivery_fee'] = compute_delivery_fee(order)
            order['total'] = recalculate_total(order) + order['delivery_fee']

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
            # Not kept on the order — it belongs to the InitiateCheckout event
            # the browser already fired, not to the purchase.
            meta_event_id     = str(order.pop('meta_event_id', '') or '')[:100]

            _pending_orders[order_id] = order

            # Server-side twin of the InitiateCheckout the browser fired when
            # the checkout modal opened. Same event ID, so Meta counts one —
            # but this copy carries the customer's hashed details, which the
            # browser event cannot.
            #
            # Sent here, before the Tranzila handshake, because the customer has
            # already started checkout by this point. Reporting it after the
            # handshake would silently lose the signal whenever Tranzila is
            # down — exactly when the funnel data matters most.
            if meta_event_id:
                _contents, _ids = meta_capi.contents_from_items(order.get('items'))
                meta_capi.send_event(
                    'InitiateCheckout',
                    event_id=meta_event_id,
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
                )

            # Internal test orders (the hidden 'test' product) go to separate
            # tabs so the real orders/marketing data stays clean.
            is_test = any(str(it.get('id')) == 'test' for it in order.get('items', []))
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
            purchase_data = build_purchase_data(order)

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
    print(f'\n  Steelo store  →  http://localhost:{PORT}')
    print(f'  Admin panel   →  http://localhost:{PORT}/admin.html')
    print(f'  Google Sheets →  {"✓ configured" if sheets_ready else "⚠ not configured (add SHEET_ID + credentials.json)"}')
    print(f'  Tranzila      →  {"✓ password set" if TRANZILA_PASSWORD else "⚠ TRANZILA_PASSWORD not set"}')
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n  Server stopped.')
