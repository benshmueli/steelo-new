/* ============================================================
   Checkout Flow  (2 steps: Details → Order Summary → Tranzila)
   ============================================================ */

function generateOrderId() {
  const now  = new Date();
  const date = now.toISOString().slice(0, 10).replace(/-/g, '');
  const time = String(now.getHours()).padStart(2, '0') + String(now.getMinutes()).padStart(2, '0');
  const rand = String(Math.floor(Math.random() * 900) + 100);
  return `STL-${date}-${time}${rand}`;
}

/* ── Delivery method + fee (mirror of DELIVERY_FEE in build.py/server.py) ── */
const DELIVERY_FEE = {
  'dining table': 300, 'coffee table': 100, 'living room table': 100,
  'side table': 70, 'nesting tables': 70, 'stool': 50,
};
function getDeliveryMethod() {
  const el = document.getElementById('co-delivery-method');
  return el && el.value ? el.value : 'ship';
}
function deliveryFee() {
  if (getDeliveryMethod() === 'pickup') return 0;
  return cart.reduce((s, i) => s + (DELIVERY_FEE[(i.category || '').toLowerCase()] || 0) * i.quantity, 0);
}
function selectDelivery(method) {
  const hidden = document.getElementById('co-delivery-method');
  if (hidden) hidden.value = method;
  document.querySelectorAll('.cdt-btn').forEach(b => b.classList.toggle('active', b.dataset.method === method));
  const isPickup = method === 'pickup';
  const ship   = document.getElementById('checkout-ship-fields');
  const pickup = document.getElementById('checkout-pickup-card');
  if (ship)   ship.style.display   = isPickup ? 'none' : '';
  if (pickup) pickup.style.display = isPickup ? '' : 'none';
  ['co-address', 'co-city', 'co-postal'].forEach(id => {
    const inp = document.getElementById(id);
    if (inp) isPickup ? inp.removeAttribute('required') : inp.setAttribute('required', '');
  });
}

/* ── Coupon ───────────────────────────────────────────────────
   One coupon per order: `appliedCoupon` is a single object, so a second code
   replaces the first rather than adding to it. Everything here is display only
   — /payment/init re-validates the code and recomputes the total from scratch,
   and its answer is the one that gets charged. */
let appliedCoupon = null;   // { code, discount, free_shipping }

const COUPON_PENDING_KEY = 'steelo_coupon';

/* A code can arrive as ?coupon=CODE — how a personal coupon gets handed out:
   send someone a link and they never have to type anything. Stashed rather than
   applied on the spot, because there is nothing to discount until checkout. */
(function captureCouponFromUrl() {
  try {
    const code = new URLSearchParams(location.search).get('coupon');
    if (code) sessionStorage.setItem(COUPON_PENDING_KEY, code.trim().toUpperCase());
  } catch (e) {}
})();

function couponPayload(code) {
  return {
    coupon_code:     code,
    delivery_method: getDeliveryMethod(),
    email:           (document.getElementById('co-email') || {}).value || '',
    phone:           (document.getElementById('co-phone') || {}).value || '',
    items:           cart.map(i => ({ id: i.id, qty: i.quantity })),
  };
}

function showCouponError(msg) {
  const el = document.getElementById('coupon-error');
  if (!el) return;
  el.textContent = msg || '';
  el.style.display = msg ? 'block' : 'none';
}

function renderCoupon() {
  const form = document.getElementById('coupon-form');
  const chip = document.getElementById('coupon-chip');
  const toggle = document.getElementById('coupon-toggle');
  if (!form || !chip || !toggle) return;
  if (appliedCoupon) {
    form.style.display   = 'none';
    toggle.style.display = 'none';
    chip.style.display   = 'flex';
    document.getElementById('coupon-chip-code').textContent = '✓ ' + appliedCoupon.code;
    // displayDiscount, so the chip and the summary row never disagree — for a
    // sale-replacing coupon the two figures differ.
    document.getElementById('coupon-chip-amount').innerHTML =
      appliedCoupon.free_shipping ? 'משלוח חינם' : '−' + fmt(appliedCoupon.displayDiscount);
  } else {
    chip.style.display   = 'none';
    toggle.style.display = '';
  }
}

