/* คืนเงินบางส่วน และใบลดหนี้ ม.86/10

   ลูกค้าสั่งห้าจาน จานหนึ่งมาผิด ร้านคืนเงินจานนั้นจานเดียว ของเดิมทำได้อย่างเดียว
   คือคืนทั้งบิลแล้วคีย์ใหม่สี่จาน ซึ่งทำให้ยอดขายของวันมีบิลผีเพิ่มหนึ่งใบ และ
   คอมมิชชันของพนักงานถูกหักเต็มทั้งที่ขายได้สี่จาน

   บิลที่เคยออกใบกำกับภาษีไว้ ต้องตามด้วยใบลดหนี้เสมอ ไม่งั้นร้านนำส่ง VAT ของเงิน
   ที่คืนไปแล้ว และผู้ซื้อก็ยังขอคืนภาษีได้เต็มจำนวนทั้งที่จ่ายน้อยกว่า หน้านี้จึง
   ถามให้ตรงนั้นเลย ไม่ปล่อยให้พนักงานไปจำเอง */
(() => {
  const host = document.querySelector('#view-cashier');
  if (!host) return;
  const auth = () => window.poswaiAuth || {};
  const branch = () => auth().branchId || 1;
  const role = () => auth().current?.role || '';
  const mayRefund = () => ['owner', 'manager', 'cashier'].includes(role());
  const preview = () => typeof state !== 'undefined' && !!state.previewOnly;
  const shortNo = no => (window.shortOrderNo ? window.shortOrderNo(no) : no);
  const money = value => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const clock = value => {
    const stamp = new Date(String(value || '').replace(' ', 'T') + 'Z');
    return Number.isNaN(stamp.valueOf()) ? ''
      : stamp.toLocaleString('th-TH', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
  };

  const api = async (path, options = {}) => {
    const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };

  const style = document.createElement('style');
  style.textContent = `
  .rfp-panel{background:#fff;border:1px solid #e6e8eb;border-radius:16px;padding:18px;margin:0 0 20px}
  .rfp-panel h3{margin:0 0 4px;font-size:1rem;color:#141b24}
  .rfp-panel p.rfp-lead{margin:0 0 14px;color:#6b7280;font-size:.84rem;line-height:1.6}
  .rfp-list{display:grid;gap:8px;margin:0;padding:0;list-style:none;max-height:320px;overflow:auto}
  .rfp-row{display:grid;gap:4px;padding:10px 12px;border:1px solid #e9ecef;border-radius:11px;font-size:.84rem}
  .rfp-row strong{font-size:.9rem;color:#141b24}
  .rfp-row small{color:#6b7280}
  .rfp-row button{margin-top:5px;justify-self:start;padding:6px 12px;border:0;border-radius:9px;font:inherit;font-size:.8rem;font-weight:700;cursor:pointer;background:#fdeae7;color:#c0372b}
  .rfp-row button:disabled{opacity:.45;cursor:not-allowed}
  .rfp-tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.72rem;font-weight:700;background:#fff5e6;color:#8a5a00;justify-self:start}
  .rfp-empty{color:#6b7280;font-size:.84rem;padding:7px 2px}
  .rfp-note{margin:12px 0 0;font-size:.84rem;min-height:1.2em}
  .rfp-note.bad{color:#c0372b}
  .rfp-note.good{color:#128a52}
  .rfp-back{position:fixed;inset:0;background:rgba(17,24,39,.55);display:grid;place-items:center;z-index:9000;padding:16px}
  .rfp-card{background:#fff;border-radius:16px;padding:20px;width:min(460px,100%);max-height:88vh;overflow:auto;display:grid;gap:11px}
  .rfp-card h4{margin:0;font-size:1rem;color:#141b24}
  .rfp-card p{margin:0;font-size:.82rem;color:#6b7280;line-height:1.6}
  .rfp-pick{display:grid;gap:7px;margin:0;padding:0;list-style:none}
  .rfp-pick li{display:flex;align-items:center;gap:9px;padding:8px 10px;border:1px solid #eceff2;border-radius:10px;font-size:.84rem}
  .rfp-pick .rfp-name{flex:1;min-width:0}
  .rfp-pick .rfp-name small{display:block;color:#6b7280}
  .rfp-step{display:flex;align-items:center;gap:6px}
  .rfp-step button{width:28px;height:28px;border:0;border-radius:8px;background:#eef1f4;color:#273142;font:inherit;font-weight:700;cursor:pointer}
  .rfp-step span{min-width:3.2em;text-align:center;font-weight:700;color:#141b24}
  .rfp-or{display:flex;align-items:center;gap:9px;font-size:.82rem;color:#6b7280}
  .rfp-card input,.rfp-card textarea{padding:9px 11px;border:1px solid #e0e3e7;border-radius:10px;font:inherit;width:100%;box-sizing:border-box}
  .rfp-card textarea{min-height:62px;resize:vertical}
  .rfp-card-row{display:flex;gap:8px;justify-content:flex-end;margin-top:4px}
  .rfp-card-row button{padding:8px 15px;border:0;border-radius:10px;font:inherit;font-weight:700;cursor:pointer}
  .rfp-card-row button.go{background:#111827;color:#fff}
  .rfp-card-row button.off{background:#eef0f3;color:#374151}
  .rfp-bad{color:#c0372b;font-size:.8rem;min-height:1.1em}`;
  document.head.append(style);

  const panel = document.createElement('section');
  panel.className = 'rfp-panel';
  panel.hidden = true;
  panel.innerHTML = `<h3>คืนเงินบางส่วน</h3>
    <p class="rfp-lead">คืนเฉพาะรายการที่มีปัญหา หรือคืนเป็นจำนวนเงิน โดยไม่ต้องยกเลิกทั้งบิล — บิลที่เคยออกใบกำกับภาษี ระบบจะถามให้ออกใบลดหนี้ตามกฎหมายต่อทันที</p>
    <ul class="rfp-list" id="rfpList"></ul>
    <p class="rfp-note" id="rfpNote" role="status"></p>`;
  host.prepend(panel);

  const byId = id => panel.querySelector(`#${id}`);
  const note = (text, kind = '') => {
    const element = byId('rfpNote');
    element.textContent = text;
    element.className = `rfp-note ${kind}`;
  };

  let settled = [];

  const ask = (title, lead, build) => new Promise(resolve => {
    const back = document.createElement('div');
    back.className = 'rfp-back';
    const card = document.createElement('div');
    card.className = 'rfp-card';
    const heading = document.createElement('h4');
    heading.textContent = title;
    const explain = document.createElement('p');
    explain.textContent = lead;
    const bad = document.createElement('div');
    bad.className = 'rfp-bad';
    const row = document.createElement('div');
    row.className = 'rfp-card-row';
    const cancel = document.createElement('button');
    cancel.type = 'button'; cancel.className = 'off'; cancel.textContent = 'ยกเลิก';
    const go = document.createElement('button');
    go.type = 'button'; go.className = 'go'; go.textContent = 'ยืนยัน';
    row.append(cancel, go);
    const body = document.createElement('div');
    body.style.display = 'grid';
    body.style.gap = '11px';
    card.append(heading, explain, body, bad, row);
    back.append(card);
    document.body.append(back);
    const picked = build(body, go);
    const close = value => { back.remove(); resolve(value); };
    cancel.addEventListener('click', () => close(null));
    back.addEventListener('click', event => { if (event.target === back) close(null); });
    go.addEventListener('click', () => {
      const answer = picked();
      if (typeof answer === 'string') { bad.textContent = answer; return; }
      go.disabled = true;
      close(answer);
    });
  });

  /* ผู้จัดการใส่รหัสของตัวเองที่หน้าจอของแคชเชียร์ ได้ใบอนุมัติใบเดียวใช้ครั้งเดียว
     เหมือนตอนยกเลิกบิล ไม่เก็บรหัสไว้ที่ไหน ส่งไปแล้วทิ้ง */
  const askManager = () => ask(
    'ให้ผู้จัดการอนุมัติ',
    'การคืนเงินเกินสิทธิ์ของคุณ ให้ผู้จัดการใส่รหัสของตัวเองเพื่ออนุมัติครั้งนี้',
    body => {
      const who = document.createElement('input');
      who.type = 'number'; who.min = '1'; who.placeholder = 'รหัสพนักงานของผู้จัดการ';
      const pin = document.createElement('input');
      pin.type = 'password'; pin.placeholder = 'PIN ของผู้จัดการ'; pin.autocomplete = 'off';
      body.append(who, pin);
      who.focus();
      return () => (Number(who.value) > 0 && pin.value
        ? {staff_id: Number(who.value), pin: pin.value}
        : 'ใส่รหัสพนักงานและ PIN ของผู้จัดการ');
    });

  const managerToken = async () => {
    const said = await askManager();
    if (!said) return null;
    try {
      const answer = await api('/api/auth/override', {method: 'POST', body: JSON.stringify({
        branch_id: branch(), action: 'refund', staff_id: said.staff_id, pin: said.pin})});
      return answer.token;
    } catch (error) {
      note(error.message, 'bad');
      return null;
    }
  };

  const askRefund = sheet => ask(
    `คืนเงินบิล ${shortNo(sheet.order_no)}`,
    `โต๊ะ ${sheet.table_no} · ยอดบิล ${money(sheet.total)}` +
    (sheet.refunded ? ` · คืนไปแล้ว ${money(sheet.refunded)}` : '') +
    ` · เหลือคืนได้ ${money(sheet.left)}`,
    body => {
      const chosen = new Map();
      const list = document.createElement('ul');
      list.className = 'rfp-pick';
      const free = document.createElement('input');
      free.type = 'number'; free.min = '0'; free.step = '0.01';
      free.placeholder = 'หรือคืนเป็นจำนวนเงิน (บาท)';
      for (const line of sheet.lines) {
        const item = document.createElement('li');
        const name = document.createElement('div');
        name.className = 'rfp-name';
        const title = document.createElement('div');
        title.textContent = `${line.name} ×${line.qty}`;
        const detail = document.createElement('small');
        detail.textContent = line.left
          ? [line.options, `${money(line.price)} · คืนได้อีก ${line.left}`].filter(Boolean).join(' · ')
          : 'คืนเงินรายการนี้ครบแล้ว';
        name.append(title, detail);
        const step = document.createElement('div');
        step.className = 'rfp-step';
        const less = document.createElement('button');
        less.type = 'button'; less.textContent = '−';
        const count = document.createElement('span');
        count.textContent = '0';
        const more = document.createElement('button');
        more.type = 'button'; more.textContent = '+';
        const set = next => {
          const take = Math.max(0, Math.min(line.left, next));
          if (take) chosen.set(line.line_id, take); else chosen.delete(line.line_id);
          count.textContent = String(take);
          if (take) free.value = '';
        };
        less.addEventListener('click', () => set((chosen.get(line.line_id) || 0) - 1));
        more.addEventListener('click', () => set((chosen.get(line.line_id) || 0) + 1));
        less.disabled = more.disabled = !line.left;
        step.append(less, count, more);
        item.append(name, step);
        list.append(item);
      }
      const or = document.createElement('div');
      or.className = 'rfp-or';
      or.textContent = 'หรือคืนเป็นจำนวนเงิน โดยไม่ระบุรายการ';
      free.addEventListener('input', () => {
        if (free.value) {
          chosen.clear();
          for (const span of list.querySelectorAll('.rfp-step span')) span.textContent = '0';
        }
      });
      const why = document.createElement('textarea');
      why.placeholder = 'เหตุผลที่คืนเงิน (3-200 ตัวอักษร) — จะถูกบันทึกไว้และลงในใบลดหนี้';
      body.append(list, or, free, why);
      return () => {
        const picks = [...chosen.entries()].map(([line_id, qty]) => ({line_id, qty}));
        const amount = Number(free.value) || 0;
        if (!picks.length && amount <= 0) return 'เลือกรายการที่จะคืน หรือใส่จำนวนเงิน';
        if (picks.length && amount > 0) return 'เลือกรายการ หรือใส่จำนวนเงิน อย่างใดอย่างหนึ่ง';
        if (amount > sheet.left + 0.005) return `บิลนี้เหลือคืนได้อีก ${money(sheet.left)}`;
        if (why.value.trim().length < 3) return 'ต้องบอกเหตุผลอย่างน้อย 3 ตัวอักษร';
        return {picks, amount: picks.length ? null : amount, reason: why.value.trim()};
      };
    });

  /* บิลที่เคยออกใบกำกับภาษี ต้องตามด้วยใบลดหนี้ ถามตรงนี้เลยตอนที่คนยังยืนอยู่ */
  const offerCreditNote = async (invoiceNumber, refundId) => {
    const agreed = await ask(
      'ออกใบลดหนี้ตามกฎหมาย',
      `บิลนี้ออกใบกำกับภาษีเลขที่ ${invoiceNumber} ไปแล้ว การคืนเงินต้องออกใบลดหนี้ (ม.86/10) ` +
      'ไม่งั้นร้านต้องนำส่ง VAT ของเงินที่คืนไปแล้ว',
      () => () => ({go: true}));
    if (!agreed) {
      note('คืนเงินแล้ว แต่ยังไม่ได้ออกใบลดหนี้ — ออกย้อนหลังได้ที่หน้าใบกำกับภาษี', 'bad');
      return;
    }
    try {
      const made = await api(`/api/tax-invoices/${encodeURIComponent(invoiceNumber)}/credit-note`, {
        method: 'POST', body: JSON.stringify({branch_id: branch(), refund_id: refundId})});
      note(`คืนเงินแล้ว · ออกใบลดหนี้เลขที่ ${made.number} ลดมูลค่า ${money(made.difference.total)} (VAT ${money(made.difference.vat)})`, 'good');
    } catch (error) {
      note(`คืนเงินแล้ว แต่ออกใบลดหนี้ไม่สำเร็จ: ${error.message}`, 'bad');
    }
  };

  const run = async (order, button) => {
    button.disabled = true;
    let sheet;
    try {
      sheet = await api(`/api/orders/${encodeURIComponent(order.order_no)}/refundable?branch_id=${branch()}`);
    } catch (error) {
      note(error.message, 'bad');
      button.disabled = false;
      return;
    }
    const asked = await askRefund(sheet);
    if (!asked) { button.disabled = false; return; }
    const body = {branch_id: branch(), event_id: crypto.randomUUID(), reason: asked.reason,
                  picks: asked.picks, amount: asked.amount};
    const send = (override = '') => api(
      `/api/orders/${encodeURIComponent(order.order_no)}/refund-partial`,
      {method: 'POST', body: JSON.stringify({...body, override})});
    let answer = null;
    try {
      answer = await send();
    } catch (error) {
      // เซิร์ฟเวอร์เป็นคนบอกว่าต้องให้ผู้จัดการอนุมัติ หน้าจอไม่เดาเอง
      if (!/อนุมัติ/.test(error.message || '')) {
        note(error.message, 'bad');
        button.disabled = false;
        return;
      }
      const token = await managerToken();
      if (!token) {
        note(`ยังไม่ได้คืนเงิน ${shortNo(order.order_no)} — ไม่มีผู้จัดการอนุมัติ`, 'bad');
        button.disabled = false;
        return;
      }
      try {
        answer = await send(token);
      } catch (retry) {
        note(retry.message, 'bad');
        button.disabled = false;
        return;
      }
    }
    note(`คืนเงิน ${money(answer.refund.amount)} ของบิล ${shortNo(order.order_no)} แล้ว · เหลือคืนได้อีก ${money(answer.left)}`, 'good');
    if (sheet.tax_invoice) await offerCreditNote(sheet.tax_invoice, answer.refund.id);
    window.poswaiLiveData?.refresh?.().catch(() => {});
    await load();
  };

  const render = () => {
    const list = byId('rfpList');
    list.replaceChildren();
    const payable = settled.filter(order => order.status !== 'refunded');
    if (!payable.length) {
      const empty = document.createElement('li');
      empty.className = 'rfp-empty';
      empty.textContent = 'ยังไม่มีบิลที่รับเงินแล้ว';
      list.append(empty);
      return;
    }
    for (const order of payable) {
      const row = document.createElement('li');
      row.className = 'rfp-row';
      const head = document.createElement('strong');
      head.textContent = `${shortNo(order.order_no)} · ${money(order.net_amount)}`;
      const detail = document.createElement('small');
      detail.textContent = [order.table_no ? `โต๊ะ ${order.table_no}` : '', clock(order.closed_at),
                            order.closed_by ? `ปิดโดย ${order.closed_by}` : '']
        .filter(Boolean).join(' · ');
      row.append(head, detail);
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'คืนบางส่วน';
      button.disabled = preview();
      button.addEventListener('click', () => run(order, button).catch(() => {}));
      row.append(button);
      list.append(row);
    }
  };

  async function load() {
    try {
      const answer = await api(`/api/orders/settled?branch_id=${branch()}&limit=20`);
      settled = answer.orders || [];
      render();
    } catch (error) {
      note(error.message, 'bad');
    }
  }

  const sync = () => {
    panel.hidden = !mayRefund();
    if (!panel.hidden) load().catch(() => {});
  };
  window.addEventListener('poswai:auth-changed', sync);
  sync();
})();
