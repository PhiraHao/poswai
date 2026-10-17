/* Staff sign-in and manager onboarding. Session credentials live only in HttpOnly cookies. */
(() => {
  const tableToken = new URLSearchParams(location.search).get('table_token') || '';
  const tableNo = new URLSearchParams(location.search).get('table') || '';
  const requestedBranch = Number(new URLSearchParams(location.search).get('branch_id'));
  const tableBranchId = Number.isInteger(requestedBranch) && requestedBranch > 0 ? requestedBranch : 1;
  const requestedShop = (new URLSearchParams(location.search).get('shop') || '').trim().toLowerCase();
  /* Set by the owner sign-in callback: "enter" one shop, "choose" between several,
     "new" to open the first one, "linked" after binding an account to this shop. */
  const ownerFlow = (new URLSearchParams(location.search).get('owner') || '').trim();
  const ownerError = (new URLSearchParams(location.search).get('owner_error') || '').trim();
  const OWNER_ERRORS = {
    state: 'คำขอเข้าสู่ระบบหมดอายุหรือไม่ถูกต้อง กรุณากดเข้าสู่ระบบอีกครั้ง',
    denied: 'คุณยกเลิกการเข้าสู่ระบบ หรือผู้ให้บริการไม่อนุญาต',
    provider: 'ติดต่อผู้ให้บริการเข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่',
    provider_unknown: 'ช่องทางเข้าสู่ระบบนี้ไม่มีในระบบ',
    id_token: 'ข้อมูลยืนยันตัวตนไม่ถูกต้อง กรุณาลองใหม่',
    nonce: 'ข้อมูลยืนยันตัวตนไม่ตรงกับคำขอนี้ กรุณาลองใหม่',
    code: 'ไม่ได้รับรหัสยืนยันจากผู้ให้บริการ กรุณาลองใหม่',
    shop: 'ร้านที่จะผูกบัญชีใช้งานไม่ได้แล้ว',
    unconfigured: 'ยังไม่ได้เปิดใช้ช่องทางนี้',
  };
  let current = null;
  let live = false;
  let preview = false;
  let shop = { slug: requestedShop || 'main', name: '', is_demo: false, trial_ends_at: null };
  let channels = { line: false, google: false, facebook: false, email: false };
  let pointBaht = 10;
  /* Mirrors ROLE_PERMISSIONS in line_pos_server.py and is refreshed from /api/permissions.
     Hiding a tab is only a convenience: every endpoint checks the role again. */
  const tabsByRole = {
    owner: ['customer','kitchen','cashier','inventory','crm','staff','analytics'],
    manager: ['customer','kitchen','cashier','inventory','crm','staff','analytics'],
    cashier: ['customer','cashier','crm','staff'],
    kitchen: ['kitchen','inventory','staff'],
    service: ['customer','staff'],
    staff: ['customer','staff'],
    guest: ['customer','staff']
  };
  let matrix = null;
  // The sample shop is a guided tour of every screen, and holds no real records.
  const canAccessTab = tab => shop.is_demo || (tabsByRole[current?.role || 'guest'] || tabsByRole.guest).includes(tab);
  const state = { get current() { return current; }, get tableToken() { return tableToken; }, get tableNo() { return tableNo; }, get branchId() { return current?.branch_id || tableBranchId; }, get permissions() { return matrix; }, get shop() { return shop; }, get pointBaht() { return pointBaht; }, canAccessTab };
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
      <div class="poswai-login-tabs" role="tablist">
        <button type="button" role="tab" data-login-tab="owner" aria-selected="true">เจ้าของร้าน</button>
        <button type="button" role="tab" data-login-tab="staff" aria-selected="false">พนักงานหน้าร้าน</button>
      </div>

      <div data-login-pane="owner">
        <div class="poswai-channels">
          <button type="button" class="poswai-channel line" data-channel="line"><span class="poswai-channel-mark" aria-hidden="true">LINE</span>เข้าสู่ระบบด้วย LINE</button>
          <button type="button" class="poswai-channel google" data-channel="google"><span class="poswai-channel-mark" aria-hidden="true">G</span>เข้าสู่ระบบด้วย Google</button>
          <button type="button" class="poswai-channel facebook" data-channel="facebook"><span class="poswai-channel-mark" aria-hidden="true">f</span>เข้าสู่ระบบด้วย Facebook</button>
        </div>
        <div class="poswai-or"><span>หรือ</span></div>
        <form id="poswaiOwnerEmailForm">
          <label for="poswaiOwnerEmail">อีเมล</label><input id="poswaiOwnerEmail" type="email" autocomplete="email" placeholder="you@example.com" required>
          <label for="poswaiOwnerPassword">รหัสผ่าน</label><input id="poswaiOwnerPassword" type="password" autocomplete="current-password" required>
          <p class="poswai-auth-error" id="poswaiOwnerError" role="alert"></p>
          <div class="poswai-auth-actions"><button class="poswai-auth-primary" type="submit">เข้าสู่ระบบ</button><button class="poswai-auth-secondary" type="button" data-close-login>ปิด</button></div>
        </form>
        <p class="poswai-auth-switch">มีชื่อร้านในลิงก์และ PIN อยู่แล้ว? <button type="button" data-login-tab="staff">เข้าด้วยชื่อร้าน</button></p>
        <p class="poswai-auth-switch">ยังไม่มีร้านในระบบ? <button type="button" id="poswaiOpenSignup">เปิดร้านใหม่ ใช้ฟรี 30 วัน</button></p>
        <p class="poswai-auth-hint">เจ้าของร้านเข้าด้วยบัญชีของตัวเอง พนักงานหน้าร้านใช้ชื่อร้านกับ PIN ที่แท็บข้าง ๆ</p>
      </div>

      <div data-login-pane="staff" hidden>
        <div class="poswai-device-shop" id="poswaiDeviceShop" hidden>
          <span id="poswaiDeviceShopName"></span>
          <button type="button" id="poswaiChangeShop">เปลี่ยนร้าน</button>
        </div>
        <div class="poswai-known-staff" id="poswaiKnownStaff" hidden></div>
        <form id="poswaiLoginForm">
          <div id="poswaiShopCodeRow">
            <label for="poswaiShopCode">ชื่อร้านในลิงก์</label><input id="poswaiShopCode" name="shop" autocomplete="organization" placeholder="เช่น baan-kaew" required>
          </div>
          <label for="poswaiStaffId">รหัสพนักงาน</label><input id="poswaiStaffId" name="staff_id" type="text" inputmode="numeric" pattern="[0-9]{1,6}" maxlength="6" autocomplete="username" placeholder="เช่น 001" required>
          <label for="poswaiStaffPin">PIN</label><input id="poswaiStaffPin" name="pin" type="password" minlength="8" autocomplete="current-password" required>
          <p class="poswai-auth-error" id="poswaiLoginError" role="alert"></p>
          <div class="poswai-auth-actions"><button class="poswai-auth-primary" type="submit">เข้าสู่ระบบ</button><button class="poswai-auth-secondary" type="button" id="poswaiCloseLogin">ปิด</button></div>
        </form>
      </div>
    </div>
    <div id="poswaiChooserPanel" hidden>
      <p class="poswai-auth-hint" id="poswaiChooserWho"></p>
      <div class="poswai-chooser-list" id="poswaiChooserList"></div>
      <p class="poswai-auth-error" id="poswaiChooserError" role="alert"></p>
      <p class="poswai-auth-switch">ต้องการเปิดร้านใหม่อีกร้าน? <button type="button" id="poswaiChooserSignup">เปิดร้านใหม่</button></p>
      <div class="poswai-auth-actions"><button class="poswai-auth-secondary" type="button" id="poswaiChooserLogout">ออกจากบัญชี</button><button class="poswai-auth-secondary" type="button" data-close-login>ปิด</button></div>
    </div>
    <div id="poswaiSignupPanel" hidden>
      <p class="poswai-auth-hint ok" id="poswaiSignupAccount" hidden></p>
      <form id="poswaiSignupForm">
        <label for="poswaiShopName">ชื่อร้าน</label><input id="poswaiShopName" maxlength="80" required>
        <label for="poswaiNewSlug">ชื่อร้านในลิงก์</label><input id="poswaiNewSlug" maxlength="30" pattern="[a-z0-9][a-z0-9-]{1,28}[a-z0-9]" placeholder="a-z ตัวเลข และขีดกลาง" required>
        <p class="poswai-auth-hint" id="poswaiSlugHint" role="status"></p>
        <p class="poswai-auth-hint">ชื่อนี้อยู่ในลิงก์ของร้าน ใครเห็นลิงก์ก็เห็นชื่อนี้ <strong>ไม่ใช่รหัสลับ</strong> สิ่งที่กันคนอื่นเข้าร้านคือ PIN</p>
        <label for="poswaiOwnerName">ชื่อเจ้าของร้าน</label><input id="poswaiOwnerName" maxlength="100" required>
        <label for="poswaiOwnerPhone">เบอร์โทร</label><input id="poswaiOwnerPhone" type="tel" maxlength="20" required>
        <label for="poswaiOwnerPin">ตั้ง PIN เจ้าของร้าน (อย่างน้อย 8 ตัวอักษร)</label><input id="poswaiOwnerPin" type="password" minlength="8" autocomplete="new-password" required>
        <p class="poswai-auth-hint">PIN คือด่านเดียวที่กันคนอื่นเข้าร้าน อย่าใช้เลขเรียง วันเกิด หรือเบอร์โทร</p>
        <label class="poswai-auth-check"><input type="checkbox" id="poswaiAcceptTerms" required> <span>ยอมรับ<a href="/terms" target="_blank" rel="noopener">ข้อตกลงการใช้งาน</a>และ<a href="/privacy" target="_blank" rel="noopener">นโยบายความเป็นส่วนตัว</a></span></label>
        <p class="poswai-auth-error" id="poswaiSignupError" role="alert"></p>
        <div class="poswai-auth-actions"><button class="poswai-auth-primary" type="submit" id="poswaiSignupSubmit">เปิดร้าน</button><button class="poswai-auth-secondary" type="button" id="poswaiCloseSignup">ปิด</button></div>
      </form>
      <p class="poswai-auth-switch">มีร้านแล้ว? <button type="button" id="poswaiBackToLogin">เข้าสู่ระบบ</button></p>
    </div>
    <div id="poswaiMemberPanel" hidden>
      <div id="poswaiMemberJoin">
        <form id="poswaiMemberForm">
          <label for="poswaiMemberName">ชื่อที่ให้ร้านเรียก</label><input id="poswaiMemberName" maxlength="100">
          <label for="poswaiMemberPhone">เบอร์โทร (ใช้บอกพนักงานตอนสะสมแต้ม)</label><input id="poswaiMemberPhone" type="tel" maxlength="20" required>
          <label class="poswai-auth-check"><input type="checkbox" id="poswaiMemberConsent"> ยินยอมรับข่าวสารและโปรโมชันจากร้าน</label>
          <p class="poswai-auth-error" id="poswaiMemberError" role="alert"></p>
          <div class="poswai-auth-actions"><button class="poswai-auth-primary" type="submit" id="poswaiMemberSubmit">สมัครสมาชิก</button><button class="poswai-auth-secondary" type="button" id="poswaiCloseMember">ปิด</button></div>
        </form>
      </div>
      <div class="poswai-member-card" id="poswaiMemberCard" hidden>
        <span>แต้มสะสม</span>
        <strong id="poswaiMemberPoints">0</strong>
        <p id="poswaiMemberSummary"></p>
        <ul id="poswaiMemberHistory"></ul>
        <div class="poswai-auth-actions"><button class="poswai-auth-secondary" type="button" id="poswaiCloseMemberCard">ปิด</button></div>
      </div>
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
      <div class="poswai-owner-accounts" id="poswaiOwnerAccounts" hidden>
        <strong>บัญชีเจ้าของร้าน</strong>
        <p class="poswai-auth-hint">ผูกบัญชี LINE หรือ Google กับร้านนี้ แล้วครั้งต่อไปเข้าได้ด้วยบัญชีตัวเอง ไม่ต้องจำชื่อร้าน · ชื่อร้านกับ PIN ยังใช้ได้เหมือนเดิม</p>
        <ul class="poswai-owner-account-list" id="poswaiOwnerAccountList"></ul>
        <div class="poswai-channels" id="poswaiLinkChannels">
          <button type="button" class="poswai-channel line" data-link-channel="line"><span class="poswai-channel-mark" aria-hidden="true">LINE</span>ผูกบัญชี LINE กับร้านนี้</button>
          <button type="button" class="poswai-channel google" data-link-channel="google"><span class="poswai-channel-mark" aria-hidden="true">G</span>ผูกบัญชี Google กับร้านนี้</button>
        </div>
        <p class="poswai-auth-error" id="poswaiOwnerAccountError" role="alert"></p>
      </div>
      <p class="poswai-auth-error" id="poswaiManagerError" role="alert"></p>
      <div class="poswai-auth-actions"><button class="poswai-auth-secondary" type="button" id="poswaiLogoutManager">ออกจากระบบ</button><button class="poswai-auth-secondary" type="button" id="poswaiCloseManager">ปิด</button></div>
    </div>
  </section>`;
  document.body.append(overlay);

  /* The front door. A phone that scanned a table QR goes straight to ordering;
     anyone else is asked who they are before the workspace appears. */
  const landing = document.createElement('div');
  landing.className = 'poswai-landing';
  landing.hidden = true;
  landing.innerHTML = `<section class="poswai-landing-card">
    <img src="/assets/brand-logo.webp" alt="POS WAI" class="poswai-landing-logo" width="96" height="96">
    <h1>POS WAI</h1>
    <p class="poswai-landing-lead">ระบบจัดการร้านอาหารและคาเฟ่</p>
    <button type="button" class="poswai-auth-primary" id="poswaiLandingLogin">เข้าสู่ระบบพนักงาน</button>
    <p class="poswai-landing-note">ลูกค้า: สแกน QR ที่โต๊ะเพื่อดูเมนูและสั่งอาหารได้เลย ไม่ต้องเข้าสู่ระบบ</p>
    <button type="button" class="poswai-landing-preview" id="poswaiLandingPreview" hidden>ดูตัวอย่างระบบโดยไม่เข้าสู่ระบบ</button>
  </section>`;
  document.body.append(landing);

  const $ = (selector) => overlay.querySelector(selector);

  /* What this tablet remembers: which shop it belongs to, and the people who
     have signed in on it. Names are kept only here, so no screen ever lists a
     shop's staff to someone who has not signed in yet. */
  const DEVICE_KEY = 'poswaiDevice';
  const readDevice = () => {
    try { return JSON.parse(localStorage.getItem(DEVICE_KEY) || '{}'); }
    catch (_) { return {}; }
  };
  const writeDevice = value => {
    try { localStorage.setItem(DEVICE_KEY, JSON.stringify(value)); } catch (_) { /* private browsing */ }
  };
  let device = readDevice();
  const rememberLogin = (slug, staff) => {
    const sameShop = device.shop === slug ? device : {shop: slug, name: '', staff: []};
    const people = [{id: staff.staff_id, name: staff.name}, ...(sameShop.staff || [])]
      .filter((person, index, all) => all.findIndex(other => other.id === person.id) === index)
      .slice(0, 6);
    device = {shop: slug, name: shop.name || sameShop.name || '', staff: people};
    writeDevice(device);
  };

  const loginFocus = () => {
    const staffTab = !$('[data-login-pane="staff"]').hidden;
    if (!staffTab) return '#poswaiOwnerEmail';
    return device.shop ? '#poswaiStaffId' : '#poswaiShopCode';
  };
  const showLoginTab = name => {
    for (const tab of overlay.querySelectorAll('[role="tab"][data-login-tab]'))
      tab.setAttribute('aria-selected', String(tab.dataset.loginTab === name));
    for (const pane of overlay.querySelectorAll('[data-login-pane]'))
      pane.hidden = pane.dataset.loginPane !== name;
    $('#poswaiAuthDescription').textContent = name === 'owner'
      ? 'เจ้าของร้านและผู้จัดการ เข้าด้วยบัญชีของตัวเอง ไม่ต้องจำชื่อร้าน'
      : device.shop ? 'เครื่องนี้จำร้านไว้แล้ว พนักงานใส่รหัสของตัวเองกับ PIN ได้เลย'
      : 'ใส่ชื่อร้านในลิงก์ รหัสพนักงาน และ PIN · เครื่องนี้จะจำร้านไว้ให้หลังเข้าครั้งแรก';
    if (name === 'staff') renderDevice();
    $(loginFocus())?.focus();
  };
  const renderDevice = () => {
    const known = $('#poswaiKnownStaff');
    const shopRow = $('#poswaiDeviceShop');
    $('#poswaiShopCodeRow').hidden = Boolean(device.shop);
    $('#poswaiShopCode').required = !device.shop;
    if (device.shop) $('#poswaiShopCode').value = device.shop;
    shopRow.hidden = !device.shop;
    $('#poswaiDeviceShopName').textContent = device.shop ? `ร้าน ${device.name || device.shop}` : '';
    const people = device.shop ? (device.staff || []) : [];
    known.hidden = !people.length;
    known.replaceChildren(...people.map(person => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = person.name;
      button.addEventListener('click', () => {
        $('#poswaiStaffId').value = (window.staffCode || String)(person.id);
        $('#poswaiStaffPin').value = '';
        $('#poswaiStaffPin').focus();
      });
      return button;
    }));
  };
  const showCreateForm = () => {
    $('#poswaiStaffForm').hidden = false;
    $('#poswaiCreateSuccess').hidden = true;
    $('#poswaiAuthTitle').textContent = 'จัดการบัญชีพนักงาน';
    $('#poswaiAuthDescription').textContent = 'กำหนด PIN ใหม่เฉพาะพนักงานคนนี้ เพื่อใช้เข้าสู่ระบบ';
    $('#poswaiManagerError').textContent = '';
  };
  const PANELS = {
    login: ['เข้าสู่ระบบ POS WAI', '', '#poswaiOwnerEmail'],
    manager: ['จัดการบัญชีพนักงาน', 'กำหนด PIN ใหม่เฉพาะพนักงานคนนี้ เพื่อใช้เข้าสู่ระบบ', '#poswaiNewName'],
    signup: ['เปิดร้านของคุณ', 'ใช้ฟรี 30 วัน ไม่ต้องใส่บัตรเครดิต', '#poswaiShopName'],
    member: ['สมาชิกร้าน', 'สะสมแต้มทุกครั้งที่ซื้อ และรับโปรโมชันจากร้าน', '#poswaiMemberPhone'],
    chooser: ['เลือกร้านที่จะเข้า', 'บัญชีของคุณเป็นเจ้าของหลายร้าน', '#poswaiChooserList'],
  };
  const open = (panel = 'login') => {
    if (panel === true) panel = 'manager';
    if (panel === 'manager') { showCreateForm(); loadOwnerAccounts(); }
    if (panel === 'login') showLoginTab(device.shop ? 'staff' : 'owner');
    $('#poswaiNewRole option[value="manager"]').hidden = current?.role !== 'owner';
    if (current?.role !== 'owner' && $('#poswaiNewRole').value === 'manager') $('#poswaiNewRole').value = 'staff';
    for (const name of Object.keys(PANELS)) {
      const box = $(`#poswai${name[0].toUpperCase()}${name.slice(1)}Panel`);
      if (box) box.hidden = name !== panel;
    }
    const [title, description, focus] = PANELS[panel];
    $('#poswaiAuthTitle').textContent = title;
    if (panel !== 'login') $('#poswaiAuthDescription').textContent = description;
    overlay.hidden = false;
    (panel === 'login' ? $(loginFocus()) : $(focus))?.focus();
  };
  const close = () => { overlay.hidden = true; };
  const api = async (url, body) => {
    const headers = { 'Content-Type': 'application/json' };
    if (tableToken) headers['X-Table-Token'] = tableToken;
    const response = await fetch(url, { method: 'POST', credentials: 'same-origin',
      headers, body: JSON.stringify(body) });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    return result;
  };
  const update = () => {
    // A demo peek only counts while the shop runs in preview mode.
    const peeking = (preview || shop.is_demo) && sessionStorage.getItem('poswaiPreviewPeek') === '1';
    const locked = live && !current && !tableToken && !peeking;
    landing.hidden = !locked;
    document.body.classList.toggle('poswai-locked', locked);
    const peek = landing.querySelector('#poswaiLandingPreview');
    if (peek) peek.hidden = !preview;
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
      const code = $('#poswaiShopCode').value.trim().toLowerCase();
      current = await api('/api/auth/login', {
        staff_id: Number($('#poswaiStaffId').value), pin: $('#poswaiStaffPin').value,
        shop: code || undefined,
      });
      $('#poswaiStaffPin').value = '';
      if (current.shop) shop = { ...shop, slug: current.shop, is_demo: false };
      rememberLogin(current.shop || shop.slug, current);
      sessionStorage.removeItem('poswaiPreviewPeek');
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
      $('#poswaiCreatedId').textContent = (window.staffCode || String)(result.staff_id);
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
  overlay.addEventListener('click', event => {
    const tab = event.target.closest('[data-login-tab]');
    if (tab) showLoginTab(tab.dataset.loginTab);
    if (event.target.closest('[data-close-login]')) close();
  });
  $('#poswaiChangeShop').addEventListener('click', () => {
    device = {};
    writeDevice(device);
    $('#poswaiShopCode').value = '';
    renderDevice();
    $('#poswaiShopCode').focus();
  });
  const CHANNEL_NAMES = {line: 'LINE', google: 'Google', facebook: 'Facebook'};
  overlay.querySelector('[data-login-pane="owner"] .poswai-channels').addEventListener('click', event => {
    const button = event.target.closest('[data-channel]');
    if (!button) return;
    const channel = button.dataset.channel;
    const name = CHANNEL_NAMES[channel];
    if (!channels[channel]) {
      $('#poswaiOwnerError').textContent =
        `ยังไม่ได้เปิดใช้การเข้าสู่ระบบด้วย ${name} ระหว่างนี้ใช้ชื่อร้านและ PIN ไปก่อน`;
      return;
    }
    $('#poswaiOwnerError').textContent = `กำลังพาไปหน้า ${name}…`;
    // The handshake is the server's: it writes the state and nonce, we only follow.
    location.href = `/api/owner/auth/${channel}/start`;
  });
  $('#poswaiLinkChannels').addEventListener('click', event => {
    const button = event.target.closest('[data-link-channel]');
    if (!button) return;
    const channel = button.dataset.linkChannel;
    if (!channels[channel]) {
      $('#poswaiOwnerAccountError').textContent =
        `ยังไม่ได้เปิดใช้การเข้าสู่ระบบด้วย ${CHANNEL_NAMES[channel]}`;
      return;
    }
    $('#poswaiOwnerAccountError').textContent = `กำลังพาไปหน้า ${CHANNEL_NAMES[channel]}…`;
    location.href = `/api/owner/auth/${channel}/start?mode=link`;
  });
  $('#poswaiOwnerEmailForm').addEventListener('submit', event => {
    event.preventDefault();
    $('#poswaiOwnerError').textContent = channels.email
      ? 'กำลังตรวจสอบ…'
      : 'ยังไม่ได้เปิดใช้การเข้าสู่ระบบด้วยอีเมล ระหว่างนี้ใช้ชื่อร้านและ PIN ไปก่อน';
  });
  $('#poswaiOpenSignup').addEventListener('click', () => open('signup'));
  $('#poswaiBackToLogin').addEventListener('click', () => open('login'));
  $('#poswaiCloseSignup').addEventListener('click', close);
  let slugTimer;
  $('#poswaiNewSlug').addEventListener('input', event => {
    const field = event.currentTarget;
    field.value = field.value.toLowerCase().replace(/[^a-z0-9-]/g, '');
    const hint = $('#poswaiSlugHint');
    clearTimeout(slugTimer);
    if (field.value.length < 3) { hint.textContent = ''; return; }
    slugTimer = setTimeout(async () => {
      try {
        const result = await (await fetch(`/api/shops/check?slug=${encodeURIComponent(field.value)}`)).json();
        hint.textContent = !result.valid ? 'ชื่อร้านในลิงก์ใช้ a-z ตัวเลข และขีดกลาง ยาว 3–30 ตัว'
            : result.available ? `ใช้ได้ · ลิงก์ร้านคุณคือ ${location.origin}/?shop=${result.slug}` : 'ชื่อนี้มีคนใช้แล้ว';
        hint.className = `poswai-auth-hint${result.valid && result.available ? ' ok' : ' bad'}`;
      } catch (_) { hint.textContent = ''; }
    }, 350);
  });
  $('#poswaiSignupForm').addEventListener('submit', async event => {
    event.preventDefault();
    const submit = $('#poswaiSignupSubmit');
    if (submit.disabled) return;
    submit.disabled = true; submit.textContent = 'กำลังเปิดร้าน…';
    $('#poswaiSignupError').textContent = '';
    try {
      const result = await api('/api/shops', {
        shop_name: $('#poswaiShopName').value.trim(), slug: $('#poswaiNewSlug').value.trim(),
        owner_name: $('#poswaiOwnerName').value.trim(), phone: $('#poswaiOwnerPhone').value.trim(),
        pin: $('#poswaiOwnerPin').value, accept_terms: $('#poswaiAcceptTerms').checked,
      });
      $('#poswaiOwnerPin').value = '';
      sessionStorage.removeItem('poswaiPreviewPeek');
      // The new shop runs for real, so reload the page on its own address.
      location.href = `/?shop=${encodeURIComponent(result.shop.slug)}`;
    } catch (error) { $('#poswaiSignupError').textContent = error.message; }
    finally { submit.disabled = false; submit.textContent = 'เปิดร้าน'; }
  });

  /* The owner account signed in on this browser, if any. It is not a staff
     session: entering a shop is what opens one. */
  let ownerAccount = null;
  const accountLabel = account => account?.name || account?.email ||
    `บัญชี ${CHANNEL_NAMES[account?.provider] || ''}`.trim();
  const dropOwnerParams = () => {
    const query = new URLSearchParams(location.search);
    if (!query.has('owner') && !query.has('owner_error')) return;
    query.delete('owner');
    query.delete('owner_error');
    const rest = query.toString();
    history.replaceState(history.state, '', `${location.pathname}${rest ? `?${rest}` : ''}`);
  };
  const enterOwnerShop = async slug => {
    $('#poswaiChooserError').textContent = '';
    try {
      await api('/api/owner/enter', { slug });
      sessionStorage.removeItem('poswaiPreviewPeek');
      // Reload on the shop's own address so its menu, billing notice and
      // permissions all come from that shop and nothing is left over.
      location.href = `/?shop=${encodeURIComponent(slug)}`;
    } catch (error) {
      open('chooser');
      $('#poswaiChooserError').textContent = error.message;
    }
  };
  const renderChooser = (shops) => {
    $('#poswaiChooserWho').textContent = `เข้าสู่ระบบเป็น ${accountLabel(ownerAccount)}`;
    $('#poswaiChooserList').replaceChildren(...shops.map(entry => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'poswai-chooser-shop';
      const name = document.createElement('strong');
      name.textContent = entry.name || entry.slug;
      const code = document.createElement('span');
      code.textContent = entry.status === 'suspended' ? `${entry.slug} · ถูกระงับการใช้งาน` : entry.slug;
      button.append(name, code);
      button.addEventListener('click', () => enterOwnerShop(entry.slug));
      return button;
    }));
    open('chooser');
  };
  const resumeOwnerSignIn = async flow => {
    let session = null;
    try {
      const response = await fetch('/api/owner/session', { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok) session = await response.json();
    } catch (_) { /* offline: the sign-in page below says what to do */ }
    dropOwnerParams();
    if (!session) {
      open('login');
      showLoginTab('owner');
      $('#poswaiOwnerError').textContent = 'เข้าสู่ระบบไม่สำเร็จ กรุณาลองอีกครั้ง';
      return;
    }
    ownerAccount = session.account;
    if (flow === 'linked') {
      if (current?.role === 'owner') {
        open('manager');
        await loadOwnerAccounts();
        $('#poswaiOwnerAccountError').textContent = '';
      }
      return;
    }
    const owned = session.shops || [];
    if (!owned.length) {
      open('signup');
      $('#poswaiSignupAccount').hidden = false;
      $('#poswaiSignupAccount').textContent =
        `ผูกบัญชี ${accountLabel(ownerAccount)} ไว้แล้ว เปิดร้านเสร็จแล้วครั้งต่อไปเข้าด้วยบัญชีนี้ได้เลย`;
      return;
    }
    if (owned.length === 1 && flow !== 'choose') { await enterOwnerShop(owned[0].slug); return; }
    renderChooser(owned);
  };
  const loadOwnerAccounts = async () => {
    const box = $('#poswaiOwnerAccounts');
    box.hidden = current?.role !== 'owner';
    if (box.hidden) return;
    let info = null;
    try {
      const response = await fetch('/api/shop/owner-accounts', { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok) info = await response.json();
    } catch (_) { /* offline */ }
    if (!info || !info.linkable) { box.hidden = true; return; }
    $('#poswaiLinkChannels').hidden = !(info.channels?.line || info.channels?.google);
    $('#poswaiOwnerAccountList').replaceChildren(...(info.accounts || []).map(account => {
      const row = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = `${CHANNEL_NAMES[account.provider] || account.provider} · ${account.email || account.name || 'ไม่ระบุ'}`;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = 'ยกเลิกการผูก';
      remove.addEventListener('click', async () => {
        remove.disabled = true;
        $('#poswaiOwnerAccountError').textContent = '';
        try {
          const response = await fetch(`/api/shop/owner-accounts/${account.id}`,
            { method: 'DELETE', credentials: 'same-origin' });
          if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'ยกเลิกไม่สำเร็จ');
          await loadOwnerAccounts();
        } catch (error) {
          remove.disabled = false;
          $('#poswaiOwnerAccountError').textContent = error.message;
        }
      });
      row.append(label, remove);
      return row;
    }));
    if (!(info.accounts || []).length) {
      const empty = document.createElement('li');
      empty.className = 'poswai-owner-account-empty';
      empty.textContent = 'ยังไม่มีบัญชีผูกกับร้านนี้';
      $('#poswaiOwnerAccountList').replaceChildren(empty);
    }
  };
  $('#poswaiChooserSignup').addEventListener('click', () => open('signup'));
  $('#poswaiChooserLogout').addEventListener('click', async () => {
    try { await api('/api/owner/logout', {}); } catch (_) { /* already gone */ }
    ownerAccount = null;
    open('login');
    showLoginTab('owner');
  });

  const showMemberCard = card => {
    $('#poswaiMemberJoin').hidden = true;
    $('#poswaiMemberCard').hidden = false;
    $('#poswaiMemberPoints').textContent = `${card.points} แต้ม`;
    $('#poswaiMemberSummary').textContent =
      `${card.display_name || 'สมาชิก'} · ซื้อแล้ว ${card.completed_orders} ครั้ง · ทุก ${card.point_baht} บาท ได้ 1 แต้ม`;
    $('#poswaiMemberHistory').replaceChildren(...(card.history || []).map(entry => {
      const row = document.createElement('li');
      row.textContent = `${entry.change > 0 ? '+' : ''}${entry.change} · ${entry.reason}`;
      return row;
    }));
    try { localStorage.setItem('poswaiMemberPhone', card.phone || ''); } catch (_) { /* private browsing */ }
  };
  /* Two ways in. Opened from inside LINE the account itself identifies the
     customer. Scanned from a table sticker there is no LINE account, so the
     name and number are enough: being at the table is the proof. Sending the
     customer to the shop's own staff sign-in, which is what used to happen,
     asked them to log in to a till they have no business in. */
  const joinMember = async () => {
    const name = $('#poswaiMemberName').value.trim();
    const phone = $('#poswaiMemberPhone').value.trim();
    /* Someone sitting at a table has already proved where they are, so that
       is what signs them up. Sending them to LINE first takes a guest who
       filled in the form and drops them on a login page for an app they may
       not have, which is what used to happen whenever the shop had LIFF set
       up at all. */
    if (tableToken) {
      if (!name) throw new Error('กรุณากรอกชื่อที่ให้ร้านเรียก');
      if (!phone) throw new Error('กรุณากรอกเบอร์โทร');
      return api('/api/members/self', {
        branch_id: state.branchId, table_no: tableNo,
        display_name: name, phone,
        marketing_opt_in: $('#poswaiMemberConsent').checked,
      });
    }
    let token = '';
    if (typeof getLineIdToken === 'function') {
      try { token = (await getLineIdToken()) || ''; } catch (_) { token = ''; }
    }
    if (!token) {
      throw new Error('สมัครสมาชิกได้ที่โต๊ะ สแกน QR บนโต๊ะก่อน หรือแจ้งพนักงานให้สมัครให้');
    }
    return api('/api/members/me', {
      branch_id: state.branchId, line_id_token: token,
      display_name: name || undefined, phone: phone || undefined,
      marketing_opt_in: $('#poswaiMemberConsent').checked,
    });
  };
  $('#poswaiMemberForm').addEventListener('submit', async event => {
    event.preventDefault();
    const submit = $('#poswaiMemberSubmit');
    if (submit.disabled) return;
    submit.disabled = true; submit.textContent = 'กำลังสมัคร…';
    $('#poswaiMemberError').textContent = '';
    try { showMemberCard(await joinMember()); }
    catch (error) { $('#poswaiMemberError').textContent = error.message; }
    finally { submit.disabled = false; submit.textContent = 'สมัครสมาชิก'; }
  });
  $('#poswaiCloseMember').addEventListener('click', close);
  $('#poswaiCloseMemberCard').addEventListener('click', close);
  const openMember = () => {
    $('#poswaiMemberJoin').hidden = false;
    $('#poswaiMemberCard').hidden = true;
    $('#poswaiMemberError').textContent = '';
    try { $('#poswaiMemberPhone').value ||= localStorage.getItem('poswaiMemberPhone') || ''; } catch (_) { /* private browsing */ }
    open('member');
  };

  const enterPreview = (tab) => {
    sessionStorage.setItem('poswaiPreviewPeek', '1');
    history.pushState({ poswaiPeek: 1 }, '', location.href);
    close();
    update();
    if (tab) document.querySelector(`.role-tab[onclick*="switchTab('${tab}'"]`)?.click();
  };
  window.addEventListener('popstate', (event) => {
    if (sessionStorage.getItem('poswaiPreviewPeek') === '1' && !event.state?.poswaiPeek) {
      sessionStorage.removeItem('poswaiPreviewPeek');
      update();
    }
  });
  landing.querySelector('#poswaiLandingLogin')?.addEventListener('click', () => open());
  landing.querySelector('#poswaiLandingPreview')?.addEventListener('click', () => enterPreview());
  $('#poswaiCloseLogin').addEventListener('click', close);
  $('#poswaiCloseManager').addEventListener('click', close);
  $('#poswaiLogoutManager').addEventListener('click', async () => {
    await api('/api/auth/logout', {}); current = null; close(); update(); if (!tableToken) open();
  });
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !overlay.hidden) close(); });
  const logout = async () => {
    sessionStorage.removeItem('poswaiPreviewPeek');
    await api('/api/auth/logout', {}); current = null; update(); if (!tableToken) open();
  };
  window.poswaiAuth.logout = logout;
  window.poswaiAuth.openLogin = () => open('login');
  window.poswaiAuth.openSignup = () => open('signup');
  window.poswaiAuth.openMember = openMember;
  window.poswaiAuth.enterPreview = enterPreview;
  Object.defineProperty(window.poswaiAuth, 'preview', { get: () => preview });
  window.poswaiAuth.openManager = () => { if (current?.role === 'manager' || current?.role === 'owner') open(true); };
  fetch('/api/permissions', { cache: 'no-store' }).then(response => response.ok ? response.json() : null).then(result => {
    if (!result?.roles) return;
    matrix = result;
    for (const [role, entry] of Object.entries(result.roles))
      if (Array.isArray(entry.tabs)) tabsByRole[role] = entry.tabs;
    update();
    window.dispatchEvent(new Event('poswai:permissions-ready'));
  }).catch(() => { /* The built-in matrix above keeps the offline shell usable. */ });
  fetch('/api/config', { cache: 'no-store' }).then(response => response.json()).then(async config => {
    preview = !!config.preview_only;
    shop = config.shop || shop;
    pointBaht = config.point_baht || pointBaht;
    channels = config.login_channels || channels;
    live = !preview || !!config.staff_live;
    if (shop.is_demo) sessionStorage.setItem('poswaiPreviewPeek', '1');
    window.dispatchEvent(new CustomEvent('poswai:shop-ready', { detail: shop }));
    document.body.classList.toggle('poswai-staff-live', !!config.staff_live);
    if (!live) { update(); return; }
    if (!preview) {
      document.body.classList.add('poswai-live');
      sessionStorage.removeItem('poswaiPreviewPeek');
    }
    try {
      const response = await fetch('/api/auth/session', { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok) current = await response.json();
    } catch (_) { /* Offline pages retain local functionality without storing credentials. */ }
    update();
    if (ownerError) {
      dropOwnerParams();
      open('login');
      showLoginTab('owner');
      $('#poswaiOwnerError').textContent = OWNER_ERRORS[ownerError] || OWNER_ERRORS.provider;
      return;
    }
    if (ownerFlow) { await resumeOwnerSignIn(ownerFlow); return; }
    const installedApp = window.matchMedia?.('(display-mode: standalone)').matches;
    if (!current && !tableToken && installedApp && sessionStorage.getItem('poswaiPreviewPeek') !== '1') open();
  }).catch(() => {});
})();
