/* Live inventory controls. The demo functions remain available only in preview. */
(() => {
  const live = () => Boolean(state.productionMode);
  let configured = false;
  let recentMovements = [];
  const branch = () => window.poswaiAuth?.current?.branch_id || 1;
  const manager = () => ['manager', 'owner'].includes(window.poswaiAuth?.current?.role);
  const inform = (message) => showToast(message);
  const request = async (path, options = {}) => {
    const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store',
      ...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };
  const refresh = async () => {
    await window.poswaiLiveData?.refresh();
    try {
      const data = await request(`/api/inventory/movements?branch_id=${branch()}`);
      recentMovements = data.items || [];
      paintMovements();
    } catch (error) {
      const panel = document.getElementById('poAndStockLogBox');
      if (panel && live()) panel.textContent = `โหลดประวัติสต็อกไม่สำเร็จ: ${error.message}`;
    }
  };
  const paintMovements = () => {
    const panel = document.getElementById('poAndStockLogBox');
    if (!panel || !live()) return;
    panel.replaceChildren();
    if (!recentMovements.length) {
      panel.textContent = 'ยังไม่มีรายการเคลื่อนไหวสต็อก';
      return;
    }
    for (const entry of recentMovements.slice(0, 20)) {
        const row = document.createElement('div');
        const label = entry.action === 'restock' ? 'รับเข้า' :
          entry.action === 'waste' ? 'ของเสีย' : 'โอนสาขา';
        row.className = 'live-stock-log';
        row.textContent = `${entry.created_at} · ${label} ${entry.ingredient_id} ` +
          `${entry.quantity} · คงเหลือ ${entry.resulting_stock}`;
        panel.append(row);
    }
  };
  const movement = async (action, ingredientId, quantity, note = '') => {
    if (!navigator.onLine) throw new Error('ต้องเชื่อมต่ออินเทอร์เน็ตเพื่อแก้สต็อก');
    if (!Number.isFinite(quantity) || quantity <= 0) throw new Error('ระบุจำนวนมากกว่า 0');
    await request('/api/inventory/movements', {method: 'POST', body: JSON.stringify({
      event_id: crypto.randomUUID(), branch_id: branch(), ingredient_id: ingredientId,
      action, quantity, note,
    })});
    await refresh();
  };
  const originalRenderInventory = window.renderInventoryView;
  const originalQuickRestock = window.quickRestock;
  const originalWaste = window.recordStockWaste;
  const originalPo = window.generatePurchaseOrder;
  const originalTransfer = window.transferStockToBranch;
  const originalStoreMode = window.onStoreModeChange;
  const originalBomEditor = window.renderBomEditor;
  const originalSaveBom = window.updateOrAddBomIngredient;

  window.renderInventoryView = function () {
    if (!live()) return originalRenderInventory();
    const table = document.getElementById('inventoryTableBody');
    const badge = document.getElementById('stockBadge');
    const depleted = state.inventory.filter(item => Number(item.stock) <= 0).length;
    if (badge) {
      badge.textContent = String(depleted);
      badge.style.display = depleted ? 'inline-block' : 'none';
    }
    /* The three numbers above the list come from the same records as the list:
       this live view replaces the one that used to refresh them, which left the
       sample shop's 9 / 2 / 7 standing over a list that said there was no stock. */
    const tiles = document.querySelectorAll('#opsInventoryStats .ops-stat strong');
    if (tiles.length === 3) {
      tiles[0].textContent = String(state.inventory.length);
      tiles[1].textContent = String(depleted);
      tiles[2].textContent = String(state.inventory.length - depleted);
    }
    if (table) {
      table.replaceChildren();
      if (!state.inventory.length) {
        const row = table.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 5;
        cell.textContent = 'ยังไม่มีข้อมูลสต็อกในสาขานี้';
      }
      for (const item of state.inventory) {
        const row = table.insertRow();
        row.insertCell().textContent = `${item.name} (${item.id})`;
        row.insertCell().textContent = `${item.stock} ${item.unit}`;
        row.insertCell().textContent = '—';
        row.insertCell().textContent = Number(item.stock) > 0 ? 'พร้อมใช้' : 'หมด';
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline';
        button.textContent = '+ รับของเข้าสต็อก';
        button.disabled = !manager();
        button.title = manager() ? 'กรอกจำนวนที่จะรับเข้าจริง' : 'ผู้จัดการเท่านั้น';
        button.addEventListener('click', () => window.quickRestock(item.id));
        row.insertCell().append(button);
      }
    }
    const selected = document.getElementById('stockActionItemSelect');
    const old = selected?.value;
    if (selected) {
      selected.replaceChildren(...state.inventory.map(item => new Option(
        `${item.name} (${item.unit})`, item.id)));
      if (old && state.inventory.some(item => item.id === old)) selected.value = old;
    }
    const bomIngredients = document.getElementById('bomIngSelect');
    const oldIngredient = bomIngredients?.value;
    if (bomIngredients) {
      bomIngredients.replaceChildren(...state.inventory.map(item => new Option(
        `${item.name} (${item.unit})`, item.id)));
      if (oldIngredient && state.inventory.some(item => item.id === oldIngredient)) {
        bomIngredients.value = oldIngredient;
      }
    }
    const wasteButton = document.querySelector('button[onclick="recordStockWaste()"]');
    if (wasteButton) wasteButton.disabled = !manager() || !state.inventory.length;
    paintMovements();
  };
  window.quickRestock = async function (ingredientId) {
    if (!live()) return originalQuickRestock(ingredientId);
    if (!manager()) return inform('ผู้จัดการเท่านั้นที่รับสต็อกได้');
    const ingredient = state.inventory.find(item => item.id === ingredientId);
    if (!ingredient) return inform('ไม่พบวัตถุดิบ');
    const typed = prompt(`รับ ${ingredient.name} เพิ่มเท่าไร (${ingredient.unit})?`, '');
    if (typed === null) return;
    const amount = Number(typed);
    try {
      await movement('restock', ingredientId, amount);
      inform(`รับ ${ingredient.name} จำนวน ${amount} ${ingredient.unit} แล้ว`);
    } catch (error) { inform(`รับสต็อกไม่สำเร็จ: ${error.message}`); }
  };
  window.recordStockWaste = async function () {
    if (!live()) return originalWaste();
    if (!manager()) return inform('ผู้จัดการเท่านั้นที่บันทึกของเสียได้');
    const ingredientId = document.getElementById('stockActionItemSelect')?.value;
    const amount = Number(document.getElementById('stockActionQty')?.value);
    if (!ingredientId) return inform('เลือกวัตถุดิบก่อน');
    const reason = prompt('ระบุสาเหตุของเสียหรือหมดอายุ', '');
    if (reason === null) return;
    if (!reason.trim()) return inform('ระบุสาเหตุของเสีย');
    try {
      await movement('waste', ingredientId, amount, reason.trim());
      inform('บันทึกของเสียและปรับสต็อกแล้ว');
    } catch (error) { inform(`บันทึกของเสียไม่สำเร็จ: ${error.message}`); }
  };
  window.generatePurchaseOrder = function () {
    if (!live()) return originalPo();
    inform('ยังไม่เชื่อมระบบใบสั่งซื้อกับซัพพลายเออร์');
  };
  window.transferStockToBranch = function () {
    if (!live()) return originalTransfer();
    inform('โอนสาขาต้องเลือกสาขาปลายทางที่ตรวจสอบได้');
  };
  window.onStoreModeChange = function () {
    if (!live()) return originalStoreMode();
    const selector = document.getElementById('storeModeSelect');
    if (selector) selector.value = 'SINGLE';
  };
  window.renderBomEditor = function () {
    if (!live()) return originalBomEditor();
    const menuSelector = document.getElementById('bomMenuSelect');
    const container = document.getElementById('bomRecipeListContainer');
    if (!container || !menuSelector) return;
    const item = DEFAULT_MENU.find(menu => String(menu.id) === menuSelector.value);
    container.replaceChildren();
    if (!item) { container.textContent = 'เลือกเมนูจากข้อมูลจริงก่อน'; return; }
    const title = document.createElement('strong');
    title.textContent = `${item.name} · ฿${Number(item.price).toFixed(2)}`;
    container.append(title);
    if (!item.bom?.length) {
      const empty = document.createElement('div');
      empty.textContent = 'ยังไม่มีสูตรวัตถุดิบสำหรับเมนูนี้';
      container.append(empty);
    }
    for (const part of item.bom || []) {
      const row = document.createElement('div');
      const ingredient = state.inventory.find(entry => entry.id === part.ingId);
      row.textContent = `${ingredient?.name || part.ingId}: ${part.qty} ${ingredient?.unit || 'หน่วย'} ต่อจาน`;
      container.append(row);
    }
  };
  window.updateOrAddBomIngredient = async function () {
    if (!live()) return originalSaveBom();
    if (!manager()) return inform('ผู้จัดการเท่านั้นที่แก้สูตรได้');
    const selectedId = document.getElementById('bomMenuSelect')?.value;
    const ingredientId = document.getElementById('bomIngSelect')?.value;
    const amount = Number(document.getElementById('bomQtyInput')?.value);
    const item = DEFAULT_MENU.find(menu => String(menu.id) === selectedId);
    if (!item?.serverId || !ingredientId || !Number.isFinite(amount) || amount <= 0) {
      return inform('เลือกเมนู วัตถุดิบ และจำนวนที่ถูกต้อง');
    }
    if (!navigator.onLine) return inform('ต้องเชื่อมต่ออินเทอร์เน็ตเพื่อแก้สูตร');
    const bom = (item.bom || []).filter(part => part.ingId !== ingredientId)
      .map(part => ({ingId: part.ingId, qty: part.qty}));
    bom.push({ingId: ingredientId, qty: amount});
    try {
      await request(`/api/menu/${encodeURIComponent(item.serverId)}`, {method: 'PUT',
        body: JSON.stringify({branch_id: branch(), name: item.name,
          price: item.price, bom, active: item.active, station: item.station})});
      await refresh();
      inform(`บันทึกสูตร ${item.name} แล้ว`);
    } catch (error) { inform(`บันทึกสูตรไม่สำเร็จ: ${error.message}`); }
  };
  const configureLive = () => {
    if (!live()) return;
    if (configured) return;
    configured = true;
    const inventory = document.getElementById('view-inventory');
    if (!inventory) return;
    const poButton = inventory.querySelector('button[onclick="generatePurchaseOrder()"]');
    if (poButton) poButton.hidden = true;
    const stockHeading = document.getElementById('inventoryTableBody')?.closest('.card')?.querySelector('.card-title');
    if (stockHeading) stockHeading.textContent = 'ยอดคงเหลือวัตถุดิบ';
    const stockTable = document.getElementById('inventoryTableBody')?.closest('table');
    if (stockTable?.tHead?.rows[0]?.cells[2]) stockTable.tHead.rows[0].cells[2].textContent = 'จุดเตือน';
    const transferButton = document.getElementById('transferActionBtn');
    if (transferButton) transferButton.hidden = true;
    const mode = document.getElementById('storeModeSelect');
    if (mode) mode.hidden = true;
    const movementCard = document.getElementById('poAndStockLogBox')?.closest('.card');
    if (movementCard) {
      const heading = movementCard.querySelector('.card-title');
      if (heading) heading.textContent = 'รับเข้าและบันทึกของเสีย';
      const explanation = movementCard.querySelector('.card-header [style*="font-size"]');
      if (explanation) explanation.textContent = 'ทุกรายการบันทึกบนเซิร์ฟเวอร์พร้อมชื่อผู้ทำรายการ';
      const warning = movementCard.querySelector('div[style*="padding:8px 10px"]');
      if (warning) warning.hidden = true;
      const quantitySelectLabel = document.getElementById('stockActionItemSelect')?.closest('div')?.querySelector('label');
      if (quantitySelectLabel) quantitySelectLabel.textContent = 'วัตถุดิบที่เสีย:';
      const quantityLabel = document.getElementById('stockActionQty')?.closest('div')?.querySelector('label');
      if (quantityLabel) quantityLabel.textContent = 'จำนวนของเสีย:';
    }
    const bomCard = document.getElementById('bomRecipeListContainer')?.closest('.card');
    if (bomCard) {
      const heading = bomCard.querySelector('.card-title');
      if (heading) heading.textContent = 'สูตรตัดวัตถุดิบของเมนู';
      const description = bomCard.querySelector('.card-header [style*="font-size"]');
      if (description) description.textContent = 'ผู้จัดการกำหนดสูตรที่ใช้ตัดสต็อกเมื่อส่งออเดอร์';
    }
    renderInventoryView();
    renderBomEditor();
    refresh().catch(error => { if (navigator.onLine) inform(`โหลดสต็อกไม่สำเร็จ: ${error.message}`); });
  };
  const startup = window.setInterval(() => {
    configureLive();
    if (configured) window.clearInterval(startup);
  }, 1000);
  window.addEventListener('poswai:auth-changed', () => {
    configureLive();
    if (live()) refresh().catch(error => { if (navigator.onLine) inform(`โหลดสต็อกไม่สำเร็จ: ${error.message}`); });
  });
  configureLive();
})();
