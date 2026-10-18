/* The two things the app's skin cannot do in CSS alone.
 *
 * 1. The signed-in person as a round initial. The page writes "Phira ▾" into
 *    its account button and rewrites it whenever someone signs in or out; this
 *    keeps a data-initial beside it for app-shell.css to draw.
 * 2. A "More" sheet that holds only the tabs that do not fit in the bar. The
 *    page's own panel moves every tab into a grid and leaves the bar empty
 *    behind it; a phone app keeps its bar and slides the rest up from below.
 *
 * Both only ever call into what the page already has — the sheet's rows click
 * the page's own tab buttons — so nothing here can drift from the web's logic.
 */
(() => {
  'use strict';
  if (!document.documentElement.classList.contains('poswai-app')) return;

  // -------------------------------------------------------- the initial
  const initialOf = (text) => {
    const name = (text || '').replace(/\s*[▾▼⌄]\s*$/u, '').trim();
    if (!name) return '';
    // Thai names start with a consonant the eye reads as the initial; a leading
    // vowel mark (เ แ โ ใ ไ) is written first but is not what people call it.
    const letters = [...name];
    const first = /^[เแโใไ]$/u.test(letters[0]) && letters[1] ? letters[1] : letters[0];
    return first.toUpperCase();
  };

  const watchAccount = (button) => {
    const sync = () => {
      const text = button.textContent || '';
      // auth-ui writes "name ▾" for whoever is signed in and plain words
      // ("เข้าสู่ระบบ") for nobody. Only a person gets an initial; the words
      // stay words, or a signed-out till would look signed in.
      const signedIn = /[▾▼⌄]\s*$/u.test(text);
      const initial = signedIn ? initialOf(text) : '';
      if (button.dataset.initial !== initial) button.dataset.initial = initial;
      button.toggleAttribute('data-signed-out', !signedIn);
      const label = signedIn ? `บัญชี ${text.replace(/\s*[▾▼⌄]\s*$/u, '').trim()}` : null;
      if (label) { if (button.getAttribute('aria-label') !== label) button.setAttribute('aria-label', label); }
      else if (button.hasAttribute('aria-label')) button.removeAttribute('aria-label');
    };
    sync();
    new MutationObserver(sync).observe(button, {childList: true, characterData: true, subtree: true});
  };

  // ---------------------------------------------------------- the sheet
  const IN_BAR = 4;   // tabs that fit the bar; the rest live in the sheet
  let sheet = null;
  let scrim = null;

  const tabs = () => [...document.querySelectorAll('.role-tabs .role-tab')];
  // auth-ui hides the tabs a role may not open; the bar is built from the rest.
  const allowed = () => tabs().filter((tab) => !tab.hidden);
  const overflow = () => allowed().filter((tab) => !tab.hasAttribute('data-in-bar'));

  const arrangeBar = () => {
    const open = allowed();
    tabs().forEach((tab) => tab.toggleAttribute('data-in-bar', open.indexOf(tab) > -1 && open.indexOf(tab) < IN_BAR));
    document.querySelector('.mobile-more')?.toggleAttribute('data-empty', open.length <= IN_BAR);
  };

  const overflowActive = () => overflow().some((tab) => tab.classList.contains('active'));

  const close = () => {
    if (!sheet) return;
    sheet.removeAttribute('data-open');
    scrim.removeAttribute('data-open');
    document.querySelector('.mobile-more')?.setAttribute('aria-expanded', 'false');
  };

  const row = (tab) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'app-sheet-item';
    if (tab.classList.contains('active')) item.setAttribute('aria-current', 'page');
    const icon = tab.querySelector('svg')?.cloneNode(true);
    if (icon) item.append(icon);
    const text = document.createElement('span');
    text.textContent = tab.querySelector(':scope > span')?.textContent || tab.title || '';
    const hint = tab.querySelector('small')?.textContent;
    if (hint) {
      const small = document.createElement('small');
      small.textContent = hint;
      text.append(small);
    }
    item.append(text);
    item.insertAdjacentHTML('beforeend',
      '<svg class="app-sheet-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>');
    item.addEventListener('click', () => { close(); tab.click(); });
    return item;
  };

  const open = () => {
    if (!sheet) {
      sheet = document.createElement('div');
      sheet.className = 'app-sheet';
      sheet.setAttribute('role', 'dialog');
      sheet.setAttribute('aria-modal', 'true');
      sheet.setAttribute('aria-label', 'เมนูเพิ่มเติม');
      scrim = document.createElement('div');
      scrim.className = 'app-sheet-scrim';
      scrim.addEventListener('click', close);
      document.body.append(sheet, scrim);
      document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
    }
    const list = document.createElement('div');
    list.className = 'app-sheet-list';
    list.append(...overflow().map(row));
    sheet.replaceChildren(
      Object.assign(document.createElement('div'), {className: 'app-sheet-grip'}),
      Object.assign(document.createElement('h2'), {textContent: 'เมนูเพิ่มเติม'}),
      list,
    );
    sheet.setAttribute('data-open', '');
    scrim.setAttribute('data-open', '');
    document.querySelector('.mobile-more')?.setAttribute('aria-expanded', 'true');
  };

  const takeOverMore = (more) => {
    // Replace the page's handler rather than add to it: its panel must not
    // open underneath ours.
    more.removeAttribute('onclick');
    more.onclick = null;
    more.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      sheet?.hasAttribute('data-open') ? close() : open();
    }, true);
  };

  /* Android's back button closes the sheet first. A backButton listener
     replaces Capacitor's default handling, so the default is done here too:
     go back if there is somewhere to go, otherwise leave the app. */
  const app = window.Capacitor?.Plugins?.App;
  app?.addListener('backButton', ({canGoBack}) => {
    if (sheet?.hasAttribute('data-open')) { close(); return; }
    if (canGoBack) window.history.back();
    else app.exitApp();
  });

  const start = () => {
    const account = document.querySelector('.poswai-auth-button');
    if (account) watchAccount(account);
    else {
      // auth-ui builds the button after the page loads.
      const wait = new MutationObserver(() => {
        const found = document.querySelector('.poswai-auth-button');
        if (found) { wait.disconnect(); watchAccount(found); }
      });
      wait.observe(document.body, {childList: true, subtree: true});
    }
    const more = document.querySelector('.mobile-more');
    if (more) takeOverMore(more);
    arrangeBar();
    new MutationObserver(arrangeBar).observe(document.querySelector('.role-tabs'),
      {attributes: true, attributeFilter: ['hidden'], subtree: true});
    // A tab chosen from anywhere closes the sheet.
    document.querySelector('.role-tabs')?.addEventListener('click', close);
    /* When the screen open is one from the sheet, More is where the user is:
       light it like any other active tab, or the bar shows nothing selected. */
    if (more) {
      const mark = () => more.toggleAttribute('data-current', overflowActive());
      mark();
      new MutationObserver(mark).observe(document.querySelector('.role-tabs'),
        {attributes: true, attributeFilter: ['class'], subtree: true});
    }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
