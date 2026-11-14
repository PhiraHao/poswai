/* Bills sold while the shop's internet was down, for the owner to check.

   The server records those sales as they happened — at the price the till
   charged, with a sold-out dish or short stock let through — and writes down
   each difference from the menu. This card on the reports screen is where the
   owner reads them and ticks each one off. Owners and managers only; the card
   stays hidden for everyone else and when there is nothing to show. */
(() => {
  const auth = () => window.poswaiAuth || {};
  const mayReview = () => ['owner', 'manager'].includes(auth().current?.role);
  const branch = () => auth().branchId || 1;
  let showAll = false;

  const style = document.createElement('style');
  style.textContent = [
    // The live reports mode hides every card but its own; this one is one of its own.
    '#view-analytics.report-live-mode>#offlineReviewCard.ofr:not([hidden]){display:block!important}',
    '.ofr{margin:0 0 16px}.ofr h3{display:flex;align-items:center;gap:8px;margin:0 0 4px}',
    '.ofr-count{min-width:22px;padding:0 7px;border-radius:999px;background:#c2382f;color:#fff;font-size:12px;line-height:22px;text-align:center}',
    '.ofr-lead{margin:0 0 12px;color:#4a5563;font-size:13px}',
    '.ofr-list{display:grid;gap:8px;margin:0;padding:0;list-style:none}',
    '.ofr-item{border:1px solid #e3e8ef;border-radius:12px;padding:12px;background:#fff}',
    '.ofr-item.done{opacity:.65}',
    '.ofr-top{display:flex;justify-content:space-between;gap:8px;font-weight:700}',
    '.ofr-meta{margin:2px 0 6px;color:#4a5563;font-size:12px}',
    '.ofr-notes{margin:0 0 8px;padding:0 0 0 18px;font-size:13px;color:#7a4b00}',
    '.ofr-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    '.ofr-actions button{min-height:36px;padding:0 14px;border:0;border-radius:10px;background:#ffc928;font-weight:700;cursor:pointer}',
    '.ofr-toggle{background:none!important;border:1px solid #e3e8ef!important}',
    '.ofr-empty{color:#4a5563;font-size:13px}',
  ].join('');
  document.head.append(style);

  const card = document.createElement('section');
  card.className = 'card ofr';
  card.id = 'offlineReviewCard';
  card.hidden = true;

  const when = text => {
    if (!text) return '';
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? text
      : date.toLocaleString('th-TH', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
  };
  const money = value => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const STATUS = {paid: 'จ่ายแล้ว', open: 'ยังไม่ปิดบิล', void: 'ยกเลิกแล้ว', refunded: 'คืนเงินแล้ว'};

  const el = (tag, props = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children.filter(child => child !== null && child !== undefined && child !== ''));
    return node;
  };

  const render = data => {
    const sales = data.sales || [];
    const header = el('h3', {}, 'บิลที่ขายตอนเน็ตหลุด',
      data.unreviewed ? el('span', {className: 'ofr-count', textContent: String(data.unreviewed)}) : null);
    const lead = el('p', {className: 'ofr-lead', textContent:
      'ระบบบันทึกตามที่ขายจริงตอนเน็ตหลุด แล้วจดไว้ว่าต่างจากเมนูตรงไหน ตรวจแล้วกด "ตรวจแล้ว" ทีละบิล'});
    const list = el('ul', {className: 'ofr-list'});
    for (const sale of sales) {
      const item = el('li', {className: `ofr-item${sale.reviewed_at ? ' done' : ''}`});
      item.append(
        el('div', {className: 'ofr-top'},
          el('span', {textContent: `โต๊ะ ${sale.table_no} · ${sale.order_no}`}),
          el('span', {textContent: money(sale.net_amount ?? sale.total_amount)})),
        el('div', {className: 'ofr-meta', textContent: [
          STATUS[sale.status] || sale.status, sale.payment_method,
          sale.ordered_offline_at ? `สั่ง ${when(sale.ordered_offline_at)}` : '',
          sale.closed_offline_at ? `ปิดบิล ${when(sale.closed_offline_at)}` : '',
          sale.taken_by_name ? `รับเงินโดย ${sale.taken_by_name}` : '',
        ].filter(Boolean).join(' · ')}),
        sale.notes?.length
          ? el('ul', {className: 'ofr-notes'}, ...sale.notes.map(note => el('li', {textContent: note})))
          : el('div', {className: 'ofr-meta', textContent: 'ไม่มีอะไรต่างจากเมนู'}));
      const actions = el('div', {className: 'ofr-actions'});
      if (sale.reviewed_at) {
        actions.append(el('span', {className: 'ofr-meta',
          textContent: `ตรวจแล้ว${sale.reviewed_by_name ? ` โดย ${sale.reviewed_by_name}` : ''} · ${when(sale.reviewed_at + 'Z')}`}));
      } else {
        const tick = el('button', {type: 'button', textContent: 'ตรวจแล้ว'});
        tick.addEventListener('click', async () => {
          tick.disabled = true;
          try {
            const reply = await fetch(`/api/reports/offline-sales/${encodeURIComponent(sale.order_no)}/review`,
              {method: 'POST', credentials: 'same-origin'});
            if (!reply.ok) throw new Error((await reply.json().catch(() => ({}))).detail || `HTTP ${reply.status}`);
            await load();
          } catch (error) {
            tick.disabled = false;
            window.showToast?.(`⚠️ บันทึกไม่สำเร็จ: ${error.message}`);
          }
        });
        actions.append(tick);
      }
      item.append(actions);
      list.append(item);
    }
    const toggle = el('button', {type: 'button', className: 'ofr-toggle',
      textContent: showAll ? 'ดูเฉพาะที่ยังไม่ตรวจ' : 'ดูทั้งหมดรวมที่ตรวจแล้ว'});
    toggle.addEventListener('click', () => { showAll = !showAll; load(); });
    card.replaceChildren(header, lead,
      sales.length ? list : el('p', {className: 'ofr-empty',
        textContent: showAll ? 'ยังไม่เคยมีบิลที่ขายตอนเน็ตหลุด' : 'ไม่มีบิลค้างตรวจ'}),
      el('div', {className: 'ofr-actions', style: 'margin-top:8px'}, toggle));
    // Nothing ever sold offline: the card does not take up the screen at all.
    card.hidden = !data.unreviewed && !showAll && !sales.length;
  };

  async function load() {
    if (!mayReview()) { card.hidden = true; return; }
    try {
      const reply = await fetch(`/api/reports/offline-sales?branch_id=${branch()}&show=${showAll ? 'all' : 'unreviewed'}`,
        {credentials: 'same-origin', cache: 'no-store'});
      if (!reply.ok) { card.hidden = true; return; }
      render(await reply.json());
    } catch (_) { /* offline: the list waits for the line to come back */ }
  }

  const mount = () => {
    const view = document.getElementById('view-analytics');
    if (view && card.parentElement !== view) {
      const intro = view.querySelector('.module-intro');
      if (intro) intro.after(card); else view.prepend(card);
    }
    load();
  };

  window.addEventListener('poswai:auth-changed', mount);
  window.addEventListener('online', load);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
