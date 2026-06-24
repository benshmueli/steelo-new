/* ============================================================
   Main — grid render, hero cycle, navbar scroll
   ============================================================ */

/* ---- Render product grid ---- */
function renderGrid() {
  const grid = document.getElementById('products-grid');
  grid.innerHTML = '';

  PRODUCTS.forEach(p => {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'background:var(--sand);display:flex;flex-direction:column;cursor:pointer;';
    wrap.setAttribute('tabindex', '0');
    wrap.setAttribute('role', 'button');
    wrap.setAttribute('aria-label', 'View ' + p.name);
    wrap.addEventListener('click', () => openModal(p.id));
    wrap.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openModal(p.id); });

    /* image box */
    const imgBox = document.createElement('div');
    imgBox.className = 'product-card';
    imgBox.style.cssText = 'position:relative;overflow:hidden;aspect-ratio:3/4;';

    const img1 = document.createElement('img');
    img1.src = p.images[0];
    img1.alt = p.name;
    img1.className = 'img-primary';
    img1.loading = 'lazy';
    img1.style.cssText = 'width:100%;height:100%;object-fit:cover;object-position:center center;display:block;';

    const img2 = document.createElement('img');
    img2.src = p.images.length > 1 ? p.images[1] : p.images[0];
    img2.alt = p.name + ' alternate view';
    img2.className = 'img-secondary';
    img2.loading = 'lazy';

    const overlay = document.createElement('div');
    overlay.className = 'card-overlay';
    const viewBtn = document.createElement('button');
    viewBtn.textContent = 'View Details';
    viewBtn.style.cssText = 'width:100%;padding:0.75rem;border:1px solid rgba(245,240,235,0.7);background:transparent;color:#F5F0EB;font-family:Montserrat;font-size:0.65rem;letter-spacing:0.2em;text-transform:uppercase;cursor:pointer;transition:background 0.2s,color 0.2s;';
    viewBtn.addEventListener('mouseover', () => { viewBtn.style.background = '#F5F0EB'; viewBtn.style.color = 'var(--ink)'; });
    viewBtn.addEventListener('mouseout',  () => { viewBtn.style.background = 'transparent'; viewBtn.style.color = '#F5F0EB'; });
    overlay.appendChild(viewBtn);

    imgBox.appendChild(img1);
    imgBox.appendChild(img2);
    imgBox.appendChild(overlay);

    /* info bar */
    const info = document.createElement('div');
    info.style.cssText = 'padding:1.25rem 1.5rem;background:var(--sand-100);border-top:1px solid var(--sand-300);display:flex;align-items:baseline;justify-content:space-between;';
    info.innerHTML = `
      <div>
        <p style="font-family:Montserrat;font-size:0.6rem;letter-spacing:0.25em;text-transform:uppercase;color:var(--ink-400);margin:0 0 0.25rem;">${p.category}</p>
        <h3 style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.5rem;color:var(--ink);margin:0;">${p.name}</h3>
      </div>
      <span style="font-family:Cormorant,Georgia,serif;font-weight:300;font-size:1.35rem;color:var(--ink);white-space:nowrap;">${fmt(p.price)}</span>`;

    wrap.appendChild(imgBox);
    wrap.appendChild(info);
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
