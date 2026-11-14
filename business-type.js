/* The shop's own words, and only the screens it has a use for.

   POS WAI was written for restaurants, so the pages say "สั่งอาหาร", "จอครัว"
   and "โต๊ะ" throughout. A clothes shop opening it for the first time reads
   that as "this is not for me" and closes it, and a kitchen screen it can
   never fill is worse than no screen.

   The page keeps the restaurant wording in its HTML, which is what a shop
   sees if this file never loads. Everything swapped here is marked in the
   markup with data-biz, so the words and the code stay in one place each. */
(() => {
  const RESTAURANT = 'restaurant';

  /* Hiding a tab is a convenience, exactly like the role matrix: the server
     still answers its endpoints. A retail shop that somehow reaches the
     kitchen screen sees an empty one, not an error. */
  const applyHiddenTabs = (hidden) => {
    for (const button of document.querySelectorAll('.role-tab')) {
      const tab = button.getAttribute('onclick')?.match(/switchTab\('([^']+)'/)?.[1];
      if (!tab) continue;
      button.dataset.bizHidden = hidden.includes(tab) ? 'yes' : '';
      if (hidden.includes(tab)) button.hidden = true;
    }
    // Standing on a screen this shop does not use: step back to the first one.
    if (hidden.includes(document.body.dataset.activeTab)) {
      document.querySelector('.role-tab:not([hidden])')?.click();
    }
  };

  const applyWords = (words) => {
    for (const element of document.querySelectorAll('[data-biz]')) {
      const word = words[element.dataset.biz];
      if (!word) continue;
      // Keep the original around so a later switch has something to go back
      // to without a reload.
      if (element.dataset.bizOriginal === undefined) {
        element.dataset.bizOriginal = element.getAttribute(element.dataset.bizAttr || 'textContent')
          ?? element.textContent;
      }
      if (element.dataset.bizAttr) element.setAttribute(element.dataset.bizAttr, word);
      else element.textContent = word;
    }
  };

  const apply = (business) => {
    if (!business) return;
    window.POSWAI_BUSINESS = business;
    document.body.dataset.businessType = business.type || RESTAURANT;
    /* The browser tab, which is what an owner sees in a row of pinned tabs
       and the name their phone gives the shortcut they saved. */
    if (business.words?.title) document.title = business.words.title;
    applyWords(business.words || {});
    applyHiddenTabs(business.tabs_hidden || []);
  };

  fetch('/api/config', { cache: 'no-store' })
    .then(response => response.json())
    .then(config => apply(config.business))
    .catch(() => { /* The restaurant wording in the HTML is the fallback. */ });

  /* The role matrix shows and hides the same buttons whenever someone signs
     in, so the business type has to be put back after it. */
  window.addEventListener('poswai:auth-changed', () => {
    const hidden = window.POSWAI_BUSINESS?.tabs_hidden || [];
    if (hidden.length) applyHiddenTabs(hidden);
  });

  // The settings screen saves a new type and asks for the words again.
  window.poswaiApplyBusiness = apply;
})();
