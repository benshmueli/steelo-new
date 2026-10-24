/* ============================================================
   Cart & Inquiry
   ============================================================ */
/* Cart persists in localStorage so it survives page navigation + refresh. */
const CART_KEY = 'steelo_cart';
let cart = [];
try { cart = JSON.parse(localStorage.getItem(CART_KEY)) || []; } catch (e) { cart = []; }
function saveCart()  { try { localStorage.setItem(CART_KEY, JSON.stringify(cart)); } catch (e) {} }
function clearCart() { cart = []; try { localStorage.removeItem(CART_KEY); } catch (e) {} syncCart(); }

function fmt(n)      { return '<span style="font-family:Heebo,sans-serif;font-weight:300;font-size:0.65em;color:inherit;vertical-align:0.1em;">₪</span>' + n.toLocaleString('he-IL'); }
function fmtPlain(n) { return '₪' + n.toLocaleString('he-IL'); }

/* ---- Discount helpers ---- */
function salePrice(price, discount) {
  if (!discount || discount <= 0) return price;
  return Math.round(price * (1 - discount / 100));
}
function fmtPrice(price, discount) {
  // Returns HTML: if product has a discount, shows ~~original~~ + sale price
  if (!discount || discount <= 0) return fmt(price);
  const sale = salePrice(price, discount);
  return `<span style="text-decoration:line-through;opacity:0.45;font-size:0.85em;margin-right:0.4rem;">${fmt(price)}</span><span style="color:#B85C38;">${fmt(sale)}</span>`;
}

/* ---- Pair deal ----
   A percentage off every second item within a group: side tables pair with side
   tables, stools with stools. Settings arrive in data.js as STEELO_PAIR_DEAL;
   without them the deal counts as off, since the drawer must never promise a
   saving the server won't give. pairDiscount() mirrors pair_deal_discount() in
   server.py, rounding each unit the same way, and the server's figure is the
   one charged. */
function pairDeal() {
  const d = window.STEELO_PAIR_DEAL;
  return (d && d.enabled && d.percent > 0 && Array.isArray(d.groups)) ? d : null;
}
function pairGroup(category, deal) {
  const cat = (category || '').toLowerCase();
  return deal.groups.findIndex(g => g.includes(cat));
}
/* The units the deal discounts — every second one within a group, ranked dearest
   first so each pair discounts its cheaper half — as one entry per unit, each
   the cart row it belongs to. Equal prices stay in cart order (sort is stable),
   so the drawer always marks the same unit. */
function pairDiscountedUnits(items) {
  const deal = pairDeal();
  if (!deal) return [];
  const discounted = [];
  deal.groups.forEach((_, g) => {
    const units = [];
    items.forEach(i => {
      if (pairGroup(i.category, deal) === g) for (let n = 0; n < i.quantity; n++) units.push(i);
    });
    units.sort((a, b) => b.price - a.price);
    for (let k = 1; k < units.length; k += 2) discounted.push(units[k]);
  });
  return discounted;
}
// Shekels off one discounted unit, rounded the way the server rounds it.
function pairUnitOff(price) {
  return Math.floor((price * pairDeal().percent + 50) / 100);
}
// Summed per unit rather than per product id, so pairOffer() can price a cart
// holding two rows of the same product.
function pairDiscount(items) {
  return pairDiscountedUnits(items).reduce((s, i) => s + pairUnitOff(i.price), 0);
}

/* The first group holding an item with no partner yet, and what to suggest for
   it: the product just added first — a matching pair is the obvious buy — then
   the rest of its group. Each saving is worked out by pricing the cart with the
   suggestion in it, so it stays right when a dearer second item moves the
   discount onto the first one. */
function pairOffer() {
  const deal = pairDeal();
  if (!deal || typeof PRODUCTS === 'undefined') return null;
  const base = pairDiscount(cart);
  for (let g = 0; g < deal.groups.length; g++) {
    const inGroup = cart.filter(i => pairGroup(i.category, deal) === g);
    if (inGroup.reduce((s, i) => s + i.quantity, 0) % 2 === 0) continue;
    const lead = inGroup[inGroup.length - 1].id;
    const options = PRODUCTS
      .filter(p => p.id !== 'test' && pairGroup(p.category, deal) === g)
      .sort((a, b) => (b.id === lead) - (a.id === lead))
      .slice(0, 4)
      .map(p => {
        const price = salePrice(p.price, p.discount);
        const saving = pairDiscount(cart.concat([{ ...p, price, quantity: 1 }])) - base;
        return { product: p, price, saving, twin: p.id === lead };
      })
      .filter(o => o.saving > 0);
    if (options.length) return { percent: deal.percent, options };
  }
  return null;
}

