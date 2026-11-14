/* สั่งของเข้าร้าน — who it was ordered from, what it cost, what turned up.

   The stock screen could say what was on the shelf and let someone type a new
   number in. It could not say what was already on its way, so a shop ordered
   twice because it forgot the first order, and could not check an invoice
   against anything. */
(() => {
  const money = (value) => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const text = (value) => String(value ?? '').replace(/[<>&]/g, '');
  const STAGE = {draft: 'ร่าง', sent: 'สั่งแล้ว รอของ', received: 'รับของแล้ว', cancelled: 'ยกเลิก'};

  const ask = async (path, options) => {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options});
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
      throw new Error(detail);
    }
    return response.json();
  };
  const send = (path, body) => ask(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})});

  const panel = document.createElement('section');
  panel.className = 'card purchasing-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="card-header"><div class="card-title">🚚 สั่งของเข้าร้าน</div></div>
    <p class="shift-hint">สั่งแล้วรอของ · พอของมาถึงกด "รับของ" แล้วสต็อกจะเพิ่มให้เอง ใส่จำนวนที่มาจริงได้ถ้าส่งมาไม่ครบ</p>

    <details class="po-block">
      <summary>ผู้ขาย</summary>
      <div class="shift-row">
        <input id="poSupplierName" class="input" maxlength="120" placeholder="ชื่อร้านที่สั่งของ">
        <input id="poSupplierPhone" class="input" maxlength="40" placeholder="เบอร์โทร">
        <button type="button" class="btn btn-outline" id="poSupplierAdd">เพิ่มผู้ขาย</button>
      </div>
      <ul class="po-suppliers" id="poSuppliers"></ul>
    </details>

    <details class="po-block" open>
      <summary>เปิดใบสั่งซื้อใหม่</summary>
      <div class="shift-row">
        <label for="poSupplier">สั่งจาก</label>
        <select id="poSupplier" class="input"></select>
      </div>
      <div id="poLines"></div>
      <div class="shift-row">
        <button type="button" class="btn btn-outline" id="poAddLine">+ เพิ่มรายการ</button>
        <span id="poTotal" class="po-total"></span>
        <button type="button" class="btn btn-line" id="poCreate">บันทึกใบสั่งซื้อ</button>
      </div>
    </details>

    <h4 class="po-heading">ใบสั่งซื้อล่าสุด</h4>
    <div id="poList" class="po-list"></div>
    <p id="poStatus" role="status" class="shift-status"></p>`;

  const at = (id) => panel.querySelector(`#${id}`);
  const branch = () => window.poswaiAuth?.branchId || 1;
  const say = (message, bad = false) => {
    at('poStatus').textContent = message;
    at('poStatus').classList.toggle('bad', bad);
  };

  let ingredients = [];

  const lineRow = () => {
    const row = document.createElement('div');
    row.className = 'po-line';
    row.innerHTML = `
      <input class="input po-ing" list="poIngredientList" maxlength="80" placeholder="รหัสวัตถุดิบ">
      <input class="input po-qty" type="number" min="0" step="any" placeholder="จำนวน">
      <input class="input po-cost" type="number" min="0" step="any" placeholder="ราคา/หน่วย">
      <button type="button" class="ghost">ลบ</button>`;
    row.querySelector('button').addEventListener('click', () => { row.remove(); retotal(); });
    row.querySelectorAll('input').forEach(input => input.addEventListener('input', retotal));
    at('poLines').append(row);
    return row;
  };

  const readLines = () => [...at('poLines').querySelectorAll('.po-line')].map(row => ({
    ingredient_id: row.querySelector('.po-ing').value.trim(),
    quantity: Number(row.querySelector('.po-qty').value) || 0,
    unit_cost: Number(row.querySelector('.po-cost').value) || 0,
  })).filter(line => line.ingredient_id && line.quantity > 0);

  const retotal = () => {
    const total = readLines().reduce((sum, line) => sum + line.quantity * line.unit_cost, 0);
    at('poTotal').textContent = total ? `รวม ${money(total)}` : '';
  };

  const drawSuppliers = (suppliers) => {
    at('poSupplier').innerHTML = suppliers
      .map(s => `<option value="${s.id}">${text(s.name)}</option>`).join('')
      || '<option value="">ยังไม่มีผู้ขาย เพิ่มด้านบนก่อน</option>';
    at('poSuppliers').innerHTML = suppliers.map(s =>
      `<li><strong>${text(s.name)}</strong> <span>${text(s.phone)}</span></li>`).join('')
      || '<li class="shift-empty">ยังไม่มีผู้ขาย</li>';
  };

  /* An order a person can act on: what stage it is at, and the one button
     that moves it to the next. Receiving asks for what actually arrived. */
  const orderCard = (order) => {
    const lines = order.lines.map(line =>
      `<tr><td>${text(line.ingredient_id)}</td><td>${line.quantity}</td>` +
      `<td>${money(line.unit_cost)}</td><td>${money(line.amount)}</td>` +
      `<td>${line.received_quantity === null || line.received_quantity === undefined
        ? '—' : line.received_quantity}</td></tr>`).join('');
    const actions = order.status === 'draft'
      ? `<button type="button" class="btn btn-outline" data-send="${order.id}">ส่งให้ผู้ขาย</button>
         <button type="button" class="btn btn-line" data-receive="${order.id}">รับของเลย</button>
         <button type="button" class="ghost" data-cancel="${order.id}">ยกเลิก</button>`
      : order.status === 'sent'
        ? `<button type="button" class="btn btn-line" data-receive="${order.id}">รับของ</button>
           <button type="button" class="ghost" data-cancel="${order.id}">ยกเลิก</button>`
        : '';
    return `<article class="po-card po-${order.status}">
      <header><strong>${text(order.number)}</strong>
        <span>${text(order.supplier.name)}</span>
        <em>${STAGE[order.status] || order.status}</em>
        <strong>${money(order.total)}</strong></header>
      <table><thead><tr><th>วัตถุดิบ</th><th>สั่ง</th><th>ราคา/หน่วย</th><th>รวม</th><th>รับจริง</th></tr></thead>
      <tbody>${lines}</tbody></table>
      ${order.cancel_reason ? `<p class="po-reason">ยกเลิก: ${text(order.cancel_reason)}</p>` : ''}
      <div class="po-actions">${actions}</div>
    </article>`;
  };

  const drawComing = (coming) => {
    const list = Object.entries(coming || {});
    const box = panel.querySelector('.shift-hint');
    box.textContent = list.length
      ? `กำลังมา: ${list.map(([id, qty]) => `${id} ${qty}`).join(' · ')} — สั่งเพิ่มก่อนเช็กตรงนี้ จะได้ไม่สั่งซ้ำ`
      : 'สั่งแล้วรอของ · พอของมาถึงกด "รับของ" แล้วสต็อกจะเพิ่มให้เอง ใส่จำนวนที่มาจริงได้ถ้าส่งมาไม่ครบ';
  };

  /* The ingredient codes the shop actually keeps, so nobody has to remember
     whether it was PORK or MOO. */
  const fillIngredients = async () => {
    const list = document.querySelector('#poIngredientList');
    if (!list) return;
    try {
      const stock = await ask(`/api/inventory?branch_id=${branch()}`);
      ingredients = stock.items || stock.inventory || [];
      list.innerHTML = ingredients.map(item =>
        `<option value="${text(item.ingredient_id || item.id)}">${
          text(item.name || item.ingredient_id || item.id)}</option>`).join('');
    } catch { /* typing the code by hand still works */ }
  };

  const load = async () => {
    try {
      await fillIngredients();
      drawSuppliers((await ask('/api/suppliers')).suppliers);
      const data = await ask(`/api/purchase-orders?branch_id=${branch()}&limit=20`);
      at('poList').innerHTML = data.orders.map(orderCard).join('')
        || '<p class="shift-empty">ยังไม่มีใบสั่งซื้อ</p>';
      drawComing(data.on_the_way);
      say('');
    } catch (error) { say(error.message, true); }
  };

  at('poSupplierAdd').addEventListener('click', async () => {
    const name = at('poSupplierName').value.trim();
    if (!name) { say('ใส่ชื่อผู้ขายก่อน', true); return; }
    try {
      await send('/api/suppliers', {name, phone: at('poSupplierPhone').value.trim()});
      at('poSupplierName').value = '';
      at('poSupplierPhone').value = '';
      await load();
      say('เพิ่มผู้ขายแล้ว');
    } catch (error) { say(error.message, true); }
  });

  at('poAddLine').addEventListener('click', () => lineRow().querySelector('.po-ing').focus());

  at('poCreate').addEventListener('click', async () => {
    const lines = readLines();
    if (!lines.length) { say('ใส่วัตถุดิบและจำนวนอย่างน้อยหนึ่งรายการ', true); return; }
    const supplier = Number(at('poSupplier').value);
    if (!supplier) { say('เลือกผู้ขายก่อน', true); return; }
    try {
      const made = await send('/api/purchase-orders',
        {branch_id: branch(), supplier_id: supplier, lines});
      at('poLines').replaceChildren();
      lineRow();
      retotal();
      await load();
      say(`บันทึกใบ ${made.number} แล้ว`);
    } catch (error) { say(error.message, true); }
  });

  at('poList').addEventListener('click', async (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    const id = button.dataset.send || button.dataset.receive || button.dataset.cancel;
    if (!id) return;
    try {
      if (button.dataset.send) {
        await send(`/api/purchase-orders/${id}/send?branch_id=${branch()}`);
        say('ส่งให้ผู้ขายแล้ว');
      } else if (button.dataset.receive) {
        /* Everything arrived unless someone says otherwise — which is the
           usual case, and saves retyping the same numbers at the back door. */
        const shortfall = window.prompt(
          'ของมาครบไหม? ถ้าครบกด OK เลย\nถ้าไม่ครบ พิมพ์เช่น PORK=18, RICE=0', '');
        if (shortfall === null) return;
        const received = {};
        for (const part of shortfall.split(',')) {
          const [name, qty] = part.split('=').map(piece => piece.trim());
          if (name && qty !== undefined) received[name] = Number(qty);
        }
        await send(`/api/purchase-orders/${id}/receive?branch_id=${branch()}`, {received});
        say('รับของแล้ว สต็อกเพิ่มให้เรียบร้อย');
        window.poswaiLiveData?.refresh?.();
      } else {
        const reason = window.prompt('ยกเลิกเพราะอะไร');
        if (!reason) return;
        await send(`/api/purchase-orders/${id}/cancel?branch_id=${branch()}`, {reason});
        say('ยกเลิกแล้ว');
      }
      await load();
    } catch (error) { say(error.message, true); }
  });

  /* Ordering lives with the stock it fills. */
  const home = document.querySelector('#view-inventory');
  if (home) home.append(panel);

  const update = () => {
    const role = window.poswaiAuth?.current?.role;
    const allowed = ['owner', 'manager', 'kitchen'].includes(role);
    const wasHidden = panel.hidden;
    panel.hidden = !allowed;
    if (allowed && wasHidden) {
      if (!at('poLines').children.length) lineRow();
      load();
    }
  };
  window.addEventListener('poswai:auth-changed', update);
  update();
})();
