/* โอนของข้ามสาขา — the note that travels with the box.

   Moving stock between branches used to happen in one instant, which is a van
   that never breaks down. Now one branch sends the note and the other says
   what actually turned up; the stock moves on that. */
(() => {
  const text = (value) => String(value ?? '').replace(/[<>&]/g, '');
  const STAGE = {sent: 'ส่งแล้ว รอปลายทางยืนยัน', received: 'รับของแล้ว', cancelled: 'ยกเลิก'};

  const ask = async (path, options) => {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options});
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
      throw new Error(detail);
    }
    return response.json();
  };
  const post = (path, body) => ask(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})});

  const panel = document.createElement('section');
  panel.className = 'card transfer-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="card-header"><div class="card-title">🔁 โอนของข้ามสาขา</div></div>
    <p class="shift-hint" id="trHint">สาขาต้นทางเขียนใบโอน · ของจะย้ายตอนสาขาปลายทางกดยืนยันว่าได้รับเท่าไหร่</p>

    <details class="po-block" open>
      <summary>เขียนใบโอนใหม่</summary>
      <div class="shift-row">
        <label for="trTo">ส่งไปสาขา</label>
        <select id="trTo" class="input"></select>
      </div>
      <div id="trLines"></div>
      <div class="shift-row">
        <button type="button" class="btn btn-outline" id="trAddLine">+ เพิ่มรายการ</button>
        <button type="button" class="btn btn-line" id="trSend">ส่งใบโอน</button>
      </div>
    </details>

    <h4 class="po-heading">ใบโอนล่าสุด</h4>
    <div id="trList" class="po-list"></div>
    <p id="trStatus" role="status" class="shift-status"></p>`;

  const at = (id) => panel.querySelector(`#${id}`);
  const branch = () => window.poswaiAuth?.branchId || 1;
  const say = (message, bad = false) => {
    at('trStatus').textContent = message;
    at('trStatus').classList.toggle('bad', bad);
  };

  const lineRow = () => {
    const row = document.createElement('div');
    row.className = 'po-line tr-line';
    row.innerHTML = `
      <input class="input tr-ing" list="poIngredientList" maxlength="80" placeholder="รหัสวัตถุดิบ">
      <input class="input tr-qty" type="number" min="0" step="any" placeholder="จำนวน">
      <button type="button" class="ghost">ลบ</button>`;
    row.querySelector('button').addEventListener('click', () => row.remove());
    at('trLines').append(row);
    return row;
  };

  const readLines = () => [...at('trLines').querySelectorAll('.tr-line')].map(row => ({
    ingredient_id: row.querySelector('.tr-ing').value.trim(),
    quantity: Number(row.querySelector('.tr-qty').value) || 0,
  })).filter(line => line.ingredient_id && line.quantity > 0);

  /* Only the receiving branch gets the confirm button, because the branch
     that sent the box cannot sign for its own delivery. */
  const card = (note, here) => {
    const mine = note.to_branch_id === here;
    const lines = note.lines.map(line =>
      `<tr><td>${text(line.ingredient_id)}</td><td>${line.quantity}</td>` +
      `<td>${line.received_quantity === null || line.received_quantity === undefined
        ? '—' : line.received_quantity}</td>` +
      `<td class="${line.missing ? 'loss' : ''}">${line.missing || ''}</td></tr>`).join('');
    const actions = note.status !== 'sent' ? ''
      : (mine ? `<button type="button" class="btn btn-line" data-receive="${note.id}">ยืนยันรับของ</button>` : '')
        + `<button type="button" class="ghost" data-cancel="${note.id}">ยกเลิก</button>`;
    return `<article class="po-card po-${note.status}">
      <header><strong>${text(note.number)}</strong>
        <span>${text(note.from_branch)} → ${text(note.to_branch)}</span>
        <em>${STAGE[note.status] || note.status}</em>
        ${note.shortfall ? '<strong class="loss">ของมาไม่ครบ</strong>' : ''}</header>
      <table><thead><tr><th>วัตถุดิบ</th><th>ส่ง</th><th>รับจริง</th><th>ขาด</th></tr></thead>
      <tbody>${lines}</tbody></table>
      ${note.cancel_reason ? `<p class="po-reason">ยกเลิก: ${text(note.cancel_reason)}</p>` : ''}
      <div class="po-actions">${actions}</div>
    </article>`;
  };

  const drawTransit = (transit) => {
    const bits = [];
    const incoming = Object.entries(transit?.incoming || {});
    const outgoing = Object.entries(transit?.outgoing || {});
    if (incoming.length) bits.push(`กำลังมาถึงสาขานี้: ${incoming.map(([i, q]) => `${i} ${q}`).join(' · ')}`);
    if (outgoing.length) bits.push(`ส่งออกไปแล้วรอปลายทางยืนยัน: ${outgoing.map(([i, q]) => `${i} ${q}`).join(' · ')}`);
    at('trHint').textContent = bits.length ? bits.join(' | ')
      : 'สาขาต้นทางเขียนใบโอน · ของจะย้ายตอนสาขาปลายทางกดยืนยันว่าได้รับเท่าไหร่';
  };

  const fillBranches = async () => {
    const pick = at('trTo');
    if (pick.options.length) return;
    try {
      const summary = await ask('/api/reports/branches');
      pick.innerHTML = summary.branches
        .filter(b => b.branch_id !== branch())
        .map(b => `<option value="${b.branch_id}">${text(b.name)}</option>`).join('');
      // One branch only: the whole panel has nothing to do.
      panel.classList.toggle('tr-single', !pick.options.length);
    } catch {
      // A manager cannot read the branch summary; they still know the number.
      pick.innerHTML = '<option value="">พิมพ์เลขสาขาปลายทางไม่ได้ ให้เจ้าของร้านเป็นคนโอน</option>';
    }
  };

  const load = async () => {
    try {
      await fillBranches();
      const data = await ask(`/api/transfers?branch_id=${branch()}&limit=20`);
      at('trList').innerHTML = data.transfers.map(note => card(note, branch())).join('')
        || '<p class="shift-empty">ยังไม่มีใบโอน</p>';
      drawTransit(data.in_transit);
      say('');
    } catch (error) { say(error.message, true); }
  };

  at('trAddLine').addEventListener('click', () => lineRow().querySelector('.tr-ing').focus());

  at('trSend').addEventListener('click', async () => {
    const lines = readLines();
    if (!lines.length) { say('ใส่วัตถุดิบและจำนวนอย่างน้อยหนึ่งรายการ', true); return; }
    const to = Number(at('trTo').value);
    if (!to) { say('เลือกสาขาปลายทางก่อน', true); return; }
    try {
      const made = await post('/api/transfers',
        {from_branch_id: branch(), to_branch_id: to, lines});
      at('trLines').replaceChildren();
      lineRow();
      await load();
      say(`ส่งใบ ${made.number} แล้ว รอสาขาปลายทางยืนยัน`);
    } catch (error) { say(error.message, true); }
  });

  at('trList').addEventListener('click', async (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    const id = button.dataset.receive || button.dataset.cancel;
    if (!id) return;
    try {
      if (button.dataset.receive) {
        const shortfall = window.prompt(
          'ของมาครบไหม? ถ้าครบกด OK เลย\nถ้าไม่ครบ พิมพ์เช่น PORK=8', '');
        if (shortfall === null) return;
        const received = {};
        for (const part of shortfall.split(',')) {
          const [name, qty] = part.split('=').map(piece => piece.trim());
          if (name && qty !== undefined) received[name] = Number(qty);
        }
        await post(`/api/transfers/${id}/receive`, {branch_id: branch(), received});
        say('ยืนยันรับแล้ว สต็อกย้ายให้เรียบร้อย');
        window.poswaiLiveData?.refresh?.();
      } else {
        const reason = window.prompt('ยกเลิกเพราะอะไร');
        if (!reason) return;
        await post(`/api/transfers/${id}/cancel`, {branch_id: branch(), reason});
        say('ยกเลิกแล้ว');
      }
      await load();
    } catch (error) { say(error.message, true); }
  });

  const home = document.querySelector('#view-inventory');
  if (home) home.append(panel);

  const update = () => {
    const role = window.poswaiAuth?.current?.role;
    const allowed = ['owner', 'manager', 'kitchen'].includes(role);
    const wasHidden = panel.hidden;
    panel.hidden = !allowed;
    if (allowed && wasHidden) {
      if (!at('trLines').children.length) lineRow();
      load();
    }
  };
  window.addEventListener('poswai:auth-changed', update);
  update();
})();
