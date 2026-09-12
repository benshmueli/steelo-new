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

   Every value below comes from the admin panel, served as window.STEELO_POPUP
   by /js/popup.js. The literals here are only the fallback for a page served
   without the server. The dates that used to retire the card on their own are
   gone: `enabled` is resolved server-side from the owner's switch and an
   optional end date, so the sale line can no longer outlive the discount that
   backs it — the two are now set in the same panel.
   ────────────────────────────────────────────────────────────────────────── */
(function () {
  var FALLBACK = {
    enabled:      true,
    intro:        'Steelo Pop-Up at KIXBOX',
    when:         '13.8–14.9',
    venue:        'Come visit us in store!',
    where:        '📍 Shenkin 57, Tel Aviv',
    image:        'images/launch-invite-panel.jpg',
    sale_enabled: false,
    sale_intro:   '',
    sale_title:   '',
    sale_note:    '',
    cta_text:     'Shop the Collection',
    cta_url:      '#collection',
    frequency:    'always',
    delay_ms:     7000
  };

  var CFG = {};
  var live = window.STEELO_POPUP;
  for (var k in FALLBACK) CFG[k] = FALLBACK[k];
  if (live && typeof live === 'object') {
    for (var j in live) if (live[j] !== undefined) CFG[j] = live[j];
  }

  /* Forces the card open regardless of the switch, the frequency rule and the
     delay. This is what the admin panel's Preview button opens, so what the
     owner checks is the real popup rather than an imitation of it. */
  var PREVIEW = false;
  try {
    PREVIEW = new URLSearchParams(location.search).get('popup_preview') === '1';
  } catch (e) {}

  if (!PREVIEW && !CFG.enabled) return;   // nothing injected — no styles, no markup

  var showSale = !!CFG.sale_enabled &&
                 !!(CFG.sale_intro || CFG.sale_title || CFG.sale_note);

  /* One key, holding either 'once' or the day it was last shown. Storage can
     throw outright in a locked-down browser, and a visitor who cannot be
     remembered should still see the popup rather than nothing. */
  var SEEN_KEY = 'steelo_popup_seen';
  function alreadySeen() {
    if (PREVIEW || CFG.frequency === 'always') return false;
    try {
      var mark = localStorage.getItem(SEEN_KEY);
      if (!mark) return false;
      return CFG.frequency === 'once' ? mark === 'once'
                                      : mark === new Date().toDateString();
    } catch (e) { return false; }
  }
  function markSeen() {
    if (PREVIEW || CFG.frequency === 'always') return;
    try {
      localStorage.setItem(SEEN_KEY,
        CFG.frequency === 'once' ? 'once' : new Date().toDateString());
    } catch (e) {}
  }

  if (alreadySeen()) return;

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
        <p class="evt-intro"></p>
        <p class="evt-night">
          <span class="evt-when"></span>
        </p>
        <p class="evt-venue"></p>
        <p class="evt-where"></p>
        ${showSale ? `<p class="evt-sale">
          <span class="evt-sale-intro"></span>
          <span class="evt-sale-title"></span>
          <span class="evt-sale-note"></span>
        </p>` : ''}
        <a class="evt-cal" id="evt-shop">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
          <span class="evt-cal-text"></span>
        </a>
      </div>

      <img class="evt-panel" alt="STEELO stainless steel pieces">
    </div>
  `;

  /* The copy is filled in as text, never interpolated into the markup above.
     These strings used to be constants in this file; now the owner types them
     into the admin panel, and an ampersand or a stray angle bracket must land
     on the card as itself rather than as HTML. Same reason src and href are
     assigned as properties. */
  function setText(sel, value) {
    var el = overlay.querySelector(sel);
    if (el) el.textContent = value || '';
  }
  setText('.evt-intro',      CFG.intro);
  setText('.evt-when',       CFG.when);
  setText('.evt-venue',      CFG.venue);
  setText('.evt-where',      CFG.where);
  setText('.evt-cal-text',   CFG.cta_text || FALLBACK.cta_text);
  if (showSale) {
    setText('.evt-sale-intro', CFG.sale_intro);
    setText('.evt-sale-title', CFG.sale_title);
    setText('.evt-sale-note',  CFG.sale_note);
  }
  overlay.querySelector('#evt-shop').href  = CFG.cta_url || FALLBACK.cta_url;
  overlay.querySelector('.evt-panel').src  = CFG.image   || FALLBACK.image;

  /* An empty line would otherwise leave its margin behind and push the card
     out of shape — the owner clearing a field should remove the line, not
     leave a gap where it was. */
  ['.evt-intro', '.evt-when', '.evt-venue', '.evt-where'].forEach(function (sel) {
    var el = overlay.querySelector(sel);
    if (el && !el.textContent) {
      (sel === '.evt-when' ? el.parentNode : el).style.display = 'none';
    }
  });

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
    // Recorded on display, not on load: a visitor who left before the delay
    // elapsed has not seen it, and should get it next time.
    markSeen();
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

  // How long after load the card appears, and how often a visitor sees it, are
  // both set in the admin panel. A preview skips the wait entirely.
  var DELAY_MS = PREVIEW ? 0 : Math.max(0, Number(CFG.delay_ms) || 0);
  function schedule() { setTimeout(open, DELAY_MS); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedule);
  } else {
    schedule();
  }
})();
