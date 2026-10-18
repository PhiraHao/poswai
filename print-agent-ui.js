/* Sending a receipt to the printer from a till that cannot reach it.

   The shop's till is a phone. A 58mm USB-and-Bluetooth printer cannot be
   driven from Safari at all, and from Chrome only with pairing dances nobody
   wants mid-service. So the receipt is handed to the shop instead: the server
   holds it, and a small program on the machine the printer is plugged into
   collects and prints it. This file is the shop's half of that — one button
   to send, and the owner's box for setting the machine up. */
(() => {
  const $ = id => document.getElementById(id);
  const auth = () => window.poswaiAuth || {};
  const branch = () => auth().branchId || 1;
  const isManager = () => ['manager', 'owner'].includes(auth().current?.role);

  const request = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };
  const post = (url, body) => request(url, {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

  const style = document.createElement('style');
  style.textContent = [
    '.prn-panel{margin:14px 0 0}',
    '.prn-row{display:flex;justify-content:space-between;align-items:center;gap:10px;',
    'border:1px solid #e9edf2;border-radius:12px;padding:11px 13px;margin:0 0 8px}',
    '.prn-row small{display:block;color:#6b7280;font-size:.76rem;margin-top:2px}',
    '.prn-key{margin:10px 0 0;padding:12px 14px;background:#fffaf0;border:1px solid #f7e4ac;',
    'border-radius:12px;color:#6b5720;font-size:.84rem;line-height:1.8;word-break:break-all}',
    '.prn-key code{display:block;margin:6px 0;font-size:.95rem;color:#17222e;font-weight:700}',
    '.prn-note{margin:10px 0 0;color:#6b7280;font-size:.8rem;line-height:1.8}',
  ].join('');
  document.head.append(style);

  /* ---- sending ---------------------------------------------------------- */
  const sendButton = document.createElement('button');
  sendButton.type = 'button';
  sendButton.className = 'btn btn-sm btn-primary';
  sendButton.textContent = '🖨️ ส่งไปเครื่องพิมพ์';
  sendButton.addEventListener('click', async () => {
    const preview = $('thermalReceiptPreview');
    const body = (preview?.textContent || '').trim();
    if (!body || body.startsWith('พร้อมพิมพ์')) {
      window.showToast?.('⚠️ กดพิมพ์ใบแจ้งหนี้หรือปิดบิลก่อน แล้วค่อยส่งไปเครื่องพิมพ์');
      return;
    }
    sendButton.disabled = true;
    const was = sendButton.textContent;
    sendButton.textContent = 'กำลังส่ง…';
    try {
      const result = await post('/api/print/jobs', {
        branch_id: branch(), title: body.split('\n')[2]?.trim() || 'ใบเสร็จ', body,
      });
      window.showToast?.(result.queued > 1
        ? `✅ ส่งแล้ว · รอพิมพ์อยู่ ${result.queued} ใบ`
        : '✅ ส่งไปเครื่องพิมพ์แล้ว');
      if (!panel.hidden) loadAgents();
    } catch (error) {
      window.showToast?.(`⚠️ ${error.message}`);
    } finally { sendButton.disabled = false; sendButton.textContent = was; }
  });

  /* ---- the owner's setup box -------------------------------------------- */
  const panel = document.createElement('div');
  panel.className = 'card prn-panel';
  panel.hidden = true;
  panel.innerHTML = `<div class="card-header">
      <div class="card-title">🖨️ เครื่องที่เสียบปริ้นเตอร์ไว้</div>
      <button type="button" class="btn btn-sm btn-primary" id="prnAdd">+ เพิ่มเครื่องพิมพ์</button>
    </div>
    <p class="prn-note">ใบเสร็จที่สั่งพิมพ์จากมือถือหรือไอแพดจะไปออกที่เครื่องนี้
      เพราะมือถือต่อกับปริ้นเตอร์ 58 มม. ตรง ๆ ไม่ได้ · ต้องเปิดโปรแกรมตัวกลาง
      (print-agent.py) ค้างไว้บนเครื่องที่เสียบปริ้นเตอร์</p>
    <div id="prnList"></div>
    <div id="prnKeyBox"></div>`;

  const loadAgents = async () => {
    const list = $('prnList');
    if (!list) return;
    try {
      const data = await request(`/api/print/agents?branch_id=${branch()}`);
      list.replaceChildren();
      if (!data.agents.length) {
        const empty = document.createElement('p');
        empty.className = 'prn-note';
        empty.textContent = 'ยังไม่ได้ตั้งค่าเครื่องพิมพ์ กดปุ่มเพิ่มเครื่องพิมพ์เพื่อรับกุญแจ';
        list.append(empty);
        return;
      }
      for (const agent of data.agents) {
        const row = document.createElement('div');
        row.className = 'prn-row';
        const who = document.createElement('div');
        const name = document.createElement('strong');
        name.textContent = agent.name || `เครื่องพิมพ์ #${agent.id}`;
        const seen = document.createElement('small');
        seen.textContent = agent.last_seen_at
          ? `ติดต่อล่าสุด ${agent.last_seen_at}`
          : 'ยังไม่เคยติดต่อมาเลย — ตรวจว่าเปิดโปรแกรมตัวกลางแล้วหรือยัง';
        who.append(name, seen);
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn btn-sm btn-outline';
        remove.textContent = 'ลบ';
        remove.addEventListener('click', async () => {
          if (!confirm(`ลบ ${name.textContent}? กุญแจเดิมจะใช้ไม่ได้ทันที`)) return;
          try {
            await request(`/api/print/agents/${agent.id}?branch_id=${branch()}`, {method: 'DELETE'});
            loadAgents();
          } catch (error) { window.showToast?.(`⚠️ ${error.message}`); }
        });
        row.append(who, remove);
        list.append(row);
      }
      if (data.waiting) {
        const waiting = document.createElement('p');
        waiting.className = 'prn-note';
        waiting.textContent = `มีใบรอพิมพ์อยู่ ${data.waiting} ใบ`;
        list.append(waiting);
      }
    } catch (error) {
      list.textContent = error.message;
    }
  };

  panel.querySelector('#prnAdd').addEventListener('click', async () => {
    const name = prompt('ตั้งชื่อเครื่องที่เสียบปริ้นเตอร์ไว้ เช่น คอมหน้าร้าน', 'คอมหน้าร้าน');
    if (name === null) return;
    try {
      const agent = await post('/api/print/agents', {branch_id: branch(), name});
      const box = $('prnKeyBox');
      box.replaceChildren();
      const note = document.createElement('div');
      note.className = 'prn-key';
      /* Shown once. The server keeps only a hash of it, the same as a PIN. */
      note.innerHTML = '<strong>กุญแจของเครื่องนี้ · จะแสดงครั้งเดียว</strong>';
      const key = document.createElement('code');
      key.textContent = agent.key;
      const how = document.createElement('span');
      how.textContent = 'ก๊อปไปใส่ในโปรแกรมตัวกลางบนเครื่องที่เสียบปริ้นเตอร์ '
        + 'ถ้าทำหาย ให้ลบเครื่องนี้แล้วเพิ่มใหม่';
      note.append(key, how);
      box.append(note);
      loadAgents();
    } catch (error) { window.showToast?.(`⚠️ ${error.message}`); }
  });

  /* ---- mounting --------------------------------------------------------- */
  const mount = () => {
    const preview = $('thermalReceiptPreview');
    const header = preview?.closest('.card')?.querySelector('.card-header div:last-child');
    if (header && sendButton.parentElement !== header) header.prepend(sendButton);
    const home = document.querySelector('#view-cashier');
    if (home && !panel.parentElement) home.append(panel);
  };

  const sync = () => {
    mount();
    const manager = isManager();
    panel.hidden = !manager;
    sendButton.hidden = !['cashier', 'manager', 'owner'].includes(auth().current?.role);
    if (manager) loadAgents();
  };

  window.addEventListener('poswai:auth-changed', sync);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sync);
  else sync();
})();
