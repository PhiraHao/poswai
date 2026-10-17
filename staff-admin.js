/* Manager controls for staff accounts, pay, leave allowance, shifts and LINE retries.
   One dialog covers a person's whole setup; the API re-checks every role. */
(() => {
  const view = document.getElementById('view-staff');
  if (!view) return;
  const ROLE_LABELS = {owner:'เจ้าของร้าน', manager:'ผู้จัดการ', cashier:'แคชเชียร์',
    kitchen:'ครัว / บาร์', service:'พนักงานเสิร์ฟ', staff:'พนักงานทั่วไป'};
  const roleOptions = roles => roles.map(role => `<option value="${role}">${ROLE_LABELS[role]}</option>`).join('');
  const quotaFields = `<div class="staff-quota-row">
      <label>ลาป่วย (วัน/ปี)<input name="sick" type="number" min="0" max="365" step="1"></label>
      <label>ลากิจ (วัน/ปี)<input name="personal" type="number" min="0" max="365" step="1"></label>
      <label>พักร้อน (วัน/ปี)<input name="vacation" type="number" min="0" max="365" step="1"></label>
    </div>`;

  const directoryCard = document.createElement('section');
  directoryCard.className = 'card staff-admin staff-directory';
  directoryCard.innerHTML = `<div class="card-header staff-directory-header">
      <div><div class="card-title">จัดการพนักงาน</div>
        <p class="staff-admin-note">ตั้งชื่อ ตำแหน่ง รหัส PIN ค่าจ้าง และโควตาวันลา ได้ในที่เดียว</p></div>
      <button type="button" id="staffAddButton" class="staff-roster-action">+ เพิ่มพนักงาน</button>
    </div>
    <details class="staff-role-policy"><summary>ตรวจสิทธิ์การใช้งานตามตำแหน่ง</summary>
      <div id="staffPermissionMatrix" class="staff-permission-matrix"></div></details>
    <form id="staffCreateForm" class="staff-create-form" hidden>
      <strong>เพิ่มพนักงานใหม่</strong>
      <label>ชื่อพนักงาน<input name="name" maxlength="100" required></label>
      <label>ตำแหน่ง<select name="role" required>${roleOptions(['staff','service','cashier','kitchen','manager'])}</select></label>
      <label>รหัส PIN อย่างน้อย 8 ตัว<input name="pin" type="password" minlength="8" autocomplete="new-password" required placeholder="ห้ามใช้ PIN ของผู้จัดการ"></label>
      <label>ค่าจ้างต่อชั่วโมง (บาท)<input name="hourly_rate" type="number" min="0" max="100000" step="0.01" placeholder="50"></label>
      <span class="staff-quota-label">โควตาวันลาต่อปี</span>${quotaFields}
      <div class="staff-admin-actions"><button type="submit">สร้างบัญชี</button>
        <button type="button" id="staffCancelCreate" class="staff-secondary">ยกเลิก</button></div>
    </form>
    <div class="staff-create-success" id="staffCreateSuccess" hidden role="status">
      <strong>สร้างบัญชีแล้ว</strong><p id="staffCreatedLine"></p>
      <p class="staff-admin-note">แจ้งรหัสพนักงานและ PIN ให้เจ้าตัวเป็นการส่วนตัว</p></div>
    <div class="staff-directory-layout"><div id="staffDirectoryList" class="staff-directory-list"></div>
      <div id="staffDirectoryDetail" class="staff-directory-detail" hidden>
        <form id="staffProfileForm"><strong id="staffDetailTitle"></strong>
          <label>ชื่อพนักงาน<input name="name" maxlength="100" required></label>
          <label>ตำแหน่ง<select name="role" required>${roleOptions(['staff','service','cashier','kitchen','manager'])}<option value="owner" disabled>เจ้าของร้าน</option></select></label>
          <label>ค่าจ้างต่อชั่วโมง (บาท)<input name="hourly_rate" type="number" min="0" max="100000" step="0.01"></label>
          <span class="staff-quota-label">โควตาวันลาต่อปี <small id="staffQuotaUsed"></small></span>${quotaFields}
          <button type="submit" id="staffSaveProfile">บันทึกข้อมูล</button>
        </form>
        <div class="staff-directory-actions"><button type="button" id="staffToggleActive"></button></div>
        <details id="staffPinDetails"><summary>ตั้ง PIN ใหม่ให้พนักงาน</summary>
          <form id="staffResetPinForm"><label>PIN ใหม่อย่างน้อย 8 ตัวอักษร<input name="pin" type="password" minlength="8" autocomplete="new-password" required></label><button type="submit">บันทึก PIN ใหม่</button></form>
        </details>
      </div></div><p id="staffDirectoryStatus" role="status"></p>`;

  const card = document.createElement('section');
  card.className = 'card staff-admin';
  card.innerHTML = `<div class="card-header"><div class="card-title">กะงานและการแจ้งเตือน LINE</div></div>
    <p class="staff-admin-note">สร้างกะไว้ก่อน แล้วเลือกกะให้แต่ละคนได้จากตารางกะด้านบน</p>
    <div class="staff-admin-grid staff-shift-grid">
      <form id="staffTemplateForm"><strong>สร้างกะ</strong><label>ชื่อกะ<input name="name" maxlength="80" required placeholder="กะเช้า"></label><label>เวลาเริ่ม<input name="start_time" type="time" required></label><label>เวลาสิ้นสุด<input name="end_time" type="time" required></label><button type="submit">บันทึกกะ</button></form>
      <div class="staff-template-list"><strong>กะที่ใช้อยู่</strong><ul id="staffTemplateList"></ul>
        <button type="button" id="staffSeedTemplates" class="staff-secondary">สร้างกะมาตรฐาน (เช้า 08:00–17:00 · บ่าย 14:00–23:00)</button></div>
    </div>
    <div class="staff-admin-line"><span>เครื่องมือประจำวัน</span><div class="staff-admin-actions"><button type="button" id="staffCheckAbsence">ตรวจคนขาดงาน</button><button type="button" id="staffRetryLine">ส่ง LINE ที่ค้าง</button></div></div><p id="staffAdminStatus" role="status"></p>`;

  const firstPanel = view.querySelector('.people-panel');
  if (firstPanel) { firstPanel.prepend(directoryCard); firstPanel.append(card); }
  else view.append(directoryCard, card);

  const $ = s => card.querySelector(s);
  const $$ = s => directoryCard.querySelector(s);
  const status = message => { $('#staffAdminStatus').textContent = message; };
  const directoryStatus = message => { $$('#staffDirectoryStatus').textContent = message; };
  const auth = () => window.poswaiAuth?.current;
  let directory = [];
  let defaultQuota = {sick: 30, personal: 3, vacation: 6};
  let selectedStaffId = null;

  const api = async (path, method='GET', body) => {
    const response = await fetch(path, {method, credentials:'same-origin', cache:'no-store',
      headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const quotaValues = form => {
    const quota = {};
    for (const field of ['sick','personal','vacation']) {
      const raw = form.elements.namedItem(field).value;
      if (raw !== '') quota[field] = Number(raw);
    }
    return quota;
  };

  function renderPermissionMatrix() {
    const matrix = window.poswaiAuth?.permissions;
    const host = $$('#staffPermissionMatrix');
    if (!matrix?.roles) { host.textContent = 'กำลังโหลดตารางสิทธิ์…'; return; }
    const rows = Object.entries(matrix.roles).filter(([role]) => role !== 'guest').map(([role, entry]) => {
      const tabs = (entry.tabs || []).map(tab => matrix.tab_labels?.[tab] || tab).join(' · ');
      const list = items => (items || []).map(item => `<li>${escape(item)}</li>`).join('') || '<li>—</li>';
      return `<tr><th scope="row">${escape(entry.label || ROLE_LABELS[role] || role)}</th>
        <td>${escape(tabs)}</td><td><ul>${list(entry.allowed)}</ul></td>
        <td class="staff-permission-locked"><ul>${list(entry.restricted)}</ul></td></tr>`;
    }).join('');
    host.innerHTML = `<table class="staff-permission-table"><thead><tr><th>ตำแหน่ง</th><th>เมนูที่เห็น</th>
      <th>ทำอะไรได้</th><th>สิ่งที่ล็อกไว้</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="staff-admin-note">ระบบตรวจสิทธิ์ซ้ำที่เซิร์ฟเวอร์ทุกครั้ง การซ่อนเมนูเป็นเพียงการจัดหน้าจอ</p>`;
  }

  function fillQuota(form, quota) {
    for (const field of ['sick','personal','vacation'])
      form.elements.namedItem(field).value = quota?.[field]?.total ?? quota?.[field] ?? '';
  }

  function renderDirectory() {
    const user = auth();
    if (!user) return;
    $$('#staffDirectoryList').innerHTML = directory.map(person =>
      `<button type="button" data-staff-id="${person.id}" class="${person.id===selectedStaffId?'selected':''}">
        <strong>${escape(person.name)}</strong><small>รหัส ${(window.staffCode || String)(person.id)} · ${escape(ROLE_LABELS[person.role] || person.role)} · ${person.is_active?'ใช้งาน':'ปิดใช้งาน'}</small></button>`).join('');
    const person = directory.find(item => item.id === selectedStaffId);
    const detail = $$('#staffDirectoryDetail');
    detail.hidden = !person;
    if (!person) return;
    const canEdit = user.role === 'owner' || !['manager','owner'].includes(person.role);
    const own = person.id === user.staff_id;
    $$('#staffDetailTitle').textContent = `${person.name} · รหัส ${(window.staffCode || String)(person.id)}`;
    const form = $$('#staffProfileForm');
    form.elements.namedItem('name').value = person.name;
    form.elements.namedItem('role').value = person.role;
    form.elements.namedItem('hourly_rate').value = person.hourly_rate ?? '';
    fillQuota(form, person.leave_quota || defaultQuota);
    $$('#staffQuotaUsed').textContent = person.leave_quota
      ? `ใช้ไปแล้วปีนี้ ป่วย ${person.leave_quota.sick.used} · กิจ ${person.leave_quota.personal.used} · พักร้อน ${person.leave_quota.vacation.used} วัน`
      : 'ยังไม่เคยกำหนด จะใช้ค่าเริ่มต้นเมื่อกดบันทึก';
    for (const field of ['name','role','hourly_rate','sick','personal','vacation'])
      form.elements.namedItem(field).disabled = !canEdit;
    form.elements.namedItem('role').disabled = !canEdit || person.role === 'owner' || own;
    form.elements.namedItem('role').querySelector('[value="manager"]').hidden = user.role !== 'owner' && person.role !== 'manager';
    $$('#staffSaveProfile').hidden = !canEdit;
    const toggle = $$('#staffToggleActive');
    toggle.hidden = !canEdit || own || person.role === 'owner';
    toggle.textContent = person.is_active ? 'ปิดใช้งานบัญชีนี้' : 'เปิดใช้งานบัญชีนี้';
    $$('#staffPinDetails').hidden = !canEdit || person.role === 'owner';
  }

  function renderTemplates(items) {
    $('#staffTemplateList').innerHTML = items.length
      ? items.map(item => `<li>${escape(item.name)} · ${escape(item.start_time)}–${escape(item.end_time)}</li>`).join('')
      : '<li class="staff-template-empty">ยังไม่มีกะ สร้างกะแรกเพื่อเริ่มจัดตาราง</li>';
    $('#staffSeedTemplates').hidden = items.length > 0;
  }

  async function refresh() {
    const user = auth();
    card.hidden = !user || !['manager','owner'].includes(user.role);
    directoryCard.hidden = card.hidden;
    if (card.hidden) return;
    renderPermissionMatrix();
    try {
      const [templates, staffDirectory] = await Promise.all([
        api(`/api/staff/shift-templates?branch_id=${user.branch_id}`),
        api(`/api/staff/directory?branch_id=${user.branch_id}`)
      ]);
      directory = staffDirectory.items;
      defaultQuota = staffDirectory.default_leave_quota || defaultQuota;
      if (!directory.some(item => item.id === selectedStaffId))
        selectedStaffId = directory.find(item => item.is_active)?.id || directory[0]?.id || null;
      renderDirectory();
      renderTemplates(templates.items);
      status(`พร้อมจัดการพนักงาน ${directory.length} คน`);
    } catch (error) { status(error.message); directoryStatus(error.message); }
  }

  $$('#staffAddButton').addEventListener('click', () => {
    const form = $$('#staffCreateForm');
    const user = auth();
    form.querySelector('[value="manager"]').hidden = user?.role !== 'owner';
    form.hidden = !form.hidden;
    $$('#staffCreateSuccess').hidden = true;
    if (!form.hidden) { fillQuota(form, defaultQuota); form.elements.namedItem('name').focus(); }
  });
  $$('#staffCancelCreate').addEventListener('click', () => { $$('#staffCreateForm').hidden = true; });
  $$('#staffCreateForm').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const rate = form.elements.namedItem('hourly_rate').value;
    try {
      const created = await api('/api/staff', 'POST', {
        name: form.elements.namedItem('name').value.trim(),
        role: form.elements.namedItem('role').value,
        pin: form.elements.namedItem('pin').value,
        hourly_rate: rate === '' ? null : Number(rate),
        leave_quota: quotaValues(form),
      });
      form.reset();
      form.hidden = true;
      $$('#staffCreatedLine').textContent = `${created.name} · รหัสพนักงาน ${(window.staffCode || String)(created.staff_id)}`;
      $$('#staffCreateSuccess').hidden = false;
      selectedStaffId = created.staff_id;
      directoryStatus('');
      await refresh();
      window.dispatchEvent(new Event('poswai:staff-refresh'));
    } catch (error) { directoryStatus(error.message); }
  });

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
      const rate = form.elements.namedItem('hourly_rate').value;
      const profile = {name: form.elements.namedItem('name').value, leave_quota: quotaValues(form)};
      if (rate !== '') profile.hourly_rate = Number(rate);
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
    if (person.is_active && !confirm(`ปิดใช้งานบัญชี ${person.name} รหัส ${(window.staffCode || String)(person.id)}?`)) return;
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

  $('#staffTemplateForm').addEventListener('submit', async event => {
    event.preventDefault();
    const user = auth(); if (!user) return;
    const form = new FormData(event.currentTarget);
    try {
      await api('/api/staff/shift-templates', 'POST', {branch_id:user.branch_id, name:form.get('name'),
        start_time:form.get('start_time'), end_time:form.get('end_time')});
      event.currentTarget.reset();
      status('บันทึกกะแล้ว');
      await refresh();
      window.dispatchEvent(new Event('poswai:staff-refresh'));
    } catch (error) { status(error.message); }
  });
  $('#staffSeedTemplates').addEventListener('click', async () => {
    const user = auth(); if (!user) return;
    try {
      for (const shift of [{name:'กะเช้า', start_time:'08:00', end_time:'17:00'},
                           {name:'กะบ่าย', start_time:'14:00', end_time:'23:00'}])
        await api('/api/staff/shift-templates', 'POST', {branch_id:user.branch_id, ...shift});
      status('สร้างกะมาตรฐานแล้ว');
      await refresh();
      window.dispatchEvent(new Event('poswai:staff-refresh'));
    } catch (error) { status(error.message); }
  });
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
  window.addEventListener('poswai:permissions-ready', renderPermissionMatrix);
  refresh();
})();
