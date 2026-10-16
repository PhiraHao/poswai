/* Staff sign-in and manager onboarding. Session credentials live only in HttpOnly cookies. */
(() => {
  const tableToken = new URLSearchParams(location.search).get('table_token') || '';
  const tableNo = new URLSearchParams(location.search).get('table') || '';
  const requestedBranch = Number(new URLSearchParams(location.search).get('branch_id'));
  const tableBranchId = Number.isInteger(requestedBranch) && requestedBranch > 0 ? requestedBranch : 1;
  let current = null;
  let live = false;
  let preview = false;
  const tabsByRole = {
    owner: ['customer','kitchen','cashier','inventory','crm','staff','analytics'],
    manager: ['customer','kitchen','cashier','inventory','crm','staff','analytics'],
    cashier: ['customer','kitchen','cashier','staff'],
    kitchen: ['customer','kitchen','inventory','staff'],
    service: ['customer','kitchen','staff'],
    staff: ['customer','staff'],
    guest: ['customer','staff']
  };
  const canAccessTab = tab => (tabsByRole[current?.role || 'guest'] || tabsByRole.guest).includes(tab);
  const state = { get current() { return current; }, get tableToken() { return tableToken; }, get tableNo() { return tableNo; }, get branchId() { return current?.branch_id || tableBranchId; }, canAccessTab };
  window.poswaiAuth = state;

  const accountButton = document.createElement('button');
  accountButton.type = 'button';
  accountButton.className = 'poswai-auth-button';
  accountButton.textContent = 'เข้าสู่ระบบ';
  accountButton.hidden = true;
  document.querySelector('.net-controls')?.prepend(accountButton);

  const overlay = document.createElement('div');
  overlay.className = 'poswai-auth-overlay';
  overlay.hidden = true;
  overlay.innerHTML = `<section class="poswai-auth-card" role="dialog" aria-modal="true" aria-labelledby="poswaiAuthTitle">
    <h2 id="poswaiAuthTitle">เข้าสู่ระบบ POS WAI</h2>
    <p id="poswaiAuthDescription">ใช้รหัสพนักงานและ PIN ส่วนตัว</p>
    <div id="poswaiLoginPanel">
      <form id="poswaiLoginForm">
        <label for="poswaiStaffId">รหัสพนักงาน</label><input id="poswaiStaffId" name="staff_id" type="number" min="1" inputmode="numeric" autocomplete="username" required>
        <label for="poswaiStaffPin">PIN</label><input id="poswaiStaffPin" name="pin" type="password" minlength="8" autocomplete="current-password" required>
        <p class="poswai-auth-error" id="poswaiLoginError" role="alert"></p>
        <div class="poswai-auth-actions"><button class="poswai-auth-primary" type="submit">เข้าสู่ระบบ</button><button class="poswai-auth-secondary" type="button" id="poswaiCloseLogin">ปิด</button></div>
      </form>
    </div>
    <div id="poswaiManagerPanel" hidden>
      <form id="poswaiStaffForm">
        <strong>เพิ่มพนักงาน</strong>
        <label for="poswaiNewName">ชื่อ</label><input id="poswaiNewName" maxlength="100" required>
        <label for="poswaiNewRole">สิทธิ์</label><select id="poswaiNewRole"><option value="staff">พนักงาน</option><option value="cashier">แคชเชียร์</option><option value="kitchen">ครัว</option><option value="service">บริการ</option><option value="manager">ผู้จัดการ</option></select>
        <label for="poswaiNewPin">ตั้ง PIN ให้พนักงานคนนี้ (อย่างน้อย 8 ตัวอักษร)</label><input id="poswaiNewPin" type="password" minlength="8" autocomplete="new-password" placeholder="ห้ามใช้ PIN ของผู้จัดการ" required>
        <div class="poswai-auth-actions"><button class="poswai-auth-primary" id="poswaiCreateStaff" type="submit">สร้างบัญชี</button></div>
      </form>
      <div class="poswai-create-success" id="poswaiCreateSuccess" role="status" hidden>
        <div class="poswai-create-check" aria-hidden="true">✓</div>
        <h3 tabindex="-1" id="poswaiCreateSuccessTitle">สร้างบัญชีสำเร็จ</h3>
        <p id="poswaiCreatedName"></p>
        <span>รหัสพนักงาน</span>
        <strong id="poswaiCreatedId"></strong>
        <p>แจ้งรหัสนี้และ PIN ที่ตั้งไว้ให้พนักงานเป็นการส่วนตัว</p>
        <button class="poswai-auth-primary" type="button" id="poswaiAddAnotherStaff">เพิ่มพนักงานอีกคน</button>
      </div>
      <p class="poswai-auth-error" id="poswaiManagerError" role="alert"></p>
      <div class="poswai-auth-actions"><button class="poswai-auth-secondary" type="button" id="poswaiLogoutManager">ออกจากระบบ</button><button class="poswai-auth-secondary" type="button" id="poswaiCloseManager">ปิด</button></div>
    </div>
  </section>`;
  document.body.append(overlay);
  const $ = (selector) => overlay.querySelector(selector);
  const showCreateForm = () => {
    $('#poswaiStaffForm').hidden = false;
    $('#poswaiCreateSuccess').hidden = true;
    $('#poswaiAuthTitle').textContent = 'จัดการบัญชีพนักงาน';
    $('#poswaiAuthDescription').textContent = 'กำหนด PIN ใหม่เฉพาะพนักงานคนนี้ เพื่อใช้เข้าสู่ระบบ';
    $('#poswaiManagerError').textContent = '';
  };
  const open = (manager = false) => {
    if (manager) showCreateForm();
    $('#poswaiNewRole option[value="manager"]').hidden = current?.role !== 'owner';
    if (current?.role !== 'owner' && $('#poswaiNewRole').value === 'manager') $('#poswaiNewRole').value = 'staff';
    $('#poswaiLoginPanel').hidden = manager;
    $('#poswaiManagerPanel').hidden = !manager;
    $('#poswaiAuthTitle').textContent = manager ? 'จัดการบัญชีพนักงาน' : 'เข้าสู่ระบบ POS WAI';
    $('#poswaiAuthDescription').textContent = manager ? 'กำหนด PIN ใหม่เฉพาะพนักงานคนนี้ เพื่อใช้เข้าสู่ระบบ' : 'ใช้รหัสพนักงานและ PIN ส่วนตัว';
    overlay.hidden = false;
    (manager ? $('#poswaiNewName') : $('#poswaiStaffId')).focus();
  };
  const close = () => { overlay.hidden = true; };
  const api = async (url, body) => {
    const response = await fetch(url, { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    return result;
  };
  const update = () => {
    document.body.classList.toggle('poswai-guest', live && !preview && !current);
    accountButton.hidden = !live;
    accountButton.textContent = current ? `${current.name} ▾` : 'เข้าสู่ระบบ';
    document.querySelectorAll('.role-tab').forEach(button => {
      const tab = button.getAttribute('onclick')?.match(/switchTab\('([^']+)'/)?.[1];
      if (tab) button.hidden = !canAccessTab(tab);
    });
    if (!canAccessTab(document.body.dataset.activeTab || 'customer')) {
      document.querySelector('.role-tab')?.click();
    }
    const navStatus = document.querySelector('.nav-footer span:last-child');
    if (navStatus) navStatus.textContent = current ? current.name : (live ? 'ยังไม่เข้าสู่ระบบ' : 'โหมดตัวอย่าง');
    if (live && !current && tableToken && document.body.dataset.activeTab !== 'customer') {
      document.querySelector('.role-tab')?.click();
    }
    window.dispatchEvent(new CustomEvent('poswai:auth-changed', { detail: current }));
  };
  accountButton.addEventListener('click', async () => {
    if (!current) { open(); return; }
    if (current.role === 'manager' || current.role === 'owner') { open(true); return; }
    if (confirm(`ออกจากระบบ ${current.name}?`)) {
      await api('/api/auth/logout', {}); current = null; update(); open();
    }
  });
  $('#poswaiLoginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    $('#poswaiLoginError').textContent = '';
    try {
      current = await api('/api/auth/login', {
        staff_id: Number($('#poswaiStaffId').value), pin: $('#poswaiStaffPin').value,
      });
      $('#poswaiStaffPin').value = '';
      close(); update();
      if (typeof flushOfflineSyncQueue === 'function') flushOfflineSyncQueue();
    } catch (error) { $('#poswaiLoginError').textContent = error.message; }
  });
  $('#poswaiStaffForm').addEventListener('submit', async (event) => {
    event.preventDefault(); $('#poswaiManagerError').textContent = '';
    const submit = $('#poswaiCreateStaff');
    if (submit.disabled) return;
    submit.disabled = true;
    submit.textContent = 'กำลังสร้างบัญชี…';
    try {
      const result = await api('/api/staff', { name: $('#poswaiNewName').value.trim(),
        role: $('#poswaiNewRole').value, pin: $('#poswaiNewPin').value });
      $('#poswaiCreatedName').textContent = result.name;
      $('#poswaiCreatedId').textContent = String(result.staff_id);
      $('#poswaiStaffForm').reset();
      $('#poswaiStaffForm').hidden = true;
      $('#poswaiCreateSuccess').hidden = false;
      $('#poswaiAuthTitle').textContent = 'สร้างบัญชีสำเร็จ';
      $('#poswaiAuthDescription').textContent = 'บัญชีพร้อมให้พนักงานเข้าสู่ระบบ';
      $('#poswaiCreateSuccessTitle').focus();
    } catch (error) { $('#poswaiManagerError').textContent = error.message; }
    finally { submit.disabled = false; submit.textContent = 'สร้างบัญชี'; }
  });
  $('#poswaiAddAnotherStaff').addEventListener('click', () => {
    showCreateForm();
    $('#poswaiNewName').focus();
  });
  $('#poswaiCloseLogin').addEventListener('click', close);
  $('#poswaiCloseManager').addEventListener('click', close);
  $('#poswaiLogoutManager').addEventListener('click', async () => {
    await api('/api/auth/logout', {}); current = null; close(); update(); if (!tableToken) open();
  });
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !overlay.hidden) close(); });
  const logout = async () => {
    await api('/api/auth/logout', {}); current = null; update(); if (!tableToken) open();
  };
  window.poswaiAuth.logout = logout;
  window.poswaiAuth.openManager = () => { if (current?.role === 'manager' || current?.role === 'owner') open(true); };
  fetch('/api/config', { cache: 'no-store' }).then(response => response.json()).then(async config => {
    preview = !!config.preview_only;
    live = !preview || !!config.staff_live;
    document.body.classList.toggle('poswai-staff-live', !!config.staff_live);
    if (!live) return;
    if (!preview) document.body.classList.add('poswai-live');
    try {
      const response = await fetch('/api/auth/session', { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok) current = await response.json();
    } catch (_) { /* Offline pages retain local functionality without storing credentials. */ }
    update();
    if (!current && !tableToken && !preview) open();
  }).catch(() => {});
})();
