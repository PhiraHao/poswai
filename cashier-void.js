/* Cancelling an unpaid bill and refunding a paid one, at the till.

   The rules live on the server: a cashier may cancel a small unpaid bill alone,
   anything larger or past the daily count needs a manager, and money already
   taken is always a manager's call. This panel shows the bills, asks for a
   reason, and reports back exactly what the server said. */
(() => {
  const host = document.querySelector('#view-cashier');
  if (!host) return;
  const auth = () => window.poswaiAuth || {};
  const branch = () => auth().branchId || 1;
  const role = () => auth().current?.role || '';
  const canRefund = () => ['manager', 'owner'].includes(role());
  const preview = () => typeof state !== 'undefined' && !!state.previewOnly;
  const money = value => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const clock = value => {
    const stamp = new Date(String(value || '').replace(' ', 'T') + 'Z');
    return Number.isNaN(stamp.valueOf()) ? '' : stamp.toLocaleString('th-TH', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
  };
  let limits = {max_amount: 200, daily_limit: 3};

  const style = document.createElement('style');
  style.textContent = `
  .void-panel{background:#fff;border:1px solid #e6e8eb;border-radius:16px;padding:18px;margin:0 0 20px}
  .void-panel h3{margin:0 0 4px;font-size:1rem;color:#141b24}
  .void-panel p.void-lead{margin:0 0 14px;color:#6b7280;font-size:.84rem;line-height:1.6}
  .void-cols{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(290px,1fr))}
  .void-col{border:1px solid #e6e8eb;border-radius:14px;padding:13px}
  .void-col.open-bills{background:#fffdf5;border-color:#f3e2bb}
  .void-col.paid-bills{background:#f6faf7;border-color:#cfe6d8}
  .void-col h4{margin:0 0 9px;font-size:.9rem;color:#141b24}
  .void-list{display:grid;gap:8px;margin:0;padding:0;list-style:none;max-height:320px;overflow:auto}
  .void-row{display:grid;gap:3px;padding:10px 11px;background:#fff;border:1px solid #e9ecef;border-radius:11px;font-size:.84rem}
  .void-row strong{font-size:.9rem;color:#141b24}
  .void-row small{color:#6b7280}
  .void-row .void-actions{display:flex;gap:7px;margin-top:5px;flex-wrap:wrap}
  .void-row button{padding:6px 12px;border:0;border-radius:9px;font:inherit;font-size:.8rem;font-weight:700;cursor:pointer}
  .void-row button.danger{background:#fdeae7;color:#c0372b}
  .void-row button.danger:hover{background:#f9d6d0}
  .void-row button:disabled{opacity:.5;cursor:not-allowed}
  .void-tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.72rem;font-weight:700}
  .void-tag.refunded{background:#eceff3;color:#4a5564}
  .void-empty{color:#6b7280;font-size:.84rem;padding:7px 2px}
  .void-note{margin:12px 0 0;font-size:.84rem;min-height:1.2em}
  .void-note.bad{color:#c0372b}
  .void-note.good{color:#128a52}`;
  document.head.append(style);

  const panel = document.createElement('section');
  panel.className = 'void-panel';
  panel.hidden = true;
  panel.innerHTML = `<h3>ยกเลิกบิล และคืนเงิน</h3>
    <p class="void-lead" id="voidLead"></p>
    <div class="void-cols">
      <div class="void-col open-bills"><h4>บิลที่ยังไม่ได้รับเงิน</h4><ul class="void-list" id="voidOpenList"></ul></div>
      <div class="void-col paid-bills"><h4>บิลที่รับเงินแล้ว</h4><ul class="void-list" id="voidPaidList"></ul></div>
    </div>
    <p class="void-note" id="voidNote" role="status"></p>`;
  host.querySelector('.module-intro')?.after(panel);
  if (!panel.parentElement) host.prepend(panel);

  const note = (message, kind = '') => {
    const target = panel.querySelector('#voidNote');
    target.textContent = message;
    target.className = `void-note ${kind}`;
  };
  const api = async (path, options = {}) => {
    const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };

  /* One event id per bill and action, kept until the server accepts it, so a
     retry after a dropped connection cannot cancel or refund the bill twice. */
  const eventId = (kind, orderNo) => {
    const key = `poswai-${kind}:${orderNo}`;
    let id = null;
    try { id = sessionStorage.getItem(key); } catch (_) { /* private browsing */ }
    if (!id) {
      id = `${kind}-${crypto.randomUUID()}`;
      try { sessionStorage.setItem(key, id); } catch (_) { /* private browsing */ }
    }
    return id;
  };
  const clearEventId = (kind, orderNo) => {
    try { sessionStorage.removeItem(`poswai-${kind}:${orderNo}`); } catch (_) { /* private browsing */ }
  };

  const act = async (kind, order, button) => {
    const isVoid = kind === 'void';
    const what = isVoid ? 'ยกเลิกบิล' : 'คืนเงิน';
    const reason = prompt(`${what} ${order.order_no} · ${money(order.amount)}\n\nพิมพ์เหตุผล (3-200 ตัวอักษร) เหตุผลนี้จะถูกบันทึกไว้และแจ้งผู้จัดการ`, '');
    if (reason === null) return;
    if (reason.trim().length < 3) { note('ต้องใส่เหตุผลอย่างน้อย 3 ตัวอักษร', 'bad'); return; }
    if (!confirm(`ยืนยัน${what} ${order.order_no} จำนวน ${money(order.amount)} ใช่หรือไม่\n\nเหตุผล: ${reason.trim()}`)) return;
    button.disabled = true;
    note(`กำลัง${what}…`);
    const path = isVoid ? `/api/orders/${encodeURIComponent(order.order_no)}/void`
                        : `/api/payments/${encodeURIComponent(order.order_no)}/refund`;
    try {
      await api(path, {method: 'POST', body: JSON.stringify({event_id: eventId(kind, order.order_no), reason: reason.trim()})});
      clearEventId(kind, order.order_no);
      note(`${what} ${order.order_no} เรียบร้อย · แจ้งผู้จัดการทาง LINE แล้ว`, 'good');
      window.poswaiLiveData?.refresh?.().catch(() => {});
      await load();
    } catch (error) {
      note(error.message, 'bad');
      button.disabled = false;
    }
  };

  const row = (order, kind) => {
    const item = document.createElement('li');
    item.className = 'void-row';
    const title = document.createElement('strong');
    title.textContent = `${order.order_no} · ${money(order.amount)}`;
    const where = document.createElement('small');
    where.textContent = [order.table_no ? `โต๊ะ ${order.table_no}` : '', clock(order.at),
                         order.closed_by ? `ปิดโดย ${order.closed_by}` : ''].filter(Boolean).join(' · ');
    item.append(title, where);
    if (order.refunded) {
      const tag = document.createElement('span');
      tag.className = 'void-tag refunded';
      tag.textContent = 'คืนเงินแล้ว';
      const why = document.createElement('small');
      why.textContent = order.refund_reason || '';
      item.append(tag, why);
      return item;
    }
    const actions = document.createElement('div');
    actions.className = 'void-actions';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'danger';
    button.textContent = kind === 'void' ? 'ยกเลิกบิล' : 'คืนเงิน';
    if (preview()) { button.disabled = true; button.title = 'ร้านตัวอย่างทำรายการจริงไม่ได้'; }
    if (kind === 'refund' && !canRefund()) { button.disabled = true; button.title = 'เฉพาะผู้จัดการหรือเจ้าของร้าน'; }
    button.addEventListener('click', () => act(kind, order, button));
    actions.append(button);
    item.append(actions);
    return item;
  };

  const fill = (list, orders, kind, emptyText) => {
    list.replaceChildren();
    if (!orders.length) {
      const empty = document.createElement('li');
      empty.className = 'void-empty';
      empty.textContent = emptyText;
      list.append(empty);
      return;
    }
    for (const order of orders) list.append(row(order, kind));
  };

  async function load() {
    if (!auth().current) return;
    try {
      const [open, settled] = await Promise.all([
        api(`/api/orders?branch_id=${branch()}`),
        api(`/api/orders/settled?branch_id=${branch()}&limit=20`),
      ]);
      fill(panel.querySelector('#voidOpenList'),
           open.orders.map(order => ({order_no: order.order_no, amount: order.total_amount,
                                      table_no: order.table_no, at: order.created_at})),
           'void', 'ยังไม่มีบิลที่เปิดค้างอยู่');
      fill(panel.querySelector('#voidPaidList'),
           settled.orders.map(order => ({order_no: order.order_no, amount: order.net_amount,
                                         table_no: order.table_no, at: order.closed_at,
                                         closed_by: order.closed_by, refunded: order.status === 'refunded',
                                         refund_reason: order.refund_reason})),
           'refund', 'ยังไม่มีบิลที่รับเงินแล้ว');
    } catch (error) {
      note(`โหลดรายการบิลไม่สำเร็จ: ${error.message}`, 'bad');
    }
  }

  const update = () => {
    const signedIn = Boolean(auth().current);
    panel.hidden = !signedIn || !['cashier', 'manager', 'owner'].includes(role());
    if (panel.hidden) return;
    panel.querySelector('#voidLead').textContent = canRefund()
      ? `คุณยกเลิกบิลได้ทุกยอด และคืนเงินบิลที่รับเงินแล้วได้ ทุกรายการต้องใส่เหตุผลและถูกบันทึกไว้`
      : `ยกเลิกเองได้เฉพาะบิลที่ยังไม่รับเงิน ไม่เกิน ${Number(limits.max_amount).toLocaleString('th-TH')} บาท และไม่เกิน ${limits.daily_limit} ครั้งต่อวัน เกินกว่านั้นต้องให้ผู้จัดการทำ · การคืนเงินเป็นสิทธิ์ของผู้จัดการเท่านั้น`;
    load();
  };

  window.addEventListener('poswai:auth-changed', update);
  fetch('/api/config', {cache: 'no-store'}).then(response => response.json()).then(config => {
    if (config.void_limits) limits = config.void_limits;
    update();
  }).catch(update);
})();
