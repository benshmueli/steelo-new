/* ============================================================
   Nav — mobile menu toggle
   Loaded on every page (homepage, product pages, content pages).
   Below 768px .nav-desktop is hidden, so these are the only nav
   links available on mobile.
   ============================================================ */
(function () {
  const btn   = document.getElementById('nav-toggle');
  const panel = document.getElementById('nav-mobile');
  if (!btn || !panel) return;

  function setOpen(open) {
    panel.classList.toggle('open', open);
    btn.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  btn.addEventListener('click', e => {
    e.stopPropagation();
    setOpen(!panel.classList.contains('open'));
  });

  // Following a link closes the panel — the hash links on the homepage
  // don't reload the page, so nothing else would close it.
  panel.addEventListener('click', e => {
    if (e.target.closest('a')) setOpen(false);
  });

  document.addEventListener('click', e => {
    if (panel.classList.contains('open') && !panel.contains(e.target)) setOpen(false);
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && panel.classList.contains('open')) {
      setOpen(false);
      btn.focus();
    }
  });
})();
