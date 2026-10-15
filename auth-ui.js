/* Staff sign-in and manager onboarding. Session credentials live only in HttpOnly cookies. */
(() => {
  const tableToken = new URLSearchParams(location.search).get('table_token') || '';
  const tableNo = new URLSearchParams(location.search).get('table') || '';
  const requestedBranch = Number(new URLSearchParams(location.search).get('branch_id'));
  const tableBranchId = Number.isInteger(requestedBranch) && requestedBranch > 0 ? requestedBranch : 1;
  let current = null;
  let live = false;
  const state = { get current() { return current; }, get tableToken() { return tableToken; }, get tableNo() { return tableNo; }, get branchId() { return current?.branch_id || tableBranchId; } };
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
    <p id="poswaiAuthDescription">ใช้รหัสพนักงานและ PIN ของสาขา</p>
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
        <label for="poswaiNewPin">PIN อย่างน้อย 8 ตัวอักษร</label><input id="poswaiNewPin" type="password" minlength="8" autocomplete="new-password" required>
        <div class="poswai-auth-actions"><button class="poswai-auth-primary" type="submit">สร้างบัญชี</button></div>
      </form>
      <form id="poswaiTableForm">
        <strong>ลิงก์ QR ประจำโต๊ะ</strong>
        <label for="poswaiTableNo">หมายเลขโต๊ะ</label><input id="poswaiTableNo" maxlength="24" required>
        <div class="poswai-auth-actions"><button class="poswai-auth-primary" type="submit">สร้างลิงก์</button></div>
      </form>
      <p class="poswai-auth-result" id="poswaiManagerResult" hidden></p>
      <p class="poswai-auth-error" id="poswaiManagerError" role="alert"></p>
      <div class="poswai-auth-actions"><button class="poswai-auth-secondary" type="button" id="poswaiLogoutManager">ออกจากระบบ</button><button class="poswai-auth-secondary" type="button" id="poswaiCloseManager">ปิด</button></div>
    </div>
  </section>`;
  document.body.append(overlay);
  const $ = (selector) => overlay.querySelector(selector);
  const open = (manager = false) => {
    $('#poswaiLoginPanel').hidden = manager;
    $('#poswaiManagerPanel').hidden = !manager;
    $('#poswaiAuthTitle').textContent = manager ? 'จัดการบัญชีและ QR โต๊ะ' : 'เข้าสู่ระบบ POS WAI';
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
    document.body.classList.toggle('poswai-guest', live && !current);
    accountButton.hidden = !live;
    accountButton.textContent = current ? `${current.name} ▾` : 'เข้าสู่ระบบ';
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
    try {
      const result = await api('/api/staff', { name: $('#poswaiNewName').value.trim(),
        role: $('#poswaiNewRole').value, pin: $('#poswaiNewPin').value });
      $('#poswaiManagerResult').hidden = false;
      $('#poswaiManagerResult').textContent = `สร้างบัญชีแล้ว: ${result.name} · รหัสพนักงาน ${result.staff_id}`;
      $('#poswaiNewPin').value = '';
    } catch (error) { $('#poswaiManagerError').textContent = error.message; }
  });
  $('#poswaiTableForm').addEventListener('submit', async (event) => {
    event.preventDefault(); $('#poswaiManagerError').textContent = '';
    try {
      const table = $('#poswaiTableNo').value.trim();
      const result = await api('/api/tables/token', { branch_id: current.branch_id, table_no: table });
      const link = new URL(location.pathname, location.origin);
      link.searchParams.set('table', table); link.searchParams.set('table_token', result.token);
      link.searchParams.set('branch_id', String(current.branch_id));
      $('#poswaiManagerResult').hidden = false;
      $('#poswaiManagerResult').textContent = link.href;
      if (navigator.clipboard) await navigator.clipboard.writeText(link.href).catch(() => {});
    } catch (error) { $('#poswaiManagerError').textContent = error.message; }
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
    live = !config.preview_only;
    if (!live) return;
    document.body.classList.add('poswai-live');
    try {
      const response = await fetch('/api/auth/session', { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok) current = await response.json();
    } catch (_) { /* Offline pages retain local functionality without storing credentials. */ }
    update();
    if (!current && !tableToken) open();
  }).catch(() => {});
})();
