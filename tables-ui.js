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
    /* A bar built for the guest, not the staff nav filtered down to one */
    '.tbl-bar{position:fixed;left:0;right:0;bottom:0;z-index:65;display:grid;grid-template-columns:repeat(3,1fr);',
    'background:#fff;border-top:1px solid #e5e7eb;box-shadow:0 -6px 20px #11182714;padding-bottom:env(safe-area-inset-bottom)}',
    '.tbl-bar button{display:grid;justify-items:center;gap:3px;padding:9px 4px 10px;background:none;border:0;cursor:pointer;',
    'color:#6b7280;font-size:.72rem;font-weight:700;line-height:1.3;position:relative}',
    '.tbl-bar button.on{color:#141b24}',
    '.tbl-bar .glyph{font-size:1.2rem;line-height:1}',
    '.tbl-bar .dot{position:absolute;top:5px;right:calc(50% - 20px);min-width:17px;height:17px;border-radius:999px;',
    'background:#c0372b;color:#fff;font-size:.66rem;display:grid;place-items:center;padding:0 4px}',
    '.tbl-member-hero{text-align:center;padding:18px 0 6px}',
    '.tbl-member-hero span{display:block;color:#6b7280;font-size:.84rem}',
    '.tbl-member-hero strong{display:block;font-size:2.6rem;line-height:1.2;color:#15803d}',
    '.tbl-member-hero em{display:block;font-style:normal;font-weight:700;font-size:1.05rem;margin-top:4px}',
    '.tbl-member-facts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0 0}',
    '.tbl-member-facts div{background:#f7f9fc;border-radius:12px;padding:11px 8px;text-align:center}',
    '.tbl-member-facts b{display:block;font-size:1.05rem}',
    '.tbl-member-facts small{color:#6b7280;font-size:.72rem}',
    '.tbl-member-list{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:7px}',
    '.tbl-member-list li{display:flex;justify-content:space-between;gap:10px;border:1px solid #eef1f5;',
    'border-radius:11px;padding:9px 12px;font-size:.85rem}',
    '.tbl-member-list li b{color:#15803d}.tbl-member-list li b.down{color:#c0372b}',
    '.tbl-member-cta{display:block;width:100%;margin:14px 0 0;padding:13px 18px;background:#ffc928;color:#141b24;',
    'border:0;border-radius:11px;font-weight:700;font-size:.95rem;cursor:pointer}',
    '.tbl-order{border:1px solid #e9edf2;border-radius:13px;padding:12px;margin:0 0 10px}',
    '.tbl-order-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:7px}',
    '.tbl-order-head strong{font-size:.9rem}',
    '.tbl-order small{color:#6b7280;font-size:.78rem}',
    '.tbl-chip{padding:3px 10px;border-radius:999px;font-size:.72rem;font-weight:700;white-space:nowrap}',
    '.tbl-chip.sent{background:#eef2f7;color:#44536a}.tbl-chip.held{background:#fff3cd;color:#8a6100}',
    '.tbl-chip.cooking{background:#fff0e6;color:#9a4b00}.tbl-chip.ready{background:#e8f6ed;color:#15803d}',
    '.tbl-order-wrong{margin-top:9px;width:100%;padding:9px;background:#fdeae7;color:#c0372b;border:0;',
    'border-radius:9px;font-weight:700;cursor:pointer;font-size:.82rem}',
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
    '.tbl-pay .slip-pick{width:100%;padding:12px;border:2px dashed #c9d2dc;border-radius:11px;background:#fff;',
    'color:#44536a;font-weight:700;font-size:.9rem;cursor:pointer;text-align:center;font-family:inherit}',
    '.tbl-pay .slip-pick.has{border-style:solid;border-color:#15803d;color:#15803d;background:#f3fbf6}',
    '.tbl-pay input[type=file]{position:absolute;opacity:0;width:0;height:0}',
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
  /* A QR goes on a table for customers' phones, so it must name the public
     server. Inside the POS WAI app this page lives at https://localhost,
     which means nothing to anyone else's phone. */
  const absolute = link => new URL(link, window.POSWAI_APP?.server || location.origin).href;

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
    <div id="tblOrderList"></div>
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
    const lines = sheet.querySelector('#tblOrderList');
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
      updateBadge();
      return;
    }
    for (const order of bill.orders) {
      lines.append(orderCard(order));
    }
    renderPay(payBox);
    updateBadge();
  };

  const KITCHEN = {
    sent: ['ส่งเข้าครัวแล้ว', 'sent'],
    held: ['พักไว้ก่อน', 'held'],
    cooking: ['กำลังทำ', 'cooking'],
    ready: ['พร้อมเสิร์ฟ', 'ready'],
  };

  /* One order the guest placed, with what the kitchen has done about it and
     a way out if they ordered the wrong thing. The guest never cancels the
     order themselves: the food may already be in a pan, and only the shop
     can decide that. So this raises a call, exactly like waving a hand. */
  const orderCard = order => {
    const card = document.createElement('article');
    card.className = 'tbl-order';
    const head = document.createElement('div');
    head.className = 'tbl-order-head';
    const left = document.createElement('div');
    const code = document.createElement('strong');
    code.textContent = window.shortOrderNo ? window.shortOrderNo(order.order_no) : order.order_no;
    const when = document.createElement('small');
    when.textContent = ' · ' + new Date(order.created_at + 'Z').toLocaleTimeString('th-TH', {hour: '2-digit', minute: '2-digit'});
    left.append(code, when);
    const [label, tone] = KITCHEN[order.kitchen] || KITCHEN.sent;
    const chip = document.createElement('span');
    chip.className = 'tbl-chip ' + tone;
    chip.textContent = label;
    head.append(left, chip);
    card.append(head);
    for (const item of order.items || []) {
      const row = document.createElement('div');
      row.className = 'tbl-line';
      const name = document.createElement('span');
      name.textContent = `${item.name} × ${Number(item.qty)}`;
      const price = document.createElement('span');
      price.textContent = money(Number(item.price) * Number(item.qty));
      row.append(name, price);
      card.append(row);
    }
    if (order.kitchen !== 'ready') {
      const wrong = document.createElement('button');
      wrong.type = 'button';
      wrong.className = 'tbl-order-wrong';
      wrong.textContent = 'สั่งผิด? แจ้งพนักงาน';
      wrong.addEventListener('click', async () => {
        wrong.disabled = true;
        const short = window.shortOrderNo ? window.shortOrderNo(order.order_no) : order.order_no;
        try {
          await window.sendTableServiceCall(`ขอแก้ไขออเดอร์ ${short}`);
          wrong.textContent = 'แจ้งพนักงานแล้ว กำลังมาหาคุณ';
        } catch (error) {
          wrong.disabled = false;
          billStatus(error.message);
        }
      });
      card.append(wrong);
    }
    return card;
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
    file.id = 'tblSlipFile';
    file.setAttribute('aria-label', 'รูปสลิปโอนเงิน');
    const pick = document.createElement('label');
    pick.className = 'slip-pick';
    pick.htmlFor = file.id;
    pick.textContent = '📷 แตะเพื่อแนบรูปสลิปโอนเงิน';
    file.addEventListener('change', () => {
      const chosen = file.files?.[0];
      pick.classList.toggle('has', !!chosen);
      pick.textContent = chosen ? `✅ แนบแล้ว: ${chosen.name}` : '📷 แตะเพื่อแนบรูปสลิปโอนเงิน';
    });
    const send = document.createElement('button');
    send.type = 'button';
    send.textContent = 'ส่งสลิปและปิดบิล';
    send.addEventListener('click', () => paySlip(file, send));
    box.append(hint, pick, file, send);
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

  openButton.addEventListener('click', () => openSheet('orders'));

  /* The guest's own bottom bar. The staff navigation filtered down to the one
     tab a customer may open, left-aligned and alone, looked like a half-built
     screen; this is four things a person at a table actually wants. */
  const bar = document.createElement('nav');
  bar.className = 'tbl-bar';
  bar.hidden = true;
  bar.setAttribute('aria-label', 'เมนูลูกค้า');
  const TABS = [
    {key: 'menu', glyph: '🍽️', label: 'สั่งอาหาร'},
    /* Only a phone sitting at a table has a bill to read or to settle. */
    {key: 'orders', glyph: '🧾', label: 'ออเดอร์ของฉัน', table: true},
    {key: 'pay', glyph: '💳', label: 'จ่ายเงิน', table: true},
    {key: 'member', glyph: '⭐', label: 'สมาชิก'},
  ];
  const barButtons = {};
  for (const tab of TABS) {
    const button = document.createElement('button');
    button.type = 'button';
    const glyph = document.createElement('span');
    glyph.className = 'glyph';
    glyph.textContent = tab.glyph;
    const label = document.createElement('span');
    label.textContent = tab.label;
    button.append(glyph, label);
    button.addEventListener('click', () => pickTab(tab.key));
    barButtons[tab.key] = button;
    bar.append(button);
  }
  const badge = document.createElement('span');
  badge.className = 'dot';
  badge.hidden = true;
  barButtons.orders.append(badge);

  const updateBadge = () => {
    const waiting = bill.orders.filter(order => order.kitchen !== 'ready').length;
    badge.textContent = String(waiting);
    badge.hidden = waiting === 0;
  };

  /* ---- the member's own page ------------------------------------------
     A loyalty card is something a customer opens on purpose and reads: how
     many points, from what, since when. It had been a small dialog with a
     number in it, which is what the shop needs at the till, not what the
     customer came for. */
  const memberSheet = document.createElement('div');
  memberSheet.className = 'tbl-sheet';
  memberSheet.hidden = true;
  memberSheet.innerHTML = `<div class="tbl-sheet-body">
    <div class="tbl-sheet-head"><h3>สมาชิกร้าน</h3>
      <button type="button" class="ghost" id="tblMemberClose">ปิด</button></div>
    <div id="tblMemberBody"></div>
  </div>`;
  const closeMember = () => { memberSheet.hidden = true; markTab('menu'); };
  memberSheet.addEventListener('click', event => { if (event.target === memberSheet) closeMember(); });
  memberSheet.querySelector('#tblMemberClose').addEventListener('click', closeMember);

  const thaiDate = text => {
    const when = new Date(String(text || '').replace(' ', 'T'));
    return Number.isNaN(when.getTime()) ? '' : when.toLocaleDateString('th-TH',
      {day: 'numeric', month: 'short', year: '2-digit'});
  };

  const renderMember = card => {
    const body = memberSheet.querySelector('#tblMemberBody');
    body.replaceChildren();
    if (!card) {
      const note = document.createElement('p');
      note.className = 'tbl-note';
      note.textContent = 'สะสมแต้มทุกครั้งที่ซื้อ และรับโปรโมชันจากร้าน '
        + 'เข้าสู่ระบบด้วย LINE, Google หรือชื่อกับเบอร์ที่เคยให้ไว้';
      const cta = document.createElement('button');
      cta.type = 'button';
      cta.className = 'tbl-member-cta';
      cta.textContent = 'เข้าสู่ระบบ / สมัครสมาชิก';
      cta.addEventListener('click', () => { closeMember(); window.poswaiAuth?.openMember?.(); });
      body.append(note, cta);
      return;
    }
    const hero = document.createElement('div');
    hero.className = 'tbl-member-hero';
    hero.innerHTML = '<span>แต้มสะสม</span>';
    const points = document.createElement('strong');
    points.textContent = `${card.points ?? 0}`;
    const who = document.createElement('em');
    who.textContent = card.display_name || 'สมาชิกร้าน';
    hero.append(points, who);

    const facts = document.createElement('div');
    facts.className = 'tbl-member-facts';
    for (const [value, label] of [
      [`${card.completed_orders ?? 0}`, 'ครั้งที่ซื้อ'],
      [money(card.lifetime_amount || 0), 'ยอดสะสม'],
      [thaiDate(card.member_since) || '—', 'เป็นสมาชิกตั้งแต่'],
    ]) {
      const cell = document.createElement('div');
      const big = document.createElement('b');
      big.textContent = value;
      const small = document.createElement('small');
      small.textContent = label;
      cell.append(big, small);
      facts.append(cell);
    }

    const how = document.createElement('p');
    how.className = 'tbl-note';
    how.textContent = `ทุก ${card.point_baht ?? 10} บาทที่จ่าย ได้ 1 แต้ม `
      + 'บอกเบอร์กับพนักงานตอนจ่ายเงินเพื่อให้แต้มเข้า';

    const title = document.createElement('p');
    title.className = 'tbl-note';
    title.textContent = 'รายการแต้มล่าสุด';
    const list = document.createElement('ul');
    list.className = 'tbl-member-list';
    for (const entry of card.history || []) {
      const row = document.createElement('li');
      const reason = document.createElement('span');
      reason.textContent = entry.reason || 'แต้ม';
      const change = document.createElement('b');
      change.textContent = `${entry.change > 0 ? '+' : ''}${entry.change}`;
      if (entry.change < 0) change.className = 'down';
      row.append(reason, change);
      list.append(row);
    }
    if (!(card.history || []).length) {
      const empty = document.createElement('p');
      empty.className = 'tbl-empty';
      empty.textContent = 'ยังไม่มีรายการแต้ม แต้มแรกมาจากบิลแรกที่จ่าย';
      list.append(empty);
    }

    const out = document.createElement('button');
    out.type = 'button';
    out.className = 'tbl-member-cta';
    out.style.background = '#f1f4f8';
    out.textContent = 'ออกจากระบบ';
    out.addEventListener('click', () => { closeMember(); window.poswaiAuth?.signOutMember?.(); });
    body.append(hero, facts, how, title, list, out);
  };

  const openMemberPage = async () => {
    memberSheet.hidden = false;
    markTab('member');
    const known = window.poswaiAuth?.member;
    renderMember(known || null);
    if (!known) return;
    /* The points may have moved since this phone last looked. */
    try {
      const response = await fetch('/api/members/card', {cache: 'no-store', credentials: 'same-origin',
        headers: known.token ? {'X-Member-Token': known.token} : {}});
      if (response.ok) renderMember({...known, ...(await response.json())});
    } catch (_) { /* offline: what the phone already had still reads fine */ }
  };
  window.poswaiMemberPage = {open: openMemberPage};

  const markTab = key => {
    for (const tab of TABS) barButtons[tab.key].classList.toggle('on', tab.key === key);
  };

  const showTabs = atTable => {
    let shown = 0;
    for (const tab of TABS) {
      const on = !tab.table || atTable;
      barButtons[tab.key].hidden = !on;
      if (on) shown += 1;
    }
    bar.style.gridTemplateColumns = `repeat(${shown}, 1fr)`;
  };

  const openSheet = where => {
    sheet.hidden = false;
    markTab(where);
    loadBill().then(() => {
      const body = sheet.querySelector('.tbl-sheet-body');
      const target = where === 'pay' ? sheet.querySelector('#tblPayBox') : null;
      body.scrollTop = target ? target.offsetTop - 70 : 0;
    });
  };

  const pickTab = async key => {
    memberSheet.hidden = true;
    if (key === 'menu') { sheet.hidden = true; markTab('menu'); window.scrollTo({top: 0, behavior: 'smooth'}); return; }
    if (key === 'member') { sheet.hidden = true; openMemberPage(); return; }
    openSheet(key);
  };
  sheet.addEventListener('click', event => { if (event.target === sheet) markTab('menu'); });
  sheet.querySelector('#tblBillClose').addEventListener('click', () => markTab('menu'));

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
    if (!memberSheet.parentElement) document.body.append(memberSheet);
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
    const staff = !!window.poswaiAuth?.current;
    const atTable = !!tableToken() && !staff;
    /* A customer signed in on their own phone, with no sticker scanned, is
       still a customer: the staff navigation filtered down to one lonely tab
       was never what they should be looking at. */
    const customer = atTable || (!staff && !!window.poswaiAuth?.member);
    openButton.hidden = !atTable;
    if (!atTable) sheet.hidden = true;
    if (!customer) memberSheet.hidden = true;
    bar.hidden = !customer;
    if (!bar.parentElement) document.body.append(bar);
    showTabs(atTable);
    /* The staff navigation has nothing left for a guest once it is filtered,
       so it steps aside rather than sitting there with a single lonely tab. */
    const staffNav = document.querySelector('.role-tabs-wrap');
    if (staffNav) staffNav.hidden = customer;
    document.body.classList.toggle('tbl-guest', customer);
    if (customer && sheet.hidden && memberSheet.hidden) markTab('menu');
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
