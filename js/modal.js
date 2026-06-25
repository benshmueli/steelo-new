/* ============================================================
   Product Modal
   ============================================================ */
let activeProd = null;
let activeImgIdx = 0;

function openModal(productId) {
  const p = PRODUCTS.find(x => x.id === productId);
  if (!p) return;
  activeProd = p;
  activeImgIdx = 0;

  document.getElementById('modal-category').textContent    = p.category;
  document.getElementById('modal-name').textContent        = p.name;
  document.getElementById('modal-description').textContent = p.description;
  document.getElementById('modal-dimensions').textContent  = p.dimensions || '—';
  document.getElementById('modal-price').innerHTML = (p.discount > 0)
    ? `<span style="text-decoration:line-through;opacity:0.4;font-size:0.7em;margin-right:0.5rem;">${fmt(p.price)}</span><span style="color:#B85C38;">${fmt(salePrice(p.price, p.discount))}</span>`
    : fmt(p.price);

  buildModalImages(p);
  renderThumbs(p.images, 0);
  updateModalNav();

  document.getElementById('product-modal').classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('product-modal').classList.remove('active');
  document.body.style.overflow = '';
  activeProd = null;
}

function buildModalImages(p) {
  const container = document.getElementById('modal-images-container');
  container.innerHTML = '';
  container.style.transform = 'translateX(0)';

  p.images.forEach((src, i) => {
    const slide = document.createElement('div');
    slide.style.cssText = 'flex-shrink:0; width:100%; height:100%; padding:2.5rem; box-sizing:border-box;';

    const img = document.createElement('img');
    img.src = src;
    img.alt = p.name + ' — view ' + (i + 1);
    img.style.cssText = 'width:100%; height:100%; object-fit:contain; display:block;';

    slide.appendChild(img);
    container.appendChild(slide);
  });
}

function renderThumbs(images, active) {
  const strip = document.getElementById('modal-thumbs');
  if (!strip) return;
  strip.innerHTML = '';

  if (images.length <= 1) { strip.style.display = 'none'; return; }
  strip.style.display = 'flex';

  images.forEach((src, i) => {
    const btn = document.createElement('button');
    btn.className = 'modal-thumb' + (i === active ? ' active' : '');
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-label', 'Image ' + (i + 1));
    btn.setAttribute('aria-selected', i === active ? 'true' : 'false');

    const img = document.createElement('img');
    img.src = src;
    img.alt = 'View ' + (i + 1);
    img.style.cssText = 'width:100%; height:100%; object-fit:contain; display:block; pointer-events:none;';

    btn.appendChild(img);
    btn.addEventListener('click', () => goToImage(i));
    strip.appendChild(btn);
  });
}

function goToImage(idx) {
  if (!activeProd) return;
  activeImgIdx = Math.max(0, Math.min(idx, activeProd.images.length - 1));
  document.getElementById('modal-images-container').style.transform = `translateX(-${activeImgIdx * 100}%)`;
  renderThumbs(activeProd.images, activeImgIdx);
  updateModalNav();
}

function updateModalNav() {
  if (!activeProd) return;
  const single = activeProd.images.length <= 1;
  const prev = document.getElementById('modal-prev');
  const next = document.getElementById('modal-next');
  prev.style.display = single ? 'none' : 'flex';
  next.style.display = single ? 'none' : 'flex';
  if (!single) {
    prev.style.opacity = activeImgIdx === 0 ? '0.3' : '1';
    next.style.opacity = activeImgIdx === activeProd.images.length - 1 ? '0.3' : '1';
  }
}

/* Wire up modal controls */
document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('product-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('product-modal')) closeModal();
});
document.getElementById('modal-prev').addEventListener('click', () => {
  if (activeImgIdx > 0) goToImage(activeImgIdx - 1);
});
document.getElementById('modal-next').addEventListener('click', () => {
  if (activeProd && activeImgIdx < activeProd.images.length - 1) goToImage(activeImgIdx + 1);
});
document.getElementById('modal-add-cart').addEventListener('click', () => {
  if (!activeProd) return;
  addToCart(activeProd);
  closeModal();
  setTimeout(openCart, 380);
});

/* Lightbox */
let lbIdx = 0;

function openLightbox(startIdx) {
  if (!activeProd) return;
  lbIdx = startIdx ?? activeImgIdx;
  lbRender();
  document.getElementById('lightbox').style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

function lbRender() {
  if (!activeProd) return;
  const imgs = activeProd.images;
  document.getElementById('lightbox-img').src = imgs[lbIdx];
  document.getElementById('lb-counter').textContent = (lbIdx + 1) + ' / ' + imgs.length;
  document.getElementById('lb-prev').style.opacity = lbIdx === 0 ? '0.3' : '1';
  document.getElementById('lb-next').style.opacity = lbIdx === imgs.length - 1 ? '0.3' : '1';
}

function lbNav(dir) {
  if (!activeProd) return;
  lbIdx = Math.max(0, Math.min(lbIdx + dir, activeProd.images.length - 1));
  lbRender();
}

function closeLightbox() {
  document.getElementById('lightbox').style.display = 'none';
  document.body.style.overflow = 'hidden';
}

document.getElementById('modal-images-container').addEventListener('click', e => {
  const img = e.target.closest('img');
  if (img) openLightbox(activeImgIdx);
});

// Swipe support
let lbTouchX = null;
document.getElementById('lightbox').addEventListener('touchstart', e => { lbTouchX = e.touches[0].clientX; }, { passive: true });
document.getElementById('lightbox').addEventListener('touchend', e => {
  if (lbTouchX === null) return;
  const dx = e.changedTouches[0].clientX - lbTouchX;
  if (Math.abs(dx) > 40) { lbNav(dx < 0 ? 1 : -1); e.stopPropagation(); }
  lbTouchX = null;
});

document.addEventListener('keydown', e => {
  if (!document.getElementById('product-modal').classList.contains('active')) return;
  if (e.key === 'Escape')      closeModal();
  if (e.key === 'ArrowLeft'  && activeImgIdx > 0) goToImage(activeImgIdx - 1);
  if (e.key === 'ArrowRight' && activeProd && activeImgIdx < activeProd.images.length - 1) goToImage(activeImgIdx + 1);
});