async function applyCoupon(code, opts) {
  code = (code || '').trim().toUpperCase();
  if (!code) return false;
  const btn = document.getElementById('coupon-apply');
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  showCouponError('');
  try {
    const res  = await fetch('/coupon/validate', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(couponPayload(code)),
    });
    const data = await res.json();
    if (!data.ok) {
      // If the code that just failed is the one already on the order, it has to
      // come off — a coupon that stopped being valid must not keep discounting
      // the summary.
      if (appliedCoupon && appliedCoupon.code === code) {
        appliedCoupon = null;
        renderCoupon();
        buildOrderSummary();
      }
      // A code that arrived in a URL and turned out to be dead should not greet
      // the customer with an error they can do nothing about.
      if (!(opts && opts.silent)) showCouponError(data.error || 'קוד קופון לא קיים');
      return false;
    }
    appliedCoupon = {
      code:          data.code,
      discount:      data.discount,
      free_shipping: data.free_shipping,
      // What the summary renders. Differs from `discount` only for a coupon
      // that replaces a sale rather than stacking with it: the rows in
      // listPriceIds are then priced at the ticket price, so a 25% code shows
      // a 25% reduction instead of a smaller number off an already-cut price.
      displaySubtotal: data.display_subtotal,
      displayDiscount: data.display_discount,
      listPriceIds:    data.list_price_ids || [],
      // Set only for a coupon limited to certain products or a category. Shown
      // under the discount row so a partly-eligible cart doesn't look like the
      // coupon shortchanged them.
      scopeNote:       data.scope_note || '',
    };
    renderCoupon();
    buildOrderSummary();
    return true;
  } catch (e) {
    if (!(opts && opts.silent)) showCouponError('לא הצלחנו לבדוק את הקוד. נסו שוב.');
    return false;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'החל'; }
  }
}

function removeCoupon() {
  appliedCoupon = null;
  try { sessionStorage.removeItem(COUPON_PENDING_KEY); } catch (e) {}
  const input = document.getElementById('coupon-input');
  if (input) input.value = '';
  showCouponError('');
  renderCoupon();
  buildOrderSummary();
}

/* ── Open / Close ─────────────────────────────────────────── */
/* Event IDs for the two Meta checkout events. Each is minted here and shared
   with its CAPI twin so Meta collapses the pair into one event.

   They deliberately fire at different moments, and their twins are sent from
   different places. InitiateCheckout goes out the instant the modal opens, its
   twin from the /meta/event beacon — that pairing is what keeps the counts 1:1
   even when the customer abandons. AddPaymentInfo fires on the click through to
   payment, its twin from /payment/init, where a real order exists and the
   customer's details can be hashed into it. */
let metaCheckoutEventId = '';
let metaPaymentEventId  = '';

function openCheckout() {
  if (!cart || cart.length === 0) return;
  showCouponError('');
  renderCoupon();
  showCheckoutStep(1);
  document.getElementById('checkout-modal').style.display = 'flex';
  document.body.style.overflow = 'hidden';
  if (typeof stlTrackInitiateCheckout === 'function') {
    metaCheckoutEventId = stlEventId('ic');
    stlTrackInitiateCheckout(cart, deliveryFee(), metaCheckoutEventId);
  }
  if (typeof stlTrack === 'function') stlTrack('details');
}

function closeCheckout() {
  document.getElementById('checkout-modal').style.display = 'none';
  document.body.style.overflow = '';
  document.getElementById('checkout-step1').style.display = 'block';
  document.getElementById('checkout-step2').style.display = 'none';
  document.getElementById('checkout-step3').style.display = 'none';
  document.getElementById('checkout-confirmation').style.display = 'none';
  document.getElementById('checkout-form').reset();
  const err = document.getElementById('checkout-error');
  if (err) err.style.display = 'none';
}

