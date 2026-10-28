/* The guest's own screen: what a customer sees after scanning the QR on a table.
 *
 * Three places, as the POS WAI redesign lays them out — เมนู · ออเดอร์ของฉัน ·
 * บัญชี — with the shop and the table in the header and the cart floating above
 * the bar. Nothing of the staff's: no kitchen, no till, no branch picker.
 *
 * Everything here goes through the page's own functions (onClickMenuCard,
 * submitOrderFromCustomer, sendTableServiceCall, the member sign-in), so the
 * table token, the menu prices and the server's checks are exactly as before.
 * It switches on only for a guest holding a table token, in a browser — never
 * in the POS WAI app, never for a signed-in member of staff.
 */
(() => {
  'use strict';
  if (window.POSWAI_APP) return;
  const params = new URLSearchParams(location.search);
  if (!params.get('table_token')) return;

  const PATHS = {
    menu: 'M4 6h16 M4 12h16 M4 18h10',
    order: 'M7 3h10a1 1 0 0 1 1 1v17l-2.5-1.5L13 21l-2.5-1.5L8 21l-2-1.5V4a1 1 0 0 1 1-1Z M9 8h6 M9 12h6 M9 16h3',
    user: 'M19 20v-1.5a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4V20 M16 7.5a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
    bell: 'M6 16.5h12l-1.5-2.5V10a4.5 4.5 0 0 0-9 0v4L6 16.5Z M10 19.5a2 2 0 0 0 4 0',
    search: 'M20 20l-4.2-4.2 M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
    plus: 'M12 5v14 M5 12h14', minus: 'M5 12h14',
    trash: 'M4 7h16 M10 11v6 M14 11v6 M6 7l1 13h10l1-13 M9 7V4h6v3',
    bag: 'M6 7h12l1.6 13.2a1 1 0 0 1-1 1.1H5.4a1 1 0 0 1-1-1.1L6 7Z M9 9V6a3 3 0 0 1 6 0v3',
    right: 'M9 5l7 7-7 7', close: 'M6 6l12 12 M18 6 6 18', arrow: 'M5 12h14 M13 6l6 6-6 6',
    table: 'M3 7h18 M5 7v12 M19 7v12 M3 7l2-3h14l2 3 M5 12h14',
    receipt: 'M6 3h12v18l-2-1.4-2 1.4-2-1.4-2 1.4-2-1.4L6 21V3Z M9 8h6 M9 12h6 M9 16h3',
    water: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z',
    star: 'm12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9L12 3Z',
    qr: 'M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h2v2h-2z M18 18h2v2h-2z M14 18h2 M18 14h2',
  };
  const icon = (name, cls = '') => `<svg class="gui-i ${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${PATHS[name]}"/></svg>`;
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const baht = (v) => `฿${Number(v || 0).toLocaleString('th-TH', {maximumFractionDigits: 2})}`;
  const auth = () => window.poswaiAuth || {};
  const menu = () => (typeof DEFAULT_MENU !== 'undefined' ? DEFAULT_MENU : []);
  const pos = () => (typeof state !== 'undefined' ? state : {cart: [], orders: []});
  const table = () => String(auth().tableNo || params.get('table') || pos().customerTable || '');
  const toast = (t) => window.showToast?.(t);
  const placeholder = '/assets/menu-placeholder.svg';
  const photo = (m) => m?.photo || placeholder;

  const ui = {tab: 'menu', category: 'ทั้งหมด', query: ''};
  try { Object.assign(ui, JSON.parse(sessionStorage.getItem('gui') || '{}')); } catch (_) { /* fresh */ }
  const remember = () => { try { sessionStorage.setItem('gui', JSON.stringify({tab: ui.tab})); } catch (_) { /* */ } };

  const root = document.createElement('div');
  root.id = 'guestUi';
  root.innerHTML = `
    <header class="gui-top">
      <img src="/assets/brand-icon.webp" alt="POS WAI" class="gui-logo">
      <div class="gui-where"><strong data-slot="shop"></strong><small>${icon('table', 'gui-i-xs')} <span data-slot="table"></span></small></div>
      <button type="button" class="gui-call" data-act="call" data-value="เรียกพนักงานที่โต๊ะ">${icon('bell')}<span>เรียกพนักงาน</span></button>
    </header>
    <main class="gui-main" data-slot="main"></main>
    <div class="gui-cartbar" data-slot="cartbar" hidden></div>
    <nav class="gui-nav" aria-label="เมนูหลัก" data-slot="nav"></nav>
    <div class="gui-ready" data-slot="ready" hidden></div>
    <div class="gui-scrim" data-slot="scrim" hidden></div>
    <section class="gui-sheet" data-slot="sheet" role="dialog" aria-modal="true" hidden></section>`;
  const slot = (n) => root.querySelector(`[data-slot="${n}"]`);

  const TABS = [['menu', 'เมนู', 'menu'], ['orders', 'ออเดอร์ของฉัน', 'order'], ['account', 'บัญชี', 'user']];

  // ------------------------------------------------------------------ menu
  const categories = () => ['ทั้งหมด', ...new Set(menu().map((m) => m.category).filter((c) => c && c !== 'ทั้งหมด'))];
  const cartCount = () => pos().cart.reduce((n, i) => n + i.qty, 0);
  const cartTotal = () => {
    const sub = pos().cart.reduce((s, i) => s + i.price * i.qty, 0);
    const off = typeof getCartDiscount === 'function' ? getCartDiscount(sub) : 0;
    return Math.max(0, sub - off);
  };
  const empty = (title, sub) => `<div class="gui-empty"><img src="/assets/mascot-wave.webp" alt=""><strong>${esc(title)}</strong><small>${esc(sub)}</small></div>`;

  const menuView = () => {
    const q = ui.query.trim().toLowerCase();
    const list = menu().filter((m) => m.active !== false)
      .filter((m) => ui.category === 'ทั้งหมด' || m.category === ui.category)
      .filter((m) => !q || m.name.toLowerCase().includes(q));
    const inCart = (m) => pos().cart.filter((i) => i.id === m.id).reduce((n, i) => n + i.qty, 0);
    return `<h1 class="gui-h1">สั่งอาหาร</h1>
      <label class="gui-search">${icon('search')}<input type="search" data-act="query" value="${esc(ui.query)}" placeholder="ค้นหาเมนู" aria-label="ค้นหาเมนู"></label>
      <div class="gui-chips">${categories().map((c) => `<button type="button" data-act="category" data-value="${esc(c)}" class="${c === ui.category ? 'on' : ''}">${esc(c)}</button>`).join('')}</div>
      ${list.length ? `<div class="gui-products">${list.map((m) => {
        const out = m.soldOut || (typeof m.quota === 'number' && m.quota <= 0);
        const n = inCart(m);
        return `<button type="button" class="gui-product ${out ? 'out' : ''}" data-act="add" data-value="${m.id}" ${out ? 'disabled' : ''}>
          <span class="gui-shot"><img src="${esc(photo(m))}" alt="" loading="lazy" onerror="this.onerror=null;this.src='${placeholder}'">${out ? '<em>หมด</em>' : ''}${n ? `<b class="gui-count">${n}</b>` : ''}</span>
          <span class="gui-pbody"><strong>${esc(m.name)}</strong>${m.description ? `<small>${esc(m.description)}</small>` : ''}<span class="gui-prow"><b>${baht(m.price)}</b><span class="gui-plus">${icon('plus')}</span></span></span></button>`;
      }).join('')}</div>` : empty(menu().length ? 'ไม่พบเมนู' : 'กำลังโหลดเมนู…', menu().length ? 'ลองค้นด้วยคำอื่น' : 'รอสักครู่')}`;
  };

  /* ----------------------------------------------------------- the pager
     A café takes the order at the counter and the guest sits where they like,
     so this phone is the pager. When the kitchen marks the drink ready it has
     to reach someone who has already put the phone away: a chime loud enough
     for a noisy room, a buzz, the system's own notification, and a card that
     stays up until it is tapped. */
  const alerted = new Set();
  let watching = false;      // the first look only learns; it never announces
  let audio = null;
  const openAudio = () => {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!audio && Ctx) { try { audio = new Ctx(); } catch (_) { return null; } }
    if (audio && audio.state === 'suspended') audio.resume().catch(() => {});
    return audio;
  };
  const chime = () => {
    const ctx = openAudio();
    if (!ctx) return;
    // Two notes, three times: one short beep is lost in a busy shop.
    [0, 0.5, 1].forEach((at) => [880, 1320].forEach((hz, step) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const from = ctx.currentTime + at + step * 0.18;
      osc.frequency.value = hz;
      gain.gain.setValueAtTime(0.0001, from);
      gain.gain.exponentialRampToValueAtTime(0.35, from + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, from + 0.16);
      osc.connect(gain).connect(ctx.destination);
      osc.start(from);
      osc.stop(from + 0.2);
    }));
  };
  const billOf = (order) => (window.shortOrderNo ? window.shortOrderNo(order.orderId) : order.orderId);
  /* The counter calls the queue number, not the bill number. */
  const calledAs = (order) => (order.queueNo ? `คิวที่ ${order.queueNo}` : `บิล ${billOf(order)}`);
  const announce = (order) => {
    chime();
    try { navigator.vibrate?.([400, 180, 400, 180, 600]); } catch (_) { /* a phone that cannot buzz still chimes */ }
    if (window.Notification && Notification.permission === 'granted') {
      try {
        new Notification('อาหารพร้อมแล้ว', {
          body: `${calledAs(order)} · รับได้ที่เคาน์เตอร์`,
          icon: '/assets/brand-icon.webp', tag: String(order.orderId), renotify: true});
      } catch (_) { /* notifications are a nicety, the card is the promise */ }
    }
    const card = slot('ready');
    card.innerHTML = `<div class="gui-ready-card">${icon('bell')}
      <strong>อาหารพร้อมแล้ว</strong>
      <small>${esc(calledAs(order))} · รับได้ที่เคาน์เตอร์</small>
      <button type="button" data-act="seen">รับทราบ</button></div>`;
    card.hidden = false;
  };
  /* Only this table's orders, and only the step into "ready". An order that
     goes back to cooking can announce itself again later. */
  const watchReady = () => {
    for (const order of pos().orders.filter((o) => String(o.table) === table())) {
      const key = String(order.orderId);
      if (order.status === 'ready') {
        if (!alerted.has(key)) { alerted.add(key); if (watching) announce(order); }
      } else alerted.delete(key);
    }
    watching = true;
  };

  // ---------------------------------------------------------------- orders
  const STAGE = {pending: 0, cooking: 1, ready: 2};
  const ordersView = () => {
    const mine = pos().orders.filter((o) => String(o.table) === table());
    const total = typeof getTableGrandTotalWithTax === 'function' ? getTableGrandTotalWithTax(table()).grand : 0;
    const pp = pos().promptPayId;
    const askable = mine.length && window.Notification && Notification.permission === 'default';
    return `<h1 class="gui-h1">ออเดอร์ของฉัน</h1>
      ${askable ? `<button type="button" class="gui-notify" data-act="notify">${icon('bell')}<span><strong>เตือนฉันเมื่ออาหารพร้อม</strong><small>เปิดไว้แล้วเดินไปนั่งตรงไหนก็ได้</small></span></button>` : ''}
      ${mine.length ? `<div class="gui-orders">${mine.map((o) => {
        const stage = STAGE[o.status] ?? 0;
        return `<article class="gui-card">
          <div class="gui-ohead">${o.queueNo ? `<b class="gui-queue">คิว ${o.queueNo}</b>` : ''}<strong>${esc(billOf(o))}</strong><span>${esc(o.time || '')}</span></div>
          <ul class="gui-items">${(o.items || []).map((i) => `<li><span>${esc(i.name)}${i.options ? `<small>${esc(i.options)}</small>` : ''}</span><b>×${Number(i.qty) || 1}</b></li>`).join('')}</ul>
          <div class="gui-steps" data-stage="${stage}">${['ส่งแล้ว', 'กำลังทำ', 'กำลังมาเสิร์ฟ'].map((l, i) => `<span class="${i < stage ? 'done' : i === stage ? 'now' : ''}"><i></i>${l}</span>`).join('')}</div>
        </article>`;
      }).join('')}</div>
      <section class="gui-card gui-bill"><div class="gui-sum"><span>ยอดรวมโต๊ะ ${esc(table())}</span><strong>${baht(total)}</strong></div>
        <div class="gui-actions">
          <button type="button" class="gui-btn" data-act="call" data-value="ขอเช็คบิล">${icon('receipt', 'gui-i-xs')} ขอเช็คบิล</button>
          ${pp ? `<button type="button" class="gui-btn primary" data-act="pay">${icon('qr', 'gui-i-xs')} จ่ายด้วยพร้อมเพย์</button>` : ''}
        </div>
        <small class="gui-hint">พนักงานจะยืนยันการชำระเงินที่เคาน์เตอร์</small></section>`
      : empty('ยังไม่ได้สั่งอาหาร', 'เลือกเมนูในแท็บ เมนู แล้วกดส่งออเดอร์')}
      <div class="gui-quick">
        <button type="button" class="gui-btn" data-act="call" data-value="เรียกพนักงานที่โต๊ะ">${icon('bell', 'gui-i-xs')} เรียกพนักงาน</button>
        <button type="button" class="gui-btn" data-act="call" data-value="ขอน้ำเปล่า/น้ำแข็ง">${icon('water', 'gui-i-xs')} ขอน้ำ/น้ำแข็ง</button>
      </div>`;
  };

  // --------------------------------------------------------------- account
  const accountView = () => {
    const member = auth().member;
    return `<h1 class="gui-h1">บัญชี</h1>
      <section class="gui-card gui-member">
        <img src="/assets/mascot-pos.webp" alt="" class="gui-mascot">
        ${member ? `<div><strong>${esc(member.display_name || 'สมาชิก')}</strong>
          <span class="gui-points">${icon('star', 'gui-i-xs')} ${Number(member.points || 0).toLocaleString('th-TH')} แต้ม</span>
          <small>ยอดสะสมจากการสั่งอาหารที่ร้านนี้</small></div>`
        : `<div><strong>สมัครสมาชิกฟรี</strong><small>สะสมแต้มทุกครั้งที่สั่ง ใช้เป็นส่วนลดครั้งต่อไป</small></div>`}
      </section>
      <div class="gui-menu">
        <button type="button" class="gui-row" data-act="member">${icon('star')}<span class="gui-grow"><strong>${member ? 'บัตรสมาชิกของฉัน' : 'สมัครสมาชิก / เข้าสู่ระบบ'}</strong><small>LINE · Google · เบอร์โทร</small></span>${icon('right', 'gui-i-xs')}</button>
        <a class="gui-row" href="/delete-account">${icon('trash')}<span class="gui-grow"><strong>ขอลบบัญชีและข้อมูล</strong><small>ส่งคำขอให้ลบบัญชีสมาชิกของคุณ</small></span>${icon('right', 'gui-i-xs')}</a>
        <button type="button" class="gui-row" data-act="tab" data-value="orders">${icon('receipt')}<span class="gui-grow"><strong>บิลของโต๊ะ ${esc(table())}</strong><small>ดูรายการที่สั่งและยอดรวม</small></span>${icon('right', 'gui-i-xs')}</button>
      </div>
      <p class="gui-foot">ร้านนี้ใช้ระบบ POS WAI · ข้อมูลของคุณใช้เพื่อสะสมแต้มเท่านั้น</p>`;
  };

  // ----------------------------------------------------------------- sheet
  const openSheet = (html) => {
    slot('sheet').innerHTML = `<div class="gui-grabber"></div>${html}`;
    slot('sheet').hidden = false;
    slot('scrim').hidden = false;
    document.documentElement.classList.add('gui-sheet-open');
  };
  const closeSheet = () => {
    slot('sheet').hidden = true;
    slot('scrim').hidden = true;
    document.documentElement.classList.remove('gui-sheet-open');
  };
  const cartSheet = () => {
    const lines = pos().cart;
    openSheet(`<div class="gui-sheet-head"><h2>ตะกร้า · โต๊ะ ${esc(table())}</h2><button type="button" class="gui-x" data-act="close" aria-label="ปิด">${icon('close')}</button></div>
      ${lines.length ? `<div class="gui-lines">${lines.map((l, i) => {
        const extra = [l.chosenLevel, ...(l.chosenAddons || []).map((a) => a.name || a)].filter(Boolean).join(' · ');
        return `<div class="gui-line"><span class="gui-grow"><b>${esc(l.name)}</b><small>${esc(extra)}${extra ? ' · ' : ''}${baht(l.price)}</small></span>
          <span class="gui-qty"><button type="button" data-act="qty" data-index="${i}" data-value="-1" aria-label="ลดจำนวน">${icon(l.qty > 1 ? 'minus' : 'trash')}</button><b>${l.qty}</b><button type="button" data-act="qty" data-index="${i}" data-value="1" aria-label="เพิ่มจำนวน">${icon('plus')}</button></span></div>`;
      }).join('')}</div>
      <label class="gui-field">ถึงครัว (ไม่บังคับ)<input type="text" data-act="note" maxlength="200" placeholder="เช่น ไม่ใส่ผัก" value="${esc(document.getElementById('orderNoteInput')?.value || '')}"></label>
      <div class="gui-sum"><span>ยอดรวม</span><strong>${baht(cartTotal())}</strong></div>
      <button type="button" class="gui-btn primary wide" data-act="send">ส่งออเดอร์ ${icon('arrow', 'gui-i-xs')}</button>`
      : empty('ตะกร้าว่าง', 'แตะเมนูเพื่อเพิ่มรายการ')}`);
  };
  const paySheet = () => {
    const total = getTableGrandTotalWithTax(table()).grand;
    openSheet(`<div class="gui-sheet-head"><h2>จ่ายด้วยพร้อมเพย์</h2><button type="button" class="gui-x" data-act="close" aria-label="ปิด">${icon('close')}</button></div>
      <div class="gui-qr"><canvas id="guiPayQr" width="236" height="236" aria-label="QR พร้อมเพย์"></canvas>
      <strong>${baht(total)}</strong><small>สแกนด้วยแอปธนาคาร แล้วแจ้งพนักงานว่าโอนแล้ว</small></div>
      <button type="button" class="gui-btn primary wide" data-act="call" data-value="โอนพร้อมเพย์แล้ว รอตรวจเงินเข้า">${icon('bell', 'gui-i-xs')} แจ้งพนักงานว่าโอนแล้ว</button>`);
    try { drawQrCodeOnCanvas('guiPayQr', generatePromptPayPayload(pos().promptPayId, total)); }
    catch (error) { toast(error.message); }
  };

  // ----------------------------------------------------------------- paint
  const paint = () => {
    const shop = auth().shop || {};
    slot('shop').textContent = shop.name || 'ร้านอาหาร';
    slot('table').textContent = `โต๊ะ ${table()}`;
    slot('nav').innerHTML = TABS.map(([id, label, ic]) => `<button type="button" data-act="tab" data-value="${id}" class="${ui.tab === id ? 'on' : ''}" ${ui.tab === id ? 'aria-current="page"' : ''}>${icon(ic)}<span>${label}</span></button>`).join('');
    const main = slot('main');
    const focused = document.activeElement?.dataset?.act === 'query';
    main.innerHTML = ({menu: menuView, orders: ordersView, account: accountView}[ui.tab] || menuView)();
    if (focused) { const input = main.querySelector('[data-act="query"]'); input?.focus(); input?.setSelectionRange(input.value.length, input.value.length); }
    const bar = slot('cartbar');
    const count = cartCount();
    bar.hidden = ui.tab !== 'menu' || !count;
    root.classList.toggle('gui-has-cart', !bar.hidden);
    if (!bar.hidden) {
      bar.innerHTML = `<button type="button" class="gui-cartbar-in" data-act="cart">${icon('bag')}<span class="gui-grow"><b>${count} รายการ</b><small>${esc([...new Set(pos().cart.map((i) => i.name))].join(', '))}</small></span><strong>${baht(cartTotal())}</strong><span class="gui-btn primary sm">ดูตะกร้า ${icon('right', 'gui-i-xs')}</span></button>`;
    }
  };

  const go = (tab) => { ui.tab = tab; remember(); window.scrollTo(0, 0); paint(); };

  const pressed = async (el) => {
    const {act, value} = el.dataset;
    switch (act) {
      case 'tab': closeSheet(); go(value); break;
      case 'category': ui.category = value; paint(); break;
      case 'add':
        onClickMenuCard(Number(value));
        mergeCart();
        paint();
        break;
      case 'cart': cartSheet(); break;
      case 'close': closeSheet(); break;
      case 'qty': {
        const line = pos().cart[Number(el.dataset.index)];
        if (!line) break;
        line.qty += Number(value);
        if (line.qty <= 0) pos().cart.splice(Number(el.dataset.index), 1);
        if (typeof renderCart === 'function') renderCart();
        paint();
        if (pos().cart.length) cartSheet(); else closeSheet();
        break;
      }
      case 'send': {
        const note = document.getElementById('orderNoteInput');
        if (note) note.value = root.querySelector('[data-act="note"]')?.value.trim() || '';
        el.disabled = true;
        el.textContent = 'กำลังส่ง…';
        try { await submitOrderFromCustomer(); } finally { el.disabled = false; }
        if (!pos().cart.length) { closeSheet(); go('orders'); }
        else cartSheet();
        break;
      }
      case 'call': await window.sendTableServiceCall?.(value); closeSheet(); break;
      case 'pay': paySheet(); break;
      case 'member': auth().openMember?.(); break;
      case 'notify':
        // Inside the tap, where both the permission box and the sound are allowed.
        openAudio();
        try { await window.Notification?.requestPermission?.(); } catch (_) { /* refused is an answer too */ }
        paint();
        break;
      case 'seen': slot('ready').hidden = true; break;
      default: break;
    }
  };

  const mergeCart = () => {
    const cart = pos().cart;
    const key = (l) => JSON.stringify([l.id, l.courseMode, l.chosenLevel || '', l.chosenAddons || [], l.price]);
    for (let i = cart.length - 1; i > 0; i -= 1) {
      const twin = cart.findIndex((l, j) => j < i && key(l) === key(cart[i]));
      if (twin > -1) { cart[twin].qty += cart[i].qty; cart.splice(i, 1); }
    }
    if (typeof renderCart === 'function') renderCart();
  };

  root.addEventListener('click', (event) => {
    if (event.target === slot('scrim')) { closeSheet(); return; }
    const el = event.target.closest('[data-act]');
    if (!el || el.tagName === 'INPUT' || el.disabled) return;
    pressed(el);
  });
  root.addEventListener('input', (event) => {
    if (event.target.dataset.act === 'query') { ui.query = event.target.value; paint(); }
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !slot('sheet').hidden) closeSheet(); });

  // ---------------------------------------------------------------- wiring
  const isGuest = () => Boolean(auth().tableToken) && !auth().current;
  const sync = () => {
    const on = isGuest();
    document.documentElement.classList.toggle('gui-on', on);
    if (on) paint(); else closeSheet();
  };
  const start = () => {
    document.body.append(root);
    if (typeof window.renderAll === 'function') {
      const original = window.renderAll;
      window.renderAll = function wrapped(...args) {
        const result = original.apply(this, args);
        if (document.documentElement.classList.contains('gui-on')) watchReady();
        if (document.documentElement.classList.contains('gui-on') && slot('sheet').hidden) paint();
        return result;
      };
    }
    const mods = document.getElementById('modifierModalBackdrop');
    if (mods) new MutationObserver(() => { if (!mods.classList.contains('active')) { mergeCart(); paint(); } }).observe(mods, {attributes: true, attributeFilter: ['class']});
    window.addEventListener('poswai:auth-changed', sync);
    /* What the kitchen is doing with the guest's food. It keeps asking while
       the screen is in a pocket and while the guest is still reading the menu:
       that is exactly when the drink becomes ready and the alert has to land. */
    setInterval(() => {
      if (!isGuest()) return;
      Promise.resolve(window.poswaiLiveData?.refresh?.()).catch(() => {}).then(watchReady);
    }, 15000);
    sync();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
