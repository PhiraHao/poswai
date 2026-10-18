/* The app's own five screens: ขาย · ออเดอร์ · สินค้า · ภาพรวม · ร้าน.
 *
 * Drawn to the POS WAI redesign board. Everything shown here is read from what
 * the page already holds — the menu in DEFAULT_MENU, the cart and open bills in
 * `state`, the kitchen tickets live-data fetched — and every action goes
 * through the page's own functions (addToCart, submitOrderFromCustomer,
 * setOrderReady…), so the offline queue, the permissions and the printing keep
 * working exactly as they do on the web. The long back-office forms (staff,
 * members, tables, settings) are not redrawn: the ร้าน screen opens the page's
 * own screen for them under an app bar with a back arrow.
 */
(() => {
  'use strict';
  if (!document.documentElement.classList.contains('poswai-app')) return;

  // ------------------------------------------------------------- helpers
  const PATHS = {
    bag: 'M6 7h12l1.6 13.2a1 1 0 0 1-1 1.1H5.4a1 1 0 0 1-1-1.1L6 7Z M9 9V6a3 3 0 0 1 6 0v3',
    order: 'M7 3h10a1 1 0 0 1 1 1v17l-2.5-1.5L13 21l-2.5-1.5L8 21l-2-1.5V4a1 1 0 0 1 1-1Z M9 8h6 M9 12h6 M9 16h3',
    box: 'm12 2.5 8.5 4.7v9.6L12 21.5l-8.5-4.7V7.2L12 2.5Z M3.5 7.2 12 12l8.5-4.8 M12 12v9.5',
    chart: 'M4 20V13 M10 20V5 M16 20V10 M3 20.5h18',
    shop: 'M4 10v10h16V10 M3 10l1.5-6h15L21 10 M3 10a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0 M10 20v-5h4v5',
    search: 'M20 20l-4.2-4.2 M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
    scan: 'M4 8V5a1 1 0 0 1 1-1h3 M16 4h3a1 1 0 0 1 1 1v3 M20 16v3a1 1 0 0 1-1 1h-3 M8 20H5a1 1 0 0 1-1-1v-3 M8 9v6 M11 9v6 M14 9v6 M17 9v6',
    plus: 'M12 5v14 M5 12h14',
    minus: 'M5 12h14',
    right: 'M9 5l7 7-7 7',
    down: 'm6 9 6 6 6-6',
    back: 'M15 5l-7 7 7 7',
    close: 'M6 6l12 12 M18 6 6 18',
    bell: 'M6 16.5h12l-1.5-2.5V10a4.5 4.5 0 0 0-9 0v4L6 16.5Z M10 19.5a2 2 0 0 0 4 0',
    table: 'M3 7h18 M5 7v12 M19 7v12 M3 7l2-3h14l2 3 M5 12h14',
    fork: 'M7 3v6a2 2 0 0 0 2 2v10 M11 3v6a2 2 0 0 1-2 2 M9 3v5 M17 21V3c-2.5 1.5-3 5-3 8h3',
    clock: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 7v5l3 2',
    dots: 'M12 6h.01 M12 12h.01 M12 18h.01',
    calendar: 'M4 6h16v14H4z M8 3v5 M16 3v5 M4 10h16',
    coins: 'M4 7c0-1.7 2.7-3 6-3s6 1.3 6 3-2.7 3-6 3-6-1.3-6-3Z M4 7v4c0 1.7 2.7 3 6 3 M4 11v4c0 1.7 2.7 3 6 3 M14 13c0-1.7 2.7-3 6-3 M20 10v8 M14 13v5c0 1.1 2.7 2 6 2',
    receipt: 'M6 3h12v18l-2-1.4-2 1.4-2-1.4-2 1.4-2-1.4L6 21V3Z M9 8h6 M9 12h6 M9 16h3',
    users: 'M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20 M13.5 8a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0 M20 20v-1.5a3.5 3.5 0 0 0-2.5-3.4 M15.5 4.6a3.5 3.5 0 0 1 0 6.8',
    user: 'M19 20v-1.5a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4V20 M16 7.5a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
    badge: 'M12 3l2.4 1.7 2.9-.2.9 2.8 2.4 1.7-.9 2.8.9 2.8-2.4 1.7-.9 2.8-2.9-.2L12 21l-2.4-1.7-2.9.2-.9-2.8-2.4-1.7.9-2.8-.9-2.8 2.4-1.7.9-2.8 2.9.2L12 3Z M9 12l2 2 4-4',
    grid: 'M4 4h16v16H4z M4 10h16 M10 10v10',
    printer: 'M7 8V3h10v5 M7 17H4V9h16v8h-3 M7 14h10v7H7z',
    gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z',
    edit: 'M4 20h4L19 9l-4-4L4 16v4Z M13.5 6.5l4 4',
    alert: 'M12 3.5 21.5 20h-19L12 3.5Z M12 10v4.5 M12 17.2h.01',
    arrow: 'M5 12h14 M13 6l6 6-6 6',
    bike: 'M5.5 18.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z M18.5 18.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z M5.5 15.5h5l3-6h3l2 6 M10 9.5h4',
    check: 'm5 12.5 4.5 4.5L19 7.5',
    refresh: 'M20 11a8 8 0 1 0-2.3 5.7 M20 4v7h-7',
    trash: 'M4 7h16 M10 11v6 M14 11v6 M6 7l1 13h10l1-13 M9 7V4h6v3',
  };
  const icon = (name, cls = '') => `<svg class="aui-i ${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${PATHS[name] || PATHS.order}"/></svg>`;
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const baht = (value) => `฿${Number(value || 0).toLocaleString('th-TH', {maximumFractionDigits: 2})}`;
  const auth = () => window.poswaiAuth || {};
  const can = (tab) => (auth().canAccessTab ? auth().canAccessTab(tab) : true);
  const branch = () => auth().branchId || 1;
  const menu = () => (typeof DEFAULT_MENU !== 'undefined' ? DEFAULT_MENU : []);
  const pos = () => (typeof state !== 'undefined' ? state : {cart: [], orders: [], tablesList: [], inventory: []});
  const asset = (name) => `assets/${name}`;
  const toast = (text) => (window.showToast ? window.showToast(text) : null);
  const api = async (path, options = {}) => {
    const reply = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
    const data = await reply.json().catch(() => ({}));
    if (!reply.ok) throw new Error(data.detail || `HTTP ${reply.status}`);
    return data;
  };
  /** A server time ("2026-10-18 12:04:00", UTC) as a Date. */
  const serverDate = (text) => (text ? new Date(String(text).replace(' ', 'T').replace(/Z?$/, 'Z')) : null);

  // --------------------------------------------------------------- state
  const TABS = [
    {id: 'sell', label: 'ขาย', icon: 'bag', allowed: () => can('customer')},
    {id: 'orders', label: 'ออเดอร์', icon: 'order', allowed: () => can('kitchen') || can('cashier')},
    {id: 'goods', label: 'สินค้า', icon: 'box', allowed: () => can('inventory')},
    {id: 'overview', label: 'ภาพรวม', icon: 'chart', allowed: () => can('analytics')},
    {id: 'shop', label: 'ร้าน', icon: 'shop', allowed: () => true},
  ];
  const ui = {
    tab: 'sell', category: 'ทั้งหมด', query: '', mode: 'ทานที่ร้าน',
    orderStatus: 'cooking', channel: 'store', goodsPane: 'menu', goodsQuery: '',
    online: [], settled: [], report: null, reportError: '', reportAt: 0,
  };
  try { Object.assign(ui, JSON.parse(sessionStorage.getItem('aui') || '{}')); } catch (_) { /* fresh */ }
  const remember = () => {
    try { sessionStorage.setItem('aui', JSON.stringify({tab: ui.tab, goodsPane: ui.goodsPane, orderStatus: ui.orderStatus, channel: ui.channel})); } catch (_) { /* fine */ }
  };

  // ---------------------------------------------------------------- frame
  const root = document.createElement('div');
  root.id = 'appUi';
  root.innerHTML = `
    <header class="aui-top">
      <button type="button" class="aui-brand" data-act="account" aria-label="บัญชีและร้าน">
        <img src="${asset('brand-icon.webp')}" alt="POS WAI" class="aui-logo">
        <span class="aui-shopname"><small><span data-slot="branch"></span>${icon('down', 'aui-i-xs')}</small></span>
      </button>
      <div class="aui-top-actions">
        <button type="button" class="aui-iconbtn" data-act="bell" aria-label="การแจ้งเตือน">${icon('bell')}<i data-slot="bell" hidden></i></button>
        <button type="button" class="aui-avatar" data-act="account" aria-label="บัญชีของฉัน" data-slot="avatar"></button>
      </div>
    </header>
    <main class="aui-main" data-slot="main"></main>
    <div class="aui-cartbar" data-slot="cartbar" hidden></div>
    <nav class="aui-nav" aria-label="เมนูหลัก" data-slot="nav"></nav>
    <div class="aui-subbar" data-slot="subbar">
      <button type="button" class="aui-iconbtn" data-act="back" aria-label="กลับ">${icon('back')}</button>
      <strong data-slot="subtitle"></strong>
    </div>
    <div class="aui-sheet-scrim" data-slot="scrim" hidden></div>
    <section class="aui-sheet" data-slot="sheet" role="dialog" aria-modal="true" hidden></section>`;
  const slot = (name) => root.querySelector(`[data-slot="${name}"]`);

  // ------------------------------------------------------------- header
  const paintHeader = () => {
    const shop = auth().shop || {};
    const name = String(pos().branch || '').replace(/^สาขา\s*\d+:\s*/, '').replace(/\s*\((.+)\)\s*$/, ' · $1');
    slot('branch').textContent = shop.name || name || 'ร้านของฉัน';
    const person = auth().current;
    const label = person?.name || '';
    const letters = [...label.trim()];
    const first = /^[เแโใไ]$/u.test(letters[0] || '') && letters[1] ? letters[1] : letters[0] || '';
    slot('avatar').textContent = first.toUpperCase();
    slot('avatar').setAttribute('aria-label', label ? `บัญชี ${label}` : 'บัญชีของฉัน');
    const waiting = (window.poswaiKdsTickets || []).filter((t) => t.status !== 'ready').length;
    const bell = slot('bell');
    bell.hidden = !waiting;
    bell.textContent = waiting > 9 ? '9+' : String(waiting);
  };

  const paintNav = () => {
    const open = TABS.filter((t) => t.allowed());
    if (!open.some((t) => t.id === ui.tab)) ui.tab = open[0]?.id || 'shop';
    slot('nav').innerHTML = open.map((t) => `<button type="button" data-act="tab" data-value="${t.id}" class="${t.id === ui.tab ? 'on' : ''}" ${t.id === ui.tab ? 'aria-current="page"' : ''}>${icon(t.icon)}<span>${t.label}</span></button>`).join('');
  };

  // ============================================================ ขาย
  const categories = () => {
    const seen = [];
    for (const m of menu()) if (m.category && m.category !== 'ทั้งหมด' && !seen.includes(m.category)) seen.push(m.category);
    return ['ทั้งหมด', ...seen];
  };
  const cartCount = () => pos().cart.reduce((n, i) => n + i.qty, 0);
  const cartTotal = () => {
    const sub = pos().cart.reduce((s, i) => s + i.price * i.qty, 0);
    const off = typeof getCartDiscount === 'function' ? getCartDiscount(sub) : 0;
    return Math.max(0, sub - off);
  };
  /** The same dish with the same choices is one line with a count, not two. */
  const mergeCart = () => {
    const cart = pos().cart;
    const key = (l) => JSON.stringify([l.id, l.courseMode, l.chosenLevel || '', l.chosenAddons || [], l.price]);
    for (let i = cart.length - 1; i > 0; i -= 1) {
      const twin = cart.findIndex((l, j) => j < i && key(l) === key(cart[i]));
      if (twin > -1) { cart[twin].qty += cart[i].qty; cart.splice(i, 1); }
    }
    if (typeof renderCart === 'function') renderCart();
  };
  const photo = (m) => m?.photo || asset('menu-placeholder.svg');

  const sellView = () => {
    const tables = pos().tablesList || [];
    const current = String(pos().customerTable || tables[0]?.no || '1');
    const q = ui.query.trim().toLowerCase();
    const list = menu().filter((m) => m.active !== false)
      .filter((m) => ui.category === 'ทั้งหมด' || m.category === ui.category)
      .filter((m) => !q || m.name.toLowerCase().includes(q) || String(m.barcode || '').toLowerCase().includes(q));
    const inCart = (m) => pos().cart.filter((i) => i.id === m.id).reduce((n, i) => n + i.qty, 0);
    return `
      <h1 class="aui-h1">ขาย</h1>
      <div class="aui-context">
        <label class="aui-select">${icon('table')}
          <select data-act="table" aria-label="เลือกโต๊ะ">${tables.map((t) => `<option value="${esc(t.no)}" ${String(t.no) === current ? 'selected' : ''}>โต๊ะ ${esc(t.no)}</option>`).join('') || `<option>โต๊ะ ${esc(current)}</option>`}</select>${icon('down', 'aui-i-xs')}</label>
        <label class="aui-select">${icon('fork')}
          <select data-act="mode" aria-label="วิธีรับอาหาร">${['ทานที่ร้าน', 'กลับบ้าน'].map((m) => `<option ${m === ui.mode ? 'selected' : ''}>${m}</option>`).join('')}</select>${icon('down', 'aui-i-xs')}</label>
      </div>
      <div class="aui-searchrow">
        <label class="aui-search">${icon('search')}<input type="search" data-act="query" value="${esc(ui.query)}" placeholder="ค้นหาเมนู เช่น กะเพรา, ผัดไทย..." aria-label="ค้นหาเมนู" enterkeyhint="search"></label>
        <button type="button" class="aui-square" data-act="scan" aria-label="ยิงบาร์โค้ด">${icon('scan')}</button>
      </div>
      <div class="aui-chips" role="tablist">${categories().map((c) => `<button type="button" role="tab" data-act="category" data-value="${esc(c)}" class="${c === ui.category ? 'on' : ''}" aria-selected="${c === ui.category}">${esc(c)}</button>`).join('')}</div>
      ${list.length ? `<div class="aui-products">${list.map((m) => {
        const out = m.soldOut || (typeof m.quota === 'number' && m.quota <= 0);
        const n = inCart(m);
        return `<button type="button" class="aui-product ${out ? 'out' : ''}" data-act="add" data-value="${m.id}" ${out ? 'disabled' : ''} aria-label="${esc(m.name)} ${baht(m.price)}">
          <span class="aui-shot"><img src="${esc(photo(m))}" alt="" loading="lazy" onerror="this.onerror=null;this.src='${asset('menu-placeholder.svg')}'">${out ? '<em>หมด</em>' : ''}${n ? `<b class="aui-count">${n}</b>` : ''}</span>
          <span class="aui-pbody"><strong>${esc(m.name)}</strong><span class="aui-prow"><b>${baht(m.price)}</b><span class="aui-plus">${icon('plus')}</span></span></span>
        </button>`;
      }).join('')}</div>` : empty(menu().length ? 'ไม่พบเมนู' : 'ยังไม่มีเมนู', menu().length ? 'ลองค้นด้วยคำอื่น' : 'เพิ่มเมนูได้ที่แท็บสินค้า')}`;
  };

  const paintCartbar = () => {
    const bar = slot('cartbar');
    const count = cartCount();
    bar.hidden = ui.tab !== 'sell' || !count || document.documentElement.classList.contains('aui-sub');
    root.classList.toggle('aui-has-cart', !bar.hidden);
    if (bar.hidden) return;
    const names = [...new Set(pos().cart.map((i) => i.name))].join(', ');
    bar.innerHTML = `<button type="button" class="aui-cartbar-in" data-act="cart">
      ${icon('bag', 'aui-cart-ic')}<span class="aui-grow"><b>${count} รายการ</b><small>${esc(names)}</small></span>
      <strong>${baht(cartTotal())}</strong><span class="aui-btn primary sm">ดูตะกร้า ${icon('right', 'aui-i-xs')}</span></button>`;
  };

  const cartSheet = () => {
    const lines = pos().cart;
    const table = pos().customerTable;
    openSheet(`
      <div class="aui-sheet-head"><h2>ตะกร้า · โต๊ะ ${esc(table)}</h2><button type="button" class="aui-iconbtn" data-act="close" aria-label="ปิด">${icon('close')}</button></div>
      ${lines.length ? `<div class="aui-lines">${lines.map((line, index) => {
        const m = menu().find((x) => x.id === line.id);
        const extra = [line.chosenLevel, ...(line.chosenAddons || []).map((a) => a.name || a)].filter(Boolean).join(' · ');
        return `<div class="aui-line"><img src="${esc(photo(m))}" alt="" onerror="this.onerror=null;this.src='${asset('menu-placeholder.svg')}'">
          <span class="aui-grow"><b>${esc(line.name)}</b><small>${esc(extra || (line.courseMode === 'HOLD' ? 'พักไว้ก่อน' : 'ทำทันที'))} · ${baht(line.price)}</small></span>
          <span class="aui-qty"><button type="button" data-act="qty" data-index="${index}" data-value="-1" aria-label="ลดจำนวน">${icon(line.qty > 1 ? 'minus' : 'trash')}</button><b>${line.qty}</b><button type="button" data-act="qty" data-index="${index}" data-value="1" aria-label="เพิ่มจำนวน">${icon('plus')}</button></span></div>`;
      }).join('')}</div>
      <label class="aui-field">หมายเหตุถึงครัว<input type="text" data-act="note" maxlength="200" placeholder="เช่น ไม่ใส่ผัก, เผ็ดน้อย" value="${esc(document.getElementById('orderNoteInput')?.value || '')}"></label>
      <div class="aui-sum"><span>ยอดรวม · ${ui.mode}</span><strong>${baht(cartTotal())}</strong></div>
      <div class="aui-sheet-actions"><button type="button" class="aui-btn" data-act="clear">ล้างตะกร้า</button>
        <button type="button" class="aui-btn primary grow" data-act="send">ส่งเข้าครัว ${icon('arrow', 'aui-i-xs')}</button></div>`
      : empty('ตะกร้าว่าง', 'แตะเมนูเพื่อเพิ่มรายการ')}`);
  };

  // ======================================================== ออเดอร์
  /** Open bills, each with what the kitchen says about it. */
  const tickets = () => {
    const byOrder = new Map();
    for (const t of window.poswaiKdsTickets || []) {
      if (!byOrder.has(t.order_no)) byOrder.set(t.order_no, []);
      byOrder.get(t.order_no).push(t);
    }
    return pos().orders.map((order) => {
      const own = byOrder.get(order.orderId) || [];
      const ready = own.length && own.every((t) => t.status === 'ready');
      const created = own.map((t) => serverDate(t.created_at)).filter(Boolean).sort((a, b) => a - b)[0];
      return {order, tickets: own, ready, created, held: own.some((t) => t.status === 'held')};
    });
  };
  const minutesSince = (date) => (date ? Math.max(0, Math.round((Date.now() - date.getTime()) / 60000)) : null);

  const ordersView = () => {
    const all = tickets();
    const cooking = all.filter((x) => !x.ready);
    const ready = all.filter((x) => x.ready);
    const online = ui.online || [];
    const status = ui.orderStatus;
    const seg = [['cooking', 'กำลังทำ', cooking.length], ['ready', 'พร้อมเสิร์ฟ', ready.length], ['done', 'เสร็จแล้ว', null]];
    const store = status === 'cooking' ? cooking : status === 'ready' ? ready : [];
    const onlineShown = online.filter((o) => (status === 'cooking' ? ['new', 'accepted', 'preparing'].includes(o.status)
      : status === 'ready' ? o.status === 'ready' : ['handed_off', 'cancelled'].includes(o.status)));
    const channels = `<div class="aui-seg outline">
      <button type="button" data-act="channel" data-value="store" class="${ui.channel === 'store' ? 'on' : ''}">หน้าร้าน ${status === 'done' ? '' : `<i>${store.length}</i>`}</button>
      <button type="button" data-act="channel" data-value="online" class="${ui.channel === 'online' ? 'on' : ''}">ออนไลน์ <i>${onlineShown.length}</i></button></div>`;
    let body = '';
    if (ui.channel === 'online') {
      body = onlineShown.length ? onlineShown.map(onlineCard).join('') : empty('ยังไม่มีออเดอร์ออนไลน์', 'ออเดอร์จาก Grab, LINE MAN และอื่นๆ จะแสดงที่นี่');
    } else if (status === 'done') {
      body = ui.settled.length ? `<div class="aui-list">${ui.settled.map((o) => `<div class="aui-row">
        <span class="aui-rowic">${icon('receipt')}</span><span class="aui-grow"><strong>โต๊ะ ${esc(o.table_no)} · ${esc(window.shortOrderNo ? window.shortOrderNo(o.order_no) : o.order_no)}</strong>
        <small>${esc(o.payment_method || '')}${o.closed_at ? ` · ${serverDate(o.closed_at).toLocaleTimeString('th-TH', {hour: '2-digit', minute: '2-digit'})}` : ''}${o.status === 'refunded' ? ' · คืนเงินแล้ว' : o.status === 'void' ? ' · ยกเลิก' : ''}</small></span>
        <b>${baht(o.net_amount)}</b></div>`).join('')}</div>` : empty('ยังไม่มีบิลที่ปิดแล้ว', 'บิลที่รับเงินแล้ววันนี้จะอยู่ที่นี่');
    } else {
      body = store.length ? store.map(storeCard).join('') : empty(status === 'cooking' ? 'ไม่มีออเดอร์ค้าง' : 'ยังไม่มีจานรอเสิร์ฟ', 'ส่งออเดอร์จากแท็บขาย แล้วจะเข้าคิวที่นี่');
    }
    return `<h1 class="aui-h1">ออเดอร์</h1>
      <div class="aui-seg amber">${seg.map(([id, label, n]) => `<button type="button" data-act="ostatus" data-value="${id}" class="${status === id ? 'on' : ''}">${label}${n === null ? '' : ` <i>${n}</i>`}</button>`).join('')}</div>
      ${channels}<div class="aui-orders">${body}</div>`;
  };

  const steps = (stage) => `<div class="aui-steps" data-stage="${stage}">
    ${['รับออเดอร์', 'กำลังทำ', 'พร้อมเสิร์ฟ'].map((label, i) => `<span class="${i < stage ? 'done' : i === stage ? 'now' : ''}"><i></i>${label}</span>`).join('')}</div>`;

  const storeCard = ({order, ready, created, held}) => {
    const mins = minutesSince(created);
    const lines = new Map();
    for (const item of order.items || []) lines.set(item.name, (lines.get(item.name) || 0) + Number(item.qty || item.quantity || 1));
    const action = ready
      ? (can('cashier') ? `<button type="button" class="aui-btn primary grow" data-act="pay" data-value="${esc(order.table)}">รับเงินโต๊ะนี้ ${icon('arrow', 'aui-i-xs')}</button>` : '')
      : held ? `<button type="button" class="aui-btn grow" data-act="fire" data-value="${esc(order.orderId)}">เริ่มทำคอร์สที่พักไว้</button>`
        : can('kitchen') ? `<button type="button" class="aui-btn primary grow" data-act="ready" data-value="${esc(order.orderId)}">ทำเสร็จแล้ว ${icon('arrow', 'aui-i-xs')}</button>` : '';
    return `<article class="aui-card aui-order">
      <div class="aui-order-head">${icon('table')}<strong>โต๊ะ ${esc(order.table)}</strong><span class="aui-tag">${esc(order.mode || 'ทานที่ร้าน')}</span>
        ${mins === null ? '<span class="aui-time grey">รอส่ง</span>' : `<span class="aui-time ${mins >= 10 ? 'late' : ''}">${icon('clock')}${mins} นาที</span>`}
        <button type="button" class="aui-iconbtn bare" data-act="ordermenu" data-value="${esc(order.orderId)}" aria-label="ตัวเลือกออเดอร์">${icon('dots')}</button></div>
      <ul class="aui-items">${[...lines].map(([name, qty]) => `<li><span>${esc(name)}</span><b>${qty}</b></li>`).join('')}</ul>
      ${steps(ready ? 2 : 1)}
      ${action ? `<div class="aui-order-foot">${action}</div>` : ''}
    </article>`;
  };

  const ONLINE_NEXT = {new: ['accepted', 'รับออเดอร์'], accepted: ['preparing', 'เริ่มทำ'], preparing: ['ready', 'ทำเสร็จแล้ว'], ready: ['handed_off', 'ส่งมอบแล้ว']};
  const onlineCard = (o) => {
    const stage = ['new'].includes(o.status) ? 0 : ['accepted', 'preparing'].includes(o.status) ? 1 : 2;
    const mins = minutesSince(serverDate(o.created_at));
    const next = ONLINE_NEXT[o.status];
    return `<article class="aui-card aui-order">
      <div class="aui-order-head">${icon('bike', 'green')}<strong>${esc(o.channel || 'ออนไลน์')} ${esc(window.shortOrderNo ? window.shortOrderNo(o.order_no) : o.order_no)}</strong><span class="aui-tag green">ออนไลน์</span>
        ${mins === null ? '' : `<span class="aui-time ${mins >= 15 ? 'late' : ''}">${icon('clock')}${mins} นาที</span>`}</div>
      <ul class="aui-items">${(o.items || []).map((i) => `<li><span>${esc(i.name)}</span><b>${Number(i.qty)}</b></li>`).join('')}</ul>
      ${steps(stage)}
      ${next ? `<div class="aui-order-foot"><button type="button" class="aui-btn primary grow" data-act="online" data-value="${esc(o.order_no)}" data-next="${next[0]}" ${next[0] === 'handed_off' && o.payment_status !== 'paid' ? 'disabled' : ''}>${next[1]} ${icon('arrow', 'aui-i-xs')}</button></div>` : ''}
    </article>`;
  };

  const loadOrdersExtra = async () => {
    if (!auth().current) return;
    const [online, settled] = await Promise.allSettled([
      api(`/api/online/orders?branch_id=${branch()}&status=all`),
      can('cashier') ? api(`/api/orders/settled?branch_id=${branch()}&limit=50`) : Promise.resolve({orders: []}),
    ]);
    if (online.status === 'fulfilled') ui.online = online.value.orders || [];
    if (settled.status === 'fulfilled') {
      const today = new Date().toDateString();
      ui.settled = (settled.value.orders || []).filter((o) => !o.closed_at || serverDate(o.closed_at).toDateString() === today);
    }
    if (ui.tab === 'orders') paint();
  };

  // ========================================================== สินค้า
  const goodsView = () => {
    const items = menu();
    const stock = pos().inventory || [];
    const low = stock.filter((s) => Number(s.stock) <= Number(s.reorder || 0) || Number(s.stock) <= 0);
    const q = ui.goodsQuery.trim().toLowerCase();
    const pane = ui.goodsPane;
    let list = '';
    if (pane === 'menu') {
      const shown = items.filter((m) => !q || m.name.toLowerCase().includes(q));
      list = shown.length ? `<div class="aui-list">${shown.map((m) => `<div class="aui-row aui-goods">
        <img src="${esc(photo(m))}" alt="" loading="lazy" onerror="this.onerror=null;this.src='${asset('menu-placeholder.svg')}'">
        <span class="aui-grow"><strong>${esc(m.name)}</strong><small>${esc(m.category || 'ไม่ระบุหมวด')}</small><b>${baht(m.price)}</b></span>
        <span class="aui-pill ${m.soldOut ? 'red' : 'green'}">${m.soldOut ? 'หมดชั่วคราว' : 'พร้อมขาย'}</span>
        <button type="button" class="aui-iconbtn bare" data-act="goodsmenu" data-value="${m.id}" aria-label="ตัวเลือก ${esc(m.name)}">${icon('dots')}</button></div>`).join('')}</div>`
        : empty(items.length ? 'ไม่พบเมนู' : 'ยังไม่มีเมนู', 'กด "เพิ่ม/แก้ไขเมนู" ด้านล่าง');
    } else if (pane === 'stock') {
      const shown = stock.filter((s) => !q || String(s.name).toLowerCase().includes(q));
      list = shown.length ? `<div class="aui-list">${shown.map((s) => {
        const short = Number(s.stock) <= Number(s.reorder || 0) || Number(s.stock) <= 0;
        return `<div class="aui-row aui-goods"><span class="aui-rowic">${icon('box')}</span>
          <span class="aui-grow"><strong>${esc(s.name)}</strong><small>${esc(s.id)}</small></span>
          <span class="aui-pill ${short ? 'red' : 'green'}">${short ? `ใกล้หมด<br>เหลือ ${Number(s.stock).toLocaleString('th-TH')}` : `เหลือ ${Number(s.stock).toLocaleString('th-TH')} ${esc(s.unit || '')}`}</span></div>`;
      }).join('')}</div>` : empty('ยังไม่ตั้งวัตถุดิบ', 'เพิ่มวัตถุดิบเพื่อให้ระบบตัดสต็อกตามสูตร');
    } else {
      const shown = items.filter((m) => !q || m.name.toLowerCase().includes(q));
      list = shown.length ? `<div class="aui-list">${shown.map((m) => {
        const bom = Array.isArray(m.bom) ? m.bom : [];
        return `<div class="aui-row aui-goods"><img src="${esc(photo(m))}" alt="" loading="lazy" onerror="this.onerror=null;this.src='${asset('menu-placeholder.svg')}'">
          <span class="aui-grow"><strong>${esc(m.name)}</strong><small>${bom.length ? bom.map((b) => `${esc(b.ingId || b.id)} ${esc(b.qty)}`).join(' · ') : 'ยังไม่ตั้งสูตร'}</small></span>
          <span class="aui-pill ${bom.length ? 'green' : 'grey'}">${bom.length ? `${bom.length} วัตถุดิบ` : 'ไม่มีสูตร'}</span></div>`;
      }).join('')}</div>` : empty('ยังไม่มีเมนู', 'เพิ่มเมนูก่อน แล้วค่อยตั้งสูตร');
    }
    return `<h1 class="aui-h1">สินค้า</h1>
      <div class="aui-summary">
        <div>${tile('box')}<span><small>สินค้าทั้งหมด</small><strong>${items.length} <em>รายการ</em></strong></span></div>
        <div>${tile('alert', 'warn')}<span><small>ใกล้หมดสต็อก</small><strong><b class="${low.length ? 'red' : ''}">${low.length}</b> <em>รายการ</em></strong></span></div>
      </div>
      <div class="aui-seg amber">${[['menu', 'เมนู'], ['stock', 'วัตถุดิบ'], ['recipe', 'สูตร']].map(([id, label]) => `<button type="button" data-act="gpane" data-value="${id}" class="${pane === id ? 'on' : ''}">${label}</button>`).join('')}</div>
      <label class="aui-search">${icon('search')}<input type="search" data-act="gquery" value="${esc(ui.goodsQuery)}" placeholder="ค้นหาสินค้า..." aria-label="ค้นหาสินค้า"></label>
      ${list}
      <button type="button" class="aui-btn wide" data-act="web" data-value="inventory">${icon('edit', 'aui-i-xs')} เพิ่ม/แก้ไข${pane === 'stock' ? 'วัตถุดิบ' : pane === 'recipe' ? 'สูตร' : 'เมนู'}</button>`;
  };
  const tile = (name, tone = '') => `<span class="aui-tile ${tone}">${icon(name)}</span>`;

  // ========================================================= ภาพรวม
  const loadReport = async (force = false) => {
    if (!auth().current || !can('analytics')) return;
    if (!force && Date.now() - ui.reportAt < 30000) return;
    ui.reportAt = Date.now();
    try { ui.report = await api(`/api/enterprise/analytics-dashboard?branch_id=${branch()}`); ui.reportError = ''; }
    catch (error) { ui.reportError = error.message; }
    if (ui.tab === 'overview') paint();
  };

  const overviewView = () => {
    const data = ui.report;
    const sales = data?.sales_realtime || {};
    const date = data?.business_date ? new Date(`${data.business_date}T12:00:00`) : new Date();
    const dateText = date.toLocaleDateString('th-TH', {day: 'numeric', month: 'short', year: 'numeric'});
    const avg = data?.food_cost_and_retention?.avg_basket_size_baht;
    const hours = data?.hourly_sales || [];
    const byHour = new Map(hours.map((h) => [Number(h.hour), Number(h.sales) || 0]));
    const span = [];
    for (let h = 8; h <= 22; h += 1) span.push(h);
    for (const h of byHour.keys()) if (!span.includes(h)) span.push(h);
    span.sort((a, b) => a - b);
    const peak = Math.max(0, ...span.map((h) => byHour.get(h) || 0));
    const scale = niceScale(peak);
    const top = (data?.top_selling_menu || []).slice(0, 3);
    const byName = (name) => menu().find((m) => m.name === name);
    return `<h1 class="aui-h1">ภาพรวม</h1>
      <button type="button" class="aui-datecard" data-act="reload">${icon('calendar')}<span class="aui-grow">วันนี้ (${dateText})</span>${icon(ui.reportAt && !data && !ui.reportError ? 'refresh' : 'down', 'aui-i-xs')}</button>
      ${ui.reportError ? `<p class="aui-note">${esc(ui.reportError)}</p>` : ''}
      <div class="aui-kpis">
        <div class="aui-kpi">${tile('coins')}<small>ยอดขายรวม</small><strong>${data ? baht(sales.today_sales) : '—'}</strong></div>
        <div class="aui-kpi">${tile('receipt')}<small>จำนวนใบเสร็จ</small><strong>${data ? `${Number(sales.paid_order_count || 0).toLocaleString('th-TH')} <em>ใบ</em>` : '—'}</strong></div>
        <div class="aui-kpi">${tile('users')}<small>ยอดเฉลี่ยต่อใบเสร็จ</small><strong>${data && avg != null ? baht(avg) : '—'}</strong></div>
      </div>
      <section class="aui-card aui-chart-card"><h2>ยอดขายรายชั่วโมง</h2>
        <div class="aui-chart" style="--rows:${scale.steps.length - 1}">
          <div class="aui-yaxis">${scale.steps.slice().reverse().map((v) => `<span>${v.toLocaleString('th-TH')}</span>`).join('')}</div>
          <div class="aui-bars">${span.map((h) => {
            const v = byHour.get(h) || 0;
            return `<div title="${h}:00 ${baht(v)}"><i style="height:${scale.max ? (v / scale.max) * 100 : 0}%"></i>${h % 2 === 0 ? `<small>${String(h).padStart(2, '0')}:00</small>` : ''}</div>`;
          }).join('')}</div>
        </div></section>
      <div class="aui-sectionhead"><h2>เมนูขายดี</h2>${can('analytics') ? `<button type="button" data-act="web" data-value="analytics">ดูทั้งหมด ${icon('right', 'aui-i-xs')}</button>` : ''}</div>
      ${top.length ? `<div class="aui-list plain">${top.map((item, i) => `<div class="aui-row aui-rank"><span class="aui-rankno">${i + 1}</span>
        <img src="${esc(photo(byName(item.name)))}" alt="" onerror="this.onerror=null;this.src='${asset('menu-placeholder.svg')}'">
        <span class="aui-grow"><strong>${esc(item.name)}</strong><small>${Number(item.quantity || 0).toLocaleString('th-TH')} รายการ</small></span><b>${baht(item.gross_sales)}</b></div>`).join('')}</div>`
        : empty('ยังไม่มียอดขายวันนี้', 'เมื่อรับเงินบิลแรก อันดับเมนูจะขึ้นที่นี่', 'wave')}`;
  };
  const niceScale = (peak) => {
    if (!peak) return {max: 120, steps: [0, 40, 80, 120]};
    const raw = peak / 3;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) || raw;
    return {max: step * 3, steps: [0, step, step * 2, step * 3]};
  };

  // ============================================================= ร้าน
  const SHOP_ROWS = [
    {icon: 'users', title: 'ลูกค้าและสมาชิก', sub: 'จัดการข้อมูลลูกค้า คะแนนสะสม', tab: 'crm'},
    {icon: 'badge', title: 'โปรโมชั่น', sub: 'ส่วนลด คูปอง และแคมเปญ', tab: 'crm', find: 'แคมเปญ'},
    {icon: 'grid', title: 'ช่องทางขาย', sub: 'หน้าร้าน, Grab, LINEMAN, Foodpanda', tab: 'crm', find: 'ช่องทาง'},
    {icon: 'user', title: 'พนักงานและสิทธิ์', sub: 'จัดการพนักงาน เวลาเข้าออกงาน', tab: 'staff'},
    {icon: 'table', title: 'โต๊ะและพื้นที่', sub: 'จัดการโต๊ะ QR และรับเงิน', tab: 'cashier'},
    {icon: 'printer', title: 'ใบเสร็จและเครื่องพิมพ์', sub: 'ตั้งค่าใบเสร็จและเครื่องพิมพ์', act: 'printer'},
    {icon: 'gear', title: 'ตั้งค่าร้าน', sub: 'ข้อมูลร้าน พร้อมเพย์ ภาษี และอื่นๆ', tab: 'cashier', find: 'ตั้งค่าร้าน'},
  ];
  const shopView = () => {
    const shop = auth().shop || {};
    const person = auth().current;
    const rows = SHOP_ROWS.filter((r) => !r.tab || can(r.tab));
    return `<h1 class="aui-h1">ร้าน</h1>
      <section class="aui-hero">
        <img src="${asset('mascot-pos.webp')}" alt="น้องไหว มาสคอต POS WAI" class="aui-hero-art">
        <div class="aui-hero-text"><img src="${asset('brand-logo.webp')}" alt="POS WAI" class="aui-hero-logo">
          <strong>${esc(shop.name || 'ร้านของฉัน')}</strong>
          <small>${esc(person ? `${person.name} · ${ROLE_NAMES[person.role] || person.role}` : 'ยังไม่เข้าสู่ระบบ')}</small>
          <small>${navigator.onLine ? 'ออนไลน์ · ข้อมูลอัปเดตอัตโนมัติ' : 'ออฟไลน์ · ขายต่อได้ ส่งทีหลัง'}</small>
          ${can('cashier') ? `<button type="button" class="aui-btn pill" data-act="web" data-value="cashier" data-find="ตั้งค่าร้าน">${icon('edit', 'aui-i-xs')} แก้ไขข้อมูล</button>` : ''}
        </div>
      </section>
      <div class="aui-menu">${rows.map((r) => `<button type="button" class="aui-mrow" ${r.act ? `data-act="${r.act}"` : `data-act="web" data-value="${r.tab}"`} ${r.find ? `data-find="${esc(r.find)}"` : ''}>
        ${icon(r.icon, 'aui-mic')}<span class="aui-grow"><strong>${r.title}</strong><small>${r.sub}</small></span>${icon('right', 'aui-i-xs')}</button>`).join('')}
        <button type="button" class="aui-mrow" data-act="account">${icon('user', 'aui-mic')}<span class="aui-grow"><strong>บัญชีของฉัน</strong><small>เชื่อม LINE/Google · ออกจากระบบ</small></span>${icon('right', 'aui-i-xs')}</button>
      </div>`;
  };
  const ROLE_NAMES = {owner: 'เจ้าของร้าน', manager: 'ผู้จัดการ', cashier: 'แคชเชียร์', kitchen: 'ครัว', service: 'พนักงานเสิร์ฟ', staff: 'พนักงาน'};

  const empty = (title, sub, art = 'wave') => `<div class="aui-empty"><img src="${asset(art === 'wave' ? 'mascot-wave.webp' : 'mascot-pos.webp')}" alt=""><strong>${esc(title)}</strong><small>${esc(sub)}</small></div>`;

  // ------------------------------------------------------------ sheets
  const openSheet = (html, kind = '') => {
    const sheet = slot('sheet');
    sheet.className = `aui-sheet ${kind}`;
    sheet.innerHTML = `<div class="aui-grabber"></div>${html}`;
    sheet.hidden = false;
    slot('scrim').hidden = false;
    document.documentElement.classList.add('aui-sheet-open');
  };
  const closeSheet = () => {
    slot('sheet').hidden = true;
    slot('scrim').hidden = true;
    document.documentElement.classList.remove('aui-sheet-open');
  };
  const actionSheet = (title, actions) => openSheet(`<div class="aui-sheet-head"><h2>${esc(title)}</h2><button type="button" class="aui-iconbtn" data-act="close" aria-label="ปิด">${icon('close')}</button></div>
    <div class="aui-menu">${actions.map((a, i) => `<button type="button" class="aui-mrow ${a.danger ? 'danger' : ''}" data-act="pick" data-value="${i}">${icon(a.icon || 'right', 'aui-mic')}<span class="aui-grow"><strong>${esc(a.label)}</strong>${a.sub ? `<small>${esc(a.sub)}</small>` : ''}</span></button>`).join('')}</div>`);
  let picks = [];

  // ----------------------------------------------------- the web screens
  /** Open one of the page's own screens full-size, under an app bar. */
  const openWeb = (tab, find = '', title = '') => {
    if (!can(tab)) { toast('บัญชีนี้ไม่มีสิทธิ์เปิดหน้านี้'); return; }
    closeSheet();
    const button = [...document.querySelectorAll('.role-tabs .role-tab')].find((b) => (b.getAttribute('onclick') || '').includes(`'${tab}'`));
    if (typeof switchTab === 'function') switchTab(tab, button);
    const names = {crm: 'ลูกค้าและช่องทางขาย', staff: 'พนักงานและสิทธิ์', cashier: 'โต๊ะและรับเงิน', inventory: 'จัดการเมนูและวัตถุดิบ', analytics: 'รายงานยอดขาย', kitchen: 'จอครัว', customer: 'สั่งอาหาร'};
    slot('subtitle').textContent = title || names[tab] || '';
    document.documentElement.classList.add('aui-sub');
    history.pushState({aui: 'sub'}, '');
    paintCartbar();
    window.scrollTo(0, 0);
    if (find) {
      requestAnimationFrame(() => {
        const view = document.getElementById(`view-${tab}`);
        const hit = view && [...view.querySelectorAll('h2,h3,h4,summary,legend')].find((el) => el.textContent.includes(find));
        if (hit) {
          hit.closest('details')?.setAttribute('open', '');
          hit.scrollIntoView({block: 'start'});
          window.scrollBy(0, -64);
        }
      });
    }
  };
  const closeWeb = () => {
    if (!document.documentElement.classList.contains('aui-sub')) return false;
    document.documentElement.classList.remove('aui-sub');
    const button = [...document.querySelectorAll('.role-tabs .role-tab')].find((b) => (b.getAttribute('onclick') || '').includes("'customer'"));
    if (can('customer') && typeof switchTab === 'function') switchTab('customer', button);
    paint();
    window.scrollTo(0, 0);
    return true;
  };
  window.addEventListener('popstate', () => { if (!slot('sheet').hidden) closeSheet(); else closeWeb(); });

  // ------------------------------------------------------------- paint
  let painting = false;
  const paint = () => {
    if (painting) return;
    painting = true;
    try {
      paintHeader();
      paintNav();
      const main = slot('main');
      const keep = document.activeElement && main.contains(document.activeElement) && document.activeElement.dataset.act;
      const caret = keep ? document.activeElement.selectionStart : null;
      const scroll = window.scrollY;
      const views = {sell: sellView, orders: ordersView, goods: goodsView, overview: overviewView, shop: shopView};
      main.innerHTML = (views[ui.tab] || shopView)();
      main.dataset.tab = ui.tab;
      if (keep) {
        const again = main.querySelector(`[data-act="${keep}"]`);
        if (again) { again.focus(); if (caret !== null && again.setSelectionRange) again.setSelectionRange(caret, caret); }
      }
      window.scrollTo(0, scroll);
      paintCartbar();
    } finally { painting = false; }
  };
  const go = (tab) => {
    ui.tab = tab;
    remember();
    window.scrollTo(0, 0);
    paint();
    if (tab === 'orders') loadOrdersExtra();
    if (tab === 'overview') loadReport();
  };

  // ------------------------------------------------------------ actions
  const pressed = async (el, event) => {
    const act = el.dataset.act;
    const value = el.dataset.value;
    switch (act) {
      case 'tab': go(value); break;
      case 'account': document.querySelector('.poswai-auth-button')?.click(); break;
      case 'bell': go(TABS[1].allowed() ? 'orders' : ui.tab); break;
      case 'back': history.back(); break;
      case 'close': if (!slot('sheet').hidden) history.back(); break;
      case 'category': ui.category = value; paint(); break;
      case 'scan': {
        const input = root.querySelector('[data-act="query"]');
        input.placeholder = 'ยิงบาร์โค้ด หรือพิมพ์รหัสสินค้า';
        input.focus();
        break;
      }
      case 'add': {
        const id = Number(value);
        if (typeof onClickMenuCard === 'function') onClickMenuCard(id);
        else if (typeof addToCart === 'function') addToCart(id);
        mergeCart();
        paint();
        break;
      }
      case 'cart': history.pushState({aui: 'sheet'}, ''); cartSheet(); break;
      case 'qty': {
        const line = pos().cart[Number(el.dataset.index)];
        if (!line) break;
        if (Number(value) > 0) {
          const m = menu().find((x) => x.id === line.id);
          const used = pos().cart.filter((i) => i.id === line.id).reduce((n, i) => n + i.qty, 0);
          if (m && typeof m.quota === 'number' && used >= m.quota) { toast('เมนูนี้ครบจำนวนที่เหลือแล้ว'); break; }
          line.qty += 1;
        } else {
          line.qty -= 1;
          if (line.qty <= 0) pos().cart.splice(Number(el.dataset.index), 1);
        }
        if (typeof renderCart === 'function') renderCart();
        paint();
        if (pos().cart.length) cartSheet(); else history.back();
        break;
      }
      case 'clear':
        if (!window.confirm('ล้างรายการทั้งหมดในตะกร้า?')) break;
        if (typeof clearCart === 'function') clearCart();
        history.back();
        paint();
        break;
      case 'send': {
        const note = document.getElementById('orderNoteInput');
        const typed = root.querySelector('[data-act="note"]')?.value.trim() || '';
        if (note) note.value = [ui.mode === 'กลับบ้าน' ? 'กลับบ้าน' : '', typed].filter(Boolean).join(' · ');
        el.disabled = true;
        el.textContent = 'กำลังส่ง...';
        const before = pos().cart.length;
        try { await submitOrderFromCustomer(); }
        finally { el.disabled = false; }
        if (!pos().cart.length && before) { history.back(); go('sell'); }
        else el.innerHTML = `ส่งเข้าครัว ${icon('arrow', 'aui-i-xs')}`;
        break;
      }
      case 'ostatus': ui.orderStatus = value; remember(); paint(); if (value === 'done') loadOrdersExtra(); break;
      case 'channel': ui.channel = value; remember(); paint(); loadOrdersExtra(); break;
      case 'ready': {
        const open = (window.poswaiKdsTickets || []).filter((t) => t.order_no === value && t.status !== 'ready' && t.status !== 'held');
        el.disabled = true;
        for (const t of open) await setOrderReady(t.order_no, t.station);
        paint();
        break;
      }
      case 'fire': {
        const held = (window.poswaiKdsTickets || []).filter((t) => t.order_no === value && t.status === 'held');
        el.disabled = true;
        for (const t of held) await fireHeldCourseOrder(t.order_no, t.station);
        paint();
        break;
      }
      case 'pay':
        openWeb('cashier', '', `รับเงิน · โต๊ะ ${value}`);
        if (typeof selectCashierTable === 'function') selectCashierTable(value);
        break;
      case 'online':
        el.disabled = true;
        try {
          await api(`/api/online/orders/${encodeURIComponent(value)}`, {method: 'PATCH', body: JSON.stringify({status: el.dataset.next})});
          await loadOrdersExtra();
        } catch (error) { toast(`อัปเดตไม่สำเร็จ: ${error.message}`); el.disabled = false; }
        break;
      case 'ordermenu': {
        const order = pos().orders.find((o) => o.orderId === value);
        if (!order) break;
        picks = [
          can('cashier') && {label: `รับเงินโต๊ะ ${order.table}`, icon: 'coins', run: () => pressed({dataset: {act: 'pay', value: order.table}})},
          can('cashier') && {label: 'พิมพ์ใบแจ้งยอดโต๊ะนี้', icon: 'printer', run: () => { if (typeof printReceiptForTable === 'function') printReceiptForTable(order.table); }},
          can('kitchen') && {label: 'เปิดจอครัวเต็ม', icon: 'order', run: () => openWeb('kitchen')},
        ].filter(Boolean);
        history.pushState({aui: 'sheet'}, '');
        actionSheet(`โต๊ะ ${order.table} · ${window.shortOrderNo ? window.shortOrderNo(order.orderId) : order.orderId}`, picks);
        break;
      }
      case 'gpane': ui.goodsPane = value; remember(); paint(); break;
      case 'goodsmenu': {
        const m = menu().find((x) => x.id === Number(value));
        if (!m) break;
        picks = [
          {label: m.soldOut ? 'เปิดขาย (พร้อมขาย)' : 'ตั้งเป็นหมดชั่วคราว', icon: m.soldOut ? 'check' : 'alert', run: () => setSoldOut(m, !m.soldOut)},
          {label: 'แก้ไขเมนู', sub: 'ชื่อ ราคา รูป ตัวเลือก สูตร', icon: 'edit', run: () => openWeb('inventory')},
        ];
        history.pushState({aui: 'sheet'}, '');
        actionSheet(m.name, picks);
        break;
      }
      case 'pick': {
        const pick = picks[Number(value)];
        history.back();
        if (pick) setTimeout(() => pick.run(), 30);
        break;
      }
      case 'web': openWeb(value, el.dataset.find || ''); break;
      case 'printer': window.POSWAI_APP?.printer?.open?.(); break;
      case 'reload': await loadReport(true); toast('อัปเดตยอดขายแล้ว'); break;
      default: break;
    }
    void event;
  };

  const setSoldOut = async (m, soldOut) => {
    if (!m.serverId) { if (typeof toggleMenuSoldOut === 'function') toggleMenuSoldOut(m.id); paint(); return; }
    try {
      await api(`/api/menu/${encodeURIComponent(m.serverId)}`, {method: 'PATCH', body: JSON.stringify({branch_id: branch(), sold_out: soldOut})});
      m.soldOut = soldOut;
      paint();
      toast(soldOut ? `ตั้ง "${m.name}" เป็นหมดชั่วคราวแล้ว` : `เปิดขาย "${m.name}" แล้ว`);
      window.poswaiLiveData?.refresh?.();
    } catch (error) { toast(`บันทึกไม่สำเร็จ: ${error.message}`); }
  };

  root.addEventListener('click', (event) => {
    if (event.target === slot('scrim')) { history.back(); return; }
    const el = event.target.closest('[data-act]');
    if (!el || el.tagName === 'SELECT' || el.tagName === 'INPUT' || el.disabled) return;
    pressed(el, event);
  });
  root.addEventListener('change', (event) => {
    const el = event.target;
    if (el.dataset.act === 'table') {
      if (pos().cart.length && String(pos().customerTable) !== el.value) {
        el.value = pos().customerTable;
        toast('ส่งหรือล้างตะกร้าก่อนเปลี่ยนโต๊ะ');
        return;
      }
      pos().customerTable = el.value;
      const web = document.getElementById('customerTableSelect');
      if (web) web.value = el.value;
      if (typeof renderAll === 'function') renderAll();
    }
    if (el.dataset.act === 'mode') ui.mode = el.value;
  });
  root.addEventListener('input', (event) => {
    const el = event.target;
    if (el.dataset.act === 'query') { ui.query = el.value; paint(); }
    if (el.dataset.act === 'gquery') { ui.goodsQuery = el.value; paint(); }
  });

  // ------------------------------------------------------------ wiring
  const signedIn = () => !document.body.classList.contains('poswai-locked') && Boolean(auth().current);
  const sync = () => {
    const on = signedIn();
    document.documentElement.classList.toggle('aui-on', on);
    if (!on) { closeSheet(); document.documentElement.classList.remove('aui-sub'); return; }
    paint();
  };

  const start = () => {
    document.body.append(root);
    // The page redraws after every change it makes; this screen follows it.
    if (typeof window.renderAll === 'function') {
      const original = window.renderAll;
      window.renderAll = function wrapped(...args) {
        const result = original.apply(this, args);
        if (document.documentElement.classList.contains('aui-on') && !document.documentElement.classList.contains('aui-sub')) paint();
        return result;
      };
    }
    // The page's own option sheet (spice level, toppings) closes into the cart.
    const mods = document.getElementById('modifierModalBackdrop');
    if (mods) new MutationObserver(() => { if (!mods.classList.contains('active')) { mergeCart(); paint(); } }).observe(mods, {attributes: true, attributeFilter: ['class']});
    new MutationObserver(sync).observe(document.body, {attributes: true, attributeFilter: ['class']});
    window.addEventListener('poswai:auth-changed', () => { sync(); loadOrdersExtra(); loadReport(true); });
    window.addEventListener('online', paint);
    window.addEventListener('offline', paint);
    // Minutes on the order cards keep counting.
    setInterval(() => { if (ui.tab === 'orders' && document.documentElement.classList.contains('aui-on')) paint(); }, 30000);
    setInterval(() => { if (document.visibilityState === 'visible' && ui.tab === 'orders') loadOrdersExtra(); }, 20000);
    sync();
    loadOrdersExtra();
    loadReport();
  };
  /** Android's back: close what is open, then return to the first tab, then leave. */
  const back = () => {
    if (!document.documentElement.classList.contains('aui-on')) return false;
    if (!slot('sheet').hidden || document.documentElement.classList.contains('aui-sub')) { history.back(); return true; }
    const first = TABS.find((t) => t.allowed());
    if (first && ui.tab !== first.id) { go(first.id); return true; }
    return false;
  };
  window.POSWAI_UI = {go, openWeb, paint, back};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
