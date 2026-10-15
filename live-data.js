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
    const selector = document.getElementById('bomMenuSelect');
    if (selector) selector.replaceChildren(...DEFAULT_MENU.map(item => new Option(item.name, item.id)));
    renderAll();
  };
  const panel = document.createElement('section');
  const style = document.createElement('style');
  style.textContent = `.live-catalog-panel{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:20px;margin:0 0 20px;box-shadow:0 8px 24px #1118270d}.live-catalog-panel h3{margin:0 0 8px}.live-catalog-panel p{color:#6b7280}.live-catalog-panel form{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;align-items:end;padding:14px 0;border-top:1px solid #eee}.live-catalog-panel label{display:grid;gap:5px;font-size:.85rem;font-weight:600}.live-catalog-panel input,.live-catalog-panel select,.live-catalog-panel textarea{width:100%;padding:10px;border:1px solid #d1d5db;border-radius:9px}.live-catalog-panel button{padding:11px 16px;background:#ffc928;color:#141b24;border:0;border-radius:9px;font-weight:700;cursor:pointer}@media(max-width:650px){.live-catalog-panel{padding:15px}.live-catalog-panel form{grid-template-columns:1fr}}`;
  document.head.append(style);
  panel.className = 'live-catalog-panel';
  panel.hidden = true;
  panel.innerHTML = `<h3>ตั้งค่าเมนูและสต็อกจริง</h3>
    <p>ผู้จัดการเพิ่มเมนูและวัตถุดิบก่อนรับออเดอร์ ราคาและสูตรตัดสต็อกจะยึดข้อมูลบนเซิร์ฟเวอร์</p>
    <form id="liveMenuForm"><label>รหัสเมนู <input name="id" required maxlength="80"></label>
      <label>ชื่อเมนู <input name="name" required maxlength="200"></label>
      <label>ราคา (บาท) <input name="price" type="number" min="0" max="1000000" step="0.01" required></label>
      <label>สเตชัน <select name="station"><option>ครัวร้อน</option><option>ครัวเย็น/ยำ</option><option>บาร์น้ำ</option></select></label>
      <label>สูตร BOM (JSON) <textarea name="bom" rows="2" placeholder='[{"ingId":"RICE","qty":1}]'>[]</textarea></label>
      <button type="submit">บันทึกเมนู</button></form>
    <form id="liveStockForm"><label>รหัสวัตถุดิบ <input name="id" required maxlength="80"></label>
      <label>จำนวนคงเหลือ <input name="stock" type="number" min="0" step="0.000001" required></label>
      <button type="submit">บันทึกสต็อก</button></form><p id="liveCatalogStatus" role="status"></p>`;
  document.querySelector('#view-inventory')?.prepend(panel);
  if (!panel.parentElement) document.body.append(panel);
  const status = message => { panel.querySelector('#liveCatalogStatus').textContent = message; };
  const submit = async (url, body) => {
    await request(url, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    await refresh(); status('บันทึกสำเร็จ');
  };
  panel.querySelector('#liveMenuForm').addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const bom = JSON.parse(String(data.get('bom') || '[]'));
      if (!Array.isArray(bom)) throw new Error('สูตร BOM ต้องเป็นรายการ');
      await submit(`/api/menu/${encodeURIComponent(String(data.get('id')).trim())}`, {
        branch_id:branch(), name:String(data.get('name')).trim(), price:Number(data.get('price')),
        station:String(data.get('station')), bom, active:true,
      });
    } catch (error) { status(error.message); }
  });
  panel.querySelector('#liveStockForm').addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try { await submit(`/api/inventory/${encodeURIComponent(String(data.get('id')).trim())}`, {
      branch_id:branch(), stock:Number(data.get('stock')),
    }); } catch (error) { status(error.message); }
  });
  const updateManager = () => {
    panel.hidden = !enabled || !['manager','owner'].includes(window.poswaiAuth?.current?.role);
    if (enabled) refresh().catch(error => showToast(`โหลดข้อมูลจริงไม่สำเร็จ: ${error.message}`));
  };
  window.addEventListener('poswai:auth-changed', updateManager);
  window.poswaiLiveData = {refresh};
  const crmNav = document.querySelector('.role-tab[onclick*="\'crm\'"]');
  const hideUnsupported = () => {
    if (crmNav) crmNav.hidden = true;
    document.getElementById('view-crm')?.setAttribute('hidden', 'hidden');
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
  if (localStorage.getItem('poswai-live-mode') === '1') enterLive();
  fetch('/api/config', {cache:'no-store'}).then(r => r.json()).then(config => {
    if (config.preview_only) { localStorage.removeItem('poswai-live-mode'); return; }
    localStorage.setItem('poswai-live-mode', '1'); enterLive();
  }).catch(() => {});
})();
