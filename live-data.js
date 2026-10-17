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
    catalog = menu.items;
    DEFAULT_MENU.splice(0, DEFAULT_MENU.length, ...menu.items.map((item, index) => ({
      id: 100000 + index, serverId: item.id, name: item.name, nameEn: item.name,
      nameCn: item.name, price: item.price, cost: item.cost || 0,
      category: item.category || 'ทั้งหมด', description: item.description || '',
      photo: item.photo || '', station: item.station || 'ครัวร้อน', emoji: '🍽️',
      soldOut: !!item.sold_out, bom: item.bom, active: item.active,
      taxMode: item.tax_mode || 'included', serviceCharge: !!item.service_charge,
      /* The shop's own options, so the customer screen stops guessing them
         from the dish's name. No options means straight into the cart. */
      optionGroupTitle: item.option_title || 'เลือกตัวเลือกเพิ่ม',
      levelOptions: item.levels || [],
      customAddons: (item.addons || []).map(addon => ({
        name: addon.name, price: addon.price, ingId: addon.ingId, qty: addon.qty,
      })),
      noModifiers: !(item.levels || []).length && !(item.addons || []).length,
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
    renderCatalogViews();
    const selector = document.getElementById('bomMenuSelect');
    if (selector) selector.replaceChildren(...DEFAULT_MENU.map(item => new Option(item.name, item.id)));
    renderAll();
  };
  const panel = document.createElement('section');
  const style = document.createElement('style');
  style.textContent = `.live-catalog-panel{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:20px;margin:0 0 20px;box-shadow:0 8px 24px #1118270d}.live-catalog-panel h3{margin:0 0 8px}.live-catalog-panel p{color:#6b7280}.live-catalog-panel form{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;align-items:end;padding:14px 0;border-top:1px solid #eee}.live-catalog-panel label{display:grid;gap:5px;font-size:.85rem;font-weight:600}.live-catalog-panel input,.live-catalog-panel select,.live-catalog-panel textarea{width:100%;padding:10px;border:1px solid #d1d5db;border-radius:9px}.live-catalog-panel button{padding:11px 16px;background:#ffc928;color:#141b24;border:0;border-radius:9px;font-weight:700;cursor:pointer}.live-catalog-panel button.ghost{background:#eef2f7;color:#141b24}.live-catalog-panel button.danger{background:#fdeae7;color:#c0372b}.live-tabs{display:flex;gap:8px;border-bottom:2px solid #eef2f7;margin:4px 0 0}.live-tabs button{background:none;color:#6b7280;border-radius:0;padding:12px 18px;border-bottom:3px solid transparent;margin-bottom:-2px}.live-tabs button.on{color:#141b24;border-bottom-color:#ffc928}.live-catalog-panel form.live-menu-grid{display:grid;grid-template-columns:minmax(0,35fr) minmax(0,65fr);gap:20px;align-items:start;border-top:0;padding:16px 0}.live-photo{display:grid;gap:10px;position:sticky;top:12px}.live-photo-box{aspect-ratio:4/3;border:2px dashed #d1d5db;border-radius:14px;display:grid;place-items:center;background:#fbfcfe;overflow:hidden;color:#9ca3af;font-size:.85rem;text-align:center;padding:10px;cursor:pointer}.live-photo-box img{width:100%;height:100%;object-fit:cover}.live-photo-actions{display:flex;gap:8px}.live-photo-actions button{flex:1;padding:9px 10px;font-size:.85rem}.live-preview{border:1px solid #e5e7eb;border-radius:14px;padding:12px;background:#fff}.live-preview-cap{font-size:.75rem;color:#6b7280;margin:0 0 8px;text-transform:none}.live-preview-card{border:1px solid #eef2f7;border-radius:12px;overflow:hidden}.live-preview-card .shot{aspect-ratio:4/3;background:#f3f4f6;display:grid;place-items:center;font-size:2rem}.live-preview-card .shot img{width:100%;height:100%;object-fit:cover}.live-preview-card .body{padding:10px}.live-preview-card .title{font-weight:700;font-size:.95rem;line-height:1.4}.live-preview-card .desc{color:#6b7280;font-size:.8rem;margin:3px 0 0;line-height:1.5}.live-preview-card .cost{display:flex;justify-content:space-between;align-items:baseline;margin-top:8px}.live-preview-card .baht{font-weight:800;color:#141b24}.live-preview-card .tag{font-size:.72rem;color:#6b7280}.live-preview-card.out{opacity:.55}.live-fields{display:grid;gap:14px}.live-group{border:1px solid #e5e7eb;border-radius:14px;padding:14px;background:#fff}.live-group>h4{margin:0 0 10px;font-size:.9rem;color:#141b24}.live-group .row{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;align-items:end}.live-group label{display:grid;gap:5px;font-size:.85rem;font-weight:600}.live-group textarea{resize:vertical;min-height:62px}.live-id-row{display:flex;gap:8px}.live-id-row input{flex:1}.live-id-row button{white-space:nowrap;padding:10px 12px;font-size:.82rem}.live-catalog-panel label.live-switch{display:flex;align-items:center;gap:9px;font-size:.85rem;font-weight:600;cursor:pointer}.live-catalog-panel label.live-switch input{width:auto;margin:0;transform:scale(1.25);accent-color:#ffc928}.live-switches{display:flex;gap:18px;flex-wrap:wrap}.live-bom{display:grid;gap:8px}.live-bom-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.live-bom-head strong{font-size:.9rem}.live-bom-row{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr) 54px auto;gap:8px;align-items:center}.live-addon-row{grid-template-columns:minmax(0,2fr) minmax(0,.8fr) minmax(0,1.1fr) minmax(0,.8fr) auto}.live-bom-row .unit{font-size:.82rem;color:#6b7280;text-align:center}.live-bom-row button{padding:9px 12px;background:#fdeae7;color:#c0372b}.live-bom-empty{color:#6b7280;font-size:.85rem;margin:0}.live-bom-note{margin:0;font-size:.8rem;color:#6b7280}.live-levels{display:grid;gap:6px}.live-table-tools{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 10px}.live-table-tools input,.live-table-tools select{flex:1;min-width:150px;padding:10px;border:1px solid #d1d5db;border-radius:9px}.live-table-wrap{overflow-x:auto;border:1px solid #e5e7eb;border-radius:14px}.live-table{width:100%;border-collapse:collapse;font-size:.88rem;min-width:620px}.live-table th{background:#141b24;color:#fff;text-align:left;padding:11px 12px;font-weight:700;white-space:nowrap}.live-table td{padding:10px 12px;border-top:1px solid #eef2f7;vertical-align:middle}.live-table tr.low td{background:#fff7ed}.live-table .thumb{width:46px;height:46px;border-radius:9px;object-fit:cover;background:#f3f4f6;display:block}.live-table .acts{display:flex;gap:6px;flex-wrap:wrap}.live-table .acts button{padding:7px 11px;font-size:.8rem}.live-pill{display:inline-block;padding:3px 9px;border-radius:999px;font-size:.75rem;font-weight:700}.live-pill.ok{background:#e8f6ed;color:#15803d}.live-pill.off{background:#f3f4f6;color:#6b7280}.live-pill.out{background:#fdeae7;color:#c0372b}.live-pill.warn{background:#fff3cd;color:#8a6100}.live-empty-row{text-align:center;color:#6b7280;padding:26px 12px}@media(max-width:900px){.live-catalog-panel form.live-menu-grid{grid-template-columns:1fr}.live-photo{position:static;order:2}.live-fields{order:1}}@media(max-width:650px){.live-bom-row,.live-addon-row{grid-template-columns:1fr;gap:6px}.live-bom-row .unit{text-align:left}}@media(max-width:650px){.live-catalog-panel{padding:15px}.live-catalog-panel form{grid-template-columns:1fr}}`;
  document.head.append(style);
  panel.className = 'live-catalog-panel';
  panel.hidden = true;
  panel.innerHTML = `<h3>เมนูและคลังวัตถุดิบ</h3>
    <p>ใส่เมนูกับวัตถุดิบที่นี่ ราคาและสูตรตัดสต็อกยึดข้อมูลบนเซิร์ฟเวอร์เสมอ</p>
    <div class="live-tabs" role="tablist">
      <button type="button" class="on" data-cat-tab="menu">จัดการเมนูอาหาร</button>
      <button type="button" data-cat-tab="stock">จัดการคลังวัตถุดิบ</button>
    </div>

    <div data-cat-pane="menu">
    <form id="liveMenuForm" class="live-menu-grid">
      <div class="live-photo">
        <div class="live-photo-box" id="liveMenuPhotoBox" role="button" tabindex="0">แตะเพื่อเลือกรูปเมนู<br>JPG, PNG หรือ WebP ไม่เกิน 3 MB</div>
        <input type="file" id="liveMenuPhotoFile" accept="image/jpeg,image/png,image/webp" hidden>
        <div class="live-photo-actions">
          <button type="button" class="ghost" id="liveMenuPhotoPick">เลือกรูป</button>
          <button type="button" class="danger" id="liveMenuPhotoClear">เอารูปออก</button>
        </div>
        <div class="live-preview">
          <p class="live-preview-cap">ลูกค้าจะเห็นแบบนี้</p>
          <div class="live-preview-card" id="liveMenuPreview"></div>
        </div>
      </div>

      <div class="live-fields">
        <div class="live-group"><h4>ข้อมูลทั่วไป</h4>
          <div class="row">
            <label>รหัสเมนู
              <span class="live-id-row">
                <input name="id" required maxlength="80" placeholder="เช่น M001">
                <button type="button" class="ghost" id="liveMenuIdAuto">สร้างให้</button>
              </span>
            </label>
            <label>ชื่อเมนู <input name="name" required maxlength="200" placeholder="เช่น กะเพราหมูสับ"></label>
            <label>หมวดหมู่
              <input name="category" maxlength="60" list="liveCategoryList" placeholder="เช่น จานหลัก, ของหวาน">
              <datalist id="liveCategoryList"></datalist>
            </label>
            <label>สเตชันครัว/บาร์ <select name="station"><option>ครัวร้อน</option><option>ครัวเย็น/ยำ</option><option>บาร์น้ำ</option></select></label>
          </div>
          <div class="row" style="margin-top:12px">
            <label style="grid-column:1/-1">คำอธิบายเมนู <textarea name="description" maxlength="500" placeholder="บอกสั้น ๆ ว่าจานนี้เป็นยังไง ลูกค้าจะเห็นใต้ชื่อเมนู"></textarea></label>
          </div>
        </div>

        <div class="live-group"><h4>ราคาและภาษี</h4>
          <div class="row">
            <label>ราคาขาย (บาท) <input name="price" type="number" min="0" max="1000000" step="0.01" required></label>
            <label>ต้นทุนมาตรฐาน (บาท) <input name="cost" type="number" min="0" max="1000000" step="0.01" value="0"></label>
            <label>การคิดภาษี <select name="tax_mode">
              <option value="included">ราคานี้รวม VAT แล้ว</option>
              <option value="excluded">ราคานี้ยังไม่รวม VAT</option>
              <option value="none">ไม่คิด VAT</option>
            </select></label>
          </div>
          <div class="live-switches" style="margin-top:12px">
            <label class="live-switch"><input type="checkbox" name="service_charge"> คิด Service Charge</label>
          </div>
          <p class="live-bom-note" id="liveMarginNote" style="margin-top:10px"></p>
        </div>

        <div class="live-group"><h4>ตัวเลือกเพิ่มเติม / ท็อปปิ้ง</h4>
          <div class="row">
            <label style="grid-column:1/-1">หัวข้อตัวเลือก <input name="option_title" maxlength="120" placeholder="เช่น เลือกระดับความเผ็ด"></label>
          </div>
          <div class="live-levels" style="margin-top:12px">
            <div class="live-bom-head"><strong>ระดับให้เลือก (หวาน/เผ็ด)</strong>
              <button type="button" class="ghost" id="liveLevelAdd">+ เพิ่มระดับ</button></div>
            <div id="liveLevelRows"></div>
          </div>
          <div class="live-bom" style="margin-top:14px">
            <div class="live-bom-head"><strong>ท็อปปิ้งที่เพิ่มเงินได้</strong>
              <button type="button" class="ghost" id="liveAddonAdd">+ เพิ่มท็อปปิ้ง</button></div>
            <div id="liveAddonRows"></div>
            <p class="live-bom-note">ใส่ราคาติดลบได้ ถ้าเป็นส่วนลด เช่น นำแก้วมาเอง −5 บาท · เลือกวัตถุดิบไว้ด้วยก็ตัดสต็อกให้ตามท็อปปิ้ง</p>
          </div>
        </div>

        <div class="live-group"><h4>สูตรตัดสต็อกวัตถุดิบ</h4>
          <div class="live-bom">
            <div class="live-bom-head"><strong>เมนูนี้ 1 จาน ใช้อะไรบ้าง</strong>
              <button type="button" class="ghost" id="liveBomAdd">+ เพิ่มวัตถุดิบ</button></div>
            <div id="liveBomRows"></div>
            <p class="live-bom-note">ขายได้แล้วระบบหักสต็อกให้เอง · เว้นว่างไว้ก็ขายได้ แค่ไม่ตัดสต็อก</p>
          </div>
        </div>

        <div class="live-group"><h4>สถานะการขาย</h4>
          <div class="live-switches">
            <label class="live-switch"><input type="checkbox" name="active" checked> แสดงในหน้าสั่งอาหารลูกค้า</label>
            <label class="live-switch"><input type="checkbox" name="sold_out"> สินค้าหมดชั่วคราว</label>
          </div>
        </div>

        <div class="live-switches">
          <button type="submit" id="liveMenuSave">บันทึกเมนู</button>
          <button type="button" class="ghost" id="liveMenuReset">ล้างฟอร์ม</button>
        </div>
      </div>
    </form>

    <div class="live-table-tools">
      <input id="liveMenuSearch" type="search" placeholder="ค้นหาชื่อเมนูหรือรหัส">
      <select id="liveMenuFilter"><option value="">ทุกหมวดหมู่</option></select>
    </div>
    <div class="live-table-wrap"><table class="live-table">
      <thead><tr><th>รูป</th><th>เมนู</th><th>หมวดหมู่</th><th>ราคา</th><th>สถานะ</th><th>จัดการ</th></tr></thead>
      <tbody id="liveMenuTable"></tbody></table></div>
    </div>

    <div data-cat-pane="stock" hidden>
      <form id="liveStockForm">
        <label>รหัสวัตถุดิบ <input name="id" required maxlength="80" placeholder="เช่น PORK, RICE, MILK"></label>
        <label>ชื่อหน่วยนับ <input name="unit" maxlength="20" list="liveUnitList" placeholder="เช่น กรัม, มล., ชิ้น">
          <datalist id="liveUnitList"><option>กรัม</option><option>กิโลกรัม</option><option>มล.</option><option>ลิตร</option><option>ชิ้น</option><option>ฟอง</option><option>ขวด</option><option>ถุง</option></datalist>
        </label>
        <label>จำนวนคงเหลือ <input name="stock" type="number" min="0" step="0.000001" required></label>
        <label>เตือนเมื่อเหลือต่ำกว่า <input name="reorder_point" type="number" min="0" step="0.000001" value="0"></label>
        <button type="submit">เพิ่มวัตถุดิบ</button>
      </form>
      <p class="live-bom-note">เพิ่มของใหม่ที่นี่ · ถ้าของมีอยู่แล้วและต้องการรับเข้าเพิ่ม ให้ใช้แท็บ "เบิก / โอน / ของเสีย" ด้านล่าง จะได้มีประวัติไว้ตรวจ</p>
      <div class="live-table-tools">
        <input id="liveStockSearch" type="search" placeholder="ค้นหารหัสวัตถุดิบ">
      </div>
      <div class="live-table-wrap"><table class="live-table">
        <thead><tr><th>วัตถุดิบ</th><th>คงเหลือ</th><th>หน่วย</th><th>เตือนเมื่อต่ำกว่า</th><th>สถานะ</th><th>จัดการ</th></tr></thead>
        <tbody id="liveStockTable"></tbody></table></div>
    </div>
    <p id="liveCatalogStatus" role="status"></p>`;
  document.querySelector('#view-inventory')?.prepend(panel);
  if (!panel.parentElement) document.body.append(panel);
  const status = message => { panel.querySelector('#liveCatalogStatus').textContent = message; };
  const submit = async (url, body) => {
    await request(url, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    await refresh(); status('บันทึกสำเร็จ');
  };
  const menuForm = panel.querySelector('#liveMenuForm');
  const field = name => menuForm.querySelector(`[name="${name}"]`);
  /* Menu items as the server last reported them, so the table and the edit
     button work from stored values rather than from whatever is on screen. */
  let catalog = [];
  let pendingPhoto = null;   // a chosen file waits here until the item exists
  let photoUrl = '';

  panel.querySelectorAll('[data-cat-tab]').forEach(tab => tab.addEventListener('click', () => {
    panel.querySelectorAll('[data-cat-tab]').forEach(other => other.classList.toggle('on', other === tab));
    panel.querySelectorAll('[data-cat-pane]').forEach(pane => {
      pane.hidden = pane.dataset.catPane !== tab.dataset.catTab;
    });
  }));

  /* ---- the picture ---------------------------------------------------- */
  const photoBox = panel.querySelector('#liveMenuPhotoBox');
  const photoFile = panel.querySelector('#liveMenuPhotoFile');
  const pickPhoto = () => photoFile.click();
  photoBox.addEventListener('click', pickPhoto);
  photoBox.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); pickPhoto(); }
  });
  panel.querySelector('#liveMenuPhotoPick').addEventListener('click', pickPhoto);
  const showPhoto = source => {
    photoBox.replaceChildren();
    if (!source) {
      photoBox.textContent = 'แตะเพื่อเลือกรูปเมนู';
      photoBox.append(document.createElement('br'));
      photoBox.append('JPG, PNG หรือ WebP ไม่เกิน 3 MB');
    } else {
      const image = document.createElement('img');
      image.src = source; image.alt = 'รูปเมนู';
      photoBox.append(image);
    }
    drawPreview();
  };
  photoFile.addEventListener('change', async () => {
    const file = photoFile.files?.[0];
    if (!file) return;
    if (file.size > 3 * 1024 * 1024) { status('รูปใหญ่เกิน 3 MB ย่อรูปก่อนแล้วลองใหม่'); photoFile.value = ''; return; }
    const itemId = String(field('id').value || '').trim();
    /* An item has to exist before the server will attach a photo to it, so a
       photo chosen for a dish not yet saved waits for the save. */
    if (!itemId || !catalog.some(item => item.id === itemId)) {
      pendingPhoto = file;
      showPhoto(URL.createObjectURL(file));
      status('เลือกรูปแล้ว กดบันทึกเมนูเพื่ออัปโหลด');
      return;
    }
    try { await uploadPhoto(itemId, file); status('อัปโหลดรูปแล้ว'); }
    catch (error) { status(error.message); }
    finally { photoFile.value = ''; }
  });
  const uploadPhoto = async (itemId, file) => {
    const body = new FormData();
    body.append('file', file);
    const result = await request(`/api/menu/${encodeURIComponent(itemId)}/photo?branch_id=${branch()}`,
      {method: 'POST', body});
    pendingPhoto = null;
    photoUrl = result.photo;
    showPhoto(photoUrl);
    await refresh();
  };
  panel.querySelector('#liveMenuPhotoClear').addEventListener('click', async () => {
    pendingPhoto = null;
    photoFile.value = '';
    const itemId = String(field('id').value || '').trim();
    if (photoUrl && catalog.some(item => item.id === itemId)) {
      try { await request(`/api/menu/${encodeURIComponent(itemId)}/photo?branch_id=${branch()}`, {method: 'DELETE'}); }
      catch (error) { status(error.message); return; }
      await refresh();
    }
    photoUrl = '';
    showPhoto('');
  });

  /* ---- the preview ---------------------------------------------------- */
  const drawPreview = () => {
    const card = panel.querySelector('#liveMenuPreview');
    const price = Number(field('price').value) || 0;
    const cost = Number(field('cost').value) || 0;
    card.classList.toggle('out', field('sold_out').checked);
    const shot = document.createElement('div');
    shot.className = 'shot';
    const source = photoBox.querySelector('img')?.src;
    if (source) {
      const image = document.createElement('img');
      image.src = source; image.alt = '';
      shot.append(image);
    } else shot.textContent = '🍽️';
    const body = document.createElement('div');
    body.className = 'body';
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = field('name').value.trim() || 'ชื่อเมนู';
    body.append(title);
    const description = field('description').value.trim();
    if (description) {
      const note = document.createElement('p');
      note.className = 'desc';
      note.textContent = description;
      body.append(note);
    }
    const cost_row = document.createElement('div');
    cost_row.className = 'cost';
    const baht = document.createElement('span');
    baht.className = 'baht';
    baht.textContent = `฿${price.toLocaleString('th-TH')}`;
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = field('sold_out').checked ? 'หมดชั่วคราว'
      : (field('category').value.trim() || field('station').value);
    cost_row.append(baht, tag);
    body.append(cost_row);
    card.replaceChildren(shot, body);
    const margin = panel.querySelector('#liveMarginNote');
    margin.textContent = price > 0 && cost > 0
      ? `กำไรต่อจาน ฿${(price - cost).toLocaleString('th-TH')} · คิดเป็น ${Math.round((price - cost) / price * 100)}% ของราคาขาย`
      : 'ใส่ต้นทุนไว้ด้วย ระบบจะคำนวณกำไรต่อจานให้เห็นทันที';
  };
  ['name', 'price', 'cost', 'description', 'category', 'station', 'sold_out']
    .forEach(name => field(name).addEventListener('input', drawPreview));
  field('sold_out').addEventListener('change', drawPreview);

  /* ---- the recipe ----------------------------------------------------- */
  const bomRows = () => panel.querySelector('#liveBomRows');
  const ingredients = () => state.inventory || [];
  const unitOf = id => (ingredients().find(item => item.id === id) || {}).unit || 'หน่วย';
  const renderBomEmpty = () => {
    const rows = bomRows();
    if (!rows || rows.querySelector('.live-bom-row')) return;
    const message = document.createElement('p');
    message.className = 'live-bom-empty';
    message.textContent = ingredients().length
      ? 'ยังไม่ได้ใส่สูตร เมนูนี้จะขายได้โดยไม่ตัดสต็อก'
      : 'ยังไม่มีวัตถุดิบในระบบ ไปที่แท็บ "จัดการคลังวัตถุดิบ" เพื่อเพิ่มก่อน';
    rows.replaceChildren(message);
  };
  const ingredientSelect = selected => {
    const pick = document.createElement('select');
    pick.setAttribute('aria-label', 'วัตถุดิบ');
    pick.replaceChildren(...ingredients().map(item =>
      new Option(item.id, item.id, false, item.id === selected)));
    return pick;
  };
  const addBomRow = (ingredient = '', amount = '') => {
    if (!ingredients().length) { renderBomEmpty(); return; }
    bomRows().querySelector('.live-bom-empty')?.remove();
    const row = document.createElement('div');
    row.className = 'live-bom-row';
    const pick = ingredientSelect(ingredient);
    const qty = document.createElement('input');
    qty.type = 'number'; qty.min = '0'; qty.step = 'any'; qty.value = amount;
    qty.placeholder = 'ใช้ต่อ 1 จาน';
    qty.setAttribute('aria-label', 'จำนวนที่ใช้ต่อหนึ่งจาน');
    const unit = document.createElement('span');
    unit.className = 'unit';
    unit.textContent = unitOf(pick.value);
    pick.addEventListener('change', () => { unit.textContent = unitOf(pick.value); });
    const remove = document.createElement('button');
    remove.type = 'button'; remove.textContent = 'ลบ';
    remove.addEventListener('click', () => { row.remove(); renderBomEmpty(); });
    row.append(pick, qty, unit, remove);
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
    if (!ingredients().length) { status('ไปเพิ่มวัตถุดิบที่แท็บคลังวัตถุดิบก่อน'); renderBomEmpty(); return; }
    addBomRow()?.querySelector('input')?.focus();
  });

  /* ---- sweetness and spice levels ------------------------------------- */
  const levelRows = () => panel.querySelector('#liveLevelRows');
  const renderLevelEmpty = () => {
    const rows = levelRows();
    if (rows.querySelector('.live-bom-row')) return;
    const message = document.createElement('p');
    message.className = 'live-bom-empty';
    message.textContent = 'ไม่ใส่ก็ได้ · ใส่แล้วลูกค้าจะต้องเลือกหนึ่งระดับก่อนสั่ง';
    rows.replaceChildren(message);
  };
  const addLevelRow = (value = '') => {
    levelRows().querySelector('.live-bom-empty')?.remove();
    const row = document.createElement('div');
    row.className = 'live-bom-row';
    row.style.gridTemplateColumns = 'minmax(0,1fr) auto';
    const input = document.createElement('input');
    input.maxLength = 80; input.value = value;
    input.placeholder = 'เช่น เผ็ดน้อย, หวาน 50%';
    input.setAttribute('aria-label', 'ชื่อระดับ');
    const remove = document.createElement('button');
    remove.type = 'button'; remove.textContent = 'ลบ';
    remove.addEventListener('click', () => { row.remove(); renderLevelEmpty(); });
    row.append(input, remove);
    levelRows().append(row);
    return row;
  };
  const readLevels = () => [...levelRows().querySelectorAll('.live-bom-row input')]
    .map(input => input.value.trim()).filter(Boolean);
  panel.querySelector('#liveLevelAdd').addEventListener('click', () => addLevelRow().querySelector('input').focus());

  /* ---- toppings -------------------------------------------------------- */
  const addonRows = () => panel.querySelector('#liveAddonRows');
  const renderAddonEmpty = () => {
    const rows = addonRows();
    if (rows.querySelector('.live-bom-row')) return;
    const message = document.createElement('p');
    message.className = 'live-bom-empty';
    message.textContent = 'ไม่ใส่ก็ได้ · ใส่แล้วลูกค้าจะเลือกเพิ่มได้ตอนสั่ง';
    rows.replaceChildren(message);
  };
  const addAddonRow = (addon = {}) => {
    addonRows().querySelector('.live-bom-empty')?.remove();
    const row = document.createElement('div');
    row.className = 'live-bom-row live-addon-row';
    const name = document.createElement('input');
    name.maxLength = 80; name.value = addon.name || '';
    name.placeholder = 'เช่น เพิ่มไข่ดาว';
    name.setAttribute('aria-label', 'ชื่อท็อปปิ้ง');
    const price = document.createElement('input');
    price.type = 'number'; price.step = '0.01'; price.value = addon.price ?? '';
    price.placeholder = 'บาท';
    price.setAttribute('aria-label', 'ราคาท็อปปิ้ง');
    const pick = ingredientSelect(addon.ingId);
    pick.prepend(new Option('ไม่ตัดสต็อก', 'NONE', false, !addon.ingId || addon.ingId === 'NONE'));
    if (!addon.ingId || addon.ingId === 'NONE') pick.value = 'NONE';
    const qty = document.createElement('input');
    qty.type = 'number'; qty.min = '0'; qty.step = 'any';
    qty.value = addon.qty || '';
    qty.placeholder = 'ใช้เท่าไหร่';
    qty.setAttribute('aria-label', 'จำนวนวัตถุดิบที่ใช้');
    const remove = document.createElement('button');
    remove.type = 'button'; remove.textContent = 'ลบ';
    remove.addEventListener('click', () => { row.remove(); renderAddonEmpty(); });
    row.append(name, price, pick, qty, remove);
    addonRows().append(row);
    return row;
  };
  const readAddons = () => {
    const result = [];
    for (const row of addonRows().querySelectorAll('.live-bom-row')) {
      const [name, price, pick, qty] = [row.children[0], row.children[1], row.children[2], row.children[3]];
      const label = name.value.trim();
      if (!label) continue;
      const ingId = pick.value;
      const amount = Number(qty.value) || 0;
      if (ingId !== 'NONE' && !(amount > 0)) throw new Error(`ท็อปปิ้ง ${label} เลือกวัตถุดิบไว้ ต้องใส่จำนวนด้วย`);
      result.push({name: label, price: Number(price.value) || 0, ingId, qty: amount});
    }
    return result;
  };
  panel.querySelector('#liveAddonAdd').addEventListener('click', () => addAddonRow().querySelector('input').focus());

  /* ---- filling and clearing the form ---------------------------------- */
  const clearForm = () => {
    menuForm.reset();
    field('active').checked = true;
    field('sold_out').checked = false;
    field('service_charge').checked = false;
    field('id').readOnly = false;
    pendingPhoto = null; photoUrl = ''; photoFile.value = '';
    bomRows().replaceChildren(); renderBomEmpty();
    levelRows().replaceChildren(); renderLevelEmpty();
    addonRows().replaceChildren(); renderAddonEmpty();
    panel.querySelector('#liveMenuSave').textContent = 'บันทึกเมนู';
    showPhoto('');
  };
  const fillForm = (item, {asCopy = false} = {}) => {
    clearForm();
    field('id').value = asCopy ? '' : item.id;
    field('id').readOnly = !asCopy;
    field('name').value = asCopy ? `${item.name} (สำเนา)` : item.name;
    field('price').value = item.price;
    field('cost').value = item.cost || 0;
    field('category').value = item.category || '';
    field('station').value = item.station || 'ครัวร้อน';
    field('description').value = item.description || '';
    field('tax_mode').value = item.tax_mode || 'included';
    field('service_charge').checked = !!item.service_charge;
    field('active').checked = item.active !== false;
    field('sold_out').checked = !!item.sold_out;
    field('option_title').value = item.option_title || '';
    (item.bom || []).forEach(part => addBomRow(part.ingId, part.qty));
    (item.levels || []).forEach(level => addLevelRow(level));
    (item.addons || []).forEach(addon => addAddonRow(addon));
    renderBomEmpty(); renderLevelEmpty(); renderAddonEmpty();
    /* A copy starts with no picture of its own: the photo belongs to the
       item it was uploaded for, and the new dish has not been saved yet. */
    photoUrl = asCopy ? '' : (item.photo || '');
    showPhoto(photoUrl);
    panel.querySelector('#liveMenuSave').textContent = asCopy ? 'บันทึกเมนูใหม่' : 'บันทึกการแก้ไข';
    menuForm.scrollIntoView({behavior: 'smooth', block: 'start'});
    (asCopy ? field('id') : field('name')).focus();
  };
  panel.querySelector('#liveMenuReset').addEventListener('click', () => { clearForm(); status(''); });
  drawPreview();   // never show the viewer an empty box before anything is typed
  panel.querySelector('#liveMenuIdAuto').addEventListener('click', () => {
    /* Keep counting from the highest M-number already used, so a shop that
       deletes an item never gets a code that collides with a live one. */
    const highest = catalog.reduce((top, item) => {
      const match = /^M(\d{3,})$/.exec(item.id);
      return match ? Math.max(top, Number(match[1])) : top;
    }, 0);
    field('id').value = 'M' + String(highest + 1).padStart(3, '0');
    field('id').readOnly = false;
    field('name').focus();
  });

  menuForm.addEventListener('submit', async event => {
    event.preventDefault();
    const itemId = String(field('id').value || '').trim();
    try {
      const body = {
        branch_id: branch(), name: field('name').value.trim(), price: Number(field('price').value),
        cost: Number(field('cost').value) || 0, station: field('station').value,
        category: field('category').value.trim(), description: field('description').value.trim(),
        tax_mode: field('tax_mode').value, service_charge: field('service_charge').checked,
        active: field('active').checked, sold_out: field('sold_out').checked,
        option_title: field('option_title').value.trim(),
        bom: readBom(), levels: readLevels(), addons: readAddons(),
      };
      await request(`/api/menu/${encodeURIComponent(itemId)}`,
        {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      if (pendingPhoto) await uploadPhoto(itemId, pendingPhoto);
      await refresh();
      clearForm();
      status(`บันทึก "${body.name}" แล้ว`);
    } catch (error) { status(error.message); }
  });

  /* ---- what is already on the menu ------------------------------------ */
  const menuSearch = panel.querySelector('#liveMenuSearch');
  const menuFilter = panel.querySelector('#liveMenuFilter');
  const renderMenuTable = () => {
    const body = panel.querySelector('#liveMenuTable');
    const query = menuSearch.value.trim().toLowerCase();
    const category = menuFilter.value;
    const rows = catalog.filter(item =>
      (!category || (item.category || '') === category) &&
      (!query || item.name.toLowerCase().includes(query) || item.id.toLowerCase().includes(query)));
    if (!rows.length) {
      const empty = document.createElement('tr');
      const cell = document.createElement('td');
      cell.className = 'live-empty-row'; cell.colSpan = 6;
      cell.textContent = catalog.length ? 'ไม่พบเมนูที่ค้นหา' : 'ยังไม่มีเมนู เพิ่มเมนูแรกจากฟอร์มด้านบนได้เลย';
      empty.append(cell); body.replaceChildren(empty);
      return;
    }
    body.replaceChildren(...rows.map(item => {
      const row = document.createElement('tr');
      const shot = document.createElement('td');
      if (item.photo) {
        const image = document.createElement('img');
        image.className = 'thumb'; image.src = item.photo; image.alt = '';
        image.loading = 'lazy';
        shot.append(image);
      } else {
        const blank = document.createElement('span');
        blank.className = 'thumb';
        shot.append(blank);
      }
      const name = document.createElement('td');
      const strong = document.createElement('strong');
      strong.textContent = item.name;
      const code = document.createElement('div');
      code.className = 'tag'; code.style.cssText = 'color:#6b7280;font-size:.78rem';
      code.textContent = item.id;
      name.append(strong, code);
      const category_cell = document.createElement('td');
      category_cell.textContent = item.category || '—';
      const price = document.createElement('td');
      price.textContent = `฿${Number(item.price).toLocaleString('th-TH')}`;
      const state_cell = document.createElement('td');
      const pill = document.createElement('span');
      pill.className = 'live-pill ' + (item.sold_out ? 'out' : item.active ? 'ok' : 'off');
      pill.textContent = item.sold_out ? 'หมดชั่วคราว' : item.active ? 'พร้อมขาย' : 'ซ่อนอยู่';
      state_cell.append(pill);
      const acts = document.createElement('td');
      const actions = document.createElement('div');
      actions.className = 'acts';
      const edit = document.createElement('button');
      edit.type = 'button'; edit.className = 'ghost'; edit.textContent = 'แก้ไข';
      edit.addEventListener('click', () => fillForm(item));
      const copy = document.createElement('button');
      copy.type = 'button'; copy.className = 'ghost'; copy.textContent = 'คัดลอก';
      copy.addEventListener('click', () => fillForm(item, {asCopy: true}));
      const drop = document.createElement('button');
      drop.type = 'button'; drop.className = 'danger'; drop.textContent = 'ลบ';
      drop.addEventListener('click', async () => {
        if (!window.confirm(`ลบเมนู "${item.name}" ออกจากร้าน?\nบิลที่ขายไปแล้วไม่เปลี่ยน`)) return;
        try {
          await request(`/api/menu/${encodeURIComponent(item.id)}?branch_id=${branch()}`, {method: 'DELETE'});
          if (field('id').value === item.id) clearForm();
          await refresh();
          status(`ลบ "${item.name}" แล้ว`);
        } catch (error) { status(error.message); }
      });
      actions.append(edit, copy, drop);
      acts.append(actions);
      row.append(shot, name, category_cell, price, state_cell, acts);
      return row;
    }));
  };
  menuSearch.addEventListener('input', renderMenuTable);
  menuFilter.addEventListener('change', renderMenuTable);

  /* ---- the stock cupboard --------------------------------------------- */
  const stockSearch = panel.querySelector('#liveStockSearch');
  const renderStockTable = () => {
    const body = panel.querySelector('#liveStockTable');
    const query = stockSearch.value.trim().toLowerCase();
    const rows = ingredients().filter(item => !query || item.id.toLowerCase().includes(query));
    if (!rows.length) {
      const empty = document.createElement('tr');
      const cell = document.createElement('td');
      cell.className = 'live-empty-row'; cell.colSpan = 6;
      cell.textContent = ingredients().length ? 'ไม่พบวัตถุดิบที่ค้นหา' : 'ยังไม่มีวัตถุดิบ เพิ่มจากฟอร์มด้านบนได้เลย';
      empty.append(cell); body.replaceChildren(empty);
      return;
    }
    body.replaceChildren(...rows.map(item => {
      const row = document.createElement('tr');
      if (item.low) row.className = 'low';
      const name = document.createElement('td');
      name.textContent = item.id;
      const stock = document.createElement('td');
      stock.textContent = Number(item.stock).toLocaleString('th-TH');
      const unit = document.createElement('td');
      const unitInput = document.createElement('input');
      unitInput.value = item.unit || 'หน่วย'; unitInput.maxLength = 20;
      unitInput.setAttribute('aria-label', `หน่วยนับของ ${item.id}`);
      unit.append(unitInput);
      const alert_cell = document.createElement('td');
      const alertInput = document.createElement('input');
      alertInput.type = 'number'; alertInput.min = '0'; alertInput.step = 'any';
      alertInput.value = item.reorder_point || 0;
      alertInput.setAttribute('aria-label', `เตือนเมื่อ ${item.id} ต่ำกว่า`);
      alert_cell.append(alertInput);
      const state_cell = document.createElement('td');
      const pill = document.createElement('span');
      pill.className = 'live-pill ' + (item.low ? 'warn' : 'ok');
      pill.textContent = item.low ? 'ใกล้หมด' : 'เพียงพอ';
      state_cell.append(pill);
      const acts = document.createElement('td');
      const save = document.createElement('button');
      save.type = 'button'; save.className = 'ghost'; save.textContent = 'บันทึก';
      save.addEventListener('click', async () => {
        try {
          await request(`/api/inventory/${encodeURIComponent(item.id)}`, {method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({branch_id: branch(), unit: unitInput.value.trim() || 'หน่วย',
                                  reorder_point: Number(alertInput.value) || 0})});
          await refresh();
          status(`บันทึก ${item.id} แล้ว`);
        } catch (error) { status(error.message); }
      });
      acts.append(save);
      row.append(name, stock, unit, alert_cell, state_cell, acts);
      return row;
    }));
  };
  stockSearch.addEventListener('input', renderStockTable);

  /* The shop's own categories, offered wherever a category is picked. */
  const categories = () => [...new Set(catalog.map(item => item.category).filter(Boolean))].sort();
  const syncCategoryPills = () => {
    const pills = document.getElementById('categoryPills');
    if (!pills) return;
    const names = categories();
    const chosen = names.includes(state.currentCategory) ? state.currentCategory : 'ทั้งหมด';
    state.currentCategory = chosen;
    pills.replaceChildren(...['ทั้งหมด', ...names].map(name => {
      const pill = document.createElement('button');
      pill.className = 'cat-pill' + (name === chosen ? ' active' : '');
      pill.type = 'button';
      pill.textContent = name;
      pill.addEventListener('click', () => filterCategory(name, pill));
      return pill;
    }));
  };
  const renderCatalogViews = () => {
    renderBomEmpty();
    renderMenuTable();
    renderStockTable();
    const names = categories();
    panel.querySelector('#liveCategoryList').replaceChildren(
      ...names.map(name => { const option = document.createElement('option'); option.value = name; return option; }));
    const kept = menuFilter.value;
    menuFilter.replaceChildren(new Option('ทุกหมวดหมู่', ''),
      ...names.map(name => new Option(name, name, false, name === kept)));
    menuFilter.value = names.includes(kept) ? kept : '';
    syncCategoryPills();
  };

  panel.querySelector('#liveStockForm').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await submit(`/api/inventory/${encodeURIComponent(String(data.get('id')).trim())}`, {
        branch_id: branch(), stock: Number(data.get('stock')),
        unit: String(data.get('unit') || '').trim() || 'หน่วย',
        reorder_point: Number(data.get('reorder_point')) || 0,
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
    panel.querySelector('[data-cat-tab="menu"]')?.click();
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
    // The strip is rebuilt from the shop's own categories once data arrives.
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
