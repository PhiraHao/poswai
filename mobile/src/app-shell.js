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
    const printer = Boolean(window.Capacitor?.Plugins?.BluetoothLe);   // its row lives in the sheet
    document.querySelector('.mobile-more')?.toggleAttribute('data-empty', open.length <= IN_BAR && !printer);
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

  const printerRow = () => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'app-sheet-item';
    item.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 9V3h10v6"/>'
      + '<rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/></svg>';
    const text = document.createElement('span');
    text.textContent = 'เครื่องพิมพ์ใบเสร็จ';
    const small = document.createElement('small');
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('poswai.app.printer') || 'null'); } catch { /* */ }
    small.textContent = saved ? saved.name : 'ยังไม่ได้เลือกเครื่อง';
    text.append(small);
    item.append(text);
    item.insertAdjacentHTML('beforeend',
      '<svg class="app-sheet-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>');
    item.addEventListener('click', () => { close(); window.POSWAI_APP.printer.open(); });
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
    // Not a screen of the POS but a setting of this device: the receipt printer.
    if (window.POSWAI_APP?.printer) list.append(printerRow());
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
    if (window.POSWAI_APP?.printer?.isOpen()) { window.POSWAI_APP.printer.close(); return; }
    if (window.POSWAI_UI?.back?.()) return;   // the app screens' own sheet, sub-page or tab
    if (canGoBack) window.history.back();
    else app.exitApp();
  });

  /* The mascot greets whoever signs in: the same POS WAI character as the
     web's landing page, on the card the app opens with. */
  const greet = () => {
    const card = document.querySelector('.poswai-auth-card');
    if (!card || card.querySelector('.app-login-mascot')) return;
    const mascot = Object.assign(document.createElement('img'), {
      className: 'app-login-mascot', src: '/assets/mascot-pos.webp', alt: '', decoding: 'async',
    });
    card.prepend(mascot);
  };

  /* ---- the line to the server ------------------------------------------
     One strip under the app bar says what a cashier needs to know about the
     shop's internet, and nothing when there is nothing to say:
       offline              ออฟไลน์ · ขายต่อได้ · ค้างส่ง N รายการ
       back, still sending  กำลังส่งข้อมูลที่ค้าง N รายการ…
       something refused    มี N รายการที่ส่งไม่ผ่าน · ดูรายการ
     The queue itself is index.html's (offlineSyncQueue); this only reads it. */
  const listOf = (key) => { try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch { return []; } };
  let strip = null;

  const describe = (event) => {
    const p = event.payload || {};
    if (event.path === '/api/payments/close') return `ปิดบิล ${p.order_no || ''} · ฿${Number(p.amount || 0).toFixed(2)}`;
    if (event.path === '/api/orders') return `ออเดอร์โต๊ะ ${p.table_no || ''}`;
    return event.path.replace('/api/', '');
  };

  const showRejected = () => {
    const rejected = listOf('offlineSyncRejected');
    const sheetEl = document.createElement('div');
    sheetEl.className = 'app-sheet';
    sheetEl.setAttribute('role', 'dialog');
    sheetEl.setAttribute('aria-label', 'รายการที่ส่งไม่ผ่าน');
    const scrimEl = Object.assign(document.createElement('div'), {className: 'app-sheet-scrim'});
    const done = () => { sheetEl.remove(); scrimEl.remove(); };
    scrimEl.addEventListener('click', done);
    const listEl = Object.assign(document.createElement('div'), {className: 'app-sheet-list'});
    /* Each one may be money already in the drawer with no record on the server,
       so nothing here is thrown away in bulk: an item is sent again (after the
       cause is fixed, e.g. the dish put back on the menu) or, one at a time,
       marked as dealt with by hand. */
    const save = (list) => localStorage.setItem('offlineSyncRejected', JSON.stringify(list));
    const redraw = () => { done(); paint(); if (listOf('offlineSyncRejected').length) showRejected(); };
    rejected.forEach((item, index) => {
      const row = Object.assign(document.createElement('div'), {className: 'app-sheet-item app-rejected-item'});
      const text = Object.assign(document.createElement('span'), {textContent: describe(item)});
      text.append(Object.assign(document.createElement('small'), {
        textContent: `${item.reason} · ${new Date(item.rejected_at).toLocaleString('th-TH')}`,
      }));
      const again = Object.assign(document.createElement('button'), {type: 'button', textContent: 'ส่งอีกครั้ง'});
      again.addEventListener('click', () => {
        const rest = listOf('offlineSyncRejected');
        const [back] = rest.splice(index, 1);
        delete back.reason;
        delete back.rejected_at;
        if (!window.requeueOfflineEvent) return;
        save(rest);
        window.requeueOfflineEvent(back);
        redraw();
      });
      const handled = Object.assign(document.createElement('button'), {type: 'button', textContent: 'จัดการแล้ว'});
      handled.addEventListener('click', () => {
        if (!window.confirm('ยืนยันว่าบันทึกรายการนี้ด้วยมือแล้ว? รายการจะหายจากที่นี่')) return;
        const rest = listOf('offlineSyncRejected');
        rest.splice(index, 1);
        save(rest);
        redraw();
      });
      row.append(text, again, handled);
      listEl.append(row);
    });
    const clear = Object.assign(document.createElement('button'), {
      type: 'button', className: 'app-printer-quiet', textContent: 'ปิด',
    });
    clear.addEventListener('click', done);
    sheetEl.append(
      Object.assign(document.createElement('div'), {className: 'app-sheet-grip'}),
      Object.assign(document.createElement('h2'), {textContent: 'รายการที่ส่งไม่ผ่าน'}),
      Object.assign(document.createElement('p'), {className: 'app-printer-hint',
        textContent: 'เซิร์ฟเวอร์ไม่รับรายการเหล่านี้ตอนเน็ตกลับมา เช่น บิลถูกแก้จากเครื่องอื่น ตรวจในหน้าแคชเชียร์แล้วทำใหม่'}),
      listEl, clear);
    document.body.append(sheetEl, scrimEl);
    requestAnimationFrame(() => { sheetEl.setAttribute('data-open', ''); scrimEl.setAttribute('data-open', ''); });
  };

  const paint = () => {
    if (!strip) return;
    const online = navigator.onLine;
    const waiting = listOf('offlineSyncQueue').length;
    const refused = listOf('offlineSyncRejected').length;
    let tone = '';
    let text = '';
    if (!online) { tone = 'offline'; text = `ออฟไลน์ · ขายต่อได้${waiting ? ` · ค้างส่ง ${waiting} รายการ` : ''}`; }
    else if (refused) { tone = 'refused'; text = `มี ${refused} รายการที่ส่งไม่ผ่าน · ดูรายการ`; }
    else if (waiting) { tone = 'sending'; text = `กำลังส่งข้อมูลที่ค้าง ${waiting} รายการ…`; }
    strip.hidden = !tone;
    strip.dataset.tone = tone;
    strip.textContent = text;
    document.getElementById('netToggleBtn')?.classList.toggle('offline', !online);
  };

  const watchLine = () => {
    strip = Object.assign(document.createElement('button'), {type: 'button', className: 'app-netbar', hidden: true});
    strip.addEventListener('click', () => { if (strip.dataset.tone === 'refused') showRejected(); });
    document.querySelector('.sim-topbar')?.after(strip);
    window.addEventListener('online', () => {
      paint();
      // index.html listens for this too; asking again is harmless and covers a
      // queue that filled while its own listener was still waiting.
      window.flushOfflineSyncQueue?.();
    });
    window.addEventListener('offline', paint);
    // The queue changes inside index.html without an event; a light look suffices.
    setInterval(paint, 2000);
    paint();
  };

  const start = () => {
    greet();
    watchLine();
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
