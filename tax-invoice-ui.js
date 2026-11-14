/* ใบกำกับภาษีเต็มรูป — the real document, issued from the bill that was paid.

   The button used to print a sheet of text with the words on it. A customer
   who filed that sheet found out at the end of the year that it was worth
   nothing, by which time the sale was long past arguing about. Now the till
   asks the server for a numbered document and prints what came back. */
(() => {
  const money = (value) => `฿${Number(value || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const clean = (value) => String(value ?? '').replace(/[<>&]/g, '');

  const ask = async (path, options) => {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options});
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
      throw new Error(detail);
    }
    return response.json();
  };

  const modal = document.createElement('div');
  modal.className = 'modal-backdrop tax-modal';
  modal.innerHTML = `
    <div class="modal-card">
      <h3>📄 ออกใบกำกับภาษีเต็มรูป</h3>
      <p class="shift-hint">สรรพากรต้องการชื่อและที่อยู่ของผู้ซื้อ · ไม่มีเลขภาษีก็ออกได้ถ้าเป็นบุคคลธรรมดา</p>
      <label class="label" for="taxBillPick">บิลที่จะออกใบกำกับภาษี</label>
      <select id="taxBillPick" class="input"></select>
      <label class="label" for="taxBuyerName">ชื่อผู้ซื้อ *</label>
      <input id="taxBuyerName" class="input" maxlength="200" placeholder="บริษัท ... จำกัด หรือ ชื่อ-นามสกุล">
      <label class="label" for="taxBuyerId">เลขประจำตัวผู้เสียภาษี 13 หลัก</label>
      <input id="taxBuyerId" class="input" maxlength="20" inputmode="numeric" placeholder="เว้นว่างได้">
      <label class="label" for="taxBuyerAddress">ที่อยู่ผู้ซื้อ</label>
      <textarea id="taxBuyerAddress" class="input" rows="2" maxlength="300"></textarea>
      <label class="label" for="taxBuyerBranch">สาขาของผู้ซื้อ</label>
      <input id="taxBuyerBranch" class="input" maxlength="60" placeholder="สำนักงานใหญ่">
      <p id="taxInvoiceError" class="shift-status bad"></p>
      <div class="modal-actions">
        <button type="button" class="btn btn-line" id="taxInvoiceIssue">ออกใบกำกับภาษี</button>
        <button type="button" class="btn btn-outline" id="taxInvoiceCancelBtn">ปิด</button>
      </div>
    </div>`;
  document.body.append(modal);
  const at = (id) => modal.querySelector(`#${id}`);

  let pendingOrders = [];
  const picked = () => {
    const chosen = at('taxBillPick').value;
    return chosen ? [chosen] : pendingOrders;
  };
  const close = () => { modal.classList.remove('show'); modal.style.display = 'none'; };
  at('taxInvoiceCancelBtn').addEventListener('click', close);
  close();

  /* A table's bill can be several orders. The Revenue Department numbers one
     document per sale, so each order gets its own and they print together —
     inventing a combined one would mean a document with no bill behind it. */
  const printable = (invoice) => {
    const seller = invoice.seller || {};
    const line = '--------------------------------';
    return [
      '        ใบกำกับภาษี/ใบเสร็จรับเงิน',
      `   ${clean(seller.name)}`,
      ...String(seller.address || '').split(/\r?\n/).filter(Boolean).map(part => `   ${clean(part.trim())}`),
      ...(seller.phone ? [`   โทร. ${clean(seller.phone)}`] : []),
      `   เลขผู้เสียภาษี ${clean(seller.tax_id)}  (${clean(seller.branch)})`,
      line,
      `เลขที่ใบกำกับภาษี: ${clean(invoice.number)}`,
      `วันที่: ${new Date(invoice.issued_at.replace(' ', 'T') + 'Z').toLocaleString('th-TH')}`,
      `บิล: ${clean(invoice.order_no)}`,
      line,
      'ผู้ซื้อ',
      `  ${clean(invoice.buyer.name)}`,
      ...(invoice.buyer.tax_id ? [`  เลขผู้เสียภาษี ${clean(invoice.buyer.tax_id)}`] : []),
      ...String(invoice.buyer.address || '').split(/\r?\n/).filter(Boolean).map(part => `  ${clean(part.trim())}`),
      ...(invoice.buyer.branch ? [`  ${clean(invoice.buyer.branch)}`] : []),
      line,
      ...invoice.lines.map(item =>
        `${clean(item.name).slice(0, 18).padEnd(18, ' ')} x${item.qty}  ${money(item.amount)}`),
      line,
      `มูลค่าสินค้า/บริการ: ${money(invoice.subtotal)}`,
      ...(invoice.discount ? [`ส่วนลด: -${money(invoice.discount)}`] : []),
      ...(invoice.service_charge ? [`ค่าบริการ: ${money(invoice.service_charge)}`] : []),
      `ภาษีมูลค่าเพิ่ม ${(invoice.vat_rate_bp / 100).toFixed(invoice.vat_rate_bp % 100 ? 2 : 0)}%: ${money(invoice.vat)}`,
      `รวมทั้งสิ้น: ${money(invoice.total)}`,
      ...(invoice.cancelled_at ? [line, '*** ใบนี้ถูกยกเลิกแล้ว ***'] : []),
    ].join('\n');
  };

  at('taxInvoiceIssue').addEventListener('click', async () => {
    const name = at('taxBuyerName').value.trim();
    if (!name) { at('taxInvoiceError').textContent = 'ต้องใส่ชื่อผู้ซื้อ'; return; }
    at('taxInvoiceError').textContent = '';
    const issued = [];
    try {
      for (const orderNo of picked()) {
        issued.push(await ask('/api/tax-invoices', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({branch_id: window.poswaiAuth?.branchId || 1, order_no: orderNo,
            name, tax_id: at('taxBuyerId').value.trim(),
            address: at('taxBuyerAddress').value.trim(),
            branch: at('taxBuyerBranch').value.trim()})}));
      }
    } catch (error) {
      at('taxInvoiceError').textContent = error.message;
      return;
    }
    const preview = document.getElementById('thermalReceiptPreview');
    if (preview) preview.textContent = issued.map(printable).join('\n\n');
    close();
    window.showToast?.(`ออกใบกำกับภาษีแล้ว เลขที่ ${issued.map(i => i.number).join(', ')}`);
  });

  /* Replaces the old button, which printed a sheet that was not a document. */
  /* Recently closed bills, because a customer asks for the document after
     paying — often after the food is done and the bill has left the table
     screen. Making them find it any other way means they do not get one. */
  const fillRecent = async (preferred) => {
    const pick = at('taxBillPick');
    pick.innerHTML = '<option value="">กำลังโหลดบิล…</option>';
    try {
      const branch = window.poswaiAuth?.branchId || 1;
      const settled = await ask(`/api/orders/settled?branch_id=${branch}&limit=20`);
      const bills = (settled.orders || settled.settled || [])
        .filter(bill => bill.status === 'paid');
      pick.innerHTML = bills.map(bill =>
        `<option value="${clean(bill.order_no)}">โต๊ะ ${clean(bill.table_no)} · ${
          money(bill.net_amount)} · ${clean(String(bill.closed_at || '').slice(11, 16))} · ${
          clean(bill.order_no).slice(-6)}</option>`).join('')
        || '<option value="">ยังไม่มีบิลที่ชำระแล้ว</option>';
      const wanted = preferred?.find(no => bills.some(bill => bill.order_no === no));
      if (wanted) pick.value = wanted;
    } catch (error) {
      pick.innerHTML = `<option value="">โหลดรายการบิลไม่สำเร็จ</option>`;
      at('taxInvoiceError').textContent = error.message;
    }
  };

  window.openTaxInvoice = (orders) => {
    pendingOrders = (orders || []).filter(Boolean);
    at('taxInvoiceError').textContent = '';
    modal.style.display = 'flex';
    modal.classList.add('show');
    fillRecent(pendingOrders);
    at('taxBuyerName').focus();
  };
})();
