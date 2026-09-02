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
   InitiateCheckout, AddPaymentInfo and Purchase. Each shares an event ID with
   its browser twin so Meta counts one event, not two — see meta_capi.py.

   Where each twin is sent from matters. AddToCart and InitiateCheckout go out
   from /meta/event, at the same instant as the Pixel call, which is what keeps
   their counts 1:1. AddPaymentInfo and Purchase are sent from the payment path
   instead, where a real order exists — so no browser can conjure them, and they
   carry the customer's hashed details rather than just cookies.
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

/* ---- Dataset routing ----

   Two Meta datasets. Production holds real customers; the test dataset holds
   internal traffic, so a ₪1 test purchase can never teach the production ad
   account what a Steelo customer is worth.

   Every event is addressed to exactly one of them with fbq('trackSingle', …).
   A bare fbq('track') goes to every initialised pixel, and since the test
   dataset is initialised lazily — part-way through a page's life, only if
   something needs it — the same call would mean different things at different
   moments. Addressing each event explicitly is what keeps one event out of two
   datasets. Never use fbq('track') in this file. */

const STL_TEST_ID = 'test';

/* Keys an item might carry its identifier under. Only `id` exists in the
   catalogue today; the rest are checked so this keeps working if the product
   schema grows a SKU or a slug. Mirrors _ID_KEYS in server.py. */
const STL_ID_KEYS = ['id', 'sku', 'slug', 'handle', 'content_id'];

/* One test line makes the whole cart a test — a mixed basket is never split
   across datasets. */
function stlIsTestItems(items) {
  return (items || []).some(function (i) {
    return i && STL_ID_KEYS.some(function (k) { return String(i[k]) === STL_TEST_ID; });
  });
}

/* A device the admin flagged with "Ignore this device", or the admin page
   itself. Same key the first-party analytics in analytics.js honour. Such a
   device routes to the test dataset even when buying a REAL product, which is
   the case that matters when exercising the live Tranzila flow. */
function stlDeviceIsInternal() {
  try {
    if (localStorage.getItem('steelo_no_track')) return true;
  } catch (e) {}
  return /\/admin(\.html)?$/.test(location.pathname);
}

/* The dataset id this event belongs to, or '' when it cannot be sent.

   '' happens when the relevant id is unconfigured. For a test event with no
   META_TEST_PIXEL_ID that means the event is dropped — deliberately, rather
   than falling back to production, which is the one outcome this whole change
   exists to prevent. */
function stlTargetDataset(items) {
  var test = stlIsTestItems(items) || stlDeviceIsInternal();
  var id   = test ? window.STEELO_TEST_PIXEL_ID : window.STEELO_PIXEL_ID;
  return id || '';
}

/* fbq('init') for a dataset, at most once per page. Production is already
   init'd by the base snippet; this is what brings the test dataset up the first
   time something is actually routed to it. */
