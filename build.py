#!/usr/bin/env python3
"""
Steelo — static product-page generator.

Reads the single source of truth (js/data.js) and generates one crawlable,
SEO-optimised HTML page per product under /products/<id>/index.html, plus
sitemap.xml and robots.txt.

Design goals:
  - Reuse the site's exact chrome (nav, footer, cart, checkout) so the pages
    look and behave like the rest of the storefront.
  - Render product info as STATIC Hebrew text (best for SEO), mirroring the
    logic in js/modal.js (category labels, dimension formatting, material).
  - Emit Product + BreadcrumbList JSON-LD.

Run:  python3 build.py
"""
import json, os, re, subprocess, html, urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE     = "https://www.steelo-design.com"
OUT_ROOT = os.path.join(BASE_DIR, "products")

# ── Load products from js/data.js via node (single source of truth) ──────────
def load_products():
    """Products in grid order. CATEGORY_ORDER comes from data.js too, so the
    static grid here and renderGrid() in main.js sort by the same list."""
    src = open(os.path.join(BASE_DIR, "js", "data.js"), encoding="utf-8").read()
    src = src.replace("const PRODUCTS", "global.PRODUCTS", 1)
    src = src.replace("const CATEGORY_ORDER", "global.CATEGORY_ORDER", 1)
    out = subprocess.check_output(
        ["node", "-e", src + "\nprocess.stdout.write(JSON.stringify("
                             "{p: global.PRODUCTS, o: global.CATEGORY_ORDER}));"],
        cwd=BASE_DIR,
    )
    data = json.loads(out)
    return sort_by_category(data["p"], data["o"] or [])


def sort_by_category(products, order):
    """Group by category, in `order`. Case-insensitive, because the data holds
    both 'Stool' and 'STOOL'. Unlisted categories sort last rather than first,
    so a new one is visible at the end instead of silently leading the grid.
    Stable, so order within a category stays as authored in data.js."""
    rank = {c.lower(): i for i, c in enumerate(order)}
    return sorted(products,
                  key=lambda p: rank.get((p.get("category") or "").lower(), len(rank)))

# ── Helpers mirroring js/modal.js ────────────────────────────────────────────
CATEGORY_HE = {
    "coffee table": "שולחן סלון",
    "living room table": "שולחן סלון",
    "dining table": "שולחן אוכל",
    "side table": "שידת צד",
    "nesting tables": "שידת צד",
    "stool": "מגזינים",
}
def category_label(cat):
    return CATEGORY_HE.get((cat or "").lower(), cat or "")

def is_public(p):
    """Internal test items keep a working URL (for ₪1 payment checks) but stay
    out of the grid, the item count and the sitemap. One rule, used everywhere,
    so the count can't drift away from the cards again."""
    return p.get("id") != "test"

# Delivery fee (₪) by raw product category — informational, shown on the page.
DELIVERY_FEE = {
    "dining table": 300,
    "coffee table": 100,
    "living room table": 100,
    "side table": 70,
    "nesting tables": 70,
    "stool": 50,
}

def delivery_section(name, cat, raw_category):
    """Build the per-product 'מדיניות משלוחים' accordion (SEO content, no JS)."""
    rows = [
        ("שולחן אוכל מנירוסטה", 300, "שולחן אוכל"),
        ("שולחן סלון מנירוסטה", 100, "שולחן סלון"),
        ("שידת צד מנירוסטה", 70, "שידת צד"),
        ("שרפרף / מעמד מגזינים מנירוסטה", 50, "מגזינים"),
    ]
    items = ""
    for label, amt, key in rows:
        active = (key == cat)
        style = ("font-weight:600;color:var(--ink);" if active
                 else "color:var(--ink-500);")
        mark = ' <span style="color:var(--ink-400);">✓</span>' if active else ""
        items += (f'<li style="{style}padding:0.3rem 0;">{esc(label)} — '
                  f'<span dir="ltr">₪{amt}</span>{mark}</li>')
    n = esc(name)
    c = esc(cat)
    return f'''
      <details class="pdp-delivery">
        <summary>מדיניות משלוחים ואספקה</summary>
        <div class="pdp-delivery-body">
          <p>המשלוח של {n} — {c} מנירוסטה — יוצא אליכם ארוז בקפידה, באותה תשומת לב שהושקעה בייצור הפריט. כאן מרוכזים דמי המשלוח, אפשרות האיסוף העצמי וזמני האספקה.</p>
          <h3>דמי משלוח</h3>
          <ul>{items}</ul>
          <p class="pdp-delivery-note">דמי המשלוח מתווספים ומחושבים בעת השלמת ההזמנה.</p>
          <h3>איסוף עצמי</h3>
          <p>אפשר לאסוף את הפריט ללא עלות ממחסני Steelo, בתיאום מראש.</p>
          <h3>זמני אספקה</h3>
          <p>עד 14 ימי עסקים מרגע אישור ההזמנה.</p>
          <h3>הובלה חריגה</h3>
          <p>כשנדרשים אמצעי הרמה מיוחדים (למשל מנוף), ההזמנה והתשלום עבורם באחריות הלקוח. הובלת פריט גדול בחדר מדרגות מעל קומה 2 — בתוספת <span dir="ltr">₪60</span> לקומה. לא מבצעים משלוחים לאזור אילת.</p>
          <h3>בדיקת המוצר ואחריות</h3>
          <p>עם קבלת הפריט עומדות לרשותכם 24 שעות לבדיקה ולדיווח על כל פגם או אי-התאמה. פנייה שתגיע לאחר מכן לא תמיד תאפשר החזר או החלפה. בבחירת איסוף עצמי, האחריות לשלמות הפריט בדרך היא על הלקוח — מומלץ לבדוק ולארוז אותו היטב לפני הנסיעה.</p>
          <p class="pdp-delivery-wa">יש שאלה על {n}? אנחנו כאן בוואטסאפ: <a href="https://wa.me/972554424206" target="_blank" rel="noopener" dir="ltr">055-4424206</a></p>
        </div>
      </details>'''

