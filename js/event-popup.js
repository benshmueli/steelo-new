/* ──────────────────────────────────────────────────────────────────────────
   STEELO — Pop-up store & sale announcement
   Shows on every visit (no dismissal memory). Clear X to close (also Esc /
   backdrop click) plus a button through to the collection.

   The invitation used to be a single 1535x1024 JPEG. On a phone that renders
   around 350px wide, so its lettering landed at roughly 23% of design size and
   no CSS could enlarge it — the text was pixels. The copy is now real HTML and
   only the product panel stayed an image (images/launch-invite-panel.jpg, the
   right half of the original). The dates can be edited here without a graphics
   tool, and a screen reader can read them.

   Was the launch-night invitation; now runs the KIXBOX pop-up and the sale.

   The two dates below expire themselves, because they expire on different days:
   the sale ends 22.8 but the pop-up runs to 14.9. Left to a human to remember,
   that gap is a fortnight in which the popup keeps promising 10% off after the
   discount has been switched off in /admin.html — and the cart charges full
   price. Extending either one means changing the date here AND the discount in
   the admin; they have to move together.
   ────────────────────────────────────────────────────────────────────────── */
(function () {
  var SHOP_URL  = '#collection';
  var PANEL_IMG = 'images/launch-invite-panel.jpg';

  var SALE_ENDS  = '2026-08-22';   // after this day the sale line disappears
  var POPUP_ENDS = '2026-09-14';   // after this day nothing shows at all

  /* Inclusive to the end of the visitor's own day: "until 22.8" has to still be
     true at 22:00 on the 22nd. No timezone suffix, so the string parses as
     local time rather than UTC. */
  function past(date) {
    return Date.now() > new Date(date + 'T23:59:59').getTime();
  }

  if (past(POPUP_ENDS)) return;    // nothing injected — no styles, no markup

  var showSale = !past(SALE_ENDS);

  // Event details — edit here.
  var EVENT = {
    intro:     'Steelo Pop-Up at KIXBOX',
    when:      '13.8–14.9',
    venue:     'Come visit us in store!',
    where:     '📍 Shenkin 57, Tel Aviv',
    saleIntro: 'Special discount for launch week',
    saleTitle: '10% off everything!',
    saleNote:  'Valid until 22.8 — don’t miss out'
  };

  // ── Styles ────────────────────────────────────────────────────────────────
  var css = `
  #event-popup-overlay{
    position:fixed;inset:0;z-index:9999;
    display:flex;align-items:center;justify-content:center;
    padding:1.25rem;
    background:rgba(20,18,16,0.55);backdrop-filter:blur(4px);
    opacity:0;animation:evtFade .35s ease forwards;
  }
  @keyframes evtFade{to{opacity:1;}}
  @keyframes evtRise{from{transform:translateY(16px);opacity:0;}to{transform:translateY(0);opacity:1;}}

  #event-popup{
    position:relative;display:grid;grid-template-columns:1fr 0.78fr;
    width:100%;max-width:860px;max-height:92vh;overflow:hidden;
    border-radius:2px;background:#fff;direction:ltr;
    box-shadow:0 30px 80px rgba(20,18,16,0.35);
    animation:evtRise .45s cubic-bezier(.2,.7,.2,1) forwards;
  }

  /* ---- copy side ---- */
  #event-popup .evt-copy{
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    gap:1.5rem;padding:3rem 2.25rem;text-align:center;
  }
  #event-popup .evt-logo{width:min(210px,60%);height:auto;display:block;}
  #event-popup .evt-intro{
    margin:0;font-family:'Montserrat',sans-serif;font-weight:300;
    font-size:1rem;line-height:1.6;color:#1A1715;max-width:22ch;
  }
  #event-popup .evt-venue,#event-popup .evt-where{
    margin:0;font-family:'Montserrat',sans-serif;font-weight:300;
    font-size:.95rem;line-height:1.5;color:#1A1715;
  }
  #event-popup .evt-night{margin:0;}
  #event-popup .evt-when{
    display:block;font-family:'Montserrat',sans-serif;font-weight:400;
    font-size:1.15rem;letter-spacing:.04em;color:#1A1715;
  }
  /* Sale block — same typographic scale as the date above it, separated by a
     hairline rather than a coloured badge so it reads as part of the card. */
  /* No max-width: the sale copy is three full sentences and a narrow measure
     was orphaning the last word of two of them. The rule spanning the copy
     column also reads more deliberate than a short centred dash. */
  #event-popup .evt-sale{
    margin:0;padding-top:1.25rem;width:100%;
    border-top:1px solid #E6DFD8;
  }
  #event-popup .evt-sale-intro{
    display:block;font-family:'Montserrat',sans-serif;font-weight:300;
    font-size:.85rem;line-height:1.5;color:#1A1715;margin-bottom:.5rem;
  }
  #event-popup .evt-sale-title{
    display:block;font-family:'Montserrat',sans-serif;font-weight:500;
    font-size:.9rem;letter-spacing:.18em;text-transform:uppercase;color:#1A1715;
    margin-bottom:.4rem;
  }
  #event-popup .evt-sale-note{
    display:block;font-family:'Montserrat',sans-serif;font-weight:300;
    font-size:.8rem;letter-spacing:.04em;color:#746862;
  }

  #event-popup .evt-cal{
    display:inline-flex;align-items:center;gap:.6rem;
    font-family:'Montserrat',sans-serif;font-weight:500;
    font-size:.78rem;letter-spacing:.22em;text-transform:uppercase;
    color:#fff;background:#1A1715;
    padding:.95rem 1.75rem;border:none;border-radius:2px;cursor:pointer;
    text-decoration:none;transition:background .25s ease,transform .25s ease;
  }
  #event-popup .evt-cal:hover{background:#2D2926;transform:translateY(-1px);}

  /* ---- product panel ---- */
  #event-popup .evt-panel{
    display:block;width:100%;height:100%;object-fit:cover;
  }

  /* Close button */
  #event-popup-close{
    position:absolute;top:.75rem;right:.75rem;z-index:2;
    width:2.4rem;height:2.4rem;display:flex;align-items:center;justify-content:center;
    background:rgba(247,243,238,.9);border:none;border-radius:50%;cursor:pointer;
    color:#1A1715;box-shadow:0 2px 10px rgba(20,18,16,.18);
    transition:background .2s ease,transform .2s ease;
  }
  #event-popup-close:hover{background:#fff;transform:rotate(90deg);}

  @media (max-width:640px){
    /* Text first, panel below — the invitation is the message, the photos are
       decoration, and on a phone only the top of the card is guaranteed seen. */
    #event-popup{grid-template-columns:1fr;max-height:90vh;overflow-y:auto;}
    #event-popup .evt-copy{padding:2.5rem 1.5rem 2rem;gap:1.25rem;}
    #event-popup .evt-panel{max-height:38vh;}
  }
  `;
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  // ── Markup ──────────────────────────────────────────────────────────────
  var overlay = document.createElement('div');
  overlay.id = 'event-popup-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', 'STEELO pop-up store and sale');
  overlay.innerHTML = `
    <div id="event-popup">
      <button id="event-popup-close" aria-label="Close invitation">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
      </button>

      <div class="evt-copy">
        <img class="evt-logo" src="images/logo.png" alt="STEELO">
        <p class="evt-intro">${EVENT.intro}</p>
        <p class="evt-night">
          <span class="evt-when">${EVENT.when}</span>
        </p>
        <p class="evt-venue">${EVENT.venue}</p>
        <p class="evt-where">${EVENT.where}</p>
        ${showSale ? `<p class="evt-sale">
          <span class="evt-sale-intro">${EVENT.saleIntro}</span>
          <span class="evt-sale-title">${EVENT.saleTitle}</span>
          <span class="evt-sale-note">${EVENT.saleNote}</span>
        </p>` : ''}
        <a class="evt-cal" id="evt-shop" href="${SHOP_URL}">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
          Shop the Collection
        </a>
      </div>

      <img class="evt-panel" src="${PANEL_IMG}" alt="Four STEELO stainless steel pieces">
    </div>
  `;

  // ── Behaviour ─────────────────────────────────────────────────────────────
  function close() {
    overlay.remove();
    document.body.style.overflow = '';
    document.removeEventListener('keydown', onKey);
  }
  function onKey(e) { if (e.key === 'Escape') close(); }

  function open() {
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    overlay.querySelector('#event-popup-close').addEventListener('click', close);
    // The CTA is an in-page anchor now, not an external link. Without this the
    // overlay would stay up and body overflow:hidden would block the very
    // scroll the anchor just asked for.
    overlay.querySelector('#evt-shop').addEventListener('click', close);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) close();      // click outside the card
    });
    document.addEventListener('keydown', onKey);
  }

  // Show the popup 7 seconds after the page loads, on every hard load.
  var DELAY_MS = 7000;
  function schedule() { setTimeout(open, DELAY_MS); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedule);
  } else {
    schedule();
  }
})();
