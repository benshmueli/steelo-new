/* ============================================================
   Meta Pixel — browser events
   ============================================================

   The only file in the site that calls fbq(). The base snippet itself is
   served by server.py at /meta/pixel.js, built from the META_PIXEL_ID env
   var, so the ID is never hardcoded here or in any committed HTML.

   Every event carries an eventID, and every event is reported to our own server
   via stlReportEvent so deduplication coverage can be measured locally rather
   than waited on in Events Manager.

   Server-side counterparts (Conversions API) exist for AddToCart,
   InitiateCheckout and Purchase. Each shares an event ID with its browser twin
   so Meta counts one event, not two — see meta_capi.py. AddToCart's twin is
   sent from /meta/event; the other two from the payment path, where the order
   is known to be real.
*/

/* Single consent gate. There is no cookie banner on the site today, so this
   returns true; wiring a banner later means setting window.STEELO_CONSENT =
   false before this script runs and flipping it on accept — no event code
   needs to change. */
function stlConsentGranted() {
  return window.STEELO_CONSENT !== false;
}

function stlReady() {
  return stlConsentGranted() && typeof fbq === 'function';
}

/* Meta's browser cookies. Passing these to the server is what lets a CAPI
   event be attributed to the same person and browser session as the Pixel
   event — without them the server event matches on hashed PII alone. */
function stlFbCookies() {
  const out = { fbp: '', fbc: '' };
  document.cookie.split(';').forEach(part => {
    const [k, ...rest] = part.trim().split('=');
    if (k === '_fbp') out.fbp = rest.join('=');
    if (k === '_fbc') out.fbc = rest.join('=');
  });
  return out;
}

function stlEventId(prefix) {
  return prefix + '-' + Date.now().toString(36) + '-' +
         Math.random().toString(36).slice(2, 10);
}

/* Tell our own server which event ID the Pixel just fired.

   Two reasons. It builds a local ledger of every event and its ID, so
   deduplication coverage can be measured from our own data instead of waiting
   on Events Manager's 7-28 day reporting window. And for the events listed in
   META_SERVER_TWIN on the server (AddToCart today), it is what lets the CAPI
   copy go out carrying the SAME id — which is the whole mechanism by which Meta
   collapses the pair into one event.

   Fire-and-forget, and wrapped: tracking must never break a page. */
function stlReportEvent(name, eventId, extra) {
  try {
    var fb   = (typeof stlFbCookies === 'function') ? stlFbCookies() : { fbp: '', fbc: '' };
    var body = JSON.stringify(Object.assign({
      event:    name,
      event_id: eventId,
      fbp:      fb.fbp,
      fbc:      fb.fbc,
      url:      location.href,
    }, extra || {}));
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/meta/event', new Blob([body], { type: 'application/json' }));
    } else {
      fetch('/meta/event', { method: 'POST', body: body, keepalive: true,
                             headers: { 'Content-Type': 'application/json' } }).catch(function () {});
    }
  } catch (e) {}
}

const STL_CURRENCY = 'ILS';

/* ---- ViewContent — product pages ---- */
/* Reads window.STEELO_PRODUCT, emitted by product_page() in build.py. */
function stlTrackViewContent() {
  if (!stlReady()) return;
  const p = window.STEELO_PRODUCT;
  if (!p) return;
  const eventId = stlEventId('vc');
  fbq('track', 'ViewContent', {
    content_ids:  [p.id],
    content_name: p.name,
    content_type: 'product',
    content_category: p.category || '',
    value:    p.price,
    currency: STL_CURRENCY,
  }, { eventID: eventId });
  stlReportEvent('ViewContent', eventId, { content_id: p.id, value: p.price, fired: true });
}

/* ---- AddToCart ---- */
/* Called from addToCart() in cart.js — the one function every add path goes
   through (quick-view modal, product page, buy-now). Fires only on a real
   add; bumping quantity with the +/- controls in the cart drawer does not
   count as a new add. */
function stlTrackAddToCart(product) {
  if (!product) return;
  const price = (typeof salePrice === 'function')
    ? salePrice(product.price, product.discount)
    : product.price;
  const eventId = stlEventId('atc');
  const fired   = stlReady();

  if (fired) {
    fbq('track', 'AddToCart', {
      content_ids:  [product.id],
      content_name: product.name,
      content_type: 'product',
      content_category: product.category || '',
      contents: [{ id: product.id, quantity: 1, item_price: price }],
      value:    price,
      currency: STL_CURRENCY,
    }, { eventID: eventId });
  }

  // Reported whether or not the Pixel fired. When it is blocked this is the
  // only copy that reaches Meta at all — the server sends the CAPI twin from
  // here. `fired` tells the server whether a browser event really happened, so
  // the ledger doesn't claim one that didn't.
  stlReportEvent('AddToCart', eventId, {
    content_id: product.id, value: price, fired: fired,
  });
}

/* ---- InitiateCheckout ---- */
/* Called from openCheckout() in checkout.js. The caller mints the event ID and
   keeps it, so the same ID can ride along to /payment/init and be reused for
   the server-side copy of this event. */
function stlTrackInitiateCheckout(items, fee, eventId) {
  if (!stlReady() || !items || !items.length) return;
  const contents = items.map(i => ({
    id: i.id, quantity: i.quantity, item_price: i.price,
  }));
  const value = items.reduce((s, i) => s + i.price * i.quantity, 0) + (fee || 0);
  fbq('track', 'InitiateCheckout', {
    content_ids:  items.map(i => i.id),
    content_type: 'product',
    contents:     contents,
    num_items:    items.reduce((s, i) => s + i.quantity, 0),
    value:        value,
    currency:     STL_CURRENCY,
  }, { eventID: eventId });
  stlReportEvent('InitiateCheckout', eventId, { value: value, fired: true });
}

/* ---- Purchase ----
   Written by checkout.js at /payment/init time, from the server's
   authoritative total (the cart alone cannot know the delivery fee), and read
   back here after Tranzila redirects to /?payment=success.

   The record is REMOVED BEFORE the event fires. That ordering is the whole
   guard: refreshing the success URL, or opening it in a second tab, finds
   nothing left to report. The server sends its own Purchase independently with
   event_id = order_id, and Meta collapses the pair.
*/
const STL_PENDING_PURCHASE = 'steelo_pending_purchase';

function stlSavePendingPurchase(record) {
  try { localStorage.setItem(STL_PENDING_PURCHASE, JSON.stringify(record)); } catch (e) {}
}

function stlClearPendingPurchase() {
  try { localStorage.removeItem(STL_PENDING_PURCHASE); } catch (e) {}
}

function stlTrackPurchaseFromRedirect(orderId) {
  let rec = null;
  try { rec = JSON.parse(localStorage.getItem(STL_PENDING_PURCHASE)); } catch (e) {}
  if (!rec || !rec.order_id) return;
  // A record left over from some other order must never be reported against
  // this one; drop it and report nothing.
  if (orderId && rec.order_id !== orderId) { stlClearPendingPurchase(); return; }

  stlClearPendingPurchase();          // consume first, then fire
  if (!stlReady()) return;

  fbq('track', 'Purchase', {
    content_ids:  (rec.contents || []).map(c => c.id),
    content_type: 'product',
    contents:     rec.contents || [],
    num_items:    (rec.contents || []).reduce((s, c) => s + c.quantity, 0),
    value:        rec.value,
    currency:     rec.currency || STL_CURRENCY,
    order_id:     rec.order_id,
    // event_id = order_id, matching the server event for this same order.
  }, { eventID: rec.order_id });
  stlReportEvent('Purchase', rec.order_id, { value: rec.value, fired: true });
}
