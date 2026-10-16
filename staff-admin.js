/* Manager controls for real staff pay inputs, shifts, and LINE notification retries. */
(() => {
  const view = document.getElementById('view-staff');
  if (!view) return;
  const card = document.createElement('section');
  card.className = 'card staff-admin';
  card.innerHTML = `<div class="card-header"><div class="card-title">ตั้งค่าทีมและ LINE</div></div>
    <p class="staff-admin-note">ตั้งค่าอัตราค่าจ้างและกะก่อนใช้รายงานเงินเดือน ตัวเลขเป็นประมาณการก่อนหักรายการต่าง ๆ</p>
    <div class="staff-admin-grid">
      <form id="staffRateForm"><strong>ค่าจ้างรายชั่วโมง</strong><label>พนักงาน<select name="staff_id" required></select></label><label>บาทต่อชั่วโมง<input name="hourly_rate" type="number" min="0" max="100000" step="0.01" required></label><button type="submit">บันทึกค่าแรง</button></form>
      <form id="staffTemplateForm"><strong>สร้างกะ</strong><label>ชื่อกะ<input name="name" maxlength="80" required placeholder="กะเช้า"></label><label>เวลาเริ่ม<input name="start_time" type="time" required></label><label>เวลาสิ้นสุด<input name="end_time" type="time" required></label><button type="submit">บันทึกกะ</button></form>
      <form id="staffAssignForm"><strong>จัดกะพนักงาน</strong><label>พนักงาน<select name="staff_id" required></select></label><label>วันที่<input name="work_date" type="date" required></label><label>กะ<select name="shift_template_id" required></select></label><button type="submit">จัดกะ</button></form>
    </div><div class="staff-admin-line"><span>กะงานและการแจ้งเตือน</span><div class="staff-admin-actions"><button type="button" id="staffCheckAbsence">ตรวจคนขาดงาน</button><button type="button" id="staffRetryLine">ส่ง LINE ที่ค้าง</button></div></div><p id="staffAdminStatus" role="status"></p>`;
  const firstPanel = view.querySelector('.people-panel');
  if (firstPanel) firstPanel.append(card);
  else view.append(card);
  const $ = s => card.querySelector(s);
  const status = message => { $('#staffAdminStatus').textContent = message; };
  const auth = () => window.poswaiAuth?.current;
  const api = async (path, method='GET', body) => {
    const response = await fetch(path, {method, credentials:'same-origin', cache:'no-store',
      headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };
  const populate = (select, items, label) => {
    const old = select.value;
    select.replaceChildren(...items.map(item => new Option(label(item), item.id)));
    if (items.some(item => String(item.id) === old)) select.value = old;
  };
  async function refresh() {
    const user = auth();
    card.hidden = !user || !['manager','owner'].includes(user.role);
    if (card.hidden) return;
    try {
      const [overview, templates] = await Promise.all([
        api(`/api/staff/overview?branch_id=${user.branch_id}`),
        api(`/api/staff/shift-templates?branch_id=${user.branch_id}`)
      ]);
      for (const select of card.querySelectorAll('[name="staff_id"]'))
        populate(select, overview.staff, item => item.name);
      populate($('#staffAssignForm [name="shift_template_id"]'), templates.items,
        item => `${item.name} · ${item.start_time}–${item.end_time}`);
      $('#staffAssignForm [name="work_date"]').value ||= new Date().toLocaleDateString('en-CA');
      status('พร้อมจัดการพนักงาน');
    } catch (error) { status(error.message); }
  }
  const submit = (selector, path, method, makeBody) => {
    $(selector).addEventListener('submit', async event => {
      event.preventDefault();
      const user = auth(); if (!user) return;
      const form = new FormData(event.currentTarget);
      try {
        await api(path(form, user), method, makeBody(form, user));
        status('บันทึกเรียบร้อย');
        window.dispatchEvent(new Event('poswai:staff-refresh'));
        await refresh();
      } catch (error) { status(error.message); }
    });
  };
  submit('#staffRateForm', form => `/api/staff/${Number(form.get('staff_id'))}/pay-rate`, 'PATCH',
    form => ({hourly_rate:Number(form.get('hourly_rate'))}));
  submit('#staffTemplateForm', () => '/api/staff/shift-templates', 'POST',
    (form,user) => ({branch_id:user.branch_id,name:form.get('name'),start_time:form.get('start_time'),end_time:form.get('end_time')}));
  submit('#staffAssignForm', () => '/api/staff/shifts', 'POST',
    (form,user) => ({branch_id:user.branch_id,staff_id:Number(form.get('staff_id')),
      work_date:form.get('work_date'),shift_template_id:Number(form.get('shift_template_id'))}));
  $('#staffRetryLine').addEventListener('click', async () => {
    const user=auth(); if(!user) return;
    try { const result=await api(`/api/line/notifications/retry?branch_id=${user.branch_id}`,'POST');
      status(result.status==='not_configured'?'ยังไม่ได้ตั้งค่าช่อง LINE OA':`ส่งสำเร็จ ${result.sent} · รอลองใหม่ ${result.failed}`);
    } catch (error) { status(error.message); }
  });
  $('#staffCheckAbsence').addEventListener('click', async () => {
    const user=auth(); if(!user) return;
    try { const result=await api(`/api/staff/absence-check?branch_id=${user.branch_id}`,'POST');
      status(result.absent_staff_ids.length ? `ตรวจพบพนักงานขาดงาน ${result.absent_staff_ids.length} คน และระงับสิทธิ์ POS แล้ว` : 'ไม่พบพนักงานขาดงานใหม่');
      window.dispatchEvent(new Event('poswai:staff-refresh'));
    } catch (error) { status(error.message); }
  });
  window.addEventListener('poswai:auth-changed', refresh);
  refresh();
})();
