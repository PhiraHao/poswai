/* Operational workspaces: keep existing controls and handlers, show one task at a time. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const text = (node, value) => { if (node) node.textContent = value; };
  const cardOf = (id) => $(id)?.closest('.card');
  function heading(card, title) {
    text(card?.querySelector('.card-title'), title);
    const titleNode = card?.querySelector('.card-title');
    if (titleNode?.parentElement !== card?.querySelector('.card-header')) {
      const detail = titleNode?.nextElementSibling;
      if (detail) detail.hidden = true;
    }
  }
  function tabs(view, entries) {
    const nav = document.createElement('div');
    nav.className = 'ops-tabs'; nav.setAttribute('role', 'tablist');
    nav.setAttribute('aria-label', 'เลือกพื้นที่ทำงาน');
    entries.forEach(([label, panel], i) => {
      panel.classList.add('ops-panel'); panel.id ||= `${view.id}-panel-${i}`;
      panel.setAttribute('role', 'tabpanel');
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = label; button.id = `${panel.id}-tab`;
      button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', panel.id);
      panel.setAttribute('aria-labelledby', button.id);
      button.addEventListener('click', () => select(i));
      button.addEventListener('keydown', event => {
        const direction = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
        if (!direction) return;
        event.preventDefault(); const next = (i + direction + entries.length) % entries.length;
        select(next); nav.children[next].focus();
      });
      nav.append(button);
    });
    function select(selected) {
      entries.forEach(([, panel], i) => {
        panel.hidden = i !== selected;
        nav.children[i].setAttribute('aria-selected', String(i === selected));
        nav.children[i].tabIndex = i === selected ? 0 : -1;
      });
    }
    view.append(nav);
    entries.forEach(([, panel]) => view.append(panel));
    select(0);
    return select;
  }
  function searchRows(card, bodyId, placeholder) {
    const bar = document.createElement('div'); bar.className = 'ops-search';
    const input = document.createElement('input'); input.type = 'search'; input.className = 'input';
    input.placeholder = placeholder; input.setAttribute('aria-label', placeholder);
    const count = document.createElement('span'); count.className = 'ops-result-count';
    const filter = () => {
      const query = input.value.trim().toLocaleLowerCase(); let shown = 0;
      for (const row of $(bodyId).rows) {
        row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
        if (!row.hidden) shown++;
      }
      count.textContent = `${shown} รายการ`;
    };
    input.addEventListener('input', filter); bar.append(input, count);
    card.querySelector('.card-header').after(bar);
    return filter;
  }
  function decorateTable(bodyId, labels) {
    for (const row of $(bodyId)?.rows || []) {
      [...row.cells].forEach((cell, i) => cell.setAttribute('data-label', labels[i] || ''));
    }
  }
  function stats(view, id, items) {
    let strip = $(id);
    if (!strip) { strip = document.createElement('div'); strip.id = id; strip.className = 'ops-stats'; view.querySelector('.module-intro').after(strip); }
    strip.replaceChildren(...items.map(([label, value, tone]) => {
      const item = document.createElement('div'); item.className = `ops-stat ${tone || ''}`;
      const caption = document.createElement('span'); caption.textContent = label;
      const number = document.createElement('strong'); number.textContent = value;
      item.append(caption, number); return item;
    }));
  }
  function shorten(view) {
    text(view.querySelector('.module-intro p'), '');
    view.querySelector('.module-state')?.remove();
  }

  const inventory = $('view-inventory');
  if (!inventory || inventory.dataset.opsRedesigned) return;
  inventory.dataset.opsRedesigned = 'true';
  const stockCard = cardOf('inventoryTableBody'), recipeCard = cardOf('bomMenuSelect'), movementCard = cardOf('stockActionItemSelect');
  const oldInventoryGrid = inventory.querySelector(':scope > .grid-2');
  shorten(inventory); text(inventory.querySelector('h1'), 'คลังสินค้า');
  heading(stockCard, 'วัตถุดิบ'); heading(recipeCard, 'สูตรอาหาร'); heading(movementCard, 'เบิก โอน และของเสีย');
  text(stockCard.querySelector('[onclick="generatePurchaseOrder()"]'), 'ดูใบสั่งซื้อ');
  stockCard.querySelector('button[disabled]')?.remove();
  recipeCard.querySelector('button[disabled]')?.remove();
  text(recipeCard.querySelector('[onclick="updateOrAddBomIngredient()"]'), 'บันทึกสูตร');
  [...recipeCard.querySelectorAll('.label')].forEach((label, i) => text(label, ['เมนูอาหาร', 'วัตถุดิบ', 'ปริมาณต่อจาน'][i]));
  recipeCard.querySelector('#bomMenuSelect').closest('[style*="display:grid"]').classList.add('ops-recipe-form');
  const wasteExplanation = [...movementCard.children].find(n => n.tagName === 'DIV' && n.textContent.includes('ทำไมร้านสาขาเดียว'));
  wasteExplanation?.remove();
  [...$('storeModeSelect').options].forEach((option, i) => text(option, ['ร้านสาขาเดียว', 'หลายสาขา'][i]));
  text(movementCard.querySelector('[onclick="recordStockWaste()"]'), 'บันทึกของเสีย');
  const stockLog = $('poAndStockLogBox'), history = document.createElement('details');
  history.className = 'ops-history'; const historyTitle = document.createElement('summary'); historyTitle.textContent = 'ประวัติการเคลื่อนไหว';
  stockLog.before(history); history.append(historyTitle, stockLog);
  const selectInventoryTab = tabs(inventory, [['วัตถุดิบ', stockCard], ['สูตรอาหาร', recipeCard], ['เบิก / โอน / ของเสีย', movementCard]]);
  oldInventoryGrid.remove();
  const originalPurchaseOrder = window.generatePurchaseOrder;
  window.generatePurchaseOrder = function (...args) {
    const result = originalPurchaseOrder.apply(this, args);
    selectInventoryTab(2); history.open = true;
    history.scrollIntoView({ block: 'nearest' });
    return result;
  };
  const stockFilter = searchRows(stockCard, 'inventoryTableBody', 'ค้นหาวัตถุดิบ');
  const originalInventory = window.renderInventoryView;
  window.renderInventoryView = function (...args) {
    const result = originalInventory.apply(this, args);
    stats(inventory, 'opsInventoryStats', [
      ['วัตถุดิบทั้งหมด', state.inventory.length],
      ['ต้องเติมสต็อก', state.inventory.filter(i => i.stock <= i.reorder).length, 'is-alert'],
      ['สต็อกเพียงพอ', state.inventory.filter(i => i.stock > i.reorder).length]
    ]);
    $('inventoryTableBody').querySelectorAll('.badge-danger').forEach(n => text(n, 'ใกล้หมด'));
    $('inventoryTableBody').querySelectorAll('button').forEach(n => text(n, '+ รับเข้า'));
    decorateTable('inventoryTableBody', ['วัตถุดิบ', 'คงเหลือ', 'ขั้นต่ำ', 'สถานะ', '']);
    text($('transferActionBtn'), state.storeMode === 'MULTI' ? 'โอนข้ามสาขา' : 'เบิกเข้าครัว');
    stockFilter(); return result;
  };
  const originalStoreMode = window.onStoreModeChange;
  window.onStoreModeChange = function (...args) {
    const result = originalStoreMode.apply(this, args);
    text($('transferActionBtn'), state.storeMode === 'MULTI' ? 'โอนข้ามสาขา' : 'เบิกเข้าครัว');
    return result;
  };
  window.renderBomEditor = function () {
    initBomDropdowns();
    const menu = DEFAULT_MENU.find(item => item.id === Number($('bomMenuSelect').value)) || DEFAULT_MENU[0];
    const list = $('bomRecipeListContainer'); list.replaceChildren();
    const title = document.createElement('div'); title.className = 'ops-recipe-title';
    title.textContent = `${menu.name} · 1 เสิร์ฟ`; list.append(title);
    const ingredients = (menu.bom || []).map(item => ({ item, ingredient: state.inventory.find(ingredient => ingredient.id === item.ingId) })).filter(entry => entry.ingredient);
    if (!ingredients.length) {
      const empty = document.createElement('p'); empty.textContent = 'เพิ่มวัตถุดิบเพื่อเริ่มต้นสูตรอาหาร'; list.append(empty);
    }
    ingredients.forEach(({ item, ingredient }) => {
      const row = document.createElement('div'); row.className = 'ops-recipe-row';
      const name = document.createElement('span'); name.textContent = ingredient.name;
      const amount = document.createElement('strong'); amount.textContent = `${item.qty} ${ingredient.unit}`;
      row.append(name, amount); list.append(row);
    });
  };

  const crm = $('view-crm'); shorten(crm); text(crm.querySelector('h1'), 'สมาชิก');
  const memberCard = cardOf('crmMembersTableBody'), deliveryCard = cardOf('deliveryOrdersLog');
  const oldCrmGrid = crm.querySelector(':scope > .grid-2');
  heading(memberCard, 'รายชื่อสมาชิก'); heading(deliveryCard, 'ช่องทางเดลิเวอรี');
  memberCard.querySelector('button[disabled]')?.remove();
  text(memberCard.querySelectorAll('th')[1], 'ระดับ');
  const deliveryBadge = deliveryCard.querySelector('.card-header .badge'); text(deliveryBadge, 'ยังไม่เชื่อมต่อ');
  const connectionInfo = [...deliveryCard.children].find(n => n.textContent.includes('สถานะการเชื่อมต่อ:') && !n.classList.contains('card-header'));
  if (connectionInfo) { connectionInfo.className = 'ops-connection-note'; connectionInfo.textContent = 'เชื่อมต่อผู้ให้บริการก่อนรับออเดอร์จริง'; }
  const apiInput = $('deliveryApiKeyInput'); if (apiInput) apiInput.parentElement.hidden = true;
  const demoButtons = [...deliveryCard.querySelectorAll('[onclick^="simulateDeliveryOrder"]')];
  const channels = document.createElement('div'); channels.className = 'ops-channels';
  ['GrabFood', 'LINE MAN', 'ShopeeFood', 'TikTok Shop'].forEach((name, i) => {
    const row = document.createElement('div'); row.className = 'ops-channel';
    const mark = document.createElement('span'); mark.className = 'ops-channel-mark'; mark.textContent = ['G', 'L', 'S', 'T'][i];
    const title = document.createElement('strong'); title.textContent = name;
    const status = document.createElement('span'); status.textContent = 'ยังไม่เชื่อมต่อ'; row.append(mark, title, status); channels.append(row);
    text(demoButtons[i], `ทดลอง ${name}`);
  });
  const demoGrid = demoButtons[0]?.parentElement;
  if (demoGrid) {
    const demos = document.createElement('details'); demos.className = 'ops-history';
    const summary = document.createElement('summary'); summary.textContent = 'ทดลองออเดอร์ตัวอย่าง';
    demoGrid.before(channels, demos); demos.append(summary, demoGrid);
  }
  tabs(crm, [['รายชื่อสมาชิก', memberCard], ['เดลิเวอรี', deliveryCard]]); oldCrmGrid.remove();
  const memberFilter = searchRows(memberCard, 'crmMembersTableBody', 'ค้นหาชื่อหรือเบอร์โทร');
  const originalCrm = window.renderCrmAndDeliveryView;
  window.renderCrmAndDeliveryView = function (...args) {
    const result = originalCrm.apply(this, args);
    stats(crm, 'opsMemberStats', [
      ['สมาชิกทั้งหมด', state.members.length],
      ['Gold / Platinum', state.members.filter(m => /gold|platinum/i.test(m.tier)).length],
      ['แต้มสะสมรวม', state.members.reduce((sum, m) => sum + Number(m.points || 0), 0).toLocaleString()]
    ]);
    decorateTable('crmMembersTableBody', ['สมาชิก', 'ระดับ', 'แต้ม', 'ยอดซื้อ', 'เมนูโปรด']);
    memberFilter(); return result;
  };

  const kitchen = $('view-kitchen'); shorten(kitchen);
  // Seeded and imported orders can omit station; resolve it from the menu before
  // falling back to the hot kitchen. All ticket and readiness handlers share this.
  window.itemMatchesStation = function (item, station) {
    const menu = DEFAULT_MENU.find(menu => String(menu.id) === String(item.id));
    return String(item.station || menu?.station || 'ครัวร้อน').includes(station);
  };
  const kitchenCard = cardOf('kdsContainer'); heading(kitchenCard, 'ออเดอร์ในครัว');
  [...$('kdsStationFilter').options].forEach((option, i) => text(option, ['ทุกแผนก', 'ครัวร้อน', 'ครัวเย็น', 'บาร์น้ำ'][i]));
  const printLabel = $('autoPrintKitchenToggle')?.parentElement;
  if (printLabel) {
    const printDetails = document.createElement('details'); printDetails.className = 'ops-kitchen-settings';
    const summary = document.createElement('summary'); summary.textContent = 'การพิมพ์';
    printLabel.before(printDetails); printDetails.append(summary, printLabel);
  }
  kitchenCard.classList.add('ops-kitchen-card');
  const originalKitchen = window.renderKitchenView;
  window.renderKitchenView = function (...args) {
    const result = originalKitchen.apply(this, args);
    const tickets = [...$('kdsContainer').querySelectorAll('.kds-ticket')];
    stats(kitchen, 'opsKitchenStats', [
      ['กำลังทำ', tickets.filter(t => t.classList.contains('is-cooking')).length],
      ['พักคอร์ส', tickets.filter(t => t.classList.contains('is-held')).length],
      ['พร้อมเสิร์ฟ', tickets.filter(t => t.classList.contains('is-ready')).length]
    ]);
    $('kdsContainer').querySelectorAll('.kds-empty').forEach(node => {
      node.innerHTML = '<span class="ops-empty-symbol" aria-hidden="true">✓</span><strong>พร้อมรับออเดอร์</strong><span>รายการใหม่จะแสดงที่นี่</span>';
    });
    return result;
  };
  window.renderInventoryView(); window.renderBomEditor(); window.renderCrmAndDeliveryView(); window.renderKitchenView();
})();
