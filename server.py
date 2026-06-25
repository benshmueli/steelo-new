#!/usr/bin/env python3
"""
Steelo dev server — serves static files + handles admin save endpoint.
Run: python3 server.py
"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json, os, re

PORT     = 8891
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JS  = os.path.join(BASE_DIR, 'js', 'data.js')


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


class Handler(SimpleHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path == '/admin/save':
            try:
                length   = int(self.headers.get('Content-Length', 0))
                raw      = self.rfile.read(length)
                products = json.loads(raw)
                js       = products_to_js(products)
                with open(DATA_JS, 'w', encoding='utf-8') as f:
                    f.write(js)
                self._json(200, {'ok': True, 'count': len(products)})
            except Exception as e:
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
    print(f'\n  Steelo store  →  http://localhost:{PORT}')
    print(f'  Admin panel   →  http://localhost:{PORT}/admin.html\n')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n  Server stopped.')
