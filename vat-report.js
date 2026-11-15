/* รายงานภาษีขาย ภ.พ.30 และไฟล์ส่งบัญชี

   ร้านที่จดทะเบียน VAT ต้องทำรายงานภาษีขายทุกเดือนและยื่น ภ.พ.30 ภายในวันที่ 15
   ของเดือนถัดไป ของเดิมร้านต้องไล่บิลทีละใบจากหน้ารายงานยอดขายแล้วพิมพ์ลง Excel
   เอง ซึ่งนอกจากกินเวลาทั้งวันแล้ว ยังเป็นที่ที่ตัวเลขเพี้ยนได้เงียบ ๆ

   หน้านี้แสดงรายงานตามรูปแบบที่สรรพากรกำหนด (ประกาศอธิบดีฯ ฉบับที่ 89) และโหลด
   เป็นไฟล์ได้สองแบบ: รายงานภาษีขายสำหรับยื่น และไฟล์รายบิลสำหรับส่งบัญชี

   เจ้าของกับผู้จัดการเท่านั้น เพราะนี่คือยอดขายทั้งเดือนของร้าน */
(() => {
  const host = document.querySelector('#view-analytics');
  if (!host) return;
  const auth = () => window.poswaiAuth || {};
  const branch = () => auth().branchId || 1;
  const role = () => auth().current?.role || '';
  const mayRead = () => ['owner', 'manager'].includes(role());
  const money = value => Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2});

  const style = document.createElement('style');
  style.textContent = `
  .vat-panel{background:#fff;border:1px solid #e6e8eb;border-radius:16px;padding:18px;margin:0 0 20px}
  .vat-panel h3{margin:0 0 4px;font-size:1rem;color:#141b24}
  .vat-panel p.vat-lead{margin:0 0 14px;color:#6b7280;font-size:.84rem;line-height:1.6}
  .vat-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
  .vat-bar input{padding:7px 10px;border:1px solid #e0e3e7;border-radius:9px;font:inherit;font-size:.82rem}
  .vat-bar button{padding:7px 14px;border:0;border-radius:9px;font:inherit;font-size:.82rem;font-weight:700;cursor:pointer;background:#eef1f4;color:#273142}
  .vat-bar button.go{background:#111827;color:#fff}
  .vat-bar button:disabled{opacity:.45;cursor:not-allowed}
  .vat-head{display:grid;gap:2px;padding:11px 13px;background:#f8fafb;border:1px solid #eceff2;border-radius:11px;font-size:.82rem;color:#374151;margin-bottom:11px}
  .vat-head strong{color:#141b24}
  .vat-sum{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:12px}
  .vat-card{flex:1;min-width:150px;padding:11px 13px;border:1px solid #eceff2;border-radius:11px}
  .vat-card small{display:block;color:#6b7280;font-size:.78rem;margin-bottom:2px}
  .vat-card b{font-size:1.02rem;color:#141b24}
  .vat-card.tax{background:#fffdf5;border-color:#f3e2bb}
  .vat-scroll{overflow:auto;max-height:420px;border:1px solid #eceff2;border-radius:11px}
  .vat-table{border-collapse:collapse;width:100%;font-size:.8rem}
  .vat-table th,.vat-table td{padding:7px 9px;border-bottom:1px solid #f0f2f4;text-align:left;white-space:nowrap}
  .vat-table th{background:#f8fafb;position:sticky;top:0;color:#374151;font-weight:700}
  .vat-table td.num{text-align:right;font-variant-numeric:tabular-nums}
  .vat-table tr.credit td{color:#c0372b}
  .vat-table tfoot td{font-weight:700;background:#f8fafb;border-top:1px solid #e0e3e7}
  .vat-note{margin:11px 0 0;font-size:.84rem;min-height:1.2em}
  .vat-note.bad{color:#c0372b}`;
  document.head.append(style);

  const panel = document.createElement('section');
  panel.className = 'vat-panel';
  panel.innerHTML = `
    <h3>รายงานภาษีขาย และ ภ.พ.30</h3>
    <p class="vat-lead">ลงรายการตามที่สรรพากรกำหนด — ใบกำกับภาษีเต็มรูปลงเป็นรายใบ บิลอย่างย่อลงยอดรวมวันละแถวพร้อมช่วงเลขที่ และใบลดหนี้ลงเป็นยอดติดลบ · ยื่น ภ.พ.30 ภายในวันที่ 15 ของเดือนถัดไป</p>
    <div class="vat-bar">
      <input type="month" id="vatMonth" />
      <button type="button" class="go" id="vatGo">ดูรายงาน</button>
      <button type="button" id="vatCsv">โหลดรายงานภาษีขาย (CSV)</button>
      <button type="button" id="vatBills">โหลดไฟล์รายบิลให้บัญชี (CSV)</button>
    </div>
    <div class="vat-head" id="vatHead" hidden></div>
    <div class="vat-sum" id="vatSum" hidden></div>
    <div class="vat-scroll" id="vatScroll" hidden><table class="vat-table" id="vatTable"></table></div>
    <p class="vat-note" id="vatNote" role="status"></p>`;
  host.append(panel);

  const byId = id => panel.querySelector(`#${id}`);
  const note = (text, kind = '') => {
    const element = byId('vatNote');
    element.textContent = text;
    element.className = `vat-note ${kind}`;
  };

  const month = () => byId('vatMonth').value ||
    new Date().toISOString().slice(0, 7);

  const show = (data) => {
    const head = byId('vatHead');
    head.hidden = false;
    head.replaceChildren();
    for (const [label, value] of [['ชื่อผู้ประกอบการ', data.seller.name],
                                  ['เลขประจำตัวผู้เสียภาษี', data.seller.tax_id],
                                  ['สถานประกอบการ', `${data.seller.branch_name} · ${data.seller.place}`],
                                  ['เดือนภาษี', data.month]]) {
      const line = document.createElement('div');
      const name = document.createElement('span');
      name.textContent = `${label}: `;
      const text = document.createElement('strong');
      text.textContent = value || '—';
      line.append(name, text);
      head.append(line);
    }

    const sum = byId('vatSum');
    sum.hidden = false;
    sum.replaceChildren();
    /* ยอดเงินแสดงเป็นเงินเสมอ แม้ลงท้ายด้วยศูนย์ — "660" กับ "฿660.00" คนละอย่าง
       บนหน้าที่เอาเลขไปกรอกแบบยื่นภาษี */
    for (const [label, value, kind] of [
      ['ยอดขายที่เสียภาษี (ก่อน VAT)', data.pp30.taxable_sales, 'baht'],
      [`ภาษีขาย (VAT ${data.pp30.vat_rate}%)`, data.pp30.output_tax, 'tax'],
      ['จำนวนรายการในรายงาน', data.totals.entries, 'count']]) {
      const card = document.createElement('div');
      card.className = `vat-card${kind === 'tax' ? ' tax' : ''}`;
      const name = document.createElement('small');
      name.textContent = label;
      const text = document.createElement('b');
      text.textContent = kind === 'count' ? String(value) : `฿${money(value)}`;
      card.append(name, text);
      sum.append(card);
    }

    byId('vatScroll').hidden = false;
    const table = byId('vatTable');
    table.replaceChildren();
    const header = document.createElement('thead');
    const headRow = document.createElement('tr');
    for (const column of data.columns) {
      const cell = document.createElement('th');
      cell.textContent = column;
      headRow.append(cell);
    }
    header.append(headRow);
    const body = document.createElement('tbody');
    if (!data.rows.length) {
      const empty = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = data.columns.length;
      cell.textContent = 'เดือนนี้ยังไม่มียอดขาย';
      empty.append(cell);
      body.append(empty);
    }
    for (const row of data.rows) {
      const line = document.createElement('tr');
      if (row.kind === 'credit') line.className = 'credit';
      for (const [value, numeric] of [[row.no, false], [row.day, false], [row.number, false],
                                      [row.buyer, false], [row.buyer_tax_id, false],
                                      [row.place, false], [money(row.value), true],
                                      [money(row.vat), true]]) {
        const cell = document.createElement('td');
        if (numeric) cell.className = 'num';
        cell.textContent = value === '' || value === null || value === undefined ? '—' : value;
        line.append(cell);
      }
      body.append(line);
    }
    const foot = document.createElement('tfoot');
    const footRow = document.createElement('tr');
    const label = document.createElement('td');
    label.colSpan = 6;
    label.textContent = 'รวม';
    const value = document.createElement('td');
    value.className = 'num';
    value.textContent = money(data.totals.value);
    const vat = document.createElement('td');
    vat.className = 'num';
    vat.textContent = money(data.totals.vat);
    footRow.append(label, value, vat);
    foot.append(footRow);
    table.append(header, body, foot);
  };

  const load = async () => {
    note('กำลังรวมยอดของเดือนนี้…');
    try {
      const response = await fetch(
        `/api/reports/vat-sales?branch_id=${branch()}&month=${encodeURIComponent(month())}`,
        {credentials: 'same-origin', cache: 'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `อ่านรายงานไม่สำเร็จ (${response.status})`);
      byId('vatMonth').value = data.month;
      show(data);
      note('');
    } catch (error) {
      byId('vatHead').hidden = byId('vatSum').hidden = byId('vatScroll').hidden = true;
      note(error.message, 'bad');
    }
  };

  /* ให้เบราว์เซอร์โหลดไฟล์เอง เพราะเส้นทางส่งหัว Content-Disposition มาอยู่แล้ว
     และไฟล์ CSV ภาษาไทยที่ประกอบเองในหน้าเว็บคือที่ที่ BOM หายไป */
  const download = path => { window.location.href = path; };

  byId('vatGo').addEventListener('click', () => load().catch(() => {}));
  byId('vatCsv').addEventListener('click', () => download(
    `/api/reports/vat-sales?branch_id=${branch()}&month=${encodeURIComponent(month())}&download=csv`));
  byId('vatBills').addEventListener('click', () => {
    const [year, number] = month().split('-').map(Number);
    const last = new Date(Date.UTC(year, number, 0)).toISOString().slice(0, 10);
    download(`/api/reports/bills-export?branch_id=${branch()}`
             + `&start=${year}-${String(number).padStart(2, '0')}-01&end=${last}`);
  });

  const sync = () => {
    panel.hidden = !mayRead();
    if (!panel.hidden && !byId('vatMonth').value) load().catch(() => {});
  };
  window.addEventListener('poswai:auth-changed', sync);
  sync();
})();