def format_dimensions(value):
    """Mirror of formatDimensions() in modal.js → labelled Hebrew, one per line."""
    if not value:
        return ""
    unit = "ס״מ"
    parts = [p.strip() for p in re.sub(r"\s*cm\s*$", "", value, flags=re.I).split("x")]
    if len(parts) == 3:
        width, length, height = parts
        if width == length:
            return f"קוטר : {width} {unit}\nגובה : {height} {unit}"
        return f"אורך : {length} {unit}\nרוחב : {width} {unit}\nגובה : {height} {unit}"
    return value

def price_html(n):
    """Mirror of fmt() in cart.js — shekel sign in Heebo + he-IL thousands."""
    return ('<span style="font-family:Heebo,sans-serif;font-weight:300;font-size:0.62em;'
            'color:inherit;vertical-align:0.12em;">₪</span>' + f"{int(n):,}")

def price_cell_html(p):
    """Mirror of fmtPrice() in cart.js — struck-through original + sale price."""
    discount = p.get("discount") or 0
    if discount <= 0:
        return price_html(p["price"])
    sale = round(p["price"] * (1 - discount / 100))
    return ('<span style="text-decoration:line-through;opacity:0.45;font-size:0.85em;'
            f'margin-right:0.4rem;">{price_html(p["price"])}</span>'
            f'<span style="color:#B85C38;">{price_html(sale)}</span>')

def meta_description(text, limit=155):
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if len(t) <= limit:
        return t
    return t[:limit].rsplit(" ", 1)[0].rstrip(" ,.;—-") + "…"

def esc(s):
    return html.escape(s or "", quote=True)

# ── Shared chrome (absolute paths, home-anchors) ─────────────────────────────
NAV = '''  <!-- NAVBAR -->
  <nav id="navbar">
    <a href="/" class="nav-link" style="display:flex;align-items:center;">
      <img src="/images/logo.png" alt="STEELO" style="height:2.2rem;width:auto;display:block;">
    </a>
    <div class="nav-desktop">
      <a href="/#collection" class="nav-link" style="font-family:Montserrat,Heebo;font-size:1.3rem;letter-spacing:0.15em;color:var(--ink);">הקולקציה</a>
      <a href="/#about"      class="nav-link" style="font-family:Montserrat,Heebo;font-size:1.3rem;letter-spacing:0.15em;color:var(--ink);">אודות</a>
      <a href="/professionals/" class="nav-link" style="font-family:Montserrat,Heebo;font-size:1.3rem;letter-spacing:0.15em;color:var(--ink);">אנשי מקצוע ועסקים</a>
      <a href="/#contact"    class="nav-link" style="font-family:Montserrat,Heebo;font-size:1.3rem;letter-spacing:0.15em;color:var(--ink);">צור קשר</a>
    </div>
    <button id="nav-toggle" class="nav-burger" aria-label="תפריט" aria-expanded="false" aria-controls="nav-mobile">
      <span></span><span></span><span></span>
    </button>
    <button id="cart-btn" aria-label="פתיחת סל" style="display:flex;align-items:center;gap:0.5rem;background:none;border:none;cursor:pointer;color:var(--ink);padding:0;">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 01-8 0"/>
      </svg>
      <span id="cart-count" style="font-family:Montserrat,Heebo;font-size:0.75rem;font-weight:500;display:none;"></span>
    </button>
    <div id="nav-mobile" class="nav-mobile">
      <a href="/#collection">הקולקציה</a>
      <a href="/#about">אודות</a>
      <a href="/professionals/">אנשי מקצוע ועסקים</a>
      <a href="/#contact">צור קשר</a>
    </div>
  </nav>
'''

FOOTER = '''    <!-- FOOTER -->
    <footer style="border-top:1px solid var(--sand-300);padding:3.5rem 2rem 3.5rem 6rem;background:var(--sand);">
      <div class="footer-row" style="display:flex;align-items:flex-start;justify-content:space-between;gap:2rem;flex-wrap:wrap;">
        <div style="margin-inline-end:2rem;">
          <img src="/images/logo.png" alt="STEELO" style="height:2.2rem;width:auto;display:block;margin-bottom:0.5rem;">
          <p style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.1em;color:var(--ink-400);margin:0;">רהיטי נירוסטה על-זמניים</p>
        </div>
        <div class="footer-links" style="display:flex;gap:3rem;align-items:center;flex-wrap:wrap;">
          <a href="/#collection" class="nav-link" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">הקולקציה</a>
          <a href="/#about"      class="nav-link" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">אודות</a>
          <a href="/professionals/" class="nav-link" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">אנשי מקצוע ועסקים</a>
          <a href="/#contact"    class="nav-link" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">צור קשר</a>
          <a href="/returns.html" class="nav-link" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">מדיניות החזרות</a>
        </div>
      </div>
      <div style="margin-top:3rem;padding-top:1.5rem;border-top:1px solid var(--sand-200);display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;">
        <p style="font-family:Montserrat,Heebo;font-size:0.7rem;color:var(--ink-400);margin:0;">© <span class="footer-year">2026</span> Steelo. כל הזכויות שמורות.</p>
      </div>
    </footer>
'''