/* ── Step indicator ───────────────────────────────────────── */
function showCheckoutStep(n) {
  [1, 2, 3].forEach(i => {
    const el = document.getElementById(`checkout-step${i}`);
    if (el) el.style.display = i === n ? 'block' : 'none';
  });
  document.getElementById('checkout-confirmation').style.display = 'none';
  document.querySelectorAll('.checkout-step-dot').forEach((dot, i) => {
    dot.classList.toggle('active', i + 1 <= n);
  });
  document.getElementById('checkout-modal-body').scrollTop = 0;
}

/* ── Order summary (step 2) ───────────────────────────────── */
function buildOrderSummary() {
  const el = document.getElementById('checkout-order-items');
  el.innerHTML = '';

  // A non-stacking coupon replaces the sale, so the rows it covers are priced
  // at the ticket price. cart.js already keeps `originalPrice` on every item.
  const listIds  = (appliedCoupon && appliedCoupon.listPriceIds) || [];
  const rowPrice = item => (listIds.includes(item.id) ? item.originalPrice : item.price);
  const replacesSale = listIds.length > 0;

  cart.forEach(item => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:space-between;align-items:baseline;padding:0.6rem 0;border-bottom:1px solid var(--sand-300);gap:1rem;';
    row.innerHTML = `
      <div>
        <span style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.15rem;color:var(--ink);">${item.name}</span>
        <span style="font-family:Montserrat;font-size:0.7rem;letter-spacing:0.15em;text-transform:uppercase;color:var(--ink-400);margin-left:0.5rem;">×${item.quantity}</span>
      </div>
      <span style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.1rem;color:var(--ink);white-space:nowrap;">${fmt(rowPrice(item) * item.quantity)}</span>`;
    el.appendChild(row);
  });

  const isPickup = getDeliveryMethod() === 'pickup';
  const freeShip = !!(appliedCoupon && appliedCoupon.free_shipping);
  const fee      = freeShip ? 0 : deliveryFee();
  // The server's figures win whenever a coupon is applied — it is the only side
  // that knows the stacking rule, and the total shown has to be the total
  // charged. Falls back to the cart's own arithmetic when there is no coupon.
  const itemsTotal = appliedCoupon && !freeShip
    ? appliedCoupon.displaySubtotal
    : cart.reduce((s, i) => s + i.price * i.quantity, 0);
  const discount = appliedCoupon && !freeShip ? appliedCoupon.displayDiscount : 0;

  const sumRow = (label, value, cls) => {
    const row = document.createElement('div');
    row.className = 'checkout-sum-row' + (cls ? ' ' + cls : '');
    row.innerHTML = `<span>${label}</span><span>${value}</span>`;
    el.appendChild(row);
  };

  // A subtotal line only earns its place once there is something between it and
  // the total; without a coupon the item rows already add up to the total.
  if (discount) {
    sumRow('ביניים', fmt(itemsTotal));
    sumRow(`הנחה (${appliedCoupon.code})`, '−' + fmt(discount), 'is-discount');
    // Explains why these rows are dearer than the sale prices on the product
    // page — the coupon took the sale's place rather than adding to it.
    const notes = [];
    if (appliedCoupon.scopeNote) notes.push(appliedCoupon.scopeNote);
    if (replacesSale)            notes.push('ללא כפל מבצעים');
    notes.forEach(text => {
      const note = document.createElement('p');
      note.className = 'coupon-stack-note';
      note.textContent = text;
      el.appendChild(note);
    });
  }
  if (isPickup)      sumRow('איסוף עצמי', 'חינם');
  else if (freeShip) sumRow('משלוח', 'חינם', 'is-discount');
  else               sumRow('משלוח', fmt(fee));

  document.getElementById('checkout-order-total').innerHTML =
    fmt(Math.max(itemsTotal - discount, 0) + fee);
}

