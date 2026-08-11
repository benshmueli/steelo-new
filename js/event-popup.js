/* ──────────────────────────────────────────────────────────────────────────
   STEELO — Launch event popup
   Shows on every visit (no dismissal memory). Clear X to close (also Esc /
   backdrop click) plus an "Add to Calendar" button linking to the event.

   The invitation used to be a single 1535x1024 JPEG. On a phone that renders
   around 350px wide, so its lettering landed at roughly 23% of design size and
   no CSS could enlarge it — the text was pixels. The copy is now real HTML and
   only the product panel stayed an image (images/launch-invite-panel.jpg, the
   right half of the original). The date can be edited here without a graphics
   tool, and a screen reader can read it.
   ────────────────────────────────────────────────────────────────────────── */
(function () {
  var CALENDAR_URL = 'https://calendar.app.google/crQeDPq9hND7Mo699';
  var PANEL_IMG    = 'images/launch-invite-panel.jpg';

  // Event details — edit here.
  var EVENT = {
    intro:  "We're excited to invite you to our launch event",
    venue:  'At KIXBOX, Tel Aviv',
    label:  'Opening night',
    when:   '13.8  |  19:00–23:00',
    where:  'Shenkin 57, Tel Aviv'
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
  #event-popup .evt-label{
    display:block;font-family:'Montserrat',sans-serif;font-weight:500;
    font-size:.8rem;letter-spacing:.22em;text-transform:uppercase;color:#1A1715;
    margin-bottom:.4rem;
  }
  #event-popup .evt-when{
    display:block;font-family:'Montserrat',sans-serif;font-weight:400;
    font-size:1.15rem;letter-spacing:.04em;color:#1A1715;
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
  overlay.setAttribute('aria-label', 'STEELO launch event invitation');
  overlay.innerHTML = `
    <div id="event-popup">
      <button id="event-popup-close" aria-label="Close invitation">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
      </button>

      <div class="evt-copy">
        <img class="evt-logo" src="images/logo.png" alt="STEELO">
        <p class="evt-intro">${EVENT.intro}</p>
        <p class="evt-venue">${EVENT.venue}</p>
        <p class="evt-night">
          <span class="evt-label">${EVENT.label}</span>
          <span class="evt-when">${EVENT.when}</span>
        </p>
        <p class="evt-where">${EVENT.where}</p>
        <a class="evt-cal" href="${CALENDAR_URL}" target="_blank" rel="noopener">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          Add to Calendar
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
