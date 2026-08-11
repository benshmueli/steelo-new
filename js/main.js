/* ============================================================
   Main — grid render, hero cycle, navbar scroll
   ============================================================ */

/* Internal test items keep a working URL (for ₪1 payment checks) but stay out
   of the grid and the item count. Mirrors is_public() in build.py. */
function publicProducts() {
  // Grouped by category via CATEGORY_ORDER in data.js — the same list build.py
  // sorts the static grid by, so the two renderers can't disagree. Matching is
  // case-insensitive ('Stool' vs 'STOOL'), unlisted categories sort last, and
  // Array.sort is stable so order within a category stays as authored.
  const rank = new Map(CATEGORY_ORDER.map((c, i) => [c.toLowerCase(), i]));
  const of = p => rank.has((p.category || '').toLowerCase())
    ? rank.get((p.category || '').toLowerCase())
    : rank.size;
  return PRODUCTS.filter(p => p.id !== 'test').sort((a, b) => of(a) - of(b));
}

/* ---- Render product grid ---- */
function renderGrid() {
  const grid = document.getElementById('products-grid');
  if (!grid) return;
  // The grid is pre-rendered as static HTML (for SEO/crawlability). If it's
  // already populated with product links, leave it as-is (CSS handles hover).
  if (grid.querySelector('a[href^="/products/"]')) return;
  grid.innerHTML = '';

  publicProducts().forEach(p => {
    const wrap = document.createElement('a');
    wrap.href = '/products/' + p.id + '/';
    wrap.style.cssText = 'background:var(--sand);display:flex;flex-direction:column;cursor:pointer;text-decoration:none;color:inherit;';
    wrap.setAttribute('aria-label', p.name);

    /* image box */
    const imgBox = document.createElement('div');
    imgBox.className = 'product-card';
    imgBox.style.cssText = 'position:relative;overflow:hidden;aspect-ratio:3/4;';

    const img1 = document.createElement('img');
    img1.src = p.images.length > 1 ? p.images[1] : p.images[0];
    img1.alt = p.name + ' close view';
    img1.className = 'img-primary';
    img1.loading = 'lazy';
    img1.style.cssText = 'width:100%;height:100%;object-fit:cover;object-position:center center;display:block;';

    const img2 = document.createElement('img');
    img2.src = p.images[0];
    img2.alt = p.name + ' alternate view';
    img2.className = 'img-secondary';
    img2.loading = 'lazy';

    const overlay = document.createElement('div');
    overlay.className = 'card-overlay';
    const viewBtn = document.createElement('span');
    viewBtn.textContent = t('view_details');
    viewBtn.style.cssText = 'display:block;width:100%;box-sizing:border-box;padding:0.75rem;border:1px solid rgba(245,240,235,0.7);background:transparent;color:#F5F0EB;font-family:Montserrat;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;text-align:center;cursor:pointer;transition:background 0.2s,color 0.2s;';
    viewBtn.addEventListener('mouseover', () => { viewBtn.style.background = '#F5F0EB'; viewBtn.style.color = 'var(--ink)'; });
    viewBtn.addEventListener('mouseout',  () => { viewBtn.style.background = 'transparent'; viewBtn.style.color = '#F5F0EB'; });
    overlay.appendChild(viewBtn);

    /* price, over the foot of the image */
    const price = document.createElement('div');
    price.className = 'card-price';
    price.innerHTML = fmtPrice(p.price, p.discount);

    imgBox.appendChild(img1);
    imgBox.appendChild(img2);
    imgBox.appendChild(price);
    imgBox.appendChild(overlay);

    /* discount badge */
    if (p.discount > 0) {
      const badge = document.createElement('div');
      badge.textContent = `${p.discount}% OFF`;
      badge.style.cssText = 'position:absolute;top:1rem;left:1rem;background:#B85C38;color:#fff;font-family:Montserrat,sans-serif;font-size:0.7rem;font-weight:600;letter-spacing:0.18em;padding:0.3rem 0.65rem;z-index:3;';
      imgBox.appendChild(badge);
    }

    /* header — category + name, above the image (mirrors grid_cards in build.py) */
    const head = document.createElement('div');
    head.className = 'card-head';
    head.innerHTML = `
      <p class="card-cat">${p.category}</p>
      <h3 class="card-name">${p.name}</h3>`;

    wrap.appendChild(head);
    wrap.appendChild(imgBox);
    grid.appendChild(wrap);
  });
}

/* ---- Hero cycling ---- */
const HERO_IMAGES = [
  { src: 'images/products/LoopSideTable/1.png',  alt: 'Loop Side Table' },
  { src: 'images/products/ElephantDining/1.png', alt: 'Elephant Dining Table' },
  { src: 'images/products/ThreeLevel/1.png',     alt: 'Three Level Coffee Table' },
  { src: 'images/products/RippleStool/1.png',    alt: 'Ripple Stool' },
  { src: 'images/products/PLIE/1.png',           alt: 'Plié Coffee Table' },
];
let heroIdx = 0;

setInterval(() => {
  heroIdx = (heroIdx + 1) % HERO_IMAGES.length;
  const img = document.getElementById('hero-img');
  img.style.opacity = '0';
  setTimeout(() => {
    img.src = HERO_IMAGES[heroIdx].src;
    img.alt = HERO_IMAGES[heroIdx].alt;
    img.style.opacity = '1';
  }, 900);
}, 5000);

/* ---- Navbar scroll ---- */
window.addEventListener('scroll', () => {
  document.getElementById('navbar').classList.toggle('scrolled', window.scrollY > 80);
}, { passive: true });

/* ---- Init ---- */
renderGrid();