# Minimal set of modals so cart.js / checkout.js init without errors, and
# add-to-cart / checkout work exactly like on the homepage.
MODALS = '''  <!-- CART -->
  <div id="cart-root" role="region" aria-label="עגלת קניות">
    <div id="cart-overlay"></div>
    <aside id="cart-sidebar">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:1.5rem 1.75rem;border-bottom:1px solid var(--sand-300);">
        <h2 style="font-family:Montserrat,Heebo;font-size:0.65rem;letter-spacing:0.3em;text-transform:uppercase;margin:0;">הסל שלי</h2>
        <button id="cart-close" aria-label="סגירת סל" style="background:none;border:none;cursor:pointer;padding:0.25rem;color:var(--ink);">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div id="cart-items" class="no-scrollbar" style="flex:1;overflow-y:auto;padding:1.5rem 1.75rem;"></div>
      <div style="border-top:1px solid var(--sand-300);padding:1.5rem 1.75rem;">
        <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:1rem;">
          <span style="font-family:Montserrat,Heebo;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">סכום ביניים</span>
          <span id="cart-total" style="font-family:'Cormorant','Frank Ruhl Libre',Georgia,serif;font-weight:300;font-size:1.75rem;color:var(--ink);">₪0</span>
        </div>
        <p style="font-family:Montserrat,Heebo;font-weight:300;font-size:0.75rem;line-height:1.7;color: var(--ink-400);margin-bottom:1rem;">כל הפריטים מיוצרים בהזמנה.</p>
        <button id="checkout-btn" class="btn-primary">לביצוע ההזמנה</button>
      </div>
    </aside>
  </div>

  <!-- INQUIRY (required by cart.js init) -->
  <div id="inquiry-modal" role="dialog" aria-modal="true">
    <div style="width:100%;max-width:520px;padding:3rem;background:var(--sand-100);position:relative;">
      <button id="inquiry-close" aria-label="Close" style="position:absolute;top:1.25rem;right:1.25rem;background:none;border:none;cursor:pointer;padding:0.25rem;color:var(--ink);">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
      <p style="font-family:Montserrat,Heebo;font-size:0.65rem;letter-spacing:0.3em;text-transform:uppercase;color:var(--ink-400);margin-bottom:0.75rem;">פנייה</p>
      <h3 id="inquiry-product-name" style="font-family:'Cormorant','Frank Ruhl Libre',Georgia,serif;font-weight:300;font-size:2.25rem;color:var(--ink);margin-bottom:2rem;line-height:1.1;"></h3>
      <form id="inquiry-form" style="display:flex;flex-direction:column;gap:1rem;">
        <input id="inq-name" type="text" required class="form-input" placeholder="השם שלכם" autocomplete="name">
        <input id="inq-email" type="email" required class="form-input" placeholder="your@email.com" autocomplete="email">
        <textarea id="inq-message" rows="4" class="form-input" style="resize:none;padding-top:0.75rem;" placeholder="ספרו לנו על החלל שלכם..."></textarea>
        <button type="submit" class="btn-primary" style="margin-top:0.5rem;">שליחת פנייה</button>
      </form>
    </div>
  </div>

  <!-- CHECKOUT -->
  <div id="checkout-modal" role="dialog" aria-modal="true" aria-label="תשלום">
    <div class="checkout-panel">
      <div class="checkout-header">
        <div>
          <p class="checkout-label">פרטי הזמנה</p>
          <div class="checkout-steps">
            <span class="checkout-step-dot active"></span><span class="checkout-step-line"></span>
            <span class="checkout-step-dot"></span><span class="checkout-step-line"></span>
            <span class="checkout-step-dot"></span>
          </div>
        </div>
        <button id="checkout-close" aria-label="Close checkout">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div id="checkout-modal-body" class="checkout-body no-scrollbar">
        <form id="checkout-form" novalidate>
          <div style="position:absolute;left:-9999px;top:-9999px;opacity:0;" aria-hidden="true">
            <label for="co-website">Website (leave blank)</label>
            <input id="co-website" name="co-website" type="text" tabindex="-1" autocomplete="off">
          </div>
          <div id="checkout-step1">
            <h2 class="checkout-title">הפרטים שלכם</h2>
            <p class="checkout-section-label">פרטי קשר</p>
            <div class="checkout-field"><label for="co-name">שם מלא *</label><input id="co-name" name="co-name" type="text" required class="form-input" placeholder="שם פרטי ומשפחה" autocomplete="name"></div>
            <div class="checkout-field"><label for="co-email">אימייל *</label><input id="co-email" name="co-email" type="email" required class="form-input" placeholder="your@email.com" autocomplete="email"></div>
            <div class="checkout-field"><label for="co-phone">טלפון / וואטסאפ *</label><input id="co-phone" name="co-phone" type="tel" required class="form-input" placeholder="+972 50 000 0000" autocomplete="tel"></div>
            <p class="checkout-section-label" style="margin-top:1.75rem;">אופן קבלת ההזמנה</p>
            <div class="checkout-delivery-toggle">
              <button type="button" class="cdt-btn active" data-method="ship">משלוח עד הבית</button>
              <button type="button" class="cdt-btn" data-method="pickup">איסוף עצמי · חינם</button>
            </div>
            <input type="hidden" id="co-delivery-method" name="co-delivery-method" value="ship">
            <div id="checkout-ship-fields">
              <p class="checkout-section-label" style="margin-top:1.5rem;">כתובת למשלוח</p>
              <div class="checkout-field-row">
                <div class="checkout-field" style="flex:2;"><label for="co-address">רחוב ומספר *</label><input id="co-address" name="co-address" type="text" required class="form-input" placeholder="הרצל 12" autocomplete="address-line1"></div>
                <div class="checkout-field" style="flex:1;"><label for="co-city">עיר *</label><input id="co-city" name="co-city" type="text" required class="form-input" placeholder="תל אביב" autocomplete="address-level2"></div>
              </div>
              <div class="checkout-field-row">
                <div class="checkout-field" style="flex:1;"><label for="co-floor">קומה</label><input id="co-floor" name="co-floor" type="text" class="form-input" placeholder="2"></div>
                <div class="checkout-field" style="flex:1;"><label for="co-apartment">דירה</label><input id="co-apartment" name="co-apartment" type="text" class="form-input" placeholder="4"></div>
                <div class="checkout-field" style="flex:1;"><label for="co-postal">מיקוד *</label><input id="co-postal" name="co-postal" type="text" required class="form-input" placeholder="6100000" autocomplete="postal-code"></div>
              </div>
              <div class="checkout-field"><label for="co-country">מדינה</label><input id="co-country" name="co-country" type="text" class="form-input" value="ישראל" autocomplete="country-name"></div>
            </div>
            <div id="checkout-pickup-card" style="display:none;">
              <div class="checkout-pickup-box">
                <p class="checkout-pickup-title">איסוף עצמי — ללא עלות</p>
                <p>הכתובת שלנו: חומה ומגדל 26, תל אביב</p>
                <p>זמין לאיסוף תוך 2–4 ימי עסקים, בתיאום מראש בוואטסאפ.</p>
              </div>
            </div>
            <p class="checkout-section-label" style="margin-top:1.75rem;">הערות להזמנה</p>
            <div class="checkout-field"><label for="co-notes">בקשות מיוחדות (לא חובה)</label><textarea id="co-notes" name="co-notes" rows="3" class="form-input" style="resize:none;padding-top:0.75rem;" placeholder="גימור מותאם (בתשלום נוסף), העדפת זמן אספקה…"></textarea></div>
            <div class="checkout-optins">
              <label class="checkout-optin"><input type="checkbox" id="co-optin-email" checked> שלחו לי עדכונים ומבצעים במייל 💌</label>
              <label class="checkout-optin"><input type="checkbox" id="co-optin-wa" checked> עדכנו אותי על דגמים חדשים ומבצעים בוואטסאפ</label>
              <p class="checkout-optin-note">מבטיחים לא להציק — רק דברים ששווים ✨</p>
            </div>
            <button type="button" id="checkout-next-btn" class="btn-primary" style="margin-top:1.5rem;">המשך לסיכום ←</button>
          </div>
          <div id="checkout-step2" style="display:none;">
            <h2 class="checkout-title">סיכום הזמנה</h2>
            <div id="checkout-order-items"></div>
            <div class="checkout-total-row"><span>סה״כ</span><span id="checkout-order-total"></span></div>
            <p class="checkout-note">כל הפריטים מיוצרים בהזמנה — זמן אספקה 5-10 ימי עסקים. נאשר את ההזמנה במייל ובוואטסאפ.</p>
            <p id="checkout-pay-error" style="display:none;font-family:Montserrat,Heebo;font-size:0.75rem;color:#c0392b;margin:1rem 0 0;"></p>
            <div style="display:flex;flex-direction:column;gap:0.75rem;margin-top:1.5rem;">
              <button type="button" id="checkout-to-payment-btn" class="btn-primary">מעבר לתשלום ←</button>
              <button type="button" id="checkout-back-btn" class="btn-outline">חזרה →</button>
            </div>
          </div>
          <div id="checkout-step3" style="display:none;padding:1rem 0;">
            <div id="checkout-spinner" style="text-align:center;padding:3rem 0;">
              <p style="font-family:Montserrat,Heebo;font-size:0.75rem;letter-spacing:0.15em;text-transform:uppercase;color:var(--ink-400);">טוען תשלום מאובטח…</p>
            </div>
            <div id="checkout-iframe-wrap" style="display:none;"></div>
            <p id="checkout-error" style="display:none;font-family:Montserrat,Heebo;font-size:0.75rem;color:#c0392b;margin:1.5rem 0 0;text-align:center;"></p>
            <button type="button" id="checkout-payment-back-btn" class="btn-outline" style="margin-top:1rem;display:none;">חזרה →</button>
          </div>
        </form>
        <div id="checkout-confirmation" style="display:none;text-align:center;padding:3rem 0;">
          <div class="checkout-confirm-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="20 6 9 17 4 12"/></svg></div>
          <p class="checkout-label" style="margin-bottom:0.5rem;">ההזמנה התקבלה</p>
          <p id="checkout-confirm-id" style="font-family:Cormorant,'Frank Ruhl Libre',Georgia,serif;font-weight:300;font-size:1.75rem;color:var(--ink);margin-bottom:1.5rem;"></p>
          <p style="font-family:Montserrat,Heebo;font-weight:300;font-size:0.875rem;line-height:1.7;color:var(--ink-400);max-width:340px;margin:0 auto 2rem;">ניצור קשר תוך 24 שעות לאישור ההזמנה ותיאום המשלוח.</p>
          <button id="checkout-done-btn" class="btn-primary" style="max-width:260px;margin:0 auto;">סיום</button>
        </div>
      </div>
    </div>
  </div>

  <!-- LIGHTBOX -->
  <div id="pdp-lightbox" style="display:none;position:fixed;inset:0;z-index:200;background:rgba(0,0,0,0.92);align-items:center;justify-content:center;">
    <button id="pdp-lb-close" aria-label="Close" style="position:absolute;top:1.25rem;right:1.25rem;background:none;border:none;cursor:pointer;color:#fff;padding:0.5rem;z-index:201;">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
    <img id="pdp-lb-img" src="" alt="" style="max-width:92%;max-height:90%;object-fit:contain;">
  </div>
'''

