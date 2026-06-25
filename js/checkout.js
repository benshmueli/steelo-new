/* ============================================================
   Checkout Flow  (3 steps: Details → Payment → Confirmation)
   ============================================================ */

function generateOrderId() {
  const now  = new Date();
  const date = now.toISOString().slice(0, 10).replace(/-/g, '');
  const time = String(now.getHours()).padStart(2, '0') + String(now.getMinutes()).padStart(2, '0');
  const rand = String(Math.floor(Math.random() * 900) + 100);
  return `STL-${date}-${time}${rand}`;
}

/* ── Open / Close ─────────────────────────────────────────── */
function openCheckout() {
  if (!cart || cart.length === 0) return;
  showCheckoutStep(1);
  document.getElementById('checkout-modal').style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

function closeCheckout() {
  document.getElementById('checkout-modal').style.display = 'none';
  document.body.style.overflow = '';
  document.getElementById('checkout-step1').style.display = 'block';
  document.getElementById('checkout-step2').style.display = 'none';
  document.getElementById('checkout-step3').style.display = 'none';
  document.getElementById('checkout-confirmation').style.display = 'none';
  document.getElementById('checkout-form').reset();
  document.getElementById('checkout-error').style.display = 'none';
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
        <span style="font-family:Montserrat;font-size:0.6rem;letter-spacing:0.15em;text-transform:uppercase;color:var(--ink-400);margin-left:0.5rem;">×${item.quantity}</span>
      </div>
      <span style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.1rem;color:var(--ink);white-space:nowrap;">${fmt(item.price * item.quantity)}</span>`;
    el.appendChild(row);
  });
  const total = cart.reduce((s, i) => s + i.price * i.quantity, 0);
  document.getElementById('checkout-order-total').innerHTML = fmt(total);
}

/* ── Card number formatting ───────────────────────────────── */
document.getElementById('co-card-number').addEventListener('input', function () {
  let v = this.value.replace(/\D/g, '').slice(0, 16);
  this.value = v.replace(/(.{4})/g, '$1 ').trim();
});
document.getElementById('co-card-expiry').addEventListener('input', function () {
  let v = this.value.replace(/\D/g, '').slice(0, 4);
  if (v.length >= 3) v = v.slice(0, 2) + '/' + v.slice(2);
  this.value = v;
});
document.getElementById('co-card-cvv').addEventListener('input', function () {
  this.value = this.value.replace(/\D/g, '').slice(0, 4);
});

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

/* ── Step 2 → Step 3 (summary → payment) ─────────────────── */
document.getElementById('checkout-to-payment-btn').addEventListener('click', () => {
  showCheckoutStep(3);
});

/* ── Step 2 back → Step 1 ─────────────────────────────────── */
document.getElementById('checkout-back-btn').addEventListener('click', () => {
  showCheckoutStep(1);
});

/* ── Step 3 back → Step 2 ─────────────────────────────────── */
document.getElementById('checkout-payment-back-btn').addEventListener('click', () => {
  showCheckoutStep(2);
});

/* ── Submit (pay) ─────────────────────────────────────────── */
document.getElementById('checkout-form').addEventListener('submit', async e => {
  e.preventDefault();
  document.getElementById('checkout-error').style.display = 'none';

  // Validate payment fields
  const payFields = document.querySelectorAll('#checkout-step3 [required]');
  let valid = true;
  payFields.forEach(f => {
    f.style.borderColor = '';
    if (!f.value.trim()) { f.style.borderColor = '#c0392b'; valid = false; }
  });
  if (!valid) return;

  const btn = document.getElementById('checkout-place-btn');
  btn.textContent = 'Processing…';
  btn.disabled = true;

  const f       = document.getElementById('checkout-form');
  const orderId = generateOrderId();
  const now     = new Date();
  const dateStr = now.toLocaleString('he-IL', { timeZone: 'Asia/Jerusalem', hour12: false });
  const total   = cart.reduce((s, i) => s + i.price * i.quantity, 0);

  const orderPayload = {
    order_id:    orderId,
    date:        dateStr,
    name:        f['co-name'].value.trim(),
    email:       f['co-email'].value.trim(),
    phone:       f['co-phone'].value.trim(),
    address:     f['co-address'].value.trim(),
    apartment:   f['co-apartment'].value.trim(),
    city:        f['co-city'].value.trim(),
    postal_code: f['co-postal'].value.trim(),
    country:     f['co-country'].value.trim(),
    notes:       f['co-notes'].value.trim(),
    website:     f['co-website'].value.trim(),   // honeypot — should always be empty
    items:       cart.map(i => ({ name: i.name, category: i.category, qty: i.quantity, price: i.price })),
    total,
  };

  // Payment payload — card details go to server only, never stored
  const paymentPayload = {
    order_id:       orderId,
    amount:         total,
    cardholder:     f['co-card-name'].value.trim(),
    card_number:    f['co-card-number'].value.replace(/\s/g, ''),
    expiry:         f['co-card-expiry'].value.trim(),
    cvv:            f['co-card-cvv'].value.trim(),
    email:          f['co-email'].value.trim(),
    phone:          f['co-phone'].value.trim(),
  };

  try {
    // 1. Charge via Tranzila
    const payRes  = await fetch('/payment/charge', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(paymentPayload),
    });
    const payData = await payRes.json();
    if (!payData.ok) throw new Error(payData.error || 'Payment failed');

    // 2. Save order to Google Sheets
    await fetch('/order', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ ...orderPayload, payment_ref: payData.transaction_id }),
    });

    // 3. Show confirmation
    document.getElementById('checkout-confirm-id').textContent = orderId;
    document.getElementById('checkout-step3').style.display = 'none';
    document.getElementById('checkout-confirmation').style.display = 'block';
    document.getElementById('checkout-modal-body').scrollTop = 0;
    cart = [];
    syncCart();

  } catch (err) {
    btn.textContent = 'Pay Now';
    btn.disabled = false;
    document.getElementById('checkout-error').textContent = err.message || 'Payment failed. Please try again.';
    document.getElementById('checkout-error').style.display = 'block';
  }
});

/* ── Close / overlay ──────────────────────────────────────── */
document.getElementById('checkout-close').addEventListener('click', closeCheckout);
document.getElementById('checkout-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('checkout-modal')) closeCheckout();
});
document.getElementById('checkout-done-btn').addEventListener('click', closeCheckout);
