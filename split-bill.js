/* แยกบิล ย้ายโต๊ะ และรวมบิล ที่หน้าเคาน์เตอร์

   โต๊ะหกคนขอจ่ายแยก ลูกค้าย้ายโต๊ะเพราะแดด สองโต๊ะที่มาด้วยกันขอจ่ายใบเดียว
   สามเรื่องนี้เกิดทุกวัน และทางออกเดิมคือยกเลิกบิลแล้วคีย์ใหม่ ซึ่งทำให้ยอด
   ยกเลิกของวันโตขึ้นโดยไม่มีใครโกงอะไร และครัวได้ตั๋วซ้ำของอาหารที่เสร็จแล้ว

   กฎทั้งหมดอยู่ที่เซิร์ฟเวอร์ หน้านี้เลือกรายการ ถามยืนยัน แล้วบอกตามที่
   เซิร์ฟเวอร์ตอบ — พนักงานเสิร์ฟย้ายโต๊ะได้ แต่แยกกับรวมบิลเปลี่ยนยอดที่จะเก็บ
   จึงเป็นเรื่องของคนที่รับเงิน */
(() => {
  const host = document.querySelector('#view-cashier');
  if (!host) return;
  const auth = () => window.poswaiAuth || {};
  const branch = () => auth().branchId || 1;
  const role = () => auth().current?.role || '';
  const mayMove = () => ['owner', 'manager', 'cashier', 'service'].includes(role());
  const mayEdit = () => ['owner', 'manager', 'cashier'].includes(role());
  const preview = () => typeof state !== 'undefined' && !!state.previewOnly;
  const shortNo = no => (window.shortOrderNo ? window.shortOrderNo(no) : no);
  const money = value => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

  const api = async (path, options = {}) => {
    const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };

  const style = document.createElement('style');
  style.textContent = `
  .spl-panel{background:#fff;border:1px solid #e6e8eb;border-radius:16px;padding:18px;margin:0 0 20px}
  .spl-panel h3{margin:0 0 4px;font-size:1rem;color:#141b24}
  .spl-panel p.spl-lead{margin:0 0 14px;color:#6b7280;font-size:.84rem;line-height:1.6}
  .spl-list{display:grid;gap:8px;margin:0;padding:0;list-style:none;max-height:340px;overflow:auto}
  .spl-row{display:grid;gap:4px;padding:10px 12px;border:1px solid #e9ecef;border-radius:11px;font-size:.84rem}
  .spl-row strong{font-size:.9rem;color:#141b24}
  .spl-row small{color:#6b7280}
  .spl-row .spl-actions{display:flex;gap:7px;margin-top:5px;flex-wrap:wrap}
  .spl-row button{padding:6px 12px;border:0;border-radius:9px;font:inherit;font-size:.8rem;font-weight:700;cursor:pointer;background:#eef1f4;color:#273142}
  .spl-row button:hover{background:#e3e8ee}
  .spl-row button:disabled{opacity:.45;cursor:not-allowed}
  .spl-empty{color:#6b7280;font-size:.84rem;padding:7px 2px}
  .spl-note{margin:12px 0 0;font-size:.84rem;min-height:1.2em}
  .spl-note.bad{color:#c0372b}
  .spl-note.good{color:#128a52}
  .spl-back{position:fixed;inset:0;background:rgba(17,24,39,.55);display:grid;place-items:center;z-index:9000;padding:16px}
  .spl-card{background:#fff;border-radius:16px;padding:20px;width:min(440px,100%);max-height:86vh;overflow:auto;display:grid;gap:11px}
  .spl-card h4{margin:0;font-size:1rem;color:#141b24}
  .spl-card p{margin:0;font-size:.82rem;color:#6b7280;line-height:1.6}
  .spl-pick{display:grid;gap:7px;margin:0;padding:0;list-style:none}
  .spl-pick li{display:flex;align-items:center;gap:9px;padding:8px 10px;border:1px solid #eceff2;border-radius:10px;font-size:.84rem}
  .spl-pick .spl-name{flex:1;min-width:0}
  .spl-pick .spl-name small{display:block;color:#6b7280}
  .spl-step{display:flex;align-items:center;gap:6px}
  .spl-step button{width:28px;height:28px;border:0;border-radius:8px;background:#eef1f4;color:#273142;font:inherit;font-weight:700;cursor:pointer}
  .spl-step span{min-width:3.2em;text-align:center;font-weight:700;color:#141b24}
  .spl-sum{display:flex;justify-content:space-between;font-size:.86rem;font-weight:700;color:#141b24;padding-top:4px;border-top:1px solid #eceff2}
  .spl-card select{padding:9px 11px;border:1px solid #e0e3e7;border-radius:10px;font:inherit}
  .spl-card-row{display:flex;gap:8px;justify-content:flex-end;margin-top:4px}
  .spl-card-row button{padding:8px 15px;border:0;border-radius:10px;font:inherit;font-weight:700;cursor:pointer}
  .spl-card-row button.go{background:#111827;color:#fff}
  .spl-card-row button.off{background:#eef0f3;color:#374151}
  .spl-bad{color:#c0372b;font-size:.8rem;min-height:1.1em}`;
  document.head.append(style);

  const panel = document.createElement('section');
  panel.className = 'spl-panel';
  panel.hidden = true;
  panel.innerHTML = `<h3>แยกบิล ย้ายโต๊ะ รวมบิล</h3>
    <p class="spl-lead" id="splLead"></p>
    <ul class="spl-list" id="splList"></ul>
    <p class="spl-note" id="splNote" role="status"></p>`;
  host.prepend(panel);

  const byId = id => panel.querySelector(`#${id}`);
  const note = (text, kind = '') => {
    const element = byId('splNote');
    element.textContent = text;
    element.className = `spl-note ${kind}`;
  };

  let bills = [];
  let board = {tables: [], open_bills: {}};

  /* หนึ่งหน้าต่าง หนึ่งงาน ปิดแล้วคืนค่าที่เลือกหรือ null ถ้ายกเลิก */
  const ask = (title, lead, build) => new Promise(resolve => {
    const back = document.createElement('div');
    back.className = 'spl-back';
    const card = document.createElement('div');
    card.className = 'spl-card';
    const heading = document.createElement('h4');
    heading.textContent = title;
    const explain = document.createElement('p');
    explain.textContent = lead;
    const bad = document.createElement('div');
    bad.className = 'spl-bad';
    const row = document.createElement('div');
    row.className = 'spl-card-row';
    const cancel = document.createElement('button');
    cancel.type = 'button'; cancel.className = 'off'; cancel.textContent = 'ยกเลิก';
    const go = document.createElement('button');
    go.type = 'button'; go.className = 'go'; go.textContent = 'ยืนยัน';
    row.append(cancel, go);
    const body = document.createElement('div');
    card.append(heading, explain, body, bad, row);
    back.append(card);
    document.body.append(back);

    const close = value => { back.remove(); resolve(value); };
    const picked = build(body, {say: text => { bad.textContent = text; }, go});
    cancel.addEventListener('click', () => close(null));
    back.addEventListener('click', event => { if (event.target === back) close(null); });
    go.addEventListener('click', async () => {
      const answer = picked();
      if (typeof answer === 'string') { bad.textContent = answer; return; }
      go.disabled = true; bad.textContent = '';
      close(answer);
    });
  });

  /* เลือกจำนวนของแต่ละรายการที่จะย้ายออกไปบิลใหม่ */
  const askSplit = bill => ask(
    `แยกบิล ${shortNo(bill.order_no)}`,
    `โต๊ะ ${bill.table_no} · ยอดทั้งบิล ${money(bill.total_amount)} — เลือกจำนวนที่จะย้ายออกไปเป็นบิลใหม่`,
    (body, ui) => {
      const chosen = new Map();
      const list = document.createElement('ul');
      list.className = 'spl-pick';
      const sum = document.createElement('div');
      sum.className = 'spl-sum';
      const refresh = () => {
        let cents = 0;
        for (const item of bill.items) {
          const take = chosen.get(item.line_id) || 0;
          cents += Math.round(item.price * 100) * take;
        }
        sum.replaceChildren();
        const left = document.createElement('span');
        left.textContent = 'ยอดรายการที่แยกออก';
        const right = document.createElement('span');
        right.textContent = money(cents / 100);
        sum.append(left, right);
      };
      for (const item of bill.items) {
        const whole = Math.round(Number(item.qty) || 0);
        const line = document.createElement('li');
        const name = document.createElement('div');
        name.className = 'spl-name';
        const title = document.createElement('div');
        title.textContent = `${item.name} ×${whole}`;
        const detail = document.createElement('small');
        detail.textContent = [item.options, money(item.price)].filter(Boolean).join(' · ');
        name.append(title, detail);
        const step = document.createElement('div');
        step.className = 'spl-step';
        const less = document.createElement('button');
        less.type = 'button'; less.textContent = '−';
        const count = document.createElement('span');
        count.textContent = '0';
        const more = document.createElement('button');
        more.type = 'button'; more.textContent = '+';
        const set = next => {
          const take = Math.max(0, Math.min(whole, next));
          if (take) chosen.set(item.line_id, take); else chosen.delete(item.line_id);
          count.textContent = String(take);
          refresh();
        };
        less.addEventListener('click', () => set((chosen.get(item.line_id) || 0) - 1));
        more.addEventListener('click', () => set((chosen.get(item.line_id) || 0) + 1));
        step.append(less, count, more);
        line.append(name, step);
        list.append(line);
      }
      refresh();
      body.append(list, sum);
      return () => {
        const picks = [...chosen.entries()].map(([line_id, qty]) => ({line_id, qty}));
        if (!picks.length) return 'ยังไม่ได้เลือกรายการที่จะแยกออก';
        const moved = picks.reduce((total, pick) => total + pick.qty, 0);
        const all = bill.items.reduce((total, item) => total + Math.round(Number(item.qty) || 0), 0);
        if (moved >= all) return 'แยกออกทั้งบิลไม่ได้ ถ้าจะเปลี่ยนโต๊ะให้ใช้ย้ายโต๊ะ';
        return {picks};
      };
    });

  const askMove = bill => ask(
    `ย้ายโต๊ะบิล ${shortNo(bill.order_no)}`,
    `บิลนี้อยู่โต๊ะ ${bill.table_no} — เลือกโต๊ะที่จะย้ายไป`,
    body => {
      const picker = document.createElement('select');
      const free = board.tables.filter(table => table.active && table.table_no !== bill.table_no);
      if (!free.length) {
        picker.append(new Option('ไม่มีโต๊ะอื่นที่เปิดใช้งาน', ''));
      }
      for (const table of free) {
        const busy = (board.open_bills[table.table_no] || []).length;
        picker.append(new Option(
          `โต๊ะ ${table.table_no}${busy ? ` (มีบิลค้าง ${busy} ใบ)` : ' (ว่าง)'}`,
          table.table_no));
      }
      body.append(picker);
      return () => (picker.value ? {table_no: picker.value} : 'ยังไม่ได้เลือกโต๊ะ');
    });

  const askMerge = bill => ask(
    `รวมบิล ${shortNo(bill.order_no)} เข้าอีกบิล`,
    `ยอด ${money(bill.total_amount)} จะถูกย้ายไปรวมกับบิลที่เลือก แล้วเก็บเงินใบเดียว`,
    body => {
      const picker = document.createElement('select');
      const others = bills.filter(other => other.order_no !== bill.order_no && !other.paid);
      if (!others.length) picker.append(new Option('ไม่มีบิลอื่นที่ยังเปิดอยู่', ''));
      for (const other of others) {
        picker.append(new Option(
          `โต๊ะ ${other.table_no} · ${shortNo(other.order_no)} · ${money(other.total_amount)}`,
          other.order_no));
      }
      body.append(picker);
      return () => (picker.value ? {into_order_no: picker.value} : 'ยังไม่ได้เลือกบิลปลายทาง');
    });

  const run = async (bill, kind, button) => {
    const asked = kind === 'split' ? await askSplit(bill)
      : kind === 'move' ? await askMove(bill) : await askMerge(bill);
    if (!asked) return;
    button.disabled = true;
    try {
      if (kind === 'split') {
        const answer = await api(`/api/orders/${encodeURIComponent(bill.order_no)}/split`, {
          method: 'POST',
          body: JSON.stringify({branch_id: branch(), event_id: crypto.randomUUID(),
                                new_order_no: `ORD-${crypto.randomUUID()}`, picks: asked.picks})});
        note(answer.status === 'existing'
          ? `บิลนี้แยกไปแล้วเป็น ${shortNo(answer.new_order_no)}`
          : `แยกแล้ว · บิลเดิม ${money(answer.kept.total_amount)} · บิลใหม่ ${shortNo(answer.created.order_no)} ${money(answer.created.total_amount)}`,
          'good');
      } else if (kind === 'move') {
        const answer = await api(`/api/orders/${encodeURIComponent(bill.order_no)}/move`, {
          method: 'POST',
          body: JSON.stringify({branch_id: branch(), table_no: asked.table_no})});
        note(`ย้ายบิล ${shortNo(bill.order_no)} จากโต๊ะ ${answer.from_table} ไปโต๊ะ ${answer.table_no} แล้ว`, 'good');
      } else {
        const answer = await api(`/api/orders/${encodeURIComponent(bill.order_no)}/merge`, {
          method: 'POST',
          body: JSON.stringify({branch_id: branch(), into_order_no: asked.into_order_no})});
        note(`รวมเข้าบิล ${shortNo(answer.into.order_no)} แล้ว · ยอดรวม ${money(answer.into.total_amount)}`, 'good');
      }
      window.poswaiLiveData?.refresh?.().catch(() => {});
      await load();
    } catch (error) {
      note(error.message, 'bad');
      button.disabled = false;
    }
  };

  const render = () => {
    byId('splLead').textContent = mayEdit()
      ? 'แยกบางรายการออกเป็นบิลใหม่ ย้ายบิลไปโต๊ะอื่น หรือรวมสองบิลให้จ่ายใบเดียว — ทุกครั้งถูกบันทึกว่าใครทำ'
      : 'ย้ายบิลที่ยังไม่จ่ายไปอีกโต๊ะได้ · การแยกและรวมบิลเป็นสิทธิ์ของคนที่รับเงิน';
    const list = byId('splList');
    list.replaceChildren();
    const open = bills.filter(bill => !bill.paid);
    if (!open.length) {
      const empty = document.createElement('li');
      empty.className = 'spl-empty';
      empty.textContent = 'ยังไม่มีบิลที่เปิดอยู่';
      list.append(empty);
      return;
    }
    for (const bill of open) {
      const row = document.createElement('li');
      row.className = 'spl-row';
      const head = document.createElement('strong');
      head.textContent = `โต๊ะ ${bill.table_no} · ${money(bill.total_amount)}`;
      const detail = document.createElement('small');
      const names = bill.items.map(item => `${item.name}×${Math.round(Number(item.qty) || 0)}`);
      detail.textContent = `${shortNo(bill.order_no)} · ${names.join(', ')}`;
      const actions = document.createElement('div');
      actions.className = 'spl-actions';
      const add = (label, kind, allowed) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.disabled = !allowed || preview();
        button.addEventListener('click', () => run(bill, kind, button).catch(() => {}));
        actions.append(button);
      };
      add('แยกบิล', 'split', mayEdit() && bill.items.length > 0);
      add('ย้ายโต๊ะ', 'move', mayMove());
      add('รวมบิล', 'merge', mayEdit() && open.length > 1);
      row.append(head, detail, actions);
      list.append(row);
    }
  };

  const load = async () => {
    try {
      const [orders, tables] = await Promise.all([
        api(`/api/orders?branch_id=${branch()}`),
        api(`/api/tables/board?branch_id=${branch()}`)]);
      bills = orders.orders || [];
      board = tables;
      render();
    } catch (error) {
      note(error.message, 'bad');
    }
  };

  /* วาดเฉพาะคนที่ทำได้อย่างน้อยหนึ่งอย่าง และเอาออกเมื่อออกจากระบบ */
  const sync = () => {
    panel.hidden = !mayMove();
    if (!panel.hidden) load().catch(() => {});
  };
  window.addEventListener('poswai:auth-changed', sync);
  window.addEventListener('poswai:orders-changed', () => { if (!panel.hidden) load().catch(() => {}); });
  sync();
})();