SCRIPTS = '''  <script src="/js/nav.js?v=1"></script>
  <script src="/js/i18n.js?v=1"></script>
  <script src="/js/data.js?v=9"></script>
  <script src="/js/cart.js?v=8"></script>
  <!-- jQuery required by Tranzila's embedded payment iframe (Apple Pay / Google Pay) -->
  <script src="/js/jquery.min.js?v=1"></script>
  <script src="/js/checkout.js?v=9"></script>
  <!-- Tranzila Apple Pay bridge (must load on the page that hosts the payment iframe) -->
  <script type="text/javascript" src="https://direct.tranzila.com/Tranzila_files/jquery.js"></script>
  <script>document.write('<script src="https://direct.tranzila.com/js/tranzilanapple_v3.js?v=' + Date.now() + '"><\\/script>');</script>
  <script>var $n = jQuery.noConflict(true);</script>
  <script>
    // Footer year
    document.querySelectorAll('.footer-year').forEach(function (el){ el.textContent = new Date().getFullYear(); });

    // Product gallery: swap main image from thumbnails + lightbox
    (function(){
      var main = document.getElementById('pdp-main-img');
      if (!main) return;
      document.querySelectorAll('.pdp-thumb').forEach(function(t){
        t.addEventListener('click', function(){
          main.src = t.dataset.full;
          document.querySelectorAll('.pdp-thumb').forEach(function(x){ x.classList.remove('active'); });
          t.classList.add('active');
        });
      });
      var lb = document.getElementById('pdp-lightbox'), lbImg = document.getElementById('pdp-lb-img');
      function openLb(){ lbImg.src = main.src; lb.style.display='flex'; document.body.style.overflow='hidden'; }
      function closeLb(){ lb.style.display='none'; document.body.style.overflow=''; }
      main.style.cursor='zoom-in';
      main.addEventListener('click', openLb);
      document.getElementById('pdp-lb-close').addEventListener('click', closeLb);
      lb.addEventListener('click', function(e){ if (e.target===lb) closeLb(); });
      document.addEventListener('keydown', function(e){ if (e.key==='Escape') closeLb(); });
    })();

    // Add to cart (uses cart.js addToCart(product) + openCart())
    (function(){
      var btn = document.getElementById('pdp-add-cart');
      if (!btn) return;
      btn.addEventListener('click', function(){
        var p = PRODUCTS.find(function(x){ return x.id === btn.dataset.id; });
        if (p){ addToCart(p); openCart(); }
      });
    })();

    // Quick buy: add to cart then go straight to checkout
    (function(){
      var btn = document.getElementById('pdp-buy-now');
      if (!btn) return;
      btn.addEventListener('click', function(){
        var p = PRODUCTS.find(function(x){ return x.id === btn.dataset.id; });
        if (!p) return;
        addToCart(p);
        if (typeof closeCart === 'function') closeCart();
        if (typeof openCheckout === 'function') openCheckout();
      });
    })();
  </script>

  <!-- Payment-result handler (for returns from Tranzila) -->
  <div id="payment-result-modal" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(20,18,16,0.5);align-items:center;justify-content:center;">
    <div style="background:var(--sand);max-width:480px;width:90%;padding:3rem 2.5rem;text-align:center;position:relative;">
      <div id="payment-result-icon" style="width:3rem;height:3rem;border-radius:50%;background:var(--sand-300);display:flex;align-items:center;justify-content:center;margin:0 auto 1.5rem;"></div>
      <h2 id="payment-result-title" style="font-family:'Cormorant','Frank Ruhl Libre',Georgia,serif;font-weight:300;font-size:2rem;color:var(--ink);margin:0 0 1rem;"></h2>
      <p id="payment-result-msg" style="font-family:Montserrat,Heebo;font-weight:300;font-size:0.875rem;line-height:1.9;color:var(--ink-400);margin:0 0 2rem;"></p>
      <p id="payment-result-order" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.15em;color:var(--ink-400);margin:0 0 2rem;"></p>
      <button onclick="document.getElementById('payment-result-modal').style.display='none';history.replaceState(null,'',location.pathname);" class="btn-primary">חזרה לחנות</button>
    </div>
  </div>
  <script>
  (function(){
    const p = new URLSearchParams(location.search); const status = p.get('payment'); if (!status) return;
    const modal=document.getElementById('payment-result-modal'),icon=document.getElementById('payment-result-icon'),title=document.getElementById('payment-result-title'),msg=document.getElementById('payment-result-msg'),orderEl=document.getElementById('payment-result-order');
    if (status.startsWith('success')) {
      if (typeof clearCart === 'function') clearCart();
      icon.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="20 6 9 17 4 12"/></svg>';
      title.textContent='תודה על הזמנתכם'; msg.textContent='התשלום התקבל. ניצור קשר בקרוב עם פרטי המשלוח.';
      const orderId=p.get('order_id'); if (orderId) orderEl.textContent='הזמנה '+orderId;
      const qs=new URLSearchParams({order_id:orderId,Response:'000',ConfirmationCode:p.get('ConfirmationCode')||''}); fetch('/payment/confirm?'+qs.toString()).catch(()=>{});
    } else { icon.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'; title.textContent='התשלום לא הושלם'; msg.textContent='הכרטיס לא חויב. אפשר לנסות שוב או ליצור איתנו קשר.'; }
    modal.style.display='flex';
  })();
  </script>
'''

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '  <link href="https://fonts.googleapis.com/css2?family=Cormorant:ital,wght@0,300;0,400;0,500;1,300;1,400&family=Frank+Ruhl+Libre:wght@300;400;500;700&family=Heebo:wght@300;400;500;600&family=Montserrat:wght@300;400;500;600&display=swap" rel="stylesheet">')

