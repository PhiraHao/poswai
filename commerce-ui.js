/* Online pickup, Songwai intake and consent-based CRM. No demo records here. */
(() => {
  const branch = () => window.poswaiAuth?.branchId || 1;
  const preview = () => typeof state !== 'undefined' && !!state.previewOnly;
  const staff = () => !!window.poswaiAuth?.current;
  const manager = () => ['manager', 'owner'].includes(window.poswaiAuth?.current?.role);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => `฿${Number(value || 0).toLocaleString('th-TH', {maximumFractionDigits:2})}`;
  const api = async (path, options = {}) => {
    const response = await fetch(path, {credentials:'same-origin', cache:'no-store', ...options,
      headers:{'Content-Type':'application/json', ...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };
  const post = (path, body, method='POST') => api(path, {method, body:JSON.stringify(body)});
  const crm = document.querySelector('#view-crm');
  if (!crm) return;
  crm.classList.add('commerce-ready');
  const shell = document.createElement('div');
  shell.className = 'commerce-shell';
  shell.innerHTML = `<div class="commerce-tabs" role="tablist" aria-label="สมาชิกและออเดอร์ออนไลน์">
    <button data-pane="orders" aria-selected="true">ออเดอร์ออนไลน์</button>
    <button data-pane="members" aria-selected="false">ลูกค้า</button>
    <button data-pane="campaigns" aria-selected="false">โปรโมชัน LINE</button>
    <button data-pane="connectors" aria-selected="false">ช่องทางขาย</button></div>
    <div id="commerceNotice" class="commerce-alert" role="status"></div>
    <section class="commerce-pane" data-pane="orders"><div class="commerce-card"><div class="commerce-toolbar"><h2>รับออเดอร์ออนไลน์</h2><select id="commerceOrderFilter" aria-label="กรองออเดอร์"><option value="active">กำลังดำเนินการ</option><option value="all">ทั้งหมด</option></select><button id="commerceRefresh" class="commerce-btn secondary">รีเฟรช</button></div><div id="commerceOrders" class="commerce-list"></div></div></section>
    <section class="commerce-pane" data-pane="members" hidden><div class="commerce-stats" id="commerceStats"></div><div class="commerce-card"><div class="commerce-toolbar"><h2>ลูกค้าร้าน</h2><select id="commerceSegment" aria-label="กลุ่มลูกค้า"><option value="all">ทั้งหมด</option><option value="new">ลูกค้าใหม่</option><option value="returning">ลูกค้าประจำ</option><option value="dormant30">หายไปเกิน 30 วัน</option></select></div><div id="commerceMembers" class="commerce-list"></div></div></section>
    <section class="commerce-pane" data-pane="campaigns" hidden><div class="commerce-card"><h2>ส่งโปรโมชันผ่าน LINE OA</h2><p class="commerce-muted">ส่งเฉพาะผู้ที่ยินยอมรับข่าวสารและเชื่อม LINE แล้ว ตรวจข้อความและจำนวนผู้รับก่อนส่งทุกครั้ง</p><form id="commerceCampaignForm" class="commerce-form"><label>กลุ่มเป้าหมาย<select name="segment"><option value="new">ลูกค้าใหม่</option><option value="returning">ลูกค้าประจำ</option><option value="dormant30">หายไปเกิน 30 วัน</option></select></label><label class="wide">ข้อความ<textarea name="message" rows="4" maxlength="500" required></textarea></label><button class="commerce-btn" type="submit">สร้างฉบับร่าง</button></form><div id="commerceCampaignDraft" class="commerce-muted"></div></div></section>
    <section class="commerce-pane" data-pane="connectors" hidden><div class="commerce-card"><h2>Songwai · ร้านโคตรเนื้อ</h2><p class="commerce-muted">เตรียมเมนูจาก Songwai เป็นฉบับร่างก่อน เมนูจะยังไม่เปิดขายจนกว่าจะใส่สูตรและสต็อกจริง</p><button id="commerceImport" class="commerce-btn" type="button">เตรียมเมนูทั้ง 8 รายการ</button><div id="commerceMap" class="commerce-list"></div></div><div class="commerce-card"><h3>ออเดอร์จากแอปอื่น · พนักงานบันทึก</h3><p class="commerce-muted">ใช้เมื่อร้านได้รับออเดอร์ในแอปแล้ว จึงบันทึกเข้าคิวครัว POS WAI ช่องทางเหล่านี้ยังไม่ได้ดึงออเดอร์อัตโนมัติ</p><form id="commerceManualForm" class="commerce-form"><label>ช่องทาง<select name="channel"><option>GrabFood</option><option>LINE MAN</option><option>ShopeeFood</option><option>TikTok Shop</option><option>โทรศัพท์</option></select></label><label>เลขออเดอร์ในแอป<input name="external_order_id" required maxlength="80" pattern="[A-Za-z0-9_-]{2,80}"></label><label>วิธีรับอาหาร<select name="fulfillment"><option value="rider_pickup">ไรเดอร์มารับ</option><option value="self_pickup">ลูกค้ามารับเอง</option></select></label><label>ชื่อลูกค้า<input name="customer_name" maxlength="100"></label><label>เบอร์โทร<input name="contact_phone" maxlength="30"></label><div class="wide commerce-menu-lines" id="commerceManualMenu"></div><button class="commerce-btn" type="submit">บันทึกเข้าคิวครัว</button></form><p id="commerceManualResult" role="status"></p></div></section>`;
  crm.querySelector('.module-intro')?.after(shell);
  const notice = message => { document.querySelector('#commerceNotice').textContent = message; };
  const panes = [...shell.querySelectorAll('.commerce-pane')];
  const openPane = name => {
    for (const pane of panes) pane.hidden = pane.dataset.pane !== name;
    for (const button of shell.querySelectorAll('.commerce-tabs button')) button.setAttribute('aria-selected', button.dataset.pane === name);
    if (name === 'orders') loadOrders();
    if (name === 'members') loadMembers();
    if (name === 'connectors') { loadMap(); loadManualMenu(); }
  };
  shell.querySelector('.commerce-tabs').addEventListener('click', event => { const name = event.target.closest('button')?.dataset.pane; if (name) openPane(name); });
  if (preview()) notice('โหมดตัวอย่าง · การรับออเดอร์และส่งข้อความจริงยังไม่เปิดใช้งาน');
  else notice('ข้อมูลออเดอร์และสมาชิกจากระบบจริง');
  async function loadOrders() {
    const box = shell.querySelector('#commerceOrders');
    if (!staff()) { box.textContent = 'เข้าสู่ระบบพนักงานเพื่อดูออเดอร์ออนไลน์'; return; }
    try {
      const {orders} = await api(`/api/online/orders?branch_id=${branch()}&status=${shell.querySelector('#commerceOrderFilter').value}`);
      if (!orders.length) { box.textContent = 'ยังไม่มีออเดอร์ในรายการนี้'; return; }
      const next = {new:['accepted','cancelled'],accepted:['preparing','cancelled'],preparing:['ready','cancelled'],ready:['handed_off']};
      const labels = {accepted:'รับออเดอร์',preparing:'เริ่มทำ',ready:'พร้อมรับ',handed_off:'ส่งมอบแล้ว',cancelled:'ยกเลิก'};
      box.innerHTML = orders.map(o => `<article class="commerce-row"><div class="commerce-row-head"><strong>${escapeHtml(o.order_no)} · ${escapeHtml(o.channel || (o.source === 'songwai' ? 'Songwai' : 'POS WAI'))}</strong><span class="commerce-pill">${escapeHtml(o.fulfillment === 'rider_pickup' ? 'ไรเดอร์รับ' : 'ลูกค้ารับเอง')}</span></div><small>${escapeHtml(o.customer_name || 'ลูกค้า')} · ${escapeHtml(o.contact_phone || 'ไม่ระบุโทรศัพท์')} · รหัสรับ ${escapeHtml(o.pickup_code)}</small><div>${o.items.map(i => `${escapeHtml(i.name)} × ${Number(i.qty)}`).join(' · ')}</div><strong>${money(o.total_amount)}</strong><small>สถานะ ${escapeHtml(o.status)} · ชำระเงิน ${escapeHtml(o.payment_status)}</small><div class="commerce-row-actions">${o.payment_status !== 'paid' && manager() ? `<button class="commerce-btn secondary" data-pay="${escapeHtml(o.order_no)}">ยืนยันรับเงิน</button>` : ''}${(next[o.status] || []).map(s => `<button class="commerce-btn ${s==='cancelled'?'secondary':''}" data-order="${escapeHtml(o.order_no)}" data-status="${s}" ${s==='handed_off' && o.payment_status!=='paid'?'disabled':''}>${labels[s]}</button>`).join('')}</div></article>`).join('');
    } catch (error) { box.textContent = `โหลดออเดอร์ไม่ได้: ${error.message}`; }
  }
  shell.querySelector('#commerceOrderFilter').addEventListener('change', loadOrders);
  shell.querySelector('#commerceRefresh').addEventListener('click', loadOrders);
  shell.querySelector('#commerceOrders').addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button || preview()) return;
    try {
      if (button.dataset.pay) { if (!confirm('ยืนยันว่าได้รับเงินจริงแล้ว?')) return; await api(`/api/online/orders/${encodeURIComponent(button.dataset.pay)}/payment`, {method:'PATCH'}); }
      else if (button.dataset.order) { if (button.dataset.status==='cancelled' && !confirm('ยกเลิกออเดอร์นี้?')) return; await post(`/api/online/orders/${encodeURIComponent(button.dataset.order)}`, {status:button.dataset.status}, 'PATCH'); }
      await loadOrders();
    } catch(error) { notice(error.message); }
  });
  async function loadMembers() {
    const box = shell.querySelector('#commerceMembers');
    if (!manager()) { box.textContent = 'ผู้จัดการเท่านั้นที่ดูข้อมูลสมาชิกได้'; return; }
    try {
      const all = (await api(`/api/crm/customers?branch_id=${branch()}`)).customers;
      const segment = shell.querySelector('#commerceSegment').value;
      const rows = segment === 'all' ? all : all.filter(c => c.segment === segment);
      shell.querySelector('#commerceStats').innerHTML = [['ทั้งหมด',all.length],['ลูกค้าประจำ',all.filter(c=>c.segment==='returning').length],['หายไป 30 วัน',all.filter(c=>c.segment==='dormant30').length]].map(([label,count])=>`<div class="commerce-stat"><span>${label}</span><strong>${count}</strong></div>`).join('');
      box.innerHTML = rows.length ? rows.map(c=>`<article class="commerce-row"><div class="commerce-row-head"><strong>${escapeHtml(c.display_name || 'ลูกค้า')}</strong><span class="commerce-pill ${c.marketing_opt_in?'green':'gray'}">${c.marketing_opt_in?'ยินยอมรับข่าวสาร':'ไม่รับข่าวสาร'}</span></div><small>${escapeHtml(c.phone || 'ไม่มีเบอร์')} · ${escapeHtml(c.source)} · ${c.completed_orders} ออเดอร์ · ${money(c.lifetime_amount)}</small><small>ล่าสุด ${escapeHtml(c.last_order_at || 'ยังไม่มีการซื้อ')} · ${escapeHtml(c.segment)}</small></article>`).join('') : 'ยังไม่มีลูกค้าในกลุ่มนี้';
    } catch(error) { box.textContent = `โหลดสมาชิกไม่ได้: ${error.message}`; }
  }
  shell.querySelector('#commerceSegment').addEventListener('change', loadMembers);
  shell.querySelector('#commerceCampaignForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (preview()) { notice('โหมดตัวอย่างยังสร้างแคมเปญไม่ได้'); return; }
    const form = event.currentTarget; const data = new FormData(form);
    try {
      const draft = await post('/api/crm/campaigns', {branch_id:branch(), segment:data.get('segment'), message:String(data.get('message')).trim()});
      const target = shell.querySelector('#commerceCampaignDraft');
      target.replaceChildren();
      const summary = document.createElement('p'); summary.textContent = `ฉบับร่าง #${draft.campaign_id} · ผู้รับที่ยินยอม ${draft.eligible_recipients} คน`;
      const send = document.createElement('button'); send.className='commerce-btn dark'; send.textContent='ตรวจและส่งผ่าน LINE OA'; send.disabled=!draft.eligible_recipients;
      send.onclick = async () => { if (!confirm(`ส่งข้อความนี้ถึงลูกค้า ${draft.eligible_recipients} คนทาง LINE OA ใช่หรือไม่?\n\n${String(data.get('message')).trim()}`)) return; try { const result=await post(`/api/crm/campaigns/${draft.campaign_id}/send`,{}); target.textContent=`LINE รับคำขอส่ง ${result.line_accepted} จาก ${result.attempted} ราย`; } catch(error) { notice(error.message); } };
      target.append(summary,send);
    } catch(error) { notice(error.message); }
  });
  async function loadMap() {
    const box = shell.querySelector('#commerceMap');
    if (!manager()) { box.textContent='ผู้จัดการเท่านั้นที่จับคู่เมนูได้'; return; }
    try {
      const [catalog, mapping, pos] = await Promise.all([api(`/api/integrations/songwai/catalog?branch_id=${branch()}`),api(`/api/integrations/songwai/menu-map?branch_id=${branch()}`),api(`/api/menu?branch_id=${branch()}&include_inactive=true`)]);
      box.innerHTML = catalog.items.length ? catalog.items.map(item=>{const mapped=mapping.mappings.find(m=>m.songwai_menu_id===item.id);const selected=pos.items.find(p=>p.id===mapped?.pos_item_id);return `<div class="commerce-map-row"><span>${escapeHtml(item.name)} · ${money(item.price)}${selected&&!selected.active?' · รอสูตรและสต็อก':''}</span><select aria-label="เมนู POS สำหรับ ${escapeHtml(item.name)}" data-menu="${Number(item.id)}"><option value="">ยังไม่จับคู่</option>${pos.items.map(p=>`<option value="${escapeHtml(p.id)}" ${mapped?.pos_item_id===p.id?'selected':''}>${escapeHtml(p.name)} · ${p.active?'เปิดขาย':'ฉบับร่าง'}</option>`).join('')}</select><button class="commerce-btn secondary" data-save="${Number(item.id)}" ${selected&&!selected.active?'disabled title="ใส่สูตรและสต็อกก่อน"':''}>บันทึก</button></div>`;}).join('') : 'ร้าน Songwai ยังไม่มีเมนู';
    } catch(error) { box.textContent=`โหลดเมนู Songwai ไม่ได้: ${error.message}`; }
  }
  shell.querySelector('#commerceMap').addEventListener('click', async event => {
    const button=event.target.closest('[data-save]'); if (!button || preview()) return;
    const menuId=Number(button.dataset.save); const value=shell.querySelector(`select[data-menu="${menuId}"]`)?.value;
    if (!value) { notice('เลือกเมนู POS WAI ก่อน'); return; }
    try { await post('/api/integrations/songwai/menu-map',{branch_id:branch(),restaurant_id:37,songwai_menu_id:menuId,pos_item_id:value},'PUT'); notice('จับคู่เมนูแล้ว'); }
    catch(error) { notice(error.message); }
  });
  shell.querySelector('#commerceImport').addEventListener('click', async () => {
    if (preview()) { notice('โหมดตัวอย่างยังบันทึกเมนูไม่ได้'); return; }
    try { const result=await post(`/api/integrations/songwai/import-drafts?branch_id=${branch()}`,{}); notice(`เตรียมเมนูใหม่ ${result.imported} จาก ${result.total} รายการแล้ว ยังไม่เปิดขาย`); await loadMap(); }
    catch(error) { notice(error.message); }
  });
  async function loadManualMenu() {
    const box = shell.querySelector('#commerceManualMenu');
    if (!staff()) { box.textContent='เข้าสู่ระบบพนักงานก่อนบันทึกออเดอร์'; return; }
    try {
      const {items}=await api(`/api/menu?branch_id=${branch()}`);
      box.innerHTML=items.length ? items.map(item=>`<label class="commerce-menu-line"><span>${escapeHtml(item.name)}</span><small>${money(item.price)}</small><input type="number" min="0" max="99" value="0" data-manual-item="${escapeHtml(item.id)}" aria-label="จำนวน ${escapeHtml(item.name)}"></label>`).join('') : 'ยังไม่มีเมนูจริงที่เปิดขาย';
    } catch(error) { box.textContent=error.message; }
  }
  shell.querySelector('#commerceManualForm').addEventListener('submit',async event=>{
    event.preventDefault();
    const result=shell.querySelector('#commerceManualResult');
    if (preview()) { result.textContent='โหมดตัวอย่างยังบันทึกออเดอร์จริงไม่ได้'; return; }
    const items=[...shell.querySelectorAll('[data-manual-item]')].map(input=>({id:input.dataset.manualItem,qty:Number(input.value)})).filter(item=>item.qty>0);
    if (!items.length) { result.textContent='เลือกอาหารอย่างน้อยหนึ่งรายการ'; return; }
    const data=new FormData(event.currentTarget);
    try {
      const order=await post('/api/online/manual-orders',{branch_id:branch(),channel:data.get('channel'),external_order_id:String(data.get('external_order_id')).trim(),fulfillment:data.get('fulfillment'),items,customer_name:data.get('customer_name'),contact_phone:data.get('contact_phone')});
      result.textContent=`เข้าคิวครัวแล้ว ${order.order_no} · ${money(order.total_amount)}`;
      await loadOrders();
    } catch(error) { result.textContent=error.message; }
  });
  const customer=document.querySelector('#view-customer .module-intro');
  if (customer) {
    const open=document.createElement('button'); open.type='button'; open.className='commerce-btn commerce-pickup-open'; open.textContent='สั่งล่วงหน้า · รับที่ร้าน'; customer.append(open);
    const modal=document.createElement('div'); modal.className='commerce-modal'; modal.hidden=true;
    modal.innerHTML=`<div class="commerce-modal-card" role="dialog" aria-modal="true" aria-label="สั่งอาหารรับที่ร้าน"><div class="commerce-modal-head"><h2>สั่งล่วงหน้า รับที่ร้าน</h2><button class="commerce-btn secondary" id="pickupClose">ปิด</button></div><p class="commerce-muted">เลือกอาหาร แล้วลงชื่อเข้าใช้ LINE เพื่อยืนยันออเดอร์</p><form id="pickupForm" class="commerce-form"><div class="commerce-menu-lines wide" id="pickupMenu"></div><label>ชื่อผู้รับ<input name="name" maxlength="100" required></label><label>เบอร์โทร<input name="phone" type="tel" maxlength="30"></label><label class="wide"><span><input name="consent" type="checkbox"> ยินยอมรับโปรโมชันทาง LINE</span></label><button class="commerce-btn" type="submit">ยืนยันออเดอร์</button></form><p id="pickupResult" role="status"></p></div>`;
    document.body.append(modal);
    open.onclick=async()=>{ modal.hidden=false; const box=modal.querySelector('#pickupMenu'); try { const {items}=await api(`/api/menu?branch_id=${branch()}`); box.innerHTML=items.filter(i=>i.active).map(i=>`<label class="commerce-menu-line"><span>${escapeHtml(i.name)}</span><small>${money(i.price)}</small><input type="number" min="0" max="99" value="0" data-item="${escapeHtml(i.id)}" aria-label="จำนวน ${escapeHtml(i.name)}"></label>`).join('') || 'ยังไม่มีเมนูที่เปิดขาย'; } catch(error) { box.textContent=error.message; } };
    modal.querySelector('#pickupClose').onclick=()=>{modal.hidden=true;};
    modal.addEventListener('click',event=>{if(event.target===modal) modal.hidden=true;});
    modal.querySelector('#pickupForm').addEventListener('submit',async event=>{
      event.preventDefault(); const result=modal.querySelector('#pickupResult');
      if (preview()) { result.textContent='โหมดตัวอย่างยังรับออเดอร์จริงไม่ได้'; return; }
      const items=[...modal.querySelectorAll('[data-item]')].map(input=>({id:input.dataset.item,qty:Number(input.value)})).filter(i=>i.qty>0);
      if (!items.length) { result.textContent='เลือกอาหารอย่างน้อยหนึ่งรายการ'; return; }
      const data=new FormData(event.currentTarget);
      try { const line_id_token=await getLineIdToken(); if(!line_id_token) throw new Error('กรุณาเปิดจาก LINE LIFF และเข้าสู่ระบบก่อน');
        const event_id=crypto.randomUUID(); const order=await post('/api/online/orders',{event_id,branch_id:branch(),fulfillment:'self_pickup',items,customer_name:data.get('name'),contact_phone:data.get('phone'),line_id_token,marketing_opt_in:!!data.get('consent')});
        result.textContent=`รับออเดอร์แล้ว รหัสรับอาหาร ${order.pickup_code} · ${money(order.total_amount)}`;
      } catch(error) { result.textContent=error.message; }
    });
  }
  window.addEventListener('poswai:config-ready',()=>{notice(preview()?'โหมดตัวอย่าง · การรับออเดอร์และส่งข้อความจริงยังไม่เปิดใช้งาน':'ข้อมูลจากระบบจริง');loadOrders();});
  window.addEventListener('poswai:auth-changed',loadOrders);
  loadOrders();
})();
