/* Cashier-only bank slip verification. QR bills never close from a visual check alone. */
(() => {
  const qrBox = document.getElementById('cashierQrBox');
  if (!qrBox) return;
  fetch('/api/config', {cache:'no-store'}).then(response => response.json()).then(config => {
    if (config.preview_only) return;
    const disable = (selector, reason) => document.querySelectorAll(selector).forEach(element => {
      element.disabled = true; element.title = reason;
    });
    disable('button[onclick*="toggleReserveTable"],button[onclick*="addNewTableDynamic"],button[onclick*="removeLastTableDynamic"],button[onclick*="scanBarcodeItem"],button[onclick*="cashierAddQuickItem"]', 'ยังไม่บันทึกบนเซิร์ฟเวอร์');
    disable('#enableVatCheckbox,#enableScCheckbox,#splitBillCount', 'ยังไม่รองรับการคิดภาษี ค่าบริการ หรือแยกบิลบนเซิร์ฟเวอร์');
    for (const id of ['enableVatCheckbox','enableScCheckbox']) {
      const checkbox = document.getElementById(id);
      if (checkbox) checkbox.checked = false;
    }
    document.getElementById('shiftSummaryText')?.closest('.card')?.setAttribute('hidden', 'hidden');
    document.getElementById('cashierQuickMenuSelect')?.closest('.card')?.setAttribute('hidden', 'hidden');
    document.querySelectorAll('button[onclick^="simulateCustomerSendSlip"]').forEach(button => {
      button.disabled = true;
      button.textContent = 'กรุณาส่งรูปสลิปให้แคชเชียร์ตรวจผ่านระบบ';
    });
    document.querySelectorAll('button[onclick*="confirmPaymentAndPrint"]').forEach(button => {
      const action = button.getAttribute('onclick') || '';
      if (!action.includes('เงินสด (Cash)')) {
        button.disabled = true;
        button.title = 'ช่องทางนี้ยังไม่ได้เชื่อมผู้ให้บริการรับชำระ';
      }
    });
    const fakeSlip = document.getElementById('slipVerifyBox');
    if (fakeSlip) fakeSlip.hidden = true;
    const oldButton = qrBox.querySelector('button[onclick*="confirmPaymentAndPrint"]');
    if (oldButton) oldButton.remove();
    const panel = document.createElement('div');
    panel.className = 'verified-slip-panel';
    panel.innerHTML = '<label for="verifiedSlipInput">แนบรูปสลิปจากลูกค้า</label><input id="verifiedSlipInput" type="file" accept="image/jpeg,image/png,image/gif,image/webp"><button type="button" id="verifySlipButton" class="btn btn-line btn-block">ตรวจ EasySlip และปิดบิล</button><small>ระบบจะตรวจบัญชีผู้รับ ยอดโอน และสลิปซ้ำก่อนปิดบิล</small>';
    qrBox.querySelector('.promptpay-body')?.append(panel);
    document.getElementById('verifySlipButton').addEventListener('click', async event => {
      const button = event.currentTarget;
      const file = document.getElementById('verifiedSlipInput').files[0];
      if (!file) { showToast('กรุณาเลือกรูปสลิปก่อน'); return; }
      if (file.size > 4 * 1024 * 1024) { showToast('รูปสลิปต้องมีขนาดไม่เกิน 4 MB'); return; }
      const table = state.selectedCashierTable;
      const orders = getTableOrders(table);
      const calc = getTableGrandTotalWithTax(table);
      if (!orders.length || calc.grand <= 0) { showToast('โต๊ะนี้ไม่มียอดค้างชำระ'); return; }
      if (calc.sc > 0 || calc.vat > 0) { showToast('ยังไม่รองรับการตรวจสลิปบิลที่บวก VAT หรือค่าบริการ'); return; }
      const orderNos = orders.map(order => order.orderId);
      const retryKey = `poswai-slip-event:${orderNos.slice().sort().join(',')}`;
      let eventId = sessionStorage.getItem(retryKey);
      if (!eventId) { eventId = crypto.randomUUID(); sessionStorage.setItem(retryKey, eventId); }
      button.disabled = true;
      button.textContent = 'กำลังตรวจสลิป...';
      try {
        const image = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(new Error('อ่านรูปสลิปไม่สำเร็จ'));
          reader.readAsDataURL(file);
        });
        const response = await fetch('/api/payments/close-table', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({event_id:eventId, branch_id:window.poswaiAuth?.branchId || 1,
            table_no:table, order_nos:orderNos, amount:Number(calc.grand.toFixed(2)), slip_image:image})
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
        sessionStorage.removeItem(retryKey);
        printReceiptForTable(table, 'ใบเสร็จรับเงิน QR PromptPay (EasySlip ตรวจสอบแล้ว)', false);
        state.shift.totalSalesToday += calc.grand;
        state.orders = state.orders.filter(order => order.table !== table);
        delete state.slips[table];
        qrBox.style.display = 'none';
        document.getElementById('verifiedSlipInput').value = '';
        renderAll();
        if (window.poswaiLiveData) await window.poswaiLiveData.refresh().catch(() => {});
        showToast(`ตรวจสลิปและปิดบิลโต๊ะ ${table} สำเร็จ · ${result.slip_reference || ''}`);
      } catch (error) {
        showToast(`ปิดบิล QR ไม่สำเร็จ: ${error.message}`);
      } finally {
        button.disabled = false;
        button.textContent = 'ตรวจ EasySlip และปิดบิล';
      }
    });
  }).catch(() => {});
})();
