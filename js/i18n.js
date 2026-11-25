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
      // {p} is the pair-deal percentage and {s} a shekel amount, filled in by cart.js
      pair_title:    'Make it a pair · {p}% off the second item',
      pair_sub:      'Add another from the same collection and the lower-priced of the two is {p}% off.',
      pair_twin:     'matching pair',
      pair_saving:   'Save',
      pair_add:      'Add',
      pair_line:     'Second item · {p}% off',
      pair_saved:    'You saved {s} with the pair deal',
      // {f} is the home-delivery price for the cart, filled in by cart.js
      cart_ship:      'Home delivery: {f} · Pickup: free',
      cart_ship_free: 'Home delivery: free',
      // {l} is the coupon's headline ("15% הנחה") and {c} its code
      cart_coupon:      '{l} · code {c} is applied for you at checkout',
      cart_coupon_code: 'Code {c} is applied for you at checkout',
    },
    he: {
      view_details:  'צפייה בפריט',
      cart_empty:    'הסל שלכם ריק',
      remove:        'הסרה',
      decrease:      'הפחתת כמות',
      increase:      'הוספת כמות',
      pay_init_fail: 'לא ניתן היה להתחיל את התשלום',
      pay_conn_fail: 'לא ניתן להתחבר לתשלום. אנא נסו שוב.',
      pair_title:    'השלימו לזוג · {p}% הנחה על הפריט השני',
      pair_sub:      'מוסיפים עוד פריט מאותה קטגוריה, והזול מבין השניים מקבל {p}% הנחה.',
      pair_twin:     'זוג תואם',
      pair_saving:   'חוסכים',
      pair_add:      'הוספה',
      pair_line:     'פריט שני · {p}% הנחה',
      pair_saved:    'חסכתם {s} במבצע זוג',
      cart_ship:      'משלוח עד הבית: {f} · איסוף עצמי: חינם',
      cart_ship_free: 'משלוח עד הבית: חינם',
      cart_coupon:      '{l} · הקוד {c} יחול אוטומטית בסיכום ההזמנה',
      cart_coupon_code: 'הקוד {c} יחול אוטומטית בסיכום ההזמנה',
    },
  };
  var dict = STRINGS[lang] || STRINGS.en;
  window.t = function (key) { return dict[key] || STRINGS.en[key] || key; };
})();
