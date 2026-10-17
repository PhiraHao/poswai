/* Server-backed catalog and open bills. Demo records must never appear in live mode. */
(() => {
  let enabled = false;
  const branch = () => window.poswaiAuth?.branchId || 1;
  const table = () => window.poswaiAuth?.tableNo || String(state.customerTable || '1');
  const token = () => window.poswaiAuth?.tableToken || '';
  const request = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (token()) headers.set('X-Table-Token', token());
    const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options, headers});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };
  const refresh = async () => {
    if (!enabled) return;
    const menu = await request(`/api/menu?branch_id=${branch()}`);
    DEFAULT_MENU.splice(0, DEFAULT_MENU.length, ...menu.items.map((item, index) => ({
      id: 100000 + index, serverId: item.id, name: item.name, nameEn: item.name,
      nameCn: item.name, price: item.price, cost: 0, category: 'อาหารจานเดียว',
      station: item.station || 'ครัวร้อน', emoji: '🍽️', noModifiers: true, soldOut: false,
      bom: item.bom, active: item.active,
    })));
    state.cart = state.cart.filter(line => DEFAULT_MENU.some(item => item.id === line.id));
    let orders = [];
    try {
      const scope = window.poswaiAuth?.current ? '' : `&table_no=${encodeURIComponent(table())}`;
      orders = (await request(`/api/orders?branch_id=${branch()}${scope}`)).orders;
    } catch (error) {
      if (window.poswaiAuth?.current || token()) showToast(`โหลดออเดอร์ไม่สำเร็จ: ${error.message}`);
    }
    state.orders = orders.map(order => ({
      orderId: order.order_no, table: order.table_no, items: order.items,
      discount: 0, note: '-', status: 'pending',
      time: new Date(order.created_at + 'Z').toLocaleTimeString('th-TH', {hour:'2-digit', minute:'2-digit'}),
      source: 'POS WAI',
    }));
    if (window.poswaiAuth?.current) {
      try { window.poswaiKdsTickets = (await request(`/api/kds?branch_id=${branch()}`)).tickets; }
      catch (error) { showToast(`โหลดจอครัวไม่สำเร็จ: ${error.message}`); }
    } else window.poswaiKdsTickets = [];
    state.orders.forEach(order => {
      const tickets = window.poswaiKdsTickets.filter(ticket => ticket.order_no === order.orderId);
      if (tickets.length) order.status = tickets.every(ticket => ticket.status === 'ready') ? 'ready' : 'cooking';
    });
    if (window.poswaiAuth?.current) {
      try {
        const inventory = await request(`/api/inventory?branch_id=${branch()}`);
        state.inventory = inventory.items.map(item => ({id:item.id, name:item.id, stock:item.stock, reorder:0, unit:'หน่วย'}));
      } catch (error) { showToast(`โหลดสต็อกไม่สำเร็จ: ${error.message}`); }
    }
    renderBomEmpty();
    const selector = document.getElementById('bomMenuSelect');
    if (selector) selector.replaceChildren(...DEFAULT_MENU.map(item => new Option(item.name, item.id)));
    renderAll();
  };
  const panel = document.createElement('section');
  const style = document.createElement('style');
  style.textContent = `.live-catalog-panel{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:20px;margin:0 0 20px;box-shadow:0 8px 24px #1118270d}.live-catalog-panel h3{margin:0 0 8px}.live-catalog-panel p{color:#6b7280}.live-catalog-panel form{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;align-items:end;padding:14px 0;border-top:1px solid #eee}.live-catalog-panel label{display:grid;gap:5px;font-size:.85rem;font-weight:600}.live-catalog-panel input,.live-catalog-panel select,.live-catalog-panel textarea{width:100%;padding:10px;border:1px solid #d1d5db;border-radius:9px}.live-catalog-panel button{padding:11px 16px;background:#ffc928;color:#141b24;border:0;border-radius:9px;font-weight:700;cursor:pointer}.live-catalog-panel button.ghost{background:#eef2f7;color:#141b24}.live-bom{grid-column:1/-1;display:grid;gap:8px;padding:12px;background:#fbfcfe;border:1px solid #e5e7eb;border-radius:12px}.live-bom-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.live-bom-head strong{font-size:.9rem}.live-bom-row{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr) auto;gap:8px;align-items:center}.live-bom-row button{padding:9px 12px;background:#fdeae7;color:#c0372b}.live-bom-empty{color:#6b7280;font-size:.85rem;margin:0}.live-bom-note{margin:0;font-size:.8rem;color:#6b7280}@media(max-width:650px){.live-bom-row{grid-template-columns:1fr;gap:6px}}@media(max-width:650px){.live-catalog-panel{padding:15px}.live-catalog-panel form{grid-template-columns:1fr}}`;
  document.head.append(style);
  panel.className = 'live-catalog-panel';
  panel.hidden = true;
  panel.innerHTML = `<h3>ตั้งค่าเมนูและสต็อกจริง</h3>
    <p>ผู้จัดการเพิ่มเมนูและวัตถุดิบก่อนรับออเดอร์ ราคาและสูตรตัดสต็อกจะยึดข้อมูลบนเซิร์ฟเวอร์</p>
    <form id="liveMenuForm"><label>รหัสเมนู <input name="id" required maxlength="80"></label>
      <label>ชื่อเมนู <input name="name" required maxlength="200"></label>
      <label>ราคา (บาท) <input name="price" type="number" min="0" max="1000000" step="0.01" required></label>
      <label>สเตชัน <select name="station"><option>ครัวร้อน</option><option>ครัวเย็น/ยำ</option><option>บาร์น้ำ</option></select></label>
      <div class="live-bom">
        <div class="live-bom-head">
          <strong>สูตรตัดสต็อก (ใส่หรือไม่ใส่ก็ได้)</strong>
          <button type="button" class="ghost" id="liveBomAdd">+ เพิ่มวัตถุดิบ</button>
        </div>
        <div id="liveBomRows"></div>
        <p class="live-bom-note">บอกว่าเมนูนี้ <strong>1 จาน</strong> ใช้อะไรเท่าไหร่ ขายได้แล้วระบบหักสต็อกให้เอง · เว้นว่างไว้ก็ขายได้ แค่ไม่ตัดสต็อก</p>
      </div>
      <button type="submit">บันทึกเมนู</button></form>
    <form id="liveStockForm"><label>รหัสวัตถุดิบ <input name="id" required maxlength="80" placeholder="เช่น PORK, RICE, MILK"></label>
      <label>จำนวนคงเหลือ <input name="stock" type="number" min="0" step="0.000001" required placeholder="ใช้หน่วยเดียวกันทั้งร้าน"></label>
      <button type="submit">บันทึกสต็อก</button></form><p id="liveCatalogStatus" role="status"></p>`;
  document.querySelector('#view-inventory')?.prepend(panel);
  if (!panel.parentElement) document.body.append(panel);
  const status = message => { panel.querySelector('#liveCatalogStatus').textContent = message; };
  const submit = async (url, body) => {
    await request(url, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    await refresh(); status('บันทึกสำเร็จ');
  };
  /* The recipe editor. Ingredients come from the shop's own stock, because an
     order naming an ingredient the shop never entered is refused outright. */
  const bomRows = () => panel.querySelector('#liveBomRows');
  const ingredients = () => (state.inventory || []).map(item => item.id);
  const renderBomEmpty = () => {
    const rows = bomRows();
    if (rows.querySelector('.live-bom-row')) return;
    const message = document.createElement('p');
    message.className = 'live-bom-empty';
    message.textContent = ingredients().length
      ? 'ยังไม่ได้ใส่สูตร เมนูนี้จะขายได้โดยไม่ตัดสต็อก'
      : 'ยังไม่มีวัตถุดิบในระบบ บันทึกวัตถุดิบในช่องด้านล่างก่อน แล้วค่อยกลับมาใส่สูตร';
    rows.replaceChildren(message);
  };
  const addBomRow = (ingredient = '', amount = '') => {
    const names = ingredients();
    if (!names.length) { renderBomEmpty(); return; }
    bomRows().querySelector('.live-bom-empty')?.remove();
    const row = document.createElement('div');
    row.className = 'live-bom-row';
    const pick = document.createElement('select');
    pick.setAttribute('aria-label', 'วัตถุดิบ');
    pick.replaceChildren(...names.map(name => new Option(name, name, false, name === ingredient)));
    const qty = document.createElement('input');
    qty.type = 'number'; qty.min = '0'; qty.step = 'any'; qty.value = amount;
    qty.placeholder = 'ใช้ต่อ 1 จาน';
    qty.setAttribute('aria-label', 'จำนวนที่ใช้ต่อหนึ่งจาน');
    const remove = document.createElement('button');
    remove.type = 'button'; remove.textContent = 'ลบ';
    remove.addEventListener('click', () => { row.remove(); renderBomEmpty(); });
    row.append(pick, qty, remove);
    bomRows().append(row);
    return row;
  };
  const readBom = () => {
    const parts = [];
    for (const row of bomRows().querySelectorAll('.live-bom-row')) {
      const name = row.querySelector('select').value;
      const amount = Number(row.querySelector('input').value);
      if (!name) continue;
      if (!(amount > 0)) throw new Error(`ใส่จำนวนที่ใช้ของ ${name} ให้มากกว่า 0`);
      parts.push({ingId: name, qty: amount});
    }
    return parts;
  };
  panel.querySelector('#liveBomAdd').addEventListener('click', () => {
    if (!ingredients().length) { status('บันทึกวัตถุดิบก่อน แล้วค่อยใส่สูตร'); renderBomEmpty(); return; }
    addBomRow()?.querySelector('input')?.focus();
  });
  panel.querySelector('#liveMenuForm').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const bom = readBom();
      await submit(`/api/menu/${encodeURIComponent(String(data.get('id')).trim())}`, {
        branch_id:branch(), name:String(data.get('name')).trim(), price:Number(data.get('price')),
        station:String(data.get('station')), bom, active:true,
      });
      form.reset();
      bomRows().replaceChildren();
      renderBomEmpty();
    } catch (error) { status(error.message); }
  });
  panel.querySelector('#liveStockForm').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await submit(`/api/inventory/${encodeURIComponent(String(data.get('id')).trim())}`, {
        branch_id:branch(), stock:Number(data.get('stock')),
      });
      form.reset();
      renderBomEmpty();   // the new ingredient is now pickable in a recipe
    } catch (error) { status(error.message); }
  });
  const shopPanel = document.createElement('section');
  shopPanel.className = 'live-catalog-panel';
  shopPanel.hidden = true;
  shopPanel.innerHTML = `<h3>ตั้งค่าร้าน</h3>
    <p>ชื่อร้านที่ลูกค้าเห็น และบัญชีพร้อมเพย์ที่รับเงินของร้านนี้</p>
    <form id="liveShopForm"><label>ชื่อร้าน <input name="name" maxlength="80" required></label>
      <label>พร้อมเพย์ (เบอร์โทรหรือเลขบัตรประชาชน) <input name="promptpay_id" maxlength="20" inputmode="numeric"></label>
      <button type="submit">บันทึกการตั้งค่า</button></form>
    <p id="liveShopStatus" role="status"></p><p id="liveShopLink"></p>`;
  panel.before(shopPanel);
  const loadShop = async () => {
    try {
      const settings = await request('/api/shop/settings');
      shopPanel.querySelector('[name="name"]').value = settings.name || '';
      shopPanel.querySelector('[name="promptpay_id"]').value = settings.promptpay_id || '';
      shopPanel.querySelector('#liveShopLink').textContent = settings.editable
        ? `ลิงก์เข้าร้านของคุณ ${location.origin}/?shop=${settings.slug} · ชื่อร้านในลิงก์ ${settings.slug}` +
          (settings.trial_ends_at ? ` · ทดลองใช้ฟรีถึง ${settings.trial_ends_at}` : '')
        : 'ร้านนี้ตั้งค่าจากเซิร์ฟเวอร์ ติดต่อทีมงานหากต้องการแก้';
      shopPanel.querySelector('#liveShopForm').hidden = !settings.editable;
    } catch (error) { shopPanel.querySelector('#liveShopStatus').textContent = error.message; }
  };
  shopPanel.querySelector('#liveShopForm').addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const note = shopPanel.querySelector('#liveShopStatus');
    try {
      await request('/api/shop/settings', {method:'PUT', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name:String(data.get('name')).trim(), promptpay_id:String(data.get('promptpay_id')).trim()})});
      note.textContent = 'บันทึกแล้ว';
      const config = await (await fetch('/api/config', {cache:'no-store'})).json();
      if (config.promptpay_id) state.promptPayId = config.promptpay_id;
    } catch (error) { note.textContent = error.message; }
  });

  const updateManager = () => {
    panel.hidden = !enabled || !['manager','owner'].includes(window.poswaiAuth?.current?.role);
    shopPanel.hidden = !enabled || window.poswaiAuth?.current?.role !== 'owner';
    if (!shopPanel.hidden) loadShop();
    if (enabled) refresh().catch(error => showToast(`โหลดข้อมูลจริงไม่สำเร็จ: ${error.message}`));
  };
  window.addEventListener('poswai:auth-changed', updateManager);
  /* The empty menu calls this: open the stock tab and put the cursor in the
     first field of the menu form, so adding the first dish is one click. */
  window.goAddMenu = () => {
    if (!['manager', 'owner'].includes(window.poswaiAuth?.current?.role)) {
      showToast('ให้ผู้จัดการหรือเจ้าของร้านเป็นคนเพิ่มเมนู');
      return;
    }
    document.querySelector(".role-tab[onclick*=\"'inventory'\"]")?.click();
    window.setTimeout(() => {
      panel.scrollIntoView({behavior: 'smooth', block: 'start'});
      panel.querySelector('#liveMenuForm [name="id"]')?.focus();
    }, 150);
  };
  window.poswaiLiveData = {refresh};
  const crmNav = document.querySelector('.role-tab[onclick*="\'crm\'"]');
  const hideUnsupported = () => {
    if (crmNav) crmNav.hidden = false;
    document.getElementById('view-crm')?.removeAttribute('hidden');
    document.querySelectorAll('#view-customer button[onclick*="quickAddNewMenuItem"],#view-customer button[onclick*="toggleManagerQuickEditMode"]').forEach(button => {
      button.disabled = true; button.title = 'ตั้งเมนูผ่านหน้าสต็อกของผู้จัดการ';
    });
    document.querySelector('#view-customer details.settings-panel')?.setAttribute('hidden', 'hidden');
    document.querySelectorAll('#categoryPills .cat-pill').forEach((button, index) => {
      if (index > 0) button.hidden = true;
    });
    state.currentCategory = 'ทั้งหมด';
  };
  const enterLive = () => {
    if (enabled) return;
    enabled = true;
    state.productionMode = true;
    state.orders = []; state.cart = []; state.inventory = []; state.members = [];
    window.poswaiKdsTickets = [];
    state.staffStats = []; state.leaveRequests = []; state.stockLogs = [];
    state.reservedTables = {}; state.slips = {};
    const branchSelect = document.getElementById('branchSelect');
    if (branchSelect) { branchSelect.selectedIndex = Math.min(branch() - 1, branchSelect.options.length - 1); branchSelect.disabled = true; }
    state.shift.startingCash = 0; state.shift.cashSales = 0;
    state.shift.totalSalesToday = 0; state.shift.totalCostToday = 0;
    document.getElementById('autoDemoBtn')?.remove();
    document.getElementById('custPromoSelect')?.setAttribute('disabled', 'disabled');
    hideUnsupported();
    updateManager();
    window.setInterval(() => { if (navigator.onLine) refresh().catch(() => {}); }, 15000);
  };
  // Remembering live mode per shop keeps the sample shop's sample records out of a real shop,
  // and starts a real shop on server data before /api/config answers.
  const KEY = 'poswai-live-shop';
  const asked = (new URLSearchParams(location.search).get('shop') || '').trim().toLowerCase();
  let remembered = '';
  try { remembered = localStorage.getItem(KEY) || ''; } catch (_) { /* private browsing */ }
  if (remembered && (!asked || asked === remembered)) enterLive();
  fetch('/api/config', {cache:'no-store'}).then(r => r.json()).then(config => {
    try {
      if (config.preview_only) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, config.shop?.slug || 'main');
    } catch (_) { /* private browsing */ }
    if (!config.preview_only) enterLive();
  }).catch(() => {});
})();
