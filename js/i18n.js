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
    },
  };
  var dict = STRINGS[lang] || STRINGS.en;
  window.t = function (key) { return dict[key] || STRINGS.en[key] || key; };
})();