WA = "https://wa.me/message/NAHJW2Z4TZE5B1"

# ── Per-product page ─────────────────────────────────────────────────────────
def product_page(p):
    pid   = p["id"]
    name  = p["name"]
    cat   = category_label(p["category"])
    price = p["price"]
    material = p.get("material") or "נירוסטה 304"
    dims  = format_dimensions(p.get("dimensions", ""))
    desc  = p.get("description", "")
    imgs  = p.get("images", [])
    url   = f"{SITE}/products/{pid}/"
    img_abs = [SITE + i for i in imgs]

    title = f"{name} — {cat} | Steelo" if cat else f"{name} | Steelo"
    mdesc = meta_description(desc) or f"{name} — {cat} מנירוסטה של Steelo. עיצוב וייצור ישראלי."

    # thumbnails
    thumbs = ""
    if len(imgs) > 1:
        cells = ""
        for i, im in enumerate(imgs):
            active = " active" if i == 0 else ""
            cells += (f'<button class="pdp-thumb{active}" data-full="{esc(im)}" aria-label="תמונה {i+1}" '
                      f'style="border:none;padding:0;cursor:pointer;background:var(--sand-200);aspect-ratio:1;overflow:hidden;">'
                      f'<img src="{esc(im)}" alt="{esc(name)} — תמונה {i+1}" loading="lazy" '
                      f'style="width:100%;height:100%;object-fit:cover;display:block;"></button>')
        thumbs = (f'<div style="display:grid;grid-template-columns:repeat({min(len(imgs),4)},1fr);gap:0.5rem;margin-top:0.75rem;">{cells}</div>')

    # dimensions block (each line)
    dim_html = ""
    if dims:
        rows = "".join(f'<div>{esc(line)}</div>' for line in dims.split("\n"))
        dim_html = (f'<div style="display:flex;justify-content:space-between;padding:0.75rem 0;border-bottom:1px solid var(--sand-200);">'
                    f'<span style="font-family:Montserrat,Heebo;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">מידות</span>'
                    f'<span dir="ltr" style="font-family:Montserrat,Heebo;font-size:0.8rem;color:var(--ink-600);text-align:left;">{rows}</span></div>')

    desc_html = ""
    if desc:
        desc_html = (f'<p style="font-family:Montserrat,Heebo;font-weight:300;font-size:1rem;line-height:1.9;color:var(--ink-400);margin:0 0 2rem;white-space:pre-line;">{esc(desc)}</p>')

    # JSON-LD
    ld_product = {
        "@context": "https://schema.org", "@type": "Product",
        "name": name, "image": img_abs, "sku": pid,
        "brand": {"@type": "Brand", "name": "Steelo"},
        "category": cat, "material": material,
        "offers": {"@type": "Offer", "url": url, "priceCurrency": "ILS",
                   "price": price, "availability": "https://schema.org/InStock",
                   "itemCondition": "https://schema.org/NewCondition"},
    }
    if desc:
        ld_product["description"] = re.sub(r"\s+", " ", desc).strip()
    ld_crumbs = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "בית", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "הקולקציה", "item": SITE + "/#collection"},
            {"@type": "ListItem", "position": 3, "name": name, "item": url},
        ],
    }

    main_src = imgs[0] if imgs else "/images/logo.png"

    return f'''<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(mdesc)}">
  <link rel="canonical" href="{url}">
  <meta name="robots" content="{'noindex, nofollow' if pid == 'test' else 'index, follow'}">
  <meta name="theme-color" content="#1A1715">
  <link rel="icon" type="image/png" href="/images/logo.png">
  <meta property="og:type" content="product">
  <meta property="og:site_name" content="Steelo">
  <meta property="og:locale" content="he_IL">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(mdesc)}">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="{esc(img_abs[0] if img_abs else SITE + '/images/logo.png')}">
  <meta property="product:price:amount" content="{price}">
  <meta property="product:price:currency" content="ILS">
  {FONTS}
  <link rel="stylesheet" href="/css/styles.css?v=25">
  <script type="application/ld+json">{json.dumps(ld_product, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(ld_crumbs, ensure_ascii=False)}</script>
</head>
<body>
{NAV}
  <div id="page-wrap">
    <main class="pdp-main">

      <!-- Breadcrumb -->
      <nav aria-label="breadcrumb" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.05em;color:var(--ink-400);margin-bottom:2.5rem;">
        <a href="/" style="color:var(--ink-400);text-decoration:none;">בית</a>
        <span style="margin:0 0.5rem;">/</span>
        <a href="/#collection" style="color:var(--ink-400);text-decoration:none;">הקולקציה</a>
        <span style="margin:0 0.5rem;">/</span>
        <span style="color:var(--ink);">{esc(name)}</span>
      </nav>

      <div class="pdp-grid">
        <!-- Gallery -->
        <div>
          <div style="background:var(--sand-200);aspect-ratio:1;overflow:hidden;">
            <img id="pdp-main-img" src="{esc(main_src)}" alt="{esc(name)} — {esc(cat)} מנירוסטה של Steelo" style="width:100%;height:100%;object-fit:cover;display:block;">
          </div>
          {thumbs}
        </div>

        <!-- Info -->
        <div>
          <p style="font-family:Montserrat,Heebo;font-size:0.65rem;letter-spacing:0.3em;text-transform:uppercase;color:var(--ink-400);margin:0 0 1rem;">{esc(cat)}</p>
          <h1 style="font-family:'Cormorant','Frank Ruhl Libre',Georgia,serif;font-weight:300;font-size:clamp(2.5rem,4.5vw,3.75rem);line-height:1.05;color:var(--ink);margin:0 0 1.5rem;">{esc(name)}</h1>
          <div style="font-family:'Cormorant','Frank Ruhl Libre',Georgia,serif;font-weight:300;font-size:2.5rem;color:var(--ink);line-height:1;margin-bottom:2rem;">{price_html(price)}</div>
          {desc_html}
          <div style="border-top:1px solid var(--sand-300);margin-bottom:2rem;">
            {dim_html}
            <div style="display:flex;justify-content:space-between;padding:0.75rem 0;">
              <span style="font-family:Montserrat,Heebo;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">חומר</span>
              <span style="font-family:Montserrat,Heebo;font-size:0.8rem;color:var(--ink-600);">{esc(material)}</span>
            </div>
          </div>
          <div style="display:flex;flex-direction:column;gap:0.75rem;">
            <button id="pdp-add-cart" data-id="{esc(pid)}" class="btn-primary" style="background:#F5F0EB;color:var(--ink);border:1px solid var(--ink);">הוספה לסל</button>
            <button id="pdp-buy-now" data-id="{esc(pid)}" class="btn-outline" style="background:var(--ink);color:var(--sand-100);border:none;">קניה מהירה</button>
          </div>
          <p style="font-family:Montserrat,Heebo;font-weight:300;font-size:0.75rem;line-height:1.7;color: var(--ink-400);margin-top:1.5rem;">מיוצר בהזמנה — זמן אספקה 5-10 ימי עסקים.</p>
          <a href="/#collection" style="display:inline-block;margin-top:2rem;font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.15em;color:var(--ink-400);text-decoration:none;">→ חזרה לקולקציה</a>
        </div>
      </div>
{delivery_section(name, cat, p["category"])}
    </main>
{FOOTER}
  </div><!-- end page-wrap -->
{MODALS}
{SCRIPTS}
</body>
</html>
'''

