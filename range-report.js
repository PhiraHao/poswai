/* รายงานยอดขายตามช่วงวันที่ — the month, not just today.

   The analytics screen answers "how is today going". An owner closing the
   month needs the other question: what did these thirty days do, which dishes
   earned their place, and who sold them. */
(() => {
  const money = (value) => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const text = (value) => String(value ?? '').replace(/[<>&]/g, '');

  const ask = async (path) => {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin'});
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
      throw new Error(detail);
    }
    return response.json();
  };

  const panel = document.createElement('section');
  panel.className = 'card range-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="card-header"><div class="card-title">📅 ยอดขายตามช่วงวันที่</div></div>
    <p class="shift-hint">เลือกช่วงวันแล้วกดดู · ว่างไว้ = 30 วันล่าสุด</p>
    <div class="shift-row">
      <label for="rangeStart">ตั้งแต่</label><input id="rangeStart" type="date" class="input">
      <label for="rangeEnd">ถึง</label><input id="rangeEnd" type="date" class="input">
      <button type="button" class="btn btn-line" id="rangeGo">ดูรายงาน</button>
      <button type="button" class="btn btn-outline" id="rangeCsv">ดาวน์โหลด Excel/CSV</button>
    </div>
    <div class="range-figures" id="rangeFigures"></div>
    <p class="range-incomplete" id="rangeIncomplete"></p>
    <div class="range-tables" id="rangeTables"></div>
    <p id="rangeStatus" role="status" class="shift-status"></p>`;

  const at = (id) => panel.querySelector(`#${id}`);
  const branch = () => window.poswaiAuth?.branchId || 1;
  const query = () => {
    const parts = [`branch_id=${branch()}`];
    if (at('rangeStart').value) parts.push(`start=${at('rangeStart').value}`);
    if (at('rangeEnd').value) parts.push(`end=${at('rangeEnd').value}`);
    return parts.join('&');
  };

  const table = (caption, columns, rows) =>
    `<table><caption>${caption}</caption><thead><tr>${
      columns.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${
      rows.join('') || `<tr><td colspan="${columns.length}">ไม่มีข้อมูลในช่วงนี้</td></tr>`
    }</tbody></table>`;

  const draw = (report) => {
    at('rangeFigures').innerHTML = [
      ['ยอดขายรวม', money(report.revenue)],
      ['จำนวนบิล', `${report.bills} บิล`],
      ['เฉลี่ยต่อบิล', money(report.average_bill)],
      ['กำไรขั้นต้น', money(report.profit.gross_profit)],
      ['อัตรากำไร', report.profit.margin_percent === null ? '—' : `${report.profit.margin_percent}%`],
    ].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join('');

    /* Sales whose cost was never filled in are named, not folded into the
       profit as if the shop got them for free. */
    at('rangeIncomplete').textContent = report.profit.complete ? ''
      : `กำไรข้างบนคิดจากเฉพาะรายการที่ใส่ต้นทุนไว้ · ยังมียอดขาย ${money(report.profit.revenue_without_cost)} ที่ยังไม่รู้ต้นทุน ใส่ต้นทุนในหน้าสต็อกแล้วตัวเลขจะครบ`;

    at('rangeTables').innerHTML = [
      table('รายวัน', ['วันที่', 'บิล', 'ยอดขาย'],
        report.by_day.map(d => `<tr><td>${text(d.date)}</td><td>${d.bills}</td><td>${money(d.revenue)}</td></tr>`)),
      table('ช่องทางชำระ', ['ช่องทาง', 'บิล', 'ยอดขาย'],
        report.by_method.map(m => `<tr><td>${text(m.method)}</td><td>${m.bills}</td><td>${money(m.revenue)}</td></tr>`)),
      table('พนักงาน', ['ชื่อ', 'บิล', 'ยอดขาย'],
        report.by_staff.map(s => `<tr><td>${text(s.name)}</td><td>${s.bills}</td><td>${money(s.revenue)}</td></tr>`)),
      table('หมวด', ['หมวด', 'จำนวน', 'ยอดขาย'],
        report.by_category.map(c => `<tr><td>${text(c.category)}</td><td>${c.qty}</td><td>${money(c.revenue)}</td></tr>`)),
      table('รายการที่ขายดี', ['ชื่อ', 'จำนวน', 'ยอดขาย', 'กำไร'],
        report.by_item.slice(0, 25).map(i =>
          `<tr><td>${text(i.name)}</td><td>${i.qty}</td><td>${money(i.revenue)}</td>` +
          `<td class="${i.profit < 0 ? 'loss' : ''}">${money(i.profit)}</td></tr>`)),
    ].join('');
    at('rangeStatus').textContent = `ช่วง ${report.start} ถึง ${report.end}`;
  };

  const load = async () => {
    at('rangeStatus').textContent = 'กำลังโหลด…';
    at('rangeStatus').classList.remove('bad');
    try {
      draw(await ask(`/api/reports/sales?${query()}`));
    } catch (error) {
      at('rangeStatus').textContent = error.message;
      at('rangeStatus').classList.add('bad');
    }
  };

  at('rangeGo').addEventListener('click', load);
  at('rangeCsv').addEventListener('click', () => {
    // A plain navigation, so the browser saves it with the server's filename
    // instead of the page trying to invent one.
    window.location.href = `/api/reports/sales.csv?${query()}`;
  });

  const home = document.querySelector('#view-analytics');
  if (home) home.prepend(panel);

  const update = () => {
    const role = window.poswaiAuth?.current?.role;
    const allowed = ['owner', 'manager'].includes(role);
    const wasHidden = panel.hidden;
    panel.hidden = !allowed;
    if (allowed && wasHidden) load();
  };
  window.addEventListener('poswai:auth-changed', update);
  update();
})();
