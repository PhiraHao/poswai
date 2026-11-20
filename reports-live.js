/* Show only server-backed figures when POS WAI leaves preview mode. */
(() => {
  const report = document.querySelector('#view-analytics');
  if (!report) return;
  const money = value => value == null ? 'ยังไม่มีข้อมูล' : `฿${Number(value).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const plain = value => value == null ? 'ยังไม่มีข้อมูล' : String(value);
  const root = document.createElement('div');
  root.id = 'report-live-root';
  root.innerHTML = `
    <div class="live-report-toolbar"><div><strong>ข้อมูลยอดขายจริง</strong><span id="liveReportDate">กำลังโหลด...</span></div><button type="button" id="liveReportRefresh">รีเฟรช</button></div>
    <div id="liveReportStatus" class="live-report-status" role="status"></div>
    <div class="live-report-grid">
      <section class="live-report-card live-report-primary"><span>ยอดขายวันนี้</span><strong id="liveSales">—</strong><small>นับเฉพาะบิลที่ชำระแล้ว</small></section>
      <section class="live-report-card"><span>บิลที่ชำระแล้ว</span><strong id="liveBills">—</strong><small>จากฐานข้อมูลสาขานี้</small></section>
      <section class="live-report-card"><span>เฉลี่ยต่อบิล</span><strong id="liveAverage">—</strong><small>ยอดขาย ÷ จำนวนบิล</small></section>
      <section class="live-report-card"><span>เทียบเมื่อวาน</span><strong id="liveDod">—</strong><small id="liveYesterday">—</small></section>
    </div>
    <div class="live-report-columns">
      <section class="live-report-card"><h2>วิธีชำระเงิน</h2><div id="livePayments" class="live-report-list"></div></section>
      <section class="live-report-card"><h2>เมนูขายดี</h2><div id="liveMenu" class="live-report-list"></div></section>
      <section class="live-report-card"><h2>ยอดขายรายชั่วโมง</h2><div id="liveHours" class="live-report-list"></div></section>
    </div>
    <p class="live-report-footnote">ต้นทุน กำไรสุทธิ ลูกค้าซื้อซ้ำ และความเร็วครัวจะแสดงเมื่อมีข้อมูลจริงสำหรับคำนวณ</p>`;
  report.append(root);
  const byId = id => document.getElementById(id);
  const renderRows = (id, rows, emptyText = 'ยังไม่มีข้อมูล') => {
    const target = byId(id);
    target.replaceChildren();
    if (!rows.length) { target.textContent = emptyText; return; }
    for (const [label, value] of rows) {
      const row = document.createElement('div');
      row.className = 'live-report-row';
      const name = document.createElement('span'); name.textContent = label;
      const amount = document.createElement('strong'); amount.textContent = value;
      row.append(name, amount); target.append(row);
    }
  };
  const branchId = () => {
    const value = document.querySelector('#branchSelect')?.value || '';
    return value.includes('แม่ริม') ? 2 : value.includes('คลัง') ? 3 : 1;
  };
  async function refresh() {
    if (!root.isConnected) return;
    byId('liveReportStatus').textContent = 'กำลังอ่านข้อมูลยอดขาย...';
    try {
      const response = await fetch(`/api/enterprise/analytics-dashboard?branch_id=${branchId()}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? 'กรุณาเข้าสู่ระบบด้วยสิทธิ์ผู้จัดการเพื่อดูรายงาน' : `โหลดรายงานไม่สำเร็จ (${response.status})`);
      const data = await response.json();
      const sales = data.sales_realtime || {};
      byId('liveReportDate').textContent = data.business_date || 'วันนี้';
      byId('liveSales').textContent = money(sales.today_sales);
      byId('liveBills').textContent = plain(sales.paid_order_count);
      byId('liveAverage').textContent = money(data.food_cost_and_retention?.avg_basket_size_baht);
      byId('liveDod').textContent = sales.dod_growth_percent == null ? 'ยังเทียบไม่ได้' : `${sales.dod_growth_percent > 0 ? '+' : ''}${sales.dod_growth_percent}%`;
      byId('liveYesterday').textContent = `เมื่อวาน ${money(sales.yesterday_sales)}`;
      renderRows('livePayments', Object.entries(sales.payment_split || {}).map(([method, amount]) => [method, money(amount)]));
      renderRows('liveMenu', (data.top_selling_menu || []).map(item => [item.name, `${Number(item.quantity).toLocaleString('th-TH')} รายการ · ${money(item.gross_sales)}`]));
      renderRows('liveHours', (data.hourly_sales || []).map(item => [`${item.hour}:00`, `${item.orders} บิล · ${money(item.sales)}`]));
      byId('liveReportStatus').textContent = '';
      if (report.querySelector('.module-state')) report.querySelector('.module-state').textContent = 'ข้อมูลจริง';
    } catch (error) {
      byId('liveReportStatus').textContent = error.message;
      if (report.querySelector('.module-state')) report.querySelector('.module-state').textContent = 'ยังไม่พร้อม';
    }
  }
  byId('liveReportRefresh').addEventListener('click', refresh);
  window.addEventListener('poswai:auth-changed', refresh);
  document.querySelector('#branchSelect')?.addEventListener('change', refresh);
  fetch('/api/config', {cache:'no-store'}).then(response => response.json()).then(config => {
    if (config.preview_only) { root.remove(); return; }
    report.classList.add('report-live-mode');
    refresh();
  }).catch(() => root.remove());
})();