# ── Static content pages ─────────────────────────────────────────────────────
# Prefilled WhatsApp lead message. Must use the phone-number form of the link —
# the short wa.me/message/<id> links silently ignore ?text=.
WA_PRO = ("https://wa.me/972554424206?text="
          + urllib.parse.quote("היי, אני מעוניין/ת בפתרון בהתאמה אישית לפרויקט"))

CONTENT_CSS = '''    .content-wrap { max-width: 760px; margin: 0 auto; padding: 9rem 2rem 5rem; }
    .content-wrap h1 {
      font-family: 'Cormorant','Frank Ruhl Libre',Georgia,serif; font-weight: 300;
      font-size: clamp(2.25rem,5vw,3.75rem); line-height: 1.12; color: var(--ink);
      margin: 0 0 2.5rem; }
    .content-wrap p {
      font-family: Montserrat, Heebo, sans-serif; font-weight: 300;
      font-size: 1rem; line-height: 1.95; color: var(--ink-500); margin: 0 0 1.75rem; }
    .content-divider { width: 2.5rem; height: 1px; background: var(--ink); margin-bottom: 2.5rem; }
    .content-cta { margin-top: 3.5rem; padding-top: 2.5rem; border-top: 1px solid var(--sand-300); }
    .content-cta h2 {
      font-family: 'Cormorant','Frank Ruhl Libre',Georgia,serif; font-weight: 300;
      font-size: clamp(1.6rem,3vw,2.25rem); color: var(--ink); margin: 0 0 1rem; }
    .content-cta p { margin-bottom: 2rem; }
    .wa-cta {
      display: inline-flex; align-items: center; gap: 0.75rem;
      font-family: Montserrat, Heebo, sans-serif; font-size: 0.75rem;
      letter-spacing: 0.2em; text-transform: uppercase; text-decoration: none;
      color: var(--ink); border: 1px solid var(--ink); padding: 1.15rem 3rem;
      transition: background 0.3s, color 0.3s; }
    .wa-cta:hover { background: var(--ink); color: #F5F0EB; }
    @media (max-width: 768px) {
      .content-wrap { padding: 7rem 1.5rem 4rem; }
      .wa-cta { width: 100%; justify-content: center; padding: 1.15rem 1.5rem; }
    }'''

