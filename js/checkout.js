/* ============================================================
   Checkout Flow
   ============================================================ */

function generateOrderId() {
  const now = new Date();
  const date = now.toISOString().slice(0, 10).replace(/-/g, '');
  const time = String(now.getHours()).padStart(2, '0') + String(now.getMinutes()).padStart(2, '0');
  const rand = String(Math.floor(Math.random() * 900) + 100);
  return `STL-${date}-${time}${rand}`;
}

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
  document.getElementById('checkout-confirmation').style.display = 'none';
  document.getElementById('checkout-form').reset();
}

function showCheckoutStep(n) {
  document.getElementById('checkout-step1').style.display = n === 1 ? 'block' : 'none';
  document.getElementById('checkout-step2').style.display = n === 2 ? 'block' : 'none';
  document.getElementById('checkout-confirmation').style.display = 'none';
  // Update step indicator
  document.querySelectorAll('.checkout-step-dot').forEach((dot, i) => {
    dot.classList.toggle('active', i + 1 <= n);
  });
}

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

/* ---- Step 1 → Step 2 ---- */
document.getElementById('checkout-next-btn').addEventListener('click', () => {
  const form = document.getElementById('checkout-form');
  // Validate required fields in step 1
  const required = form.querySelectorAll('[required]');
  let valid = true;
  required.forEach(field => {
    field.style.borderColor = '';
    if (!field.value.trim()) {
      field.style.borderColor = '#c0392b';
      valid = false;
    }
  });
  if (!valid) return;
  buildOrderSummary();
  showCheckoutStep(2);
  document.getElementById('checkout-modal-body').scrollTop = 0;
});

document.getElementById('checkout-back-btn').addEventListener('click', () => {
  showCheckoutStep(1);
  document.getElementById('checkout-modal-body').scrollTop = 0;
});

/* ---- Submit order ---- */
document.getElementById('checkout-form').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('checkout-place-btn');
  btn.textContent = 'Placing Order…';
  btn.disabled = true;

  const f = document.getElementById('checkout-form');
  const orderId = generateOrderId();
  const now = new Date();
  const dateStr = now.toLocaleString('he-IL', { timeZone: 'Asia/Jerusalem', hour12: false });

  const payload = {
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
    items: cart.map(i => ({ name: i.name, category: i.category, qty: i.quantity, price: i.price })),
    total: cart.reduce((s, i) => s + i.price * i.quantity, 0),
  };

  try {
    const res = await fetch('/order', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Server error');

    // Success
    document.getElementById('checkout-confirm-id').textContent = orderId;
    document.getElementById('checkout-step2').style.display = 'none';
    document.getElementById('checkout-confirmation').style.display = 'block';
    document.getElementById('checkout-modal-body').scrollTop = 0;

    // Clear cart
    cart = [];
    syncCart();

  } catch (err) {
    btn.textContent = 'Place Order';
    btn.disabled = false;
    document.getElementById('checkout-error').textContent = 'Something went wrong. Please try again or contact us directly.';
    document.getElementById('checkout-error').style.display = 'block';
  }
});

/* ---- Close / overlay ---- */
document.getElementById('checkout-close').addEventListener('click', closeCheckout);
document.getElementById('checkout-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('checkout-modal')) closeCheckout();
});
document.getElementById('checkout-done-btn').addEventListener('click', closeCheckout);
