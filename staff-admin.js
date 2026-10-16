/* Manager controls for real staff pay inputs, shifts, and LINE notification retries. */
(() => {
  const view = document.getElementById('view-staff');
  if (!view) return;
  const directoryCard = document.createElement('section');
  directoryCard.className = 'card staff-admin staff-directory';
  directoryCard.innerHTML = `<div class="card-header"><div class="card-title">จัดการพนักงานรายคน</div></div>
    <p class="staff-admin-note">เลือกชื่อเพื่อดูรหัสพนักงาน แก้ข้อมูล กำหนดสิทธิ์ หรือระงับบัญชี</p>
    <details class="staff-role-policy"><summary>สิทธิ์แต่ละตำแหน่ง</summary><ul>
      <li><strong>เจ้าของร้าน</strong> ทุกส่วน รวมถึงแต่งตั้งผู้จัดการ</li>
      <li><strong>ผู้จัดการ</strong> การขาย ทีมงาน สต็อก สมาชิก และรายงาน; จัดการพนักงานระดับปฏิบัติงาน</li>
      <li><strong>แคชเชียร์</strong> สั่งอาหาร แคชเชียร์ จอครัว และเวลางานของตน</li>
      <li><strong>ครัว</strong> จอครัว ดูสต็อก บันทึกของเสีย และเวลางานของตน</li>
      <li><strong>บริการ</strong> สั่งอาหาร จอครัว และเวลางานของตน</li>
      <li><strong>พนักงานทั่วไป</strong> สั่งอาหารและเวลางานของตน</li>
    </ul></details>
    <div class="staff-directory-layout"><div id="staffDirectoryList" class="staff-directory-list"></div>
      <div id="staffDirectoryDetail" class="staff-directory-detail" hidden>
        <form id="staffProfileForm"><strong id="staffDetailTitle"></strong>
          <label>ชื่อพนักงาน<input name="name" maxlength="100" required></label>
          <label>ตำแหน่ง<select name="role" required><option value="staff">พนักงานทั่วไป</option><option value="service">บริการ</option><option value="cashier">แคชเชียร์</option><option value="kitchen">ครัว</option><option value="manager">ผู้จัดการ</option><option value="owner" disabled>เจ้าของร้าน</option></select></label>
          <button type="submit" id="staffSaveProfile">บันทึกข้อมูล</button>
        </form>
        <div class="staff-directory-actions"><button type="button" id="staffToggleActive"></button></div>
        <details id="staffPinDetails"><summary>ตั้ง PIN ใหม่ให้พนักงาน</summary>
          <form id="staffResetPinForm"><label>PIN ใหม่อย่างน้อย 8 ตัวอักษร<input name="pin" type="password" minlength="8" autocomplete="new-password" required></label><button type="submit">บันทึก PIN ใหม่</button></form>
        </details>
      </div></div><p id="staffDirectoryStatus" role="status"></p>`;
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
  if (firstPanel) { firstPanel.prepend(directoryCard); firstPanel.append(card); }
  else view.append(directoryCard,card);
  const $ = s => card.querySelector(s);
  const $$ = s => directoryCard.querySelector(s);
  const status = message => { $('#staffAdminStatus').textContent = message; };
  const directoryStatus = message => { $$('#staffDirectoryStatus').textContent = message; };
  const auth = () => window.poswaiAuth?.current;
  let directory = [];
  let selectedStaffId = null;
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
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function renderDirectory() {
    const user = auth();
    if (!user) return;
    $$('#staffDirectoryList').innerHTML = directory.map(person =>
      `<button type="button" data-staff-id="${person.id}" class="${person.id===selectedStaffId?'selected':''}">
        <strong>${escape(person.name)}</strong><small>รหัส ${person.id} · ${escape(person.role)} · ${person.is_active?'ใช้งาน':'ปิดใช้งาน'}</small></button>`).join('');
    const person = directory.find(item => item.id === selectedStaffId);
    const detail = $$('#staffDirectoryDetail');
    detail.hidden = !person;
    if (!person) return;
    const canEdit = user.role === 'owner' || !['manager','owner'].includes(person.role);
    const own = person.id === user.staff_id;
    $$('#staffDetailTitle').textContent = `${person.name} · รหัส ${person.id}`;
    const form = $$('#staffProfileForm');
    form.elements.namedItem('name').value = person.name;
    form.elements.namedItem('role').value = person.role;
    form.elements.namedItem('name').disabled = !canEdit;
    form.elements.namedItem('role').disabled = !canEdit || person.role === 'owner' || own;
    form.elements.namedItem('role').querySelector('[value="manager"]').hidden = user.role !== 'owner' && person.role !== 'manager';
    $$('#staffSaveProfile').hidden = !canEdit;
    const toggle = $$('#staffToggleActive');
    toggle.hidden = !canEdit || own || person.role === 'owner';
    toggle.textContent = person.is_active ? 'ปิดใช้งานบัญชีนี้' : 'เปิดใช้งานบัญชีนี้';
    $$('#staffPinDetails').hidden = !canEdit || person.role === 'owner';
  }
  async function refresh() {
    const user = auth();
    card.hidden = !user || !['manager','owner'].includes(user.role);
    directoryCard.hidden = card.hidden;
    if (card.hidden) return;
    try {
      const [overview, templates, staffDirectory] = await Promise.all([
        api(`/api/staff/overview?branch_id=${user.branch_id}`),
        api(`/api/staff/shift-templates?branch_id=${user.branch_id}`),
        api(`/api/staff/directory?branch_id=${user.branch_id}`)
      ]);
      directory = staffDirectory.items;
      if (!directory.some(item => item.id === selectedStaffId)) selectedStaffId = directory.find(item => item.is_active)?.id || directory[0]?.id || null;
      renderDirectory();
      for (const select of card.querySelectorAll('[name="staff_id"]'))
        populate(select, overview.staff, item => item.name);
      populate($('#staffAssignForm [name="shift_template_id"]'), templates.items,
        item => `${item.name} · ${item.start_time}–${item.end_time}`);
      $('#staffAssignForm [name="work_date"]').value ||= new Date().toLocaleDateString('en-CA');
      status('พร้อมจัดการพนักงาน');
    } catch (error) { status(error.message); directoryStatus(error.message); }
  }
  $$('#staffDirectoryList').addEventListener('click', event => {
    const button = event.target.closest('[data-staff-id]');
    if (!button) return;
    selectedStaffId = Number(button.dataset.staffId);
    directoryStatus('');
    renderDirectory();
  });
  $$('#staffProfileForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedStaffId) return;
    const form = event.currentTarget;
    try {
      const person = directory.find(item => item.id === selectedStaffId);
      const profile = {name:form.elements.namedItem('name').value};
      if (person && person.id !== auth()?.staff_id && person.role !== 'owner') profile.role = form.elements.namedItem('role').value;
      await api(`/api/staff/${selectedStaffId}/profile`, 'PATCH', profile);
      directoryStatus('บันทึกข้อมูลพนักงานแล้ว');
      await refresh();
      window.dispatchEvent(new Event('poswai:staff-refresh'));
    } catch (error) { directoryStatus(error.message); }
  });
  $$('#staffToggleActive').addEventListener('click', async () => {
    const person = directory.find(item => item.id === selectedStaffId);
    if (!person) return;
    if (person.is_active && !confirm(`ปิดใช้งานบัญชี ${person.name} รหัส ${person.id}?`)) return;
    try {
      await api(`/api/staff/${person.id}/profile`, 'PATCH', {is_active:!person.is_active});
      directoryStatus(person.is_active?'ปิดใช้งานบัญชีแล้ว':'เปิดใช้งานบัญชีแล้ว');
      await refresh();
      window.dispatchEvent(new Event('poswai:staff-refresh'));
    } catch (error) { directoryStatus(error.message); }
  });
  $$('#staffResetPinForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedStaffId) return;
    const form = event.currentTarget;
    try {
      await api(`/api/staff/${selectedStaffId}/pin`, 'PUT', {pin:form.elements.namedItem('pin').value});
      form.reset();
      $$('#staffPinDetails').open = false;
      directoryStatus('ตั้ง PIN ใหม่แล้ว พนักงานต้องเข้าสู่ระบบอีกครั้ง');
    } catch (error) { directoryStatus(error.message); }
  });
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