var stlInitedDatasets = {};
function stlEnsureDataset(id) {
  if (!id || stlInitedDatasets[id]) return;
  stlInitedDatasets[id] = true;
  if (id !== window.STEELO_PIXEL_ID) fbq('init', id);
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
      // Lets the server route its CAPI twin to the same dataset. It re-derives
      // this from the item ids it can verify; this flag is what additionally
      // carries the "Ignore this device" case, which is invisible server-side.
      test:     stlDeviceIsInternal(),
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
  const target  = stlTargetDataset([p]);
  if (!target) return;
  stlEnsureDataset(target);
  fbq('trackSingle', target, 'ViewContent', {
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
  const target  = stlTargetDataset([product]);
  const fired   = stlReady() && !!target;

  if (fired) {
    stlEnsureDataset(target);
    fbq('trackSingle', target, 'AddToCart', {
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
  if (!items || !items.length) return;
  const contents = items.map(i => ({
    id: i.id, quantity: i.quantity, item_price: i.price,
  }));
  const value  = items.reduce((s, i) => s + i.price * i.quantity, 0) + (fee || 0);
  const target = stlTargetDataset(items);
  const fired  = stlReady() && !!target;

  if (fired) {
    stlEnsureDataset(target);
    fbq('trackSingle', target, 'InitiateCheckout', {
      content_ids:  items.map(i => i.id),
      content_type: 'product',
      contents:     contents,
      num_items:    items.reduce((s, i) => s + i.quantity, 0),
      value:        value,
      currency:     STL_CURRENCY,
    }, { eventID: eventId });
  }

  // The server twin is sent from this beacon, at the same moment as the Pixel
  // event. It used to be sent from /payment/init instead, which fired only for
  // customers who reached the payment step — so everyone who opened checkout and
  // abandoned produced a browser event with no server counterpart, and Meta
  // reported the resulting coverage gap.
  //
  // Item ids and quantities only: the server prices them from the catalogue, so
  // a forged beacon cannot report an invented cart value into the ad account.
  stlReportEvent('InitiateCheckout', eventId, {
    items: items.map(i => ({ id: i.id, qty: i.quantity })),
    fee:   fee || 0,
    fired: fired,
  });
}

/* ---- AddPaymentInfo ---- */
/* Fired from checkout.js when the customer commits to paying. This is the point
   the old server-side InitiateCheckout used to represent, and it is where the
   customer's details finally exist — so its CAPI twin, sent from /payment/init,
   carries a full set of hashed identifiers rather than just cookies. */
function stlTrackAddPaymentInfo(items, total, eventId) {
  const target = stlTargetDataset(items);
  const fired  = stlReady() && !!target;
  if (fired) {
    stlEnsureDataset(target);
    fbq('trackSingle', target, 'AddPaymentInfo', {
      content_ids:  (items || []).map(i => i.id),
      content_type: 'product',
      contents:     (items || []).map(i => ({
        id: i.id, quantity: i.quantity, item_price: i.price,
      })),
      num_items:    (items || []).reduce((s, i) => s + i.quantity, 0),
      value:        total,
      currency:     STL_CURRENCY,
    }, { eventID: eventId });
  }
  // Log only — the server copy comes from /payment/init, where the order is
  // real, so this beacon must not be able to conjure one.
  stlReportEvent('AddPaymentInfo', eventId, { fired: fired });
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
  // The dataset decision is taken here, while the cart is still in hand, and
  // carried on the record. On the way back only content_ids survive, which
  // catches a test product but not a flagged device buying a real one.
  try {
    if (record && stlDeviceIsInternal()) record.test = true;
    localStorage.setItem(STL_PENDING_PURCHASE, JSON.stringify(record));
  } catch (e) {}
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

  const contentIds = (rec.contents || []).map(c => c.id);

  // A Purchase with no real amount is worse than no Purchase: it is the number
  // Meta optimises on. Report the skip rather than staying silent, so a broken
  // /payment/init shows up in the admin ledger instead of quietly
  // under-counting sales.
  const value = Number(rec.value);
  if (!isFinite(value) || value <= 0) {
    stlReportEvent('Purchase', rec.order_id,
                   { value: rec.value, fired: false, note: 'bad value' });
    return;
  }

  // Routed off the content_ids that came back with the order, exactly as they
  // will be reported — plus the flag stashed at save time for the case where
  // the device is internal but every product in the basket is real.
  const isTest = contentIds.indexOf(STL_TEST_ID) !== -1 || !!rec.test;
  const target = isTest ? window.STEELO_TEST_PIXEL_ID : window.STEELO_PIXEL_ID;
  if (!stlReady() || !target) return;
  stlEnsureDataset(target);

  fbq('trackSingle', target, 'Purchase', {
    content_ids:  contentIds,
    content_type: 'product',
    contents:     rec.contents || [],
    num_items:    (rec.contents || []).reduce((s, c) => s + c.quantity, 0),
    value:        value,
    currency:     rec.currency || STL_CURRENCY,
    order_id:     rec.order_id,
    // event_id = order_id, matching the server event for this same order.
  }, { eventID: rec.order_id });
  stlReportEvent('Purchase', rec.order_id, { value: value, fired: true });
}