/* ── Step 1 → Step 2 (details → summary) ─────────────────── */
document.getElementById('checkout-next-btn').addEventListener('click', () => {
  const step1Fields = document.querySelectorAll('#checkout-step1 [required]');
  let valid = true;
  step1Fields.forEach(f => {
    f.style.borderColor = '';
    if (!f.value.trim()) { f.style.borderColor = '#c0392b'; valid = false; }
  });
  if (!valid) return;
  buildOrderSummary();
  showCheckoutStep(2);
  if (typeof stlTrack === 'function') stlTrack('summary');

  // A coupon's discount is an absolute figure computed for one particular cart,
  // so it has to be re-checked every time this summary is built — the customer
  // may have changed the cart or the delivery method since applying it. This is
  // also where a code from ?coupon=… first applies itself, now that there is a
  // cart and a customer for the server to validate against.
  let pending = appliedCoupon ? appliedCoupon.code : '';
  if (!pending) {
    try { pending = sessionStorage.getItem(COUPON_PENDING_KEY) || ''; } catch (e) {}
  }
  if (pending) applyCoupon(pending, { silent: true });
});

/* ── Coupon controls ──────────────────────────────────────── */
document.getElementById('coupon-toggle').addEventListener('click', () => {
  const form  = document.getElementById('coupon-form');
  const open  = form.style.display !== 'none';
  form.style.display = open ? 'none' : 'flex';
  if (!open) document.getElementById('coupon-input').focus();
});
document.getElementById('coupon-apply').addEventListener('click', () => {
  applyCoupon(document.getElementById('coupon-input').value);
});
document.getElementById('coupon-input').addEventListener('keydown', e => {
  // Enter inside a form would submit it; this field is a lookup, not a submit.
  if (e.key === 'Enter') { e.preventDefault(); applyCoupon(e.target.value); }
});
document.getElementById('coupon-remove').addEventListener('click', removeCoupon);

/* ── Step 2 back → Step 1 ─────────────────────────────────── */
document.getElementById('checkout-back-btn').addEventListener('click', () => {
  showCheckoutStep(1);
});

