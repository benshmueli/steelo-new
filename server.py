#!/usr/bin/env python3
"""
Steelo dev server — serves static files + handles admin save + order endpoints.
Run: python3 server.py
"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json, os, re, hashlib, time

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
]

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


def ensure_header_row(service):
    """Write the header row if the sheet is empty."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range='Sheet1!A1:N1'
        ).execute()
        if not result.get('values'):
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID,
                range='Sheet1!A1',
                valueInputOption='RAW',
                body={'values': [SHEET_COLUMNS]},
            ).execute()
    except Exception as e:
        print(f'  [Sheets] Header row error: {e}')


def append_order_to_sheet(service, order):
    """Append one order row to the Google Sheet."""
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
        'New',
    ]
    try:
        ensure_header_row(service)
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range='Sheet1!A1',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body={'values': [row]},
        ).execute()
        print(f'  [Sheets] Order {order["order_id"]} appended ✓')
        return True
    except Exception as e:
        print(f'  [Sheets] Append error: {e}')
        return False


# ── Tranzila config ──────────────────────────────────────────────────────────
# When you're ready to go live:
# 1. Sign up at https://www.tranzila.com and get your terminal name & credentials
# 2. Set these env vars (or paste directly):
TRANZILA_TERMINAL = os.environ.get('TRANZILA_TERMINAL', '')   # your terminal name
TRANZILA_PASSWORD = os.environ.get('TRANZILA_PASSWORD', '')   # terminal password
TRANZILA_API_URL  = 'https://secure5.tranzila.com/cgi-bin/tranzila71u.cgi'


def charge_tranzila(amount_ils, card_number, expiry_mmyy, cvv, cardholder, email, order_id):
    """
    Charge a card via Tranzila API.
    Returns (success: bool, transaction_id: str, error: str)

    Tranzila docs: https://www.tranzila.com/api
    Parameters reference:
      supplier   — terminal name
      TranzilaPW — terminal password
      ccno       — card number (digits only)
      expdate    — expiry as MMYY
      mycvv      — CVV
      sum        — amount in ILS (e.g. "1200.00")
      currency   — 1 = ILS
      cred_type  — 1 = regular charge
      tranmode   — A = auth+capture
    """
    if not TRANZILA_TERMINAL or not TRANZILA_PASSWORD:
        # ── Sandbox / stub mode ───────────────────────────────────────────
        # When credentials aren't configured, simulate a successful charge.
        # Replace this block with a real call once credentials are set.
        import random, string
        fake_id = 'TZ-' + ''.join(random.choices(string.digits, k=8))
        print(f'  [Tranzila] STUB mode — simulated charge ₪{amount_ils} → {fake_id}')
        return True, fake_id, ''

    try:
        import urllib.request, urllib.parse
        expiry_clean = expiry_mmyy.replace('/', '')          # "MM/YY" → "MMYY"
        params = urllib.parse.urlencode({
            'supplier':   TRANZILA_TERMINAL,
            'TranzilaPW': TRANZILA_PASSWORD,
            'ccno':       card_number,
            'expdate':    expiry_clean,
            'mycvv':      cvv,
            'sum':        f'{amount_ils:.2f}',
            'currency':   '1',
            'cred_type':  '1',
            'tranmode':   'A',
            'email':      email,
            'remarks':    order_id,
        }).encode()
        req  = urllib.request.Request(TRANZILA_API_URL, data=params, method='POST')
        resp = urllib.request.urlopen(req, timeout=15).read().decode()
        # Tranzila returns key=value pairs separated by & or newline
        result = dict(p.split('=', 1) for p in resp.replace('\n', '&').split('&') if '=' in p)
        conf_code = result.get('ConfirmationCode', '')
        error_code = result.get('Response', '')
        if conf_code and conf_code != '000':
            return True, conf_code, ''
        else:
            err_msg = result.get('error', f'Tranzila error code {error_code}')
            print(f'  [Tranzila] Charge failed: {err_msg} | raw: {resp}')
            return False, '', err_msg
    except Exception as ex:
        print(f'  [Tranzila] Exception: {ex}')
        return False, '', str(ex)


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
    required = ['name', 'email', 'phone', 'address', 'city', 'postal_code']
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

    def do_GET(self):
        super().do_GET()

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

        else:
            self.send_response(404)
            self.end_headers()

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
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n  Server stopped.')
