/* Minimal i18n for strings injected by shared JS (cart, grid, checkout).
   Reads the page language from <html lang="…"> so /en and / share one codebase. */
(function () {
  var lang = (document.documentElement.lang || 'en').slice(0, 2);
  var STRINGS = {
    en: {
      view_details:  'View Details',
      cart_empty:    'Your cart is empty',
      remove:        'Remove',
      decrease:      'Decrease',
      increase:      'Increase',
      pay_init_fail: 'Could not initiate payment',
      pay_conn_fail: 'Could not connect to payment. Please try again.',
    },
    he: {
      view_details:  'צפייה בפריט',
      cart_empty:    'הסל שלכם ריק',
      remove:        'הסרה',
      decrease:      'הפחתת כמות',
      increase:      'הוספת כמות',
      pay_init_fail: 'לא ניתן היה להתחיל את התשלום',
      pay_conn_fail: 'לא ניתן להתחבר לתשלום. אנא נסו שוב.',
    },
  };
  var dict = STRINGS[lang] || STRINGS.en;
  window.t = function (key) { return dict[key] || STRINGS.en[key] || key; };
})();
