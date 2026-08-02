/* ──────────────────────────────────────────────────────────────────────────
   STEELO — Launch event popup
   Shows on every visit (no dismissal memory). Displays the exact launch
   invitation image. Clear X to close (also Esc / backdrop click) plus an
   "Add to Calendar" button linking to the Google Calendar event.
   ────────────────────────────────────────────────────────────────────────── */
(function () {
  var CALENDAR_URL = 'https://calendar.app.google/crQeDPq9hND7Mo699';
  var INVITE_IMG   = 'images/Launch_Invitataion.jpeg';

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
    position:relative;display:flex;flex-direction:column;
    width:100%;max-width:760px;max-height:92vh;overflow:hidden;
    border-radius:2px;background:#fff;
    box-shadow:0 30px 80px rgba(20,18,16,0.35);
    animation:evtRise .45s cubic-bezier(.2,.7,.2,1) forwards;
  }
  #event-popup .evt-img{
    display:block;width:100%;height:auto;max-height:76vh;object-fit:contain;
  }

  /* CTA bar under the invitation */
  #event-popup .evt-bar{
    display:flex;justify-content:center;
    padding:1rem 1.25rem 1.25rem;background:#fff;
  }
  #event-popup .evt-cal{
    display:inline-flex;align-items:center;gap:.6rem;
    font-family:'Montserrat',sans-serif;font-weight:500;
    font-size:.72rem;letter-spacing:.22em;text-transform:uppercase;
    color:#fff;background:var(--ink,#1A1715);
    padding:.95rem 1.75rem;border:none;border-radius:2px;cursor:pointer;
    text-decoration:none;transition:background .25s ease,transform .25s ease;
  }
  #event-popup .evt-cal:hover{background:var(--ink-800,#2D2926);transform:translateY(-1px);}

  /* Close button */
  #event-popup-close{
    position:absolute;top:.75rem;right:.75rem;z-index:2;
    width:2.4rem;height:2.4rem;display:flex;align-items:center;justify-content:center;
    background:rgba(247,243,238,.9);border:none;border-radius:50%;cursor:pointer;
    color:var(--ink,#1A1715);box-shadow:0 2px 10px rgba(20,18,16,.18);
    transition:background .2s ease,transform .2s ease;
  }
  #event-popup-close:hover{background:#fff;transform:rotate(90deg);}

  @media (max-width:640px){
    #event-popup{max-height:90vh;overflow-y:auto;}
    #event-popup .evt-img{max-height:none;}
    #event-popup .evt-bar{padding:.85rem 1rem 1.1rem;}
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

      <img class="evt-img" src="${INVITE_IMG}" alt="STEELO launch event — Opening night 13.8, 19:00–23:00, KIXBOX, Shenkin 57, Tel Aviv">

      <div class="evt-bar">
        <a class="evt-cal" href="${CALENDAR_URL}" target="_blank" rel="noopener">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          Add to Calendar
        </a>
      </div>
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
