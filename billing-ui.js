/* The shop's own service fee: the notice in the app and paying it with a slip.
   The receiving account belongs to ZZAX Studio and comes from the server, never
   from the shop's own PromptPay setting. */
(() => {
  const STATE_CLASS = {due_soon: 'is-due', overdue: 'is-late'};
  let info = null;       // the last /api/billing body
  let notice = null;
  let dialog = null;

  const money = value => Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const signedIn = () => window.poswaiAuth?.current || null;
  const owner = () => ['owner', 'manager'].includes(signedIn()?.role);
  /* The fee is never taken inside the app from Google Play. Play's Payments
     policy counts a subscription to business software as a digital purchase
     that must go through Google Play's billing system, and it forbids leading
     the user to any other way to pay — a link to our own page included. So the
     app only says, in words, that the fee is due and where to renew; the web
     keeps the QR and the slip, and the shop pays there. */
  const inApp = () => document.documentElement.classList.contains('poswai-app');
  const mayPay = () => owner() && !inApp();

  const buildNotice = () => {
    if (notice) return notice;
    notice = document.createElement('div');
    notice.className = 'poswai-billing-notice';
    notice.hidden = true;
    notice.innerHTML = '<p class="pbn-text"></p><div class="pbn-actions">'
      + '<button type="button" class="pbn-pay">ชำระค่าบริการ</button>'
      + '<button type="button" class="pbn-close" aria-label="ซ่อนข้อความนี้">✕</button></div>';
    notice.querySelector('.pbn-pay').addEventListener('click', openDialog);
    notice.querySelector('.pbn-close').addEventListener('click', () => {
      notice.hidden = true;
      // An overdue shop sees it again on the next load; nothing is dismissed for good.
      sessionStorage.setItem('poswaiBillingHidden', info?.billing?.due_date || '1');
    });
    document.body.prepend(notice);
    return notice;
  };

  const renderNotice = () => {
    const state = info?.billing;
    const element = buildNotice();
    if (!state?.applicable || !signedIn() || !['due_soon', 'overdue'].includes(state.state)) {
      element.hidden = true;
      document.body.classList.remove('poswai-has-billing-notice');
      return;
    }
    element.classList.remove('is-due', 'is-late');
    element.classList.add(STATE_CLASS[state.state]);
    element.querySelector('.pbn-text').textContent = state.message
      + (!owner() ? ' · แจ้งเจ้าของร้านให้ชำระค่าบริการ'
        : inApp() ? ' · ต่ออายุได้ที่เว็บ poswai.zzaxstudio.com' : '');
    element.querySelector('.pbn-pay').hidden = !mayPay();
    const hidden = sessionStorage.getItem('poswaiBillingHidden') === state.due_date;
    element.hidden = hidden && state.state !== 'overdue';
    document.body.classList.toggle('poswai-has-billing-notice', !element.hidden);
  };

  const buildDialog = () => {
    if (dialog) return dialog;
    dialog = document.createElement('div');
    dialog.className = 'poswai-billing-overlay';
    dialog.hidden = true;
    dialog.innerHTML = `<section class="pbo-card" role="dialog" aria-modal="true" aria-labelledby="pboTitle">
      <h2 id="pboTitle">ชำระค่าบริการ POS WAI</h2>
      <p class="pbo-state"></p>
      <label for="pboMonths">ชำระล่วงหน้า</label>
      <select id="pboMonths"></select>
      <p class="pbo-total"></p>
      <div class="pbo-qr"><canvas id="pboQrCanvas" width="220" height="220"></canvas>
        <p class="pbo-account"></p></div>
      <label for="pboSlip">แนบรูปสลิปที่โอนแล้ว</label>
      <input id="pboSlip" type="file" accept="image/jpeg,image/png,image/gif,image/webp">
      <p class="pbo-message"></p>
      <div class="pbo-buttons">
        <button type="button" class="pbo-send">ส่งสลิปและต่ออายุ</button>
        <button type="button" class="pbo-cancel">ปิด</button>
      </div>
      <p class="pbo-history"></p>
    </section>`;
    document.body.append(dialog);
    dialog.querySelector('.pbo-cancel').addEventListener('click', () => { dialog.hidden = true; });
    dialog.querySelector('#pboMonths').addEventListener('change', drawQr);
    dialog.querySelector('.pbo-send').addEventListener('click', submitSlip);
    return dialog;
  };

  const monthsValue = () => Number(dialog?.querySelector('#pboMonths')?.value || 1);

  function drawQr() {
    const total = Number((info.price * monthsValue()).toFixed(2));
    dialog.querySelector('.pbo-total').textContent = `ยอดที่ต้องโอน ${money(total)} บาท (${monthsValue()} เดือน)`;
    const account = info.service_promptpay_id;
    const accountLine = dialog.querySelector('.pbo-account');
    const canvas = dialog.querySelector('#pboQrCanvas');
    if (!account) {
      canvas.hidden = true;
      accountLine.textContent = 'ยังไม่ได้ตั้งค่าบัญชีรับเงินของผู้ให้บริการ กรุณาติดต่อ ZZAX Studio';
      return;
    }
    try {
      drawQrCodeOnCanvas('pboQrCanvas', generatePromptPayPayload(account, total));
      canvas.hidden = false;
      accountLine.textContent = `พร้อมเพย์ ZZAX Studio · ${account}`;
    } catch (error) {
      canvas.hidden = true;
      accountLine.textContent = `สร้าง QR ไม่สำเร็จ: ${error.message} · โอนเข้าพร้อมเพย์ ${account}`;
    }
  }

  function openDialog() {
    if (!info?.billing?.applicable || !mayPay()) return;
    const element = buildDialog();
    const select = element.querySelector('#pboMonths');
    if (!select.options.length) {
      for (let month = 1; month <= 12; month++) {
        const option = document.createElement('option');
        option.value = String(month);
        option.textContent = `${month} เดือน`;
        select.append(option);
      }
    }
    element.querySelector('.pbo-state').textContent = info.billing.message;
    element.querySelector('.pbo-message').textContent = info.slip_check_ready ? ''
      : 'ระบบตรวจสลิปของผู้ให้บริการยังไม่เปิด กรุณาส่งสลิปให้ทีมงาน ZZAX Studio ยืนยันให้';
    element.querySelector('.pbo-send').disabled = !info.slip_check_ready || !info.service_promptpay_id;
    const last = (info.payments || [])[0];
    element.querySelector('.pbo-history').textContent = last
      ? `ชำระครั้งล่าสุด ${money(last.amount)} บาท วันที่ ${String(last.created_at).slice(0, 10)} ใช้ได้ถึง ${last.period_end}`
      : 'ยังไม่มีประวัติการชำระค่าบริการ';
    drawQr();
    element.hidden = false;
  }

  async function submitSlip(event) {
    const button = event.currentTarget;
    const message = dialog.querySelector('.pbo-message');
    const file = dialog.querySelector('#pboSlip').files[0];
    if (!file) { message.textContent = 'เลือกรูปสลิปก่อน'; return; }
    if (file.size > 4 * 1024 * 1024) { message.textContent = 'รูปสลิปต้องมีขนาดไม่เกิน 4 MB'; return; }
    const months = monthsValue();
    const total = Number((info.price * months).toFixed(2));
    // One event ID per attempt keeps a retry after a timeout from buying two months.
    const retryKey = `poswai-service-fee:${info.billing.due_date}:${months}`;
    let eventId = sessionStorage.getItem(retryKey);
    if (!eventId) { eventId = 'fee-' + crypto.randomUUID(); sessionStorage.setItem(retryKey, eventId); }
    button.disabled = true;
    message.textContent = 'กำลังตรวจสลิป...';
    try {
      const image = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error('อ่านรูปสลิปไม่สำเร็จ'));
        reader.readAsDataURL(file);
      });
      const response = await fetch('/api/billing/pay', {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({event_id: eventId, amount: total, months, slip_image: image})
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
      sessionStorage.removeItem(retryKey);
      sessionStorage.removeItem('poswaiBillingHidden');
      message.textContent = `ชำระเรียบร้อย ใช้งานได้ถึง ${body.paid_until}`;
      dialog.querySelector('#pboSlip').value = '';
      await refresh();
      window.showToast?.(`ต่ออายุ POS WAI ถึง ${body.paid_until}`);
    } catch (error) {
      message.textContent = `ชำระไม่สำเร็จ: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  }

  async function refresh() {
    if (!signedIn()) { info = null; renderNotice(); return; }
    try {
      const response = await fetch('/api/billing', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      info = await response.json();
    } catch (_) { return; /* Offline: the shell keeps working without the notice. */ }
    renderNotice();
    if (dialog && !dialog.hidden) openDialog();
  }

  window.poswaiBilling = {refresh, open: openDialog, get info() { return info; }};
  window.addEventListener('poswai:auth-changed', refresh);
  if (signedIn()) refresh();
})();
