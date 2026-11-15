/* ใครทำอะไรกับเงินและของในร้าน

   กะกับลิ้นชักบอกว่าเงินหาย หน้านี้บอกว่าหายตรงไหน — ส่วนลด ราคาเมนูที่ถูกแก้
   เงินที่ออกจากลิ้นชัก บิลที่ถูกยกเลิก และใครอนุมัติให้

   เจ้าของกับผู้จัดการเท่านั้นที่เปิดได้ เพราะนี่คือหน้าที่ใช้ตรวจแคชเชียร์
   เซิร์ฟเวอร์เป็นคนบังคับ หน้านี้แค่ไม่วาดให้คนที่เปิดไม่ได้ */
(() => {
  const host = document.querySelector('#view-analytics');
  if (!host) return;
  const auth = () => window.poswaiAuth || {};
  const branch = () => auth().branchId || 1;
  const role = () => auth().current?.role || '';
  const mayRead = () => ['owner', 'manager'].includes(role());
  const money = value => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const clock = value => {
    const stamp = new Date(String(value || '').replace(' ', 'T') + 'Z');
    return Number.isNaN(stamp.valueOf()) ? ''
      : stamp.toLocaleString('th-TH', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
  };

  const style = document.createElement('style');
  style.textContent = `
  .act-panel{background:#fff;border:1px solid #e6e8eb;border-radius:16px;padding:18px;margin:0 0 20px}
  .act-panel h3{margin:0 0 4px;font-size:1rem;color:#141b24}
  .act-panel p.act-lead{margin:0 0 14px;color:#6b7280;font-size:.84rem;line-height:1.6}
  .act-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
  .act-filters input,.act-filters select{padding:7px 10px;border:1px solid #e0e3e7;border-radius:9px;font:inherit;font-size:.82rem}
  .act-filters button{padding:7px 14px;border:0;border-radius:9px;background:#111827;color:#fff;font:inherit;font-size:.82rem;font-weight:700;cursor:pointer}
  .act-chips{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:12px}
  .act-chip{background:#f4f6f8;border-radius:999px;padding:5px 12px;font-size:.78rem;color:#374151}
  .act-chip strong{color:#111827}
  .act-list{display:grid;gap:7px;margin:0;padding:0;list-style:none;max-height:420px;overflow:auto}
  .act-row{display:grid;gap:2px;padding:9px 11px;border:1px solid #eceff2;border-radius:11px;font-size:.83rem}
  .act-row .act-head{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
  .act-row strong{color:#141b24}
  .act-row small{color:#6b7280}
  .act-row .act-amount{font-weight:700;color:#111827;white-space:nowrap}
  .act-row.is-money{background:#fffdf5;border-color:#f3e2bb}
  .act-note{margin:11px 0 0;font-size:.84rem;min-height:1.2em}
  .act-note.bad{color:#c0372b}`;
  document.head.append(style);

  const panel = document.createElement('section');
  panel.className = 'act-panel';
  panel.innerHTML = `
    <h3>บันทึกกิจกรรมพนักงาน</h3>
    <p class="act-lead">ทุกครั้งที่มีคนแตะเงินหรือของในร้าน ระบบจดไว้ที่นี่ — ส่วนลด ราคาเมนู เงินเข้าออกลิ้นชัก บิลที่ถูกยกเลิก และใครอนุมัติ</p>
    <div class="act-filters">
      <input type="date" id="actStart" />
      <span style="color:#9ca3af">ถึง</span>
      <input type="date" id="actEnd" />
      <select id="actAction"><option value="">ทุกอย่าง</option></select>
      <button type="button" id="actGo">ดู</button>
    </div>
    <div class="act-chips" id="actChips"></div>
    <ul class="act-list" id="actList"></ul>
    <p class="act-note" id="actNote"></p>`;

  const byId = id => panel.querySelector(`#${id}`);
  const note = (text, kind = '') => {
    const element = byId('actNote');
    element.textContent = text;
    element.className = `act-note ${kind}`;
  };

  /* รายการที่เป็นเรื่องเงินโดยตรง ไฮไลต์ไว้ เพราะเป็นสิ่งที่เจ้าของเปิดหน้านี้มาหา */
  const MONEY = new Set(['discount', 'void', 'refund', 'cash_out', 'cash_in']);

  const render = (data) => {
    const chips = byId('actChips');
    chips.replaceChildren();
    for (const row of data.by_action.slice(0, 8)) {
      const chip = document.createElement('span');
      chip.className = 'act-chip';
      chip.innerHTML = `${row.label} <strong>${row.count}</strong>`;
      chips.append(chip);
    }
    for (const row of data.by_staff.slice(0, 6)) {
      const chip = document.createElement('span');
      chip.className = 'act-chip';
      chip.innerHTML = `${row.staff} <strong>${row.count}</strong> ครั้ง`;
      chips.append(chip);
    }

    const list = byId('actList');
    list.replaceChildren();
    if (!data.entries.length) {
      const empty = document.createElement('li');
      empty.className = 'act-row';
      empty.textContent = 'ยังไม่มีกิจกรรมในช่วงวันที่เลือก';
      list.append(empty);
      return;
    }
    for (const entry of data.entries) {
      const row = document.createElement('li');
      row.className = `act-row${MONEY.has(entry.action) ? ' is-money' : ''}`;
      const head = document.createElement('div');
      head.className = 'act-head';
      const left = document.createElement('strong');
      left.textContent = `${entry.action_label}${entry.subject ? ` · ${entry.subject}` : ''}`;
      head.append(left);
      if (entry.amount) {
        const amount = document.createElement('span');
        amount.className = 'act-amount';
        amount.textContent = money(entry.amount);
        head.append(amount);
      }
      const who = document.createElement('small');
      who.textContent = `${entry.staff}${entry.role ? ` (${entry.role})` : ''} · ${clock(entry.at)}`;
      row.append(head, who);
      if (entry.detail) {
        const detail = document.createElement('small');
        detail.textContent = entry.detail;
        row.append(detail);
      }
      list.append(row);
    }
  };

  const load = async () => {
    note('กำลังอ่านบันทึก...');
    const query = new URLSearchParams({branch_id: String(branch()), limit: '200'});
    if (byId('actStart').value) query.set('start', byId('actStart').value);
    if (byId('actEnd').value) query.set('end', byId('actEnd').value);
    if (byId('actAction').value) query.set('action', byId('actAction').value);
    try {
      const response = await fetch(`/api/reports/activity?${query}`,
                                   {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `อ่านบันทึกไม่สำเร็จ (${response.status})`);
      }
      const data = await response.json();
      const picker = byId('actAction');
      if (picker.options.length === 1) {
        for (const item of data.actions) {
          picker.append(new Option(item.label, item.action));
        }
      }
      byId('actStart').value = data.start;
      byId('actEnd').value = data.end;
      render(data);
      note('');
    } catch (error) {
      note(error.message, 'bad');
    }
  };

  byId('actGo').addEventListener('click', () => load().catch(() => {}));

  /* วาดเฉพาะตอนที่คนเปิดมีสิทธิ์อ่าน และเอาออกเมื่อเขาออกจากระบบ */
  const sync = () => {
    if (mayRead()) {
      if (!panel.isConnected) host.prepend(panel);
      load().catch(() => {});
    } else if (panel.isConnected) {
      panel.remove();
    }
  };
  window.addEventListener('poswai:auth-changed', sync);
  sync();
})();
