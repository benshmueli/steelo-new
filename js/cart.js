/* ============================================================
   Cart & Inquiry
   ============================================================ */
let cart = [];

function fmt(n)      { return '<span style="font-family:Heebo,sans-serif;font-weight:300;font-size:0.65em;color:inherit;vertical-align:0.1em;">₪</span>' + n.toLocaleString('he-IL'); }
function fmtPlain(n) { return '₪' + n.toLocaleString('he-IL'); }

/* ---- Cart state ---- */
function addToCart(product) {
  const existing = cart.find(i => i.id === product.id);
  if (existing) { existing.quantity++; }
  else { cart.push({ ...product, quantity: 1 }); }
  syncCart();
}

function changeQty(id, delta) {
  const item = cart.find(x => x.id === id);
  if (!item) return;
  item.quantity += delta;
  if (item.quantity <= 0) cart = cart.filter(x => x.id !== id);
  syncCart();
}

function removeItem(id) {
  cart = cart.filter(x => x.id !== id);
  syncCart();
}

function syncCart() {
  const count = cart.reduce((s, i) => s + i.quantity, 0);
  const total = cart.reduce((s, i) => s + i.price * i.quantity, 0);

  const countEl = document.getElementById('cart-count');
  countEl.textContent = count;
  countEl.style.display = count > 0 ? 'inline' : 'none';

  document.getElementById('cart-total').innerHTML = fmt(total);
  renderCartItems();
}

function renderCartItems() {
  const el = document.getElementById('cart-items');
  if (cart.length === 0) {
    el.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;padding:4rem 0;text-align:center;gap:1rem;">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" style="color:var(--ink-200);" aria-hidden="true">
          <path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/>
          <line x1="3" y1="6" x2="21" y2="6"/>
          <path d="M16 10a4 4 0 01-8 0"/>
        </svg>
        <p style="font-family:Montserrat;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-300);">Your cart is empty</p>
      </div>`;
    return;
  }

  el.innerHTML = '';
  cart.forEach(item => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:1rem;padding-bottom:1.5rem;margin-bottom:1.5rem;border-bottom:1px solid var(--sand-300);';
    row.innerHTML = `
      <img src="${item.images[0]}" alt="${item.name}" loading="lazy"
           style="width:72px;height:88px;object-fit:cover;object-position:center;flex-shrink:0;">
      <div style="flex:1;">
        <p style="font-family:Montserrat;font-size:0.6rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);margin:0 0 0.2rem;">${item.category}</p>
        <h4 style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.4rem;color:var(--ink);margin:0 0 0.4rem;line-height:1.1;">${item.name}</h4>
        <p style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.15rem;color:var(--ink);margin:0 0 0.75rem;">${fmt(item.price)}</p>
        <div style="display:flex;align-items:center;gap:0.75rem;">
          <button class="qty-btn" onclick="changeQty('${item.id}',-1)" aria-label="Decrease">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
          <span style="font-family:Montserrat;font-size:0.85rem;width:1rem;text-align:center;">${item.quantity}</span>
          <button class="qty-btn" onclick="changeQty('${item.id}',1)" aria-label="Increase">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
          <button onclick="removeItem('${item.id}')"
            style="margin-left:auto;background:none;border:none;cursor:pointer;font-family:Montserrat;font-size:0.65rem;color:var(--ink-300);transition:color 0.2s;"
            onmouseover="this.style.color='var(--ink)'" onmouseout="this.style.color='var(--ink-300)'">Remove</button>
        </div>
      </div>`;
    el.appendChild(row);
  });
}

/* ---- Cart open/close ---- */
function openCart() {
  document.getElementById('cart-root').classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeCart() {
  document.getElementById('cart-root').classList.remove('active');
  document.body.style.overflow = '';
}

document.getElementById('cart-btn').addEventListener('click', openCart);
document.getElementById('cart-close').addEventListener('click', closeCart);
document.getElementById('cart-overlay').addEventListener('click', closeCart);

document.getElementById('checkout-btn').addEventListener('click', () => {
  if (cart.length === 0) return;
  closeCart();
  openCheckout();
});

/* ---- Inquiry modal ---- */
function openInquiry(title, prefill) {
  document.getElementById('inquiry-product-name').textContent = title;
  document.getElementById('inq-message').value = prefill || '';
  document.getElementById('inquiry-modal').style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

document.getElementById('inquiry-close').addEventListener('click', () => {
  document.getElementById('inquiry-modal').style.display = 'none';
  document.body.style.overflow = '';
});
document.getElementById('inquiry-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('inquiry-modal')) {
    document.getElementById('inquiry-modal').style.display = 'none';
    document.body.style.overflow = '';
  }
});

document.getElementById('inquiry-form').addEventListener('submit', e => {
  e.preventDefault();
  const name = document.getElementById('inq-name').value.split(' ')[0];
  document.getElementById('inquiry-form').innerHTML = `
    <div style="text-align:center;padding:2rem 0;">
      <div style="width:3rem;height:3rem;border:1px solid var(--ink);border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 1.5rem;">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </div>
      <p style="font-family:Montserrat;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink);margin-bottom:0.75rem;">Thank you, ${name}</p>
      <p style="font-family:Montserrat;font-weight:300;font-size:0.875rem;line-height:1.7;color:var(--ink-400);">We'll be in touch within 24 hours.</p>
    </div>`;
  setTimeout(() => {
    document.getElementById('inquiry-modal').style.display = 'none';
    document.body.style.overflow = '';
  }, 3000);
});

/* Init */
syncCart();