/* ── Step 2 → Tranzila (proceed to payment) ──────────────── */
document.getElementById('checkout-to-payment-btn').addEventListener('click', async () => {
  showCheckoutStep(3); // show spinner

  const errEl = document.getElementById('checkout-error');
  const backBtn = document.getElementById('checkout-payment-back-btn');
  if (errEl) errEl.style.display = 'none';
  if (backBtn) backBtn.style.display = 'none';

  const f       = document.getElementById('checkout-form');
  const orderId = generateOrderId();
  const now     = new Date();
  const dateStr = now.toLocaleString('he-IL', { timeZone: 'Asia/Jerusalem', hour12: false });
  const method    = getDeliveryMethod();
  const freeShip  = !!(appliedCoupon && appliedCoupon.free_shipping);
  const fee       = freeShip ? 0 : deliveryFee();
  // `discount`, not `displayDiscount`: this pairs with the cart's sale prices,
  // where the summary pairs displayDiscount with displaySubtotal. Both land on
  // the same total, and the server recomputes it regardless.
  const discount  = appliedCoupon && !freeShip ? appliedCoupon.discount : 0;
  const itemsTotal = cart.reduce((s, i) => s + i.price * i.quantity, 0);
  const total     = Math.max(itemsTotal - discount, 0) + fee;
  const val = id => (f[id] ? f[id].value.trim() : '');
  const checked = id => { const el = document.getElementById(id); return !!(el && el.checked); };

  // Fired here, before the request, so its id can ride along and the CAPI twin
  // sent from /payment/init carries the same one.
  if (typeof stlTrackAddPaymentInfo === 'function') {
    metaPaymentEventId = stlEventId('api');
    stlTrackAddPaymentInfo(cart, total, metaPaymentEventId);
  }

  const payload = {
    order_id:    orderId,
    date:        dateStr,
    name:        f['co-name'].value.trim(),
    email:       f['co-email'].value.trim(),
    phone:       f['co-phone'].value.trim(),
    delivery_method: method,
    delivery_fee:    fee,
    address:     val('co-address'),
    floor:       val('co-floor'),
    apartment:   val('co-apartment'),
    city:        val('co-city'),
    postal_code: val('co-postal'),
    country:     val('co-country'),
    notes:       f['co-notes'].value.trim(),
    optin_email: checked('co-optin-email'),
    optin_wa:    checked('co-optin-wa'),
    website:     f['co-website'].value.trim(),
    items:       cart.map(i => ({ id: i.id, name: i.name, category: i.category, qty: i.quantity, price: i.price })),
    coupon_code: appliedCoupon ? appliedCoupon.code : '',
    total,
  };

  // Meta match signals. The server cannot read these cookies itself — they are
  // first-party to this page — and without them its Purchase event has only
  // hashed PII to match on.
  if (typeof stlFbCookies === 'function') {
    const fb = stlFbCookies();
    payload.meta_fbp = fb.fbp;
    payload.meta_fbc = fb.fbc;
    payload.meta_event_id = metaCheckoutEventId;
    payload.meta_api_event_id = metaPaymentEventId;
  }

  // Lets the server record the last two funnel stages against the same person
  // who did the browsing. Those two are recorded server-side so they survive ad
  // blockers — but only the browser knows which visitor this is.
  if (typeof stlVisitorId === 'function') {
    payload.visitor_id = stlVisitorId();
    try {
      payload.visitor_source = JSON.parse(sessionStorage.getItem('steelo_src')).source;
    } catch (e) {}
  }

  try {
    const res  = await fetch('/payment/init', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    const data = await res.json();

    // The coupon passed in the summary but not on the server — paused since, or
    // someone else just took the last use of a limited run. Drop it and send the
    // customer back to a summary showing the real total, rather than charging a
    // number they never agreed to.
    if (data.coupon_removed) {
      appliedCoupon = null;
      try { sessionStorage.removeItem(COUPON_PENDING_KEY); } catch (e) {}
      renderCoupon();
      buildOrderSummary();
      showCheckoutStep(2);
      showCouponError(data.error || 'הקופון אינו תקף עוד');
      return;
    }
    if (!data.ok) throw new Error(data.error || t('pay_init_fail'));

    // Stash what the Purchase event will need, using the server's total rather
    // than the cart's — only the server knows the delivery fee. Read back and
    // deleted after Tranzila redirects to /?payment=success, which is what
    // stops a refresh of that page counting a second purchase.
    if (typeof stlSavePendingPurchase === 'function') {
      stlSavePendingPurchase({
        order_id: orderId,
        value:    data.total,
        currency: 'ILS',
        contents: cart.map(i => ({ id: i.id, quantity: i.quantity, item_price: i.price })),
      });
    }

    // Embed Tranzila's payment form in-page (enables Apple Pay / Google Pay).
    // The cart is in-memory only, so it clears naturally when Tranzila redirects
    // the top window back to /?payment=… on completion; leaving via the Back
    // button keeps the cart intact.
    const wrap    = document.getElementById('checkout-iframe-wrap');
    const spinner = document.getElementById('checkout-spinner');
    wrap.innerHTML = '';
    const iframe = document.createElement('iframe');
    iframe.src   = data.iframe_url;
    iframe.title = 'תשלום מאובטח';
    iframe.setAttribute('allow', 'payment');
    iframe.setAttribute('allowpaymentrequest', 'true'); // legacy Safari fallback
    iframe.style.cssText = 'width:100%;min-height:640px;border:0;display:block;background:var(--sand-100);';
    wrap.appendChild(iframe);
    if (spinner) spinner.style.display = 'none';
    wrap.style.display = 'block';
    if (backBtn) backBtn.style.display = '';
  } catch (err) {
    showCheckoutStep(2);
    const errEl2 = document.getElementById('checkout-pay-error');
    if (errEl2) {
      errEl2.textContent = err.message || t('pay_conn_fail');
      errEl2.style.display = 'block';
    }
  }
});

/* ── Step 3 back ──────────────────────────────────────────── */
document.getElementById('checkout-payment-back-btn').addEventListener('click', () => {
  showCheckoutStep(2);
});

/* ── Close / overlay ──────────────────────────────────────── */
document.getElementById('checkout-close').addEventListener('click', closeCheckout);
document.getElementById('checkout-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('checkout-modal')) closeCheckout();
});
document.getElementById('checkout-done-btn').addEventListener('click', closeCheckout);

/* ── Delivery method toggle (Ship / Pickup) ───────────────── */
document.querySelectorAll('.cdt-btn').forEach(b =>
  b.addEventListener('click', () => selectDelivery(b.dataset.method))
);
