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

/* ── Open / Close ─────────────────────────────────────────── */
/* Event ID for the InitiateCheckout pair. Minted in the browser when checkout
   opens, then sent to /payment/init so the server-side copy of the same event
   carries the same ID and Meta counts one, not two. */
let metaCheckoutEventId = '';

function openCheckout() {
  if (!cart || cart.length === 0) return;
  showCheckoutStep(1);
  document.getElementById('checkout-modal').style.display = 'flex';
  document.body.style.overflow = 'hidden';
  if (typeof stlTrackInitiateCheckout === 'function') {
    metaCheckoutEventId = stlEventId('ic');
    stlTrackInitiateCheckout(cart, deliveryFee(), metaCheckoutEventId);
  }
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
  cart.forEach(item => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:space-between;align-items:baseline;padding:0.6rem 0;border-bottom:1px solid var(--sand-300);gap:1rem;';
    row.innerHTML = `
      <div>
        <span style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.15rem;color:var(--ink);">${item.name}</span>
        <span style="font-family:Montserrat;font-size:0.7rem;letter-spacing:0.15em;text-transform:uppercase;color:var(--ink-400);margin-left:0.5rem;">×${item.quantity}</span>
      </div>
      <span style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.1rem;color:var(--ink);white-space:nowrap;">${fmt(item.price * item.quantity)}</span>`;
    el.appendChild(row);
  });
  const itemsTotal = cart.reduce((s, i) => s + i.price * i.quantity, 0);
  const isPickup = getDeliveryMethod() === 'pickup';
  const fee = deliveryFee();
  const drow = document.createElement('div');
  drow.style.cssText = 'display:flex;justify-content:space-between;align-items:baseline;padding:0.6rem 0;gap:1rem;';
  drow.innerHTML =
    `<span style="font-family:Montserrat,Heebo;font-size:0.75rem;letter-spacing:0.05em;color:var(--ink-500);">${isPickup ? 'איסוף עצמי' : 'משלוח'}</span>` +
    `<span style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.1rem;color:var(--ink);white-space:nowrap;">${isPickup ? 'חינם' : fmt(fee)}</span>`;
  el.appendChild(drow);
  document.getElementById('checkout-order-total').innerHTML = fmt(itemsTotal + fee);
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
});

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
  const fee       = deliveryFee();
  const itemsTotal = cart.reduce((s, i) => s + i.price * i.quantity, 0);
  const total     = itemsTotal + fee;
  const val = id => (f[id] ? f[id].value.trim() : '');
  const checked = id => { const el = document.getElementById(id); return !!(el && el.checked); };

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
  }

  try {
    const res  = await fetch('/payment/init', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    const data = await res.json();
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
