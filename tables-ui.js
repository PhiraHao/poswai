/* Tables: the sticker the shop prints, and the bill the guest settles.

   The printed sticker carries no token, only the table's own code. Scanning it
   reaches the server, which mints a short-lived token for that one sitting. So
   a photograph of the paper is worth nothing once the meal is over, and a shop
   that loses a sticker revokes one table instead of reprinting the room. */
(() => {
  const money = value => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const branch = () => window.poswaiAuth?.branchId || 1;
  const tableToken = () => window.poswaiAuth?.tableToken || '';
  const tableNo = () => window.poswaiAuth?.tableNo || '';
  const isManager = () => ['manager', 'owner'].includes(window.poswaiAuth?.current?.role);

  const request = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (tableToken()) headers.set('X-Table-Token', tableToken());
    const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options, headers});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };

  const style = document.createElement('style');
  style.textContent = [
    '.tbl-panel{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:20px;margin:0 0 20px;box-shadow:0 8px 24px #1118270d}',
    '.tbl-panel h3{margin:0 0 6px}.tbl-panel>p{color:#6b7280;margin:0 0 14px}',
    '.tbl-panel form{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;align-items:end;padding:14px 0;border-top:1px solid #eee}',
    '.tbl-panel label{display:grid;gap:5px;font-size:.85rem;font-weight:600}',
    '.tbl-panel input{width:100%;padding:10px;border:1px solid #d1d5db;border-radius:9px}',
    '.tbl-panel button{padding:11px 16px;background:#ffc928;color:#141b24;border:0;border-radius:9px;font-weight:700;cursor:pointer}',
    '.tbl-panel button.ghost{background:#eef2f7}.tbl-panel button.danger{background:#fdeae7;color:#c0372b}',
    '.tbl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px;margin-top:4px}',
    '.tbl-card{border:1px solid #e5e7eb;border-radius:14px;padding:14px;text-align:center;background:#fff}',
    '.tbl-card.off{opacity:.55;background:#fafafa}',
    '.tbl-card h4{margin:0 0 2px;font-size:1.05rem}.tbl-card .seats{color:#6b7280;font-size:.8rem;margin:0 0 10px}',
    '.tbl-card canvas{width:140px;height:140px;image-rendering:pixelated;background:#fff}',
    '.tbl-card .acts{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin-top:10px}',
    '.tbl-card .acts button{padding:7px 10px;font-size:.78rem}',
    '.tbl-pill{display:inline-block;padding:3px 9px;border-radius:999px;font-size:.73rem;font-weight:700;margin-bottom:8px}',
    '.tbl-pill.on{background:#e8f6ed;color:#15803d}.tbl-pill.off{background:#fdeae7;color:#c0372b}',
    '.tbl-note{margin:14px 0 0;font-size:.82rem;color:#6b7280;line-height:1.7}',
    '.tbl-empty{color:#6b7280;padding:22px 0;margin:0}',
    /* The guest's own bill, opened from the ordering screen. */
'.tbl-bill-open{display:block;width:100%;margin:10px 0 0;padding:13px 18px;background:#141b24;color:#ffc928;',
    'border:0;border-radius:11px;font-weight:700;cursor:pointer;font-size:.95rem}',
    '.tbl-sheet{position:fixed;inset:0;z-index:70;background:#0009;display:grid;place-items:end center}',
    '.tbl-sheet[hidden]{display:none}',
    '.tbl-sheet-body{background:#fff;width:min(560px,100%);max-height:88vh;overflow:auto;border-radius:20px 20px 0 0;padding:20px 20px 150px}',
    '.tbl-sheet-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:6px}',
    '.tbl-sheet-head h3{margin:0;font-size:1.15rem}',
    '.tbl-line{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid #f1f3f6;font-size:.92rem}',
    '.tbl-total{display:flex;justify-content:space-between;align-items:baseline;margin:14px 0;font-size:1.15rem;font-weight:800}',
    '.tbl-pay{display:grid;gap:12px;justify-items:center;padding:16px;background:#fbfcfe;border:1px solid #e5e7eb;border-radius:14px}',
    '.tbl-pay canvas{width:220px;height:220px;image-rendering:pixelated;background:#fff}',
    '.tbl-pay small{color:#6b7280;text-align:center;line-height:1.7}',
    '.tbl-pay input[type=file]{width:100%}',
    '.tbl-pay button{width:100%;padding:13px;background:#ffc928;border:0;border-radius:11px;font-weight:700;cursor:pointer}',
    '@media(max-width:560px){.tbl-card canvas{width:120px;height:120px}}',
  ].join('');
  document.head.append(style);

  /* ---- drawing a QR we can also hand to the printer ------------------- */
  const QR_BYTE_LIMIT = 106;   // version 5 holds 108 data bytes, less the header
  const drawQr = (canvas, text) => {
    if (!canvas.id) canvas.id = 'tblQr' + Math.random().toString(36).slice(2);
    if (text.length > QR_BYTE_LIMIT) throw new Error('ลิงก์ยาวเกินกว่าจะทำเป็น QR ได้');
    if (typeof drawQrCodeOnCanvas !== 'function') throw new Error('ยังโหลดตัววาด QR ไม่เสร็จ');
    drawQrCodeOnCanvas(canvas.id, text);
  };
  const absolute = link => new URL(link, location.origin).href;

  /* ================= the shop's side: tables and stickers ============== */
  const panel = document.createElement('section');
  panel.className = 'tbl-panel';
  panel.hidden = true;
  panel.innerHTML = `<h3>โต๊ะและ QR สำหรับติดโต๊ะ</h3>
    <p>พิมพ์ QR ไปติดโต๊ะครั้งเดียว ลูกค้าสแกนแล้วสั่งอาหารและจ่ายเงินเองได้ · QR ไม่มีวันหมดอายุ แต่ยกเลิกรายโต๊ะได้ทุกเมื่อ</p>
    <form id="tblAddForm">
      <label>ชื่อหรือเลขโต๊ะ <input name="table_no" required maxlength="24" placeholder="เช่น 1, A3, ระเบียง"></label>
      <label>จำนวนที่นั่ง <input name="seats" type="number" min="0" max="999" value="0"></label>
      <label>หมายเหตุ <input name="note" maxlength="120" placeholder="เช่น ริมหน้าต่าง"></label>
      <button type="submit">เพิ่มโต๊ะ</button>
    </form>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 14px">
      <button type="button" class="ghost" id="tblPrintAll">พิมพ์ QR ทุกโต๊ะ</button>
    </div>
    <div class="tbl-grid" id="tblGrid"></div>
    <p class="tbl-note">ถ้ามีคนถ่ายรูป QR ของโต๊ะไหนไป ให้กด <strong>ออกรหัสใหม่</strong> เฉพาะโต๊ะนั้น แผ่นที่ติดโต๊ะอื่นยังใช้ได้ตามปกติ · การ <strong>ยกเลิก</strong> จะปิด QR ไว้ชั่วคราวโดยไม่เปลี่ยนรหัส กดคืนสิทธิ์แล้วแผ่นเดิมกลับมาใช้ได้</p>
    <p id="tblStatus" role="status"></p>`;

  const status = message => { panel.querySelector('#tblStatus').textContent = message; };
  let tables = [];

  const renderTables = () => {
    const grid = panel.querySelector('#tblGrid');
    if (!tables.length) {
      const empty = document.createElement('p');
      empty.className = 'tbl-empty';
      empty.textContent = 'ยังไม่มีโต๊ะ เพิ่มโต๊ะแรกจากฟอร์มด้านบนได้เลย';
      grid.replaceChildren(empty);
      return;
    }
    grid.replaceChildren(...tables.map(table => {
      const card = document.createElement('article');
      card.className = 'tbl-card' + (table.active ? '' : ' off');
      const pill = document.createElement('span');
      pill.className = 'tbl-pill ' + (table.active ? 'on' : 'off');
      pill.textContent = table.active ? 'ใช้งานได้' : 'ยกเลิกแล้ว';
      const title = document.createElement('h4');
      title.textContent = `โต๊ะ ${table.table_no}`;
      const seats = document.createElement('p');
      seats.className = 'seats';
      seats.textContent = [table.seats ? `${table.seats} ที่นั่ง` : '', table.note].filter(Boolean).join(' · ') || ' ';
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 140;
      /* Drawn after the grid is in the document: the encoder finds its canvas
         by id, so a card still being built has nothing to draw on. */
      canvas.dataset.link = absolute(table.link);
      card.append(pill, title, seats, canvas);
      const acts = document.createElement('div');
      acts.className = 'acts';
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = table.active ? 'danger' : 'ghost';
      toggle.textContent = table.active ? 'ยกเลิก' : 'คืนสิทธิ์';
      toggle.addEventListener('click', () => act(
        () => request(`/api/tables/${encodeURIComponent(table.table_no)}`, {method: 'PATCH',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({branch_id: branch(), active: !table.active})}),
        table.active ? `ยกเลิก QR โต๊ะ ${table.table_no} แล้ว` : `เปิด QR โต๊ะ ${table.table_no} แล้ว`));
      const reissue = document.createElement('button');
      reissue.type = 'button'; reissue.className = 'ghost'; reissue.textContent = 'ออกรหัสใหม่';
      reissue.addEventListener('click', () => {
        if (!window.confirm(`ออกรหัสใหม่ให้โต๊ะ ${table.table_no}?\nแผ่น QR ที่ติดโต๊ะนี้อยู่จะใช้ไม่ได้ทันที ต้องพิมพ์ใหม่`)) return;
        act(() => request(`/api/tables/${encodeURIComponent(table.table_no)}/reissue?branch_id=${branch()}`,
          {method: 'POST'}), `ออกรหัสใหม่ให้โต๊ะ ${table.table_no} แล้ว อย่าลืมพิมพ์ไปติดใหม่`);
      });
      const print = document.createElement('button');
      print.type = 'button'; print.className = 'ghost'; print.textContent = 'พิมพ์';
      print.addEventListener('click', () => printSheet([table]));
      const drop = document.createElement('button');
      drop.type = 'button'; drop.className = 'danger'; drop.textContent = 'ลบ';
      drop.addEventListener('click', () => {
        if (!window.confirm(`ลบโต๊ะ ${table.table_no} ออกจากระบบ?`)) return;
        act(() => request(`/api/tables/${encodeURIComponent(table.table_no)}?branch_id=${branch()}`,
          {method: 'DELETE'}), `ลบโต๊ะ ${table.table_no} แล้ว`);
      });
      acts.append(toggle, reissue, print, drop);
      card.append(acts);
      return card;
    }));
    for (const canvas of grid.querySelectorAll('canvas[data-link]')) {
      try { drawQr(canvas, canvas.dataset.link); }
      catch (error) {
        const problem = document.createElement('p');
        problem.className = 'tbl-empty';
        problem.textContent = error.message;
        canvas.replaceWith(problem);
      }
    }
  };

  const load = async () => {
    try {
      tables = (await request(`/api/tables?branch_id=${branch()}`)).tables;
      renderTables();
    } catch (error) { status(error.message); }
  };
  const act = async (work, done) => {
    try { await work(); await load(); status(done); }
    catch (error) { status(error.message); }
  };

  panel.querySelector('#tblAddForm').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await request('/api/tables', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({branch_id: branch(), table_no: String(data.get('table_no')).trim(),
                              seats: Number(data.get('seats')) || 0, note: String(data.get('note') || '').trim()})});
      form.reset();
      await load();
      status('เพิ่มโต๊ะแล้ว');
    } catch (error) { status(error.message); }
  });

  /* A print window of its own, so the shop's screen is not what gets printed.
     The codes are rasterised here and sent across as images: the print window
     has no scripts of its own and needs none. */
  const printSheet = list => {
    const usable = list.filter(table => table.active);
    if (!usable.length) { status('โต๊ะที่ยกเลิกแล้วพิมพ์ไม่ได้ กดคืนสิทธิ์ก่อน'); return; }
    const cards = [];
    for (const table of usable) {
      const canvas = document.createElement('canvas');
      canvas.id = 'tblPrint' + Math.random().toString(36).slice(2);
      canvas.width = canvas.height = 220;
      document.body.append(canvas);
      let image = '';
      try { drawQr(canvas, absolute(table.link)); image = canvas.toDataURL('image/png'); }
      catch (error) { status(error.message); canvas.remove(); return; }
      canvas.remove();
      const name = String(table.table_no).replace(/[&<>"]/g, '');
      cards.push(`<article><h2>โต๊ะ ${name}</h2><img src="${image}" alt=""><p>สแกนเพื่อดูเมนู สั่งอาหาร และจ่ายเงิน</p><small>${shopName}</small></article>`);
    }
    const sheet = window.open('', '_blank');
    if (!sheet) { status('เบราว์เซอร์บล็อกหน้าต่างพิมพ์ไว้ กรุณาอนุญาตป๊อปอัปแล้วลองใหม่'); return; }
    sheet.document.write(`<!doctype html><html lang="th"><head><meta charset="utf-8">
      <title>QR โต๊ะ</title><style>
      @page{margin:12mm}
      body{margin:0;font-family:"Noto Sans Thai",system-ui,sans-serif;color:#141b24;
        display:grid;grid-template-columns:repeat(2,1fr);gap:10mm}
      article{border:1.5pt dashed #9aa3ae;border-radius:6mm;padding:8mm 4mm;text-align:center;
        break-inside:avoid;page-break-inside:avoid}
      h2{margin:0 0 4mm;font-size:18pt}
      img{width:55mm;height:55mm;image-rendering:pixelated}
      p{margin:4mm 0 1mm;font-size:11pt;line-height:1.6}
      small{color:#5d6b7a;font-size:9pt}
      </style></head><body>${cards.join('')}</body></html>`);
    sheet.document.close();
    sheet.focus();
    /* Give the browser a tick to lay the images out before the dialog opens. */
    sheet.setTimeout(() => sheet.print(), 400);
  };
  panel.querySelector('#tblPrintAll').addEventListener('click', () => printSheet(tables));

  let shopName = 'POS WAI';

  /* ================= the guest's side: see the bill, pay it ============ */
  const openButton = document.createElement('button');
  openButton.type = 'button';
  openButton.className = 'tbl-bill-open';
  openButton.hidden = true;
  openButton.textContent = '🧾 ดูออเดอร์ที่สั่งไปแล้ว · จ่ายเงิน';

  const sheet = document.createElement('div');
  sheet.className = 'tbl-sheet';
  sheet.hidden = true;
  sheet.innerHTML = `<div class="tbl-sheet-body">
    <div class="tbl-sheet-head"><h3>บิลโต๊ะ <span id="tblBillTable"></span></h3>
      <button type="button" class="ghost" id="tblBillClose">ปิด</button></div>
    <div id="tblBillLines"></div>
    <div class="tbl-total"><span>ยอดที่ต้องชำระ</span><span id="tblBillTotal">฿0.00</span></div>
    <div class="tbl-pay" id="tblPayBox"></div>
    <p id="tblBillStatus" role="status" style="margin:12px 0 0;color:#6b7280"></p>
  </div>`;
  sheet.addEventListener('click', event => { if (event.target === sheet) sheet.hidden = true; });
  sheet.querySelector('#tblBillClose').addEventListener('click', () => { sheet.hidden = true; });

  const billStatus = message => { sheet.querySelector('#tblBillStatus').textContent = message; };
  let bill = {orders: [], total: 0};

  const loadBill = async () => {
    const table = tableNo();
    sheet.querySelector('#tblBillTable').textContent = table;
    const lines = sheet.querySelector('#tblBillLines');
    const payBox = sheet.querySelector('#tblPayBox');
    lines.replaceChildren();
    payBox.replaceChildren();
    billStatus('กำลังโหลดบิล...');
    try {
      const data = await request(`/api/orders?branch_id=${branch()}&table_no=${encodeURIComponent(table)}`);
      bill = {orders: data.orders || [],
              total: (data.orders || []).reduce((sum, order) => sum + Number(order.total_amount || 0), 0)};
    } catch (error) { billStatus(error.message); return; }
    billStatus('');
    sheet.querySelector('#tblBillTotal').textContent = money(bill.total);
    if (!bill.orders.length) {
      const empty = document.createElement('p');
      empty.className = 'tbl-empty';
      empty.textContent = 'โต๊ะนี้ยังไม่มีรายการค้างชำระ';
      lines.append(empty);
      return;
    }
    for (const order of bill.orders) {
      for (const item of order.items || []) {
        const row = document.createElement('div');
        row.className = 'tbl-line';
        const name = document.createElement('span');
        name.textContent = `${item.name} × ${Number(item.qty)}`;
        const price = document.createElement('span');
        price.textContent = money(Number(item.price) * Number(item.qty));
        row.append(name, price);
        lines.append(row);
      }
    }
    renderPay(payBox);
  };

  const renderPay = box => {
    /* Read from the shop's own config rather than from the ordering screen's
       state: a guest's page never enters the staff live mode that fills it. */
    const account = shopPromptPay || state.promptPayId || '';
    if (!account) {
      const note = document.createElement('small');
      note.textContent = 'ร้านยังไม่ได้ตั้งบัญชีพร้อมเพย์ กรุณาเรียกพนักงานเพื่อชำระเงิน';
      box.append(note);
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.id = 'tblPayQr';
    canvas.width = canvas.height = 220;
    box.append(canvas);
    try { drawQrCodeOnCanvas('tblPayQr', generatePromptPayPayload(account, Number(bill.total.toFixed(2)))); }
    catch (error) {
      canvas.remove();
      const note = document.createElement('small');
      note.textContent = `สร้าง QR ไม่สำเร็จ: ${error.message} · โอนเข้าพร้อมเพย์ ${account}`;
      box.append(note);
    }
    const hint = document.createElement('small');
    hint.innerHTML = `สแกนจ่าย <strong>${money(bill.total)}</strong> แล้วแนบรูปสลิปด้านล่าง<br>ระบบจะตรวจยอดและบัญชีผู้รับก่อนปิดบิลให้เอง`;
    const file = document.createElement('input');
    file.type = 'file';
    file.accept = 'image/jpeg,image/png,image/gif,image/webp';
    file.setAttribute('aria-label', 'รูปสลิปโอนเงิน');
    const send = document.createElement('button');
    send.type = 'button';
    send.textContent = 'ส่งสลิปและปิดบิล';
    send.addEventListener('click', () => paySlip(file, send));
    box.append(hint, file, send);
  };

  const paySlip = async (file, button) => {
    const chosen = file.files?.[0];
    if (!chosen) { billStatus('กรุณาเลือกรูปสลิปก่อน'); return; }
    if (chosen.size > 4 * 1024 * 1024) { billStatus('รูปสลิปต้องไม่เกิน 4 MB'); return; }
    const orderNos = bill.orders.map(order => order.order_no).sort();
    if (!orderNos.length || bill.total <= 0) { billStatus('โต๊ะนี้ไม่มียอดค้างชำระ'); return; }
    /* One event id per set of orders, kept for retries: sending the same slip
       twice must close the bill once, not twice. */
    const retryKey = `poswai-table-pay:${orderNos.join(',')}`;
    let eventId = sessionStorage.getItem(retryKey);
    if (!eventId) { eventId = crypto.randomUUID(); sessionStorage.setItem(retryKey, eventId); }
    button.disabled = true;
    button.textContent = 'กำลังตรวจสลิป...';
    billStatus('');
    try {
      const image = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error('อ่านรูปสลิปไม่สำเร็จ'));
        reader.readAsDataURL(chosen);
      });
      await request('/api/payments/close-table', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({event_id: eventId, branch_id: branch(), table_no: tableNo(),
                              order_nos: orderNos, amount: Number(bill.total.toFixed(2)), slip_image: image})});
      sessionStorage.removeItem(retryKey);
      billStatus('ชำระเงินเรียบร้อย ขอบคุณครับ');
      sheet.querySelector('#tblPayBox').replaceChildren();
      if (window.poswaiLiveData) await window.poswaiLiveData.refresh();
      window.setTimeout(() => { sheet.hidden = true; }, 2500);
    } catch (error) {
      /* Whatever went wrong, the guest still wants to pay and leave. Tell them
         the way that always works: show the slip to someone who works here. */
      billStatus(`${error.message} · แจ้งพนักงานเพื่อปิดบิลให้ได้เลย`);
      button.disabled = false;
      button.textContent = 'ส่งสลิปและปิดบิล';
    }
  };

  openButton.addEventListener('click', () => { sheet.hidden = false; loadBill(); });

  /* ---- mounting -------------------------------------------------------- */
  const mount = () => {
    /* Tables live where tables are worked with. The stock tab is ingredients
       and dishes; a table is neither, and the cashier screen is where the
       shop already looks at its tables all day. */
    const home = document.querySelector('#view-cashier') || document.querySelector('#view-inventory');
    if (home && !panel.parentElement) {
      /* Below the day's work, above the shop's settings: printing stickers is
         a job for opening day, not for the middle of service. */
      const settings = home.querySelector('.live-catalog-panel');
      if (settings) settings.before(panel); else home.append(panel);
    }
    if (!sheet.parentElement) document.body.append(sheet);
    /* In the cart, under "send order": the guest is already looking there once
       the food is ordered, and the next thing they want is the bill. Floating
       it could not work — the app's own fixed bars cover that strip of screen,
       so the button was visible to the DOM and invisible to the customer. */
    const cartButton = document.querySelector('#view-customer button[onclick*="submitOrderFromCustomer"]');
    if (cartButton) {
      if (openButton.previousElementSibling !== cartButton) cartButton.after(openButton);
    } else if (!openButton.parentElement) document.body.append(openButton);
  };

  /* A scanned phone orders for the table it is sitting at, and for no other.
     The server refuses anything else anyway; the screen should not offer it. */
  const lockTable = () => {
    const table = tableNo();
    if (!table || window.poswaiAuth?.current) return;
    state.customerTable = table;
    const select = document.getElementById('customerTableSelect');
    if (!select) return;
    if (![...select.options].some(option => option.value === table)) {
      select.append(new Option(`โต๊ะ ${table}`, table));
    }
    select.value = table;
    select.disabled = true;
    select.title = 'โต๊ะนี้มาจาก QR ที่สแกน';
  };

  const sync = () => {
    mount();
    panel.hidden = !isManager();
    if (!panel.hidden && !tables.length) load();
    /* The guest's button belongs to a phone that scanned a sticker, not to a
       member of staff looking at the same screen. */
    openButton.hidden = !tableToken() || !!window.poswaiAuth?.current;
    if (openButton.hidden) sheet.hidden = true;
    lockTable();
  };

  let shopPromptPay = '';
  fetch('/api/config', {cache: 'no-store'}).then(response => response.json())
    .then(config => {
      shopName = config.shop?.name || config.shop_name || 'POS WAI';
      shopPromptPay = config.promptpay_id || '';
    })
    .catch(() => { /* the printed sheet simply says POS WAI */ });

  window.addEventListener('poswai:auth-changed', sync);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sync);
  else sync();
  window.poswaiTables = {reload: load};
})();