/* ---- Cart state ---- */
function addToCart(product) {
  const existing = cart.find(i => i.id === product.id);
  if (existing) { existing.quantity++; }
  else {
    const effectivePrice = salePrice(product.price, product.discount);
    cart.push({ ...product, originalPrice: product.price, price: effectivePrice, quantity: 1 });
  }
  syncCart();
  // Every add path funnels through here — the quick-view modal, the product
  // page button and buy-now — so this is the only place AddToCart is reported.
  if (typeof stlTrackAddToCart === 'function') stlTrackAddToCart(product);
  if (typeof stlTrack === 'function') stlTrack('add_to_cart');
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
  const total = cart.reduce((s, i) => s + i.price * i.quantity, 0) - pairDiscount(cart);

  const countEl = document.getElementById('cart-count');
  countEl.textContent = count;
  countEl.style.display = count > 0 ? 'inline' : 'none';

  document.getElementById('cart-total').innerHTML = fmt(total);
  renderCartItems();
  saveCart();
}

function renderCartItems() {
  const el = document.getElementById('cart-items');
  if (cart.length === 0) {
    el.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;padding:4rem 0;text-align:center;gap:1rem;">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" style="color:var(--ink-400);" aria-hidden="true">
          <path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/>
          <line x1="3" y1="6" x2="21" y2="6"/>
          <path d="M16 10a4 4 0 01-8 0"/>
        </svg>
        <p style="font-family:Montserrat,Heebo;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;color: var(--ink-400);">${t('cart_empty')}</p>
      </div>`;
    return;
  }

  el.innerHTML = '';
  // A product's discounted units get a row of their own under its full-price
  // one, so a second table bought at 20% off shows up as an item, not just as a
  // smaller total. The −/+ buttons still move the product's whole quantity, and
  // the split is worked out again from it.
  const discounted = pairDiscountedUnits(cart);
  cart.forEach(item => {
    const offCount  = discounted.filter(u => u === item).length;
    const fullCount = item.quantity - offCount;
    if (offCount > 0 && fullCount === 0) { el.appendChild(pairLineRow(item, offCount)); return; }
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:1rem;padding-bottom:1.5rem;margin-bottom:1.5rem;border-bottom:1px solid var(--sand-300);';
    row.innerHTML = `
      <img src="${item.images[0]}" alt="${item.name}" loading="lazy"
           style="width:72px;height:88px;object-fit:cover;object-position:center;flex-shrink:0;">
      <div style="flex:1;">
        <p style="font-family:Montserrat;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);margin:0 0 0.2rem;">${item.category}</p>
        <h4 style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.4rem;color:var(--ink);margin:0 0 0.4rem;line-height:1.1;">${item.name}</h4>
        <p style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.15rem;color:var(--ink);margin:0 0 0.75rem;">${item.originalPrice && item.originalPrice !== item.price ? `<span style="text-decoration:line-through;opacity:0.4;font-size:0.85em;margin-right:0.35rem;">${fmt(item.originalPrice)}</span><span style="color:#B85C38;">${fmt(item.price)}</span>` : fmt(item.price)}</p>
        <div style="display:flex;align-items:center;gap:0.75rem;">
          <button class="qty-btn" onclick="changeQty('${item.id}',-1)" aria-label="${t('decrease')}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
          <span style="font-family:Montserrat;font-size:0.85rem;width:1rem;text-align:center;">${fullCount}</span>
          <button class="qty-btn" onclick="changeQty('${item.id}',1)" aria-label="${t('increase')}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
          <button onclick="removeItem('${item.id}')"
            style="margin-inline-start:auto;background:none;border:none;cursor:pointer;font-family:Montserrat,Heebo;font-size:0.65rem;color: var(--ink-400);transition:color 0.2s;"
            onmouseover="this.style.color='var(--ink)'" onmouseout="this.style.color='var(--ink-400)'">${t('remove')}</button>
        </div>
      </div>`;
    el.appendChild(row);
    if (offCount > 0) el.appendChild(pairLineRow(item, offCount));
  });

  const saving = discounted.reduce((s, i) => s + pairUnitOff(i.price), 0);
  if (saving > 0) el.appendChild(pairSavingRow(saving));
  const offer = pairOffer();
  if (offer) el.appendChild(pairOfferCard(offer));
}

/* A product's discounted units as an item of their own: the same row as a
   full-price one, priced after the deal. Remove takes off a single unit — the
   one this row stands for. */
function pairLineRow(item, count) {
  const label = t('pair_line').replace('{p}', pairDeal().percent);
  const row = document.createElement('div');
  row.style.cssText = 'display:flex;gap:1rem;padding-bottom:1.5rem;margin-bottom:1.5rem;border-bottom:1px solid var(--sand-300);';
  row.innerHTML = `
    <img src="${item.images[0]}" alt="${item.name}" loading="lazy"
         style="width:72px;height:88px;object-fit:cover;object-position:center;flex-shrink:0;">
    <div style="flex:1;">
      <p style="font-family:Montserrat;font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--ink-400);margin:0 0 0.2rem;">${item.category}</p>
      <h4 style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.4rem;color:var(--ink);margin:0 0 0.3rem;line-height:1.1;">${item.name}</h4>
      <p style="font-family:Montserrat,Heebo;font-size:0.7rem;color:#B85C38;margin:0 0 0.3rem;">${label}</p>
      <p style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.15rem;color:var(--ink);margin:0 0 0.75rem;"><span style="text-decoration:line-through;opacity:0.4;font-size:0.85em;margin-right:0.35rem;">${fmt(item.price)}</span><span style="color:#B85C38;">${fmt(item.price - pairUnitOff(item.price))}</span></p>
      <div style="display:flex;align-items:center;gap:0.75rem;">
        ${count > 1 ? `<span style="font-family:Montserrat;font-size:0.85rem;">×${count}</span>` : ''}
        <button onclick="changeQty('${item.id}',-1)" aria-label="${t('remove')}: ${item.name} · ${label}"
          style="margin-inline-start:auto;background:none;border:none;cursor:pointer;font-family:Montserrat,Heebo;font-size:0.65rem;color: var(--ink-400);transition:color 0.2s;"
          onmouseover="this.style.color='var(--ink)'" onmouseout="this.style.color='var(--ink-400)'">${t('remove')}</button>
      </div>
    </div>`;
  return row;
}

// The deal is already in the rows' prices, so this is what it came to — not a
// further deduction, which is how a "−₪440" under them read.
function pairSavingRow(saving) {
  const row = document.createElement('div');
  row.style.cssText = 'padding-bottom:1.5rem;margin-bottom:1.5rem;border-bottom:1px solid var(--sand-300);color:#B85C38;font-family:Montserrat,Heebo;font-size:0.75rem;letter-spacing:0.05em;';
  row.innerHTML = t('pair_saved').replace('{s}', fmt(saving));
  return row;
}

function pairOfferCard(offer) {
  const card = document.createElement('div');
  card.style.cssText = 'border:1px solid var(--sand-300);padding:1rem 1rem 0.25rem;margin-bottom:1.5rem;';
  card.innerHTML = `
    <p style="font-family:Montserrat,Heebo;font-size:0.8rem;font-weight:500;color:var(--ink);margin:0 0 0.3rem;">${t('pair_title').replace('{p}', offer.percent)}</p>
    <p style="font-family:Montserrat,Heebo;font-weight:300;font-size:0.72rem;line-height:1.6;color:var(--ink-400);margin:0 0 0.5rem;">${t('pair_sub').replace('{p}', offer.percent)}</p>`;
  offer.options.forEach(o => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:0.75rem;padding:0.65rem 0;border-top:1px solid var(--sand-300);';
    row.innerHTML = `
      <img src="${o.product.images[0]}" alt="${o.product.name}" loading="lazy"
           style="width:44px;height:54px;object-fit:cover;object-position:center;flex-shrink:0;">
      <div style="flex:1;min-width:0;">
        <p style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.15rem;color:var(--ink);margin:0;line-height:1.1;">${o.product.name}${o.twin ? `<span style="font-family:Montserrat,Heebo;font-size:0.62rem;color:var(--ink-400);margin-inline-start:0.4rem;">${t('pair_twin')}</span>` : ''}</p>
        <p style="font-family:Montserrat,Heebo;font-size:0.7rem;color:var(--ink-400);margin:0.25rem 0 0;">${fmt(o.price)} · <span style="color:#B85C38;">${t('pair_saving')} ${fmt(o.saving)}</span></p>
      </div>
      <button type="button" aria-label="${t('pair_add')}: ${o.product.name}"
        style="flex-shrink:0;background:transparent;border:1px solid var(--ink);color:var(--ink);cursor:pointer;padding:0.45rem 0.9rem;font-family:Montserrat,Heebo;font-size:0.68rem;transition:background 0.2s;"
        onmouseover="this.style.background='var(--sand-200)'" onmouseout="this.style.background='transparent'">${t('pair_add')}</button>`;
    // The same addToCart every other add path uses, so it is reported to Meta
    // and the funnel exactly like an add from the product page.
    row.querySelector('button').addEventListener('click', () => addToCart(o.product));
    card.appendChild(row);
  });
  return card;
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
