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
import json, os, re, subprocess, html

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE     = "https://www.steelo-design.com"
OUT_ROOT = os.path.join(BASE_DIR, "products")

# ── Load products from js/data.js via node (single source of truth) ──────────
def load_products():
    src = open(os.path.join(BASE_DIR, "js", "data.js"), encoding="utf-8").read()
    src = src.replace("const PRODUCTS", "global.PRODUCTS", 1)
    out = subprocess.check_output(
        ["node", "-e", src + "\nprocess.stdout.write(JSON.stringify(global.PRODUCTS));"],
        cwd=BASE_DIR,
    )
    return json.loads(out)

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
      <a href="/#contact"    class="nav-link" style="font-family:Montserrat,Heebo;font-size:1.3rem;letter-spacing:0.15em;color:var(--ink);">צור קשר</a>
    </div>
    <button id="cart-btn" aria-label="פתיחת סל" style="display:flex;align-items:center;gap:0.5rem;background:none;border:none;cursor:pointer;color:var(--ink);padding:0;">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 01-8 0"/>
      </svg>
      <span id="cart-count" style="font-family:Montserrat,Heebo;font-size:0.75rem;font-weight:500;display:none;"></span>
    </button>
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
          <a href="/#contact"    class="nav-link" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">צור קשר</a>
          <a href="/returns.html" class="nav-link" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);">מדיניות החזרות</a>
        </div>
      </div>
      <div style="margin-top:3rem;padding-top:1.5rem;border-top:1px solid var(--sand-200);display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;">
        <p style="font-family:Montserrat,Heebo;font-size:0.7rem;color:var(--ink-200);margin:0;">© <span class="footer-year">2026</span> Steelo. כל הזכויות שמורות.</p>
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
        <p style="font-family:Montserrat,Heebo;font-weight:300;font-size:0.75rem;line-height:1.7;color:var(--ink-300);margin-bottom:1rem;">כל הפריטים מיוצרים בהזמנה.</p>
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
            <p class="checkout-section-label" style="margin-top:1.75rem;">כתובת למשלוח</p>
            <div class="checkout-field-row">
              <div class="checkout-field" style="flex:2;"><label for="co-address">רחוב ומספר *</label><input id="co-address" name="co-address" type="text" required class="form-input" placeholder="Herzl 12" autocomplete="address-line1"></div>
              <div class="checkout-field" style="flex:1;"><label for="co-apartment">דירה / קומה</label><input id="co-apartment" name="co-apartment" type="text" class="form-input" placeholder="4B" autocomplete="address-line2"></div>
            </div>
            <div class="checkout-field-row">
              <div class="checkout-field" style="flex:2;"><label for="co-city">עיר *</label><input id="co-city" name="co-city" type="text" required class="form-input" placeholder="תל אביב" autocomplete="address-level2"></div>
              <div class="checkout-field" style="flex:1;"><label for="co-postal">מיקוד *</label><input id="co-postal" name="co-postal" type="text" required class="form-input" placeholder="6100000" autocomplete="postal-code"></div>
            </div>
            <div class="checkout-field"><label for="co-country">מדינה</label><input id="co-country" name="co-country" type="text" class="form-input" value="ישראל" autocomplete="country-name"></div>
            <p class="checkout-section-label" style="margin-top:1.75rem;">הערות להזמנה</p>
            <div class="checkout-field"><label for="co-notes">בקשות מיוחדות (לא חובה)</label><textarea id="co-notes" name="co-notes" rows="3" class="form-input" style="resize:none;padding-top:0.75rem;" placeholder="גימור מותאם, העדפת זמן אספקה…"></textarea></div>
            <button type="button" id="checkout-next-btn" class="btn-primary" style="margin-top:1.5rem;">המשך לסיכום ←</button>
          </div>
          <div id="checkout-step2" style="display:none;">
            <h2 class="checkout-title">סיכום הזמנה</h2>
            <div id="checkout-order-items"></div>
            <div class="checkout-total-row"><span>סה״כ</span><span id="checkout-order-total"></span></div>
            <p class="checkout-note">כל הפריטים מיוצרים בהזמנה — זמן אספקה 4–6 שבועות. נאשר את ההזמנה במייל ובוואטסאפ.</p>
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

SCRIPTS = '''  <script src="/js/i18n.js?v=1"></script>
  <script src="/js/data.js?v=6"></script>
  <script src="/js/cart.js?v=6"></script>
  <script src="/js/checkout.js?v=5"></script>
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
  <meta name="robots" content="index, follow">
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
  <link rel="stylesheet" href="/css/styles.css?v=14">
  <script type="application/ld+json">{json.dumps(ld_product, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(ld_crumbs, ensure_ascii=False)}</script>
</head>
<body>
{NAV}
  <div id="page-wrap">
    <main style="padding:7rem 6rem 5rem;max-width:1200px;margin:0 auto;">

      <!-- Breadcrumb -->
      <nav aria-label="breadcrumb" style="font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.05em;color:var(--ink-400);margin-bottom:2.5rem;">
        <a href="/" style="color:var(--ink-400);text-decoration:none;">בית</a>
        <span style="margin:0 0.5rem;">/</span>
        <a href="/#collection" style="color:var(--ink-400);text-decoration:none;">הקולקציה</a>
        <span style="margin:0 0.5rem;">/</span>
        <span style="color:var(--ink);">{esc(name)}</span>
      </nav>

      <div class="pdp-grid" style="display:grid;grid-template-columns:1.1fr 0.9fr;gap:4rem;align-items:start;">
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
            <a href="{WA}" target="_blank" rel="noopener" class="btn-outline" style="background:var(--ink);color:var(--sand-100);border:none;display:flex;align-items:center;justify-content:center;text-decoration:none;">שאלה על המוצר בוואטסאפ</a>
          </div>
          <p style="font-family:Montserrat,Heebo;font-weight:300;font-size:0.75rem;line-height:1.7;color:var(--ink-300);margin-top:1.5rem;">מיוצר בהזמנה — זמן אספקה 4–6 שבועות.</p>
          <a href="/#collection" style="display:inline-block;margin-top:2rem;font-family:Montserrat,Heebo;font-size:0.7rem;letter-spacing:0.15em;color:var(--ink-400);text-decoration:none;">→ חזרה לקולקציה</a>
        </div>
      </div>
    </main>
{FOOTER}
  </div><!-- end page-wrap -->
{MODALS}
{SCRIPTS}
</body>
</html>
'''

# ── Sitemap + robots ─────────────────────────────────────────────────────────
def write_sitemap(products):
    urls = [f"{SITE}/", f"{SITE}/returns.html"] + [f"{SITE}/products/{p['id']}/" for p in products]
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
    write_sitemap(products)
    print(f"  ✓ sitemap.xml + robots.txt")
    print(f"\nGenerated {len(products)} product pages.")

if __name__ == "__main__":
    main()