WA_ICON = ('<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
           'stroke-width="1.5"><path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 '
           '8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 '
           '013.8-.9h.5a8.48 8.48 0 018 8v.5z"/></svg>')


def content_page(slug, title, mdesc, h1, body_html, crumb, ld_extra=None):
    """A crawlable static content page using the site's exact chrome, so the
    nav, footer and cart behave the same as everywhere else."""
    url = f"{SITE}/{slug}/"
    ld_crumbs = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "בית", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": crumb, "item": url},
        ],
    }
    extra_ld = (f'\n  <script type="application/ld+json">'
                f'{json.dumps(ld_extra, ensure_ascii=False)}</script>') if ld_extra else ""
    return f'''<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(mdesc)}">
  <link rel="canonical" href="{url}">
  <meta name="robots" content="index, follow">
  <meta name="theme-color" content="#1A1715">
  <link rel="icon" type="image/png" href="/images/logo.png">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Steelo">
  <meta property="og:locale" content="he_IL">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(mdesc)}">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="{SITE}/images/logo.png">
  {FONTS}
  <link rel="stylesheet" href="/css/styles.css?v=25">
  <style>
{CONTENT_CSS}
  </style>
  <script type="application/ld+json">{json.dumps(ld_crumbs, ensure_ascii=False)}</script>{extra_ld}
</head>
<body>
{NAV}
  <div id="page-wrap">
    <main class="content-wrap">

      <nav aria-label="breadcrumb" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.05em;color:var(--ink-400);margin-bottom:2.5rem;">
        <a href="/" style="color:var(--ink-400);text-decoration:none;">בית</a>
        <span style="margin:0 0.5rem;">/</span>
        <span style="color:var(--ink);">{esc(crumb)}</span>
      </nav>

      <div class="content-divider"></div>
      <h1>{esc(h1)}</h1>
{body_html}
    </main>
{FOOTER}
  </div><!-- end page-wrap -->
{MODALS}
{SCRIPTS}
</body>
</html>
'''


