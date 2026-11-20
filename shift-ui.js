/* กะการขายและลิ้นชักเงินสด — the drawer, on the cashier's own screen.

   The shop has always known what it sold. What it has never known is what is
   actually in the drawer, and the gap between the two is the only place a
   shop ever finds out that money went missing.

   The screen shows one number large — what the drawer should hold right now —
   because that is the number a person compares against a handful of notes. */
(() => {
  const money = (value) => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const KIND_WORDS = {in: 'นำเงินเข้า', out: 'นำเงินออก', expense: 'จ่ายค่าของ'};

  const ask = async (path, options) => {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options});
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
      throw new Error(detail);
    }
    return response.json();
  };
  const send = (path, body) => ask(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

  const panel = document.createElement('section');
  panel.className = 'card shift-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="card-header"><div class="card-title">💵 กะการขาย · ลิ้นชักเงินสด</div></div>
    <div id="shiftClosed">
      <p class="shift-hint">เปิดกะตอนเริ่มงาน แล้วนับเงินอีกครั้งตอนปิด ระบบจะบอกว่าเงินขาดหรือเกินเท่าไหร่</p>
      <div class="shift-row">
        <label for="shiftOpening">เงินทอนตั้งต้นในลิ้นชัก</label>
        <input id="shiftOpening" type="number" min="0" step="1" value="0" class="input">
        <button type="button" class="btn btn-line" id="shiftOpenButton">เปิดกะ</button>
      </div>
    </div>
    <div id="shiftOpenBox" hidden>
      <div class="shift-expected">
        <span>เงินที่ควรมีในลิ้นชักตอนนี้</span>
        <strong id="shiftExpected">฿0.00</strong>
      </div>
      <div class="shift-figures" id="shiftFigures"></div>
      <div class="shift-row">
        <select id="shiftMoveKind" class="input">
          <option value="in">นำเงินเข้าลิ้นชัก</option>
          <option value="out">นำเงินออก (เช่น ไปฝากธนาคาร)</option>
          <option value="expense">จ่ายค่าของจากลิ้นชัก</option>
        </select>
        <input id="shiftMoveAmount" type="number" min="1" step="1" class="input" placeholder="บาท">
        <input id="shiftMoveReason" class="input" maxlength="200" placeholder="เหตุผล (ต้องกรอกเมื่อนำเงินออก)">
        <button type="button" class="btn btn-outline" id="shiftMoveButton">บันทึก</button>
      </div>
      <ul class="shift-moves" id="shiftMoves"></ul>
      <div class="shift-row shift-close">
        <label for="shiftCounted">นับเงินในลิ้นชักได้</label>
        <input id="shiftCounted" type="number" min="0" step="1" class="input" placeholder="บาท">
        <button type="button" class="btn btn-warning" id="shiftCloseButton">ปิดกะ</button>
      </div>
      <p id="shiftDifference" class="shift-difference"></p>
    </div>
    <p id="shiftStatus" role="status" class="shift-status"></p>`;

  const at = (id) => panel.querySelector(`#${id}`);
  const branch = () => window.poswaiAuth?.branchId || 1;
  const say = (text, bad = false) => {
    at('shiftStatus').textContent = text;
    at('shiftStatus').classList.toggle('bad', bad);
  };

  let shift = null;

  const draw = () => {
    at('shiftClosed').hidden = !!shift;
    at('shiftOpenBox').hidden = !shift;
    if (!shift) return;
    at('shiftExpected').textContent = money(shift.expected);
    at('shiftFigures').innerHTML = [
      ['เงินทอนตั้งต้น', shift.opening],
      ['ขายเป็นเงินสด', shift.cash_sales],
      ['นำเงินเข้า', shift.cash_in],
      ['นำเงินออก', -shift.cash_out],
    ].map(([label, value]) =>
      `<div><span>${label}</span><strong>${money(value)}</strong></div>`).join('')
      + `<div><span>ขายรวมทุกช่องทาง</span><strong>${money(shift.takings)} · ${shift.bills} บิล</strong></div>`;
    at('shiftMoves').innerHTML = (shift.movements || []).slice().reverse().map(move =>
      `<li><span>${KIND_WORDS[move.kind] || move.kind}</span>
         <strong>${money(move.amount)}</strong>
         <em>${move.reason ? move.reason.replace(/[<>&]/g, '') : ''}</em></li>`).join('')
      || '<li class="shift-empty">ยังไม่มีเงินเข้าออกนอกจากการขาย</li>';
  };

  const load = async () => {
    try {
      shift = (await ask(`/api/shifts/current?branch_id=${branch()}`)).shift;
      draw();
      say('');
    } catch (error) { say(error.message, true); }
  };

  at('shiftOpenButton').addEventListener('click', async () => {
    try {
      shift = (await send('/api/shifts/open',
        {branch_id: branch(), opening: Number(at('shiftOpening').value) || 0})).shift;
      draw();
      say('เปิดกะแล้ว');
    } catch (error) { say(error.message, true); }
  });

  at('shiftMoveButton').addEventListener('click', async () => {
    const amount = Number(at('shiftMoveAmount').value);
    if (!amount) { say('ใส่จำนวนเงินก่อน', true); return; }
    try {
      shift = (await send('/api/shifts/cash', {branch_id: branch(), kind: at('shiftMoveKind').value,
        amount, reason: at('shiftMoveReason').value.trim()})).shift;
      at('shiftMoveAmount').value = '';
      at('shiftMoveReason').value = '';
      draw();
      say('บันทึกแล้ว');
    } catch (error) { say(error.message, true); }
  });

  at('shiftCloseButton').addEventListener('click', async () => {
    const counted = at('shiftCounted').value;
    if (counted === '') { say('นับเงินในลิ้นชักแล้วใส่ตัวเลขก่อนปิดกะ', true); return; }
    try {
      const closed = (await send('/api/shifts/close',
        {branch_id: branch(), counted: Number(counted)})).shift;
      shift = null;
      at('shiftCounted').value = '';
      draw();
      /* The difference is said plainly and left on screen. A drawer that is
         short is the one thing this whole screen exists to surface. */
      const gap = closed.difference;
      at('shiftDifference').textContent = gap === 0
        ? `ปิดกะแล้ว เงินตรงพอดี ${money(closed.counted)}`
        : gap > 0
          ? `ปิดกะแล้ว เงินเกิน ${money(gap)} (ควรมี ${money(closed.expected)} นับได้ ${money(closed.counted)})`
          : `ปิดกะแล้ว เงินขาด ${money(Math.abs(gap))} (ควรมี ${money(closed.expected)} นับได้ ${money(closed.counted)})`;
      at('shiftDifference').classList.toggle('bad', gap < 0);
      say('');
    } catch (error) { say(error.message, true); }
  });

  /* The drawer belongs to the till, so it sits on the cashier screen. Only
     the roles that may touch it ever see it. */
  const home = document.querySelector('#view-cashier');
  if (home) home.append(panel);

  const update = () => {
    const role = window.poswaiAuth?.current?.role;
    const allowed = ['owner', 'manager', 'cashier'].includes(role);
    panel.hidden = !allowed;
    if (allowed) load();
  };
  window.addEventListener('poswai:auth-changed', update);
  update();

  // The bill that was just closed is money in this drawer.
  window.addEventListener('poswai:bill-closed', load);
  window.poswaiShift = {reload: load};
})();
