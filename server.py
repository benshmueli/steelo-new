#!/usr/bin/env python3
"""
Steelo dev server — serves static files + handles admin save + order endpoints.
Run: python3 server.py
"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json, os, re

PORT     = 8891
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JS  = os.path.join(BASE_DIR, 'js', 'data.js')

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
    """Return an authenticated Google Sheets service, or None if not configured."""
    if not SHEET_ID or not os.path.exists(CREDENTIALS_FILE):
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=['https://www.googleapis.com/auth/spreadsheets'],
        )
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
        lines.append(f"""  {{
    id: '{p['id']}',
    name: '{name}',
    category: '{cat}',
    price: {int(p['price'])},
    dimensions: '{dims}',
    description: '{desc}',
    images: [{imgs}],
  }},""")
    lines.append('];\n')
    return '\n'.join(lines)


# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        raw    = self.rfile.read(length)

        if self.path == '/admin/save':
            try:
                products = json.loads(raw)
                js = products_to_js(products)
                with open(DATA_JS, 'w', encoding='utf-8') as f:
                    f.write(js)
                self._json(200, {'ok': True, 'count': len(products)})
            except Exception as e:
                self._json(500, {'ok': False, 'error': str(e)})

        elif self.path == '/order':
            try:
                order = json.loads(raw)
                order_id = order.get('order_id', 'unknown')
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