def professionals_page():
    """B2B / trade landing page — architects, interior designers, hospitality."""
    h1 = "פתרונות בהתאמה אישית לאדריכלים, מעצבים ועסקים"
    paras = [
        "אנחנו עובדים בשיתוף פעולה עם מעצבי פנים, אדריכלים, בתי קפה, מסעדות, מלונות ועסקים נוספים, ומציעים אפשרות לייצור פריטים בהתאמה אישית ישירות דרך המפעלים שלנו.",
        "בין אם מדובר במידות מיוחדות, התאמות עיצוביות, חומרים, צבעים, כמויות גדולות או פריטים ייחודיים לפרויקט — אנחנו יודעים ללוות את התהליך משלב הרעיון ועד לייצור, ולהתאים את הפתרון לאופי החלל, לצרכים התפעוליים ולשפה העיצובית של הפרויקט.",
        "אנחנו מלווים פרויקטים פרטיים ומסחריים כאחד, עם גמישות בייצור ויכולת לתת מענה גם לפרויקטים בהיקפים גדולים.",
    ]
    body = "\n".join(f"      <p>{esc(t)}</p>" for t in paras)
    body += f'''

      <div class="content-cta">
        <h2>מחפשים פתרון מותאם לפרויקט שלכם?</h2>
        <p>לפרטים נוספים, התייעצות והצעת מחיר — צרו איתנו קשר ישירות בוואטסאפ.</p>
        <a class="wa-cta" href="{WA_PRO}" target="_blank" rel="noopener">
          {WA_ICON}
          דברו איתנו בוואטסאפ
        </a>
      </div>
'''
    ld_service = {
        "@context": "https://schema.org", "@type": "Service",
        "name": "ייצור רהיטי נירוסטה בהתאמה אישית לאדריכלים, מעצבים ועסקים",
        "serviceType": "ייצור רהיטים בהתאמה אישית",
        "provider": {"@type": "Organization", "name": "Steelo", "url": SITE + "/"},
        "areaServed": {"@type": "Country", "name": "IL"},
        "audience": {"@type": "BusinessAudience",
                     "audienceType": "אדריכלים, מעצבי פנים, בתי קפה, מסעדות, מלונות ועסקים"},
        "description": meta_description(paras[0], 300),
        "url": f"{SITE}/professionals/",
    }
    return content_page(
        slug="professionals",
        title="אנשי מקצוע ועסקים — ריהוט נירוסטה בהתאמה אישית | Steelo",
        mdesc=meta_description(paras[0]),
        h1=h1,
        body_html=body,
        crumb="אנשי מקצוע ועסקים",
        ld_extra=ld_service,
    )


# ── Sitemap + robots ─────────────────────────────────────────────────────────
def grid_cards(products):
    """Static HTML for the homepage collection grid — crawlable <a> links to
    each product, mirroring js/main.js renderGrid so it renders identically."""
    out = []
    for p in products:
        if not is_public(p):
            continue
        pid  = p["id"]
        name = p["name"]
        cat  = category_label(p["category"])
        raw  = p.get("category", "")
        imgs = p.get("images", [])
        primary   = imgs[1] if len(imgs) > 1 else (imgs[0] if imgs else "/images/logo.png")
        secondary = imgs[0] if imgs else primary
        alt = f"{name} — {cat} מנירוסטה" if cat else name
        discount = p.get("discount") or 0
        badge = (f'\n          <div style="position:absolute;top:1rem;left:1rem;background:#B85C38;color:#fff;'
                 f'font-family:Montserrat,sans-serif;font-size:0.7rem;font-weight:600;letter-spacing:0.18em;'
                 f'padding:0.3rem 0.65rem;z-index:3;">{discount}% OFF</div>') if discount > 0 else ""
        out.append(
f'''<a href="/products/{esc(pid)}/" aria-label="{esc(name)}" style="background:var(--sand);display:flex;flex-direction:column;cursor:pointer;text-decoration:none;color:inherit;">
        <div class="card-head">
          <p class="card-cat">{esc(raw)}</p>
          <h3 class="card-name">{esc(name)}</h3>
        </div>
        <div class="product-card" style="position:relative;overflow:hidden;aspect-ratio:3/4;">
          <img class="img-primary" src="{esc(primary)}" alt="{esc(alt)}" loading="lazy" style="width:100%;height:100%;object-fit:cover;object-position:center center;display:block;">
          <img class="img-secondary" src="{esc(secondary)}" alt="{esc(name)} — תמונה נוספת" loading="lazy">
          <div class="card-price">{price_cell_html(p)}</div>
          <div class="card-overlay"><span style="display:block;width:100%;box-sizing:border-box;padding:0.75rem;border:1px solid rgba(245,240,235,0.7);background:transparent;color:#F5F0EB;font-family:Montserrat;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;text-align:center;">צפייה בפריט</span></div>{badge}
        </div>
      </a>''')
    return "\n      ".join(out)



def inject_home_grid(products):
    """Replace the marked region inside index.html #products-grid with static
    cards, and sync the collection count to len(products)."""
    path = os.path.join(BASE_DIR, "index.html")
    txt = open(path, encoding="utf-8").read()
    start, end = "<!--grid:start-->", "<!--grid:end-->"
    if start in txt and end in txt:
        before = txt.split(start)[0]
        after  = txt.split(end, 1)[1]
        txt = before + start + "\n      " + grid_cards(products) + "\n      " + end + after
        print("  ✓ index.html collection grid injected (static, crawlable)")
    else:
        print("  ! index.html grid markers not found — skipped")
    open(path, "w", encoding="utf-8").write(txt)


def write_sitemap(products):
    urls = ([f"{SITE}/", f"{SITE}/professionals/", f"{SITE}/returns.html"]
            + [f"{SITE}/products/{p['id']}/" for p in products if is_public(p)])
    items = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{items}\n</urlset>\n")
    open(os.path.join(BASE_DIR, "sitemap.xml"), "w", encoding="utf-8").write(xml)

    robots = f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"
    open(os.path.join(BASE_DIR, "robots.txt"), "w", encoding="utf-8").write(robots)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    products = load_products()
    for p in products:
        d = os.path.join(OUT_ROOT, p["id"])
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(product_page(p))
        print(f"  ✓ /products/{p['id']}/")
    pro_dir = os.path.join(BASE_DIR, "professionals")
    os.makedirs(pro_dir, exist_ok=True)
    open(os.path.join(pro_dir, "index.html"), "w", encoding="utf-8").write(professionals_page())
    print("  ✓ /professionals/")
    inject_home_grid(products)
    write_sitemap(products)
    print(f"  ✓ sitemap.xml + robots.txt")
    print(f"\nGenerated {len(products)} product pages.")

if __name__ == "__main__":
    main()
