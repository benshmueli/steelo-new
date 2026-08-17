/* ============================================================
   First-party funnel analytics — collector
   ============================================================

   Sends funnel stages to POST /a, which server.py stores in SQLite on the
   Railway volume. Separate from tracking.js on purpose: that file talks to
   Meta, this one only ever talks to our own server, and neither should break
   if the other is blocked.

   Three rules this file must never violate:
     1. It is fire-and-forget. sendBeacon, no callbacks, no awaits — nothing
        here may delay a page or a checkout.
     2. Every call is wrapped so a failure is silent. Analytics must not be
        able to take the store down.
     3. It stores nothing about the visitor beyond a random id. No name, no
        email, no address — those live in the order, not here.
*/

(function () {
  'use strict';

  var VISITOR_KEY = 'steelo_vid';
  var SESSION_KEY = 'steelo_sid';
  var SOURCE_KEY  = 'steelo_src';
  var OPT_OUT_KEY = 'steelo_no_track';

  /* The admin looks at its own dashboard constantly; counting that would be
     absurd. Opting a device out is a button in the admin panel. */
  function disabled() {
    try {
      if (localStorage.getItem(OPT_OUT_KEY)) return true;
    } catch (e) { return true; }          // no storage → no stable id → no point
    return /\/admin(\.html)?$/.test(location.pathname);
  }

  function rid() {
    return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  }

  function stored(store, key) {
    try {
      var v = store.getItem(key);
      if (!v) { v = rid(); store.setItem(key, v); }
      return v;
    } catch (e) { return ''; }
  }

  /* Persistent, so a visitor who comes back next week is still one person —
     weekly and monthly unique counts are impossible without it. */
  function visitorId() { return stored(localStorage, VISITOR_KEY); }
  function sessionId() { return stored(sessionStorage, SESSION_KEY); }

  /* Where this session came from. Meta appends fbclid to every ad click, and
     any utm_* the owner adds to the ad link is honoured too. Worked out once
     per session and kept, so the source survives navigation within the visit —
     otherwise every page after the landing one would look "direct". */
  function classify() {
    try {
      var cached = sessionStorage.getItem(SOURCE_KEY);
      if (cached) return JSON.parse(cached);
    } catch (e) {}

    var qs       = new URLSearchParams(location.search);
    var fbclid   = qs.get('fbclid');
    var utmSrc   = (qs.get('utm_source') || '').toLowerCase();
    var utmMed   = (qs.get('utm_medium') || '').toLowerCase();
    var campaign = qs.get('utm_campaign') || qs.get('utm_content') || '';
    var ref      = document.referrer || '';
    var refHost  = '';
    try { refHost = ref ? new URL(ref).hostname.toLowerCase() : ''; } catch (e) {}

    var SEARCH = /google|bing|duckduckgo|yahoo|ecosia/;
    var isMeta = /facebook|instagram|^fb$|^ig$|meta/.test(utmSrc) ||
                 /facebook\.com|instagram\.com/.test(refHost);
    var isPaid = !!fbclid || /paid|cpc|ppc|ad$|ads/.test(utmMed);

    var source;
    if (fbclid || (isPaid && isMeta))                  source = 'paid_meta';
    else if (isPaid)                                   source = 'paid_other';
    else if (isMeta)                                   source = 'referral';
    // utm_source is checked as well as the referrer: a tagged link opened from
    // an email or an app arrives with no referrer at all, and would otherwise
    // be filed as "direct" despite saying exactly where it came from.
    else if (SEARCH.test(utmSrc) || SEARCH.test(refHost)) source = 'organic_search';
    else if (utmSrc)                                   source = 'referral';
    else if (refHost && refHost !== location.hostname)  source = 'referral';
    else                                               source = 'direct';

    var out = { source: source, campaign: campaign.slice(0, 120) };
    try { sessionStorage.setItem(SOURCE_KEY, JSON.stringify(out)); } catch (e) {}
    return out;
  }

  function send(stage, extra) {
    if (disabled()) return;
    try {
      var src = classify();
      var body = JSON.stringify(Object.assign({
        stage:    stage,
        visitor:  visitorId(),
        session:  sessionId(),
        source:   src.source,
        campaign: src.campaign,
      }, extra || {}));
      // sendBeacon survives the page being closed mid-navigation, which fetch
      // does not; the fetch is only a fallback for browsers without it.
      if (navigator.sendBeacon) {
        navigator.sendBeacon('/a', new Blob([body], { type: 'application/json' }));
      } else {
        fetch('/a', { method: 'POST', body: body, keepalive: true,
                      headers: { 'Content-Type': 'application/json' } }).catch(function () {});
      }
    } catch (e) { /* analytics never breaks a page */ }
  }

  /* Exposed for cart.js / checkout.js, and for the admin's opt-out button. */
  window.stlTrack        = send;
  window.stlVisitorId    = visitorId;
  window.stlAnalyticsOff = function (off) {
    try {
      if (off) localStorage.setItem(OPT_OUT_KEY, '1');
      else     localStorage.removeItem(OPT_OUT_KEY);
    } catch (e) {}
  };

  send('visit');
  // `view_product` is fired by the product page itself, from the same inline
  // block that sets STEELO_PRODUCT and calls stlTrackViewContent — that block
  // runs after this file, so checking for STEELO_PRODUCT here would always miss.
})();
