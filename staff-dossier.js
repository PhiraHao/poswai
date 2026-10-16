/* Staff dossier tab: employment facts, hiring documents, store assets and history.
   Managers edit their team; everyone else sees their own file, read-only. */
(() => {
  const host = document.getElementById('staffDossierHost');
  if (!host) return;
  const ROLE_LABELS = {owner:'เจ้าของร้าน', manager:'ผู้จัดการ', cashier:'แคชเชียร์',
    kitchen:'ครัว / บาร์', service:'พนักงานเสิร์ฟ', staff:'พนักงานทั่วไป'};
  const STATE_LABELS = {received:'ส่งครบแล้ว', missing:'ค้างส่งเอกสาร',
    expiring:'ใกล้หมดอายุ', expired:'หมดอายุแล้ว', optional:'เฉพาะแรงงานต่างด้าว'};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const api = async (path, method = 'GET', body) => {
    const response = await fetch(path, {method, credentials:'same-origin', cache:'no-store',
      headers: body ? {'Content-Type':'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };

  host.innerHTML = `<section class="card staff-dossier">
    <div class="card-header"><div>
      <div class="card-title">แฟ้มประวัติพนักงาน</div>
      <p class="staff-admin-note">ข้อมูลการจ้าง เอกสารที่ต้องส่ง ของที่เบิกไป และประวัติการทำงานรายคน</p>
    </div></div>
    <p class="dossier-privacy">แฟ้มนี้เก็บ “ข้อเท็จจริง” ของเอกสาร เช่น ส่งแล้วหรือยัง หมดอายุวันไหน
      ไม่ได้เก็บไฟล์สำเนาบัตรประชาชนไว้บนเซิร์ฟเวอร์ และไม่แสดงรหัส PIN ของใครทั้งสิ้น</p>
    <div class="dossier-layout">
      <div id="dossierPeople" class="staff-directory-list"></div>
      <div id="dossierDetail" class="dossier-detail"></div>
    </div>
    <p id="dossierStatus" role="status"></p></section>`;

  const $ = selector => host.querySelector(selector);
  const status = message => { $('#dossierStatus').textContent = message; };
  const auth = () => window.poswaiAuth?.current;
  let people = [];
  let selectedId = null;
  let dossier = null;
  let canEdit = false;

  const field = (name, label, value, type = 'text', extra = '') =>
    `<label>${label}<input name="${name}" type="${type}" value="${escape(value ?? '')}" ${extra}></label>`;

  function renderPeople() {
    const list = $('#dossierPeople');
    if (!people.length) { list.innerHTML = ''; return; }
    list.innerHTML = people.map(person => {
      const flags = [];
      if (person.missing) flags.push(`<em class="dossier-flag is-missing">ค้างเอกสาร ${person.missing}</em>`);
      if (person.attention) flags.push(`<em class="dossier-flag is-expiring">ใกล้หมดอายุ ${person.attention}</em>`);
      if (person.probation?.on_probation) flags.push(`<em class="dossier-flag is-probation">ทดลองงาน</em>`);
      if (person.assets_outstanding) flags.push(`<em class="dossier-flag">ของค้าง ${person.assets_outstanding}</em>`);
      return `<button type="button" data-staff-id="${person.id}" class="${person.id === selectedId ? 'selected' : ''}">
        <strong>${escape(person.name)}</strong>
        <small>รหัส ${person.id} · ${escape(ROLE_LABELS[person.role] || person.role)} · ${escape(person.tenure)}</small>
        ${flags.length ? `<span class="dossier-flags">${flags.join('')}</span>` : ''}</button>`;
    }).join('');
  }

  function renderDetail() {
    const detail = $('#dossierDetail');
    if (!dossier) { detail.innerHTML = '<p class="people-empty">เลือกพนักงานเพื่อดูแฟ้มประวัติ</p>'; return; }
    const profile = dossier.profile;
    const disabled = canEdit ? '' : 'disabled';
    const documents = dossier.documents.map(doc => `
      <li class="dossier-doc is-${doc.state}">
        <label class="dossier-doc-main">
          <input type="checkbox" data-doc="${doc.key}" ${doc.received ? 'checked' : ''} ${disabled}>
          <span>${escape(doc.label)}</span>
        </label>
        <span class="dossier-doc-state">${STATE_LABELS[doc.state]}${
          doc.days_left !== null && doc.days_left !== undefined && doc.received
            ? ` · ${doc.days_left < 0 ? `เกินมา ${Math.abs(doc.days_left)} วัน` : `อีก ${doc.days_left} วัน`}` : ''}</span>
        ${doc.expires ? `<input class="dossier-doc-date" type="date" data-expiry="${doc.key}"
            value="${escape(doc.expires_on || '')}" aria-label="วันหมดอายุของ ${escape(doc.label)}" ${disabled}>` : ''}
        <input class="dossier-doc-note" data-note="${doc.key}" maxlength="200" placeholder="เช่น เก็บไว้ที่แฟ้มหน้าร้าน"
          value="${escape(doc.note || '')}" aria-label="หมายเหตุของ ${escape(doc.label)}" ${disabled}>
      </li>`).join('');
    const assets = dossier.assets.length ? dossier.assets.map(asset => `
      <li class="${asset.returned_on ? 'is-returned' : ''}">
        <span>${escape(asset.item)}<small>เบิก ${escape(asset.issued_on)}${
          asset.returned_on ? ` · คืนแล้ว ${escape(asset.returned_on)}` : ''}</small></span>
        ${canEdit ? `<button type="button" data-asset="${asset.id}" data-returned="${asset.returned_on ? '1' : '0'}">${
          asset.returned_on ? 'ยังไม่ได้คืน' : 'รับคืนแล้ว'}</button>` : ''}</li>`).join('')
      : '<li class="people-empty">ยังไม่มีรายการเบิกของ</li>';
    const timeline = dossier.timeline.length ? dossier.timeline.map(entry => `
      <li class="is-${entry.kind}"><strong>${escape(entry.event_date)}</strong>
        <em>${escape(entry.kind_label)}</em><span>${escape(entry.detail)}</span></li>`).join('')
      : '<li class="people-empty">ยังไม่มีบันทึก</li>';

    detail.innerHTML = `
      <div class="dossier-head">
        <div><h3>${escape(dossier.staff.name)}${profile.nickname ? ` (${escape(profile.nickname)})` : ''}</h3>
          <p>รหัสพนักงาน ${dossier.staff.id} · ${escape(ROLE_LABELS[dossier.staff.role] || dossier.staff.role)}
            · ${escape(dossier.employment_label)}</p></div>
        <div class="dossier-head-facts">
          <span>อายุงาน<strong>${escape(dossier.tenure.text)}</strong></span>
          <span>ค่าจ้าง<strong>${dossier.staff.hourly_rate ?? '—'} บาท/ชม.</strong></span>
          <span>สถานะทดลองงาน<strong>${escape(dossier.probation.status)}</strong></span>
        </div>
      </div>
      <form id="dossierProfileForm" class="dossier-form">
        <strong>ข้อมูลการจ้างงานและการติดต่อ</strong>
        <div class="dossier-grid">
          ${field('nickname', 'ชื่อเล่น', profile.nickname, 'text', `maxlength="120" ${disabled}`)}
          ${field('phone', 'เบอร์โทร', profile.phone, 'text', `maxlength="120" ${disabled}`)}
          ${field('line_display', 'LINE ID', profile.line_display, 'text', `maxlength="120" ${disabled}`)}
          ${field('start_date', 'วันที่เริ่มงานวันแรก', profile.start_date, 'date', disabled)}
          <label>ประเภทการจ้าง<select name="employment_type" ${disabled}>
            <option value="full_time">พนักงานประจำ</option><option value="part_time">พาร์ทไทม์</option>
            <option value="daily">รายวัน</option><option value="probation">ทดลองงาน</option></select></label>
          ${field('probation_end_date', 'วันครบกำหนดประเมิน', profile.probation_end_date, 'date', disabled)}
          ${field('bank_name', 'ธนาคารรับเงินเดือน', profile.bank_name, 'text', `maxlength="120" ${disabled}`)}
          ${field('bank_account', 'เลขบัญชี', profile.bank_account, 'text', `maxlength="120" ${disabled}`)}
          ${field('emergency_contact', 'ผู้ติดต่อฉุกเฉิน (ญาติ)', profile.emergency_contact, 'text', `maxlength="120" ${disabled}`)}
          ${field('emergency_phone', 'เบอร์ผู้ติดต่อฉุกเฉิน', profile.emergency_phone, 'text', `maxlength="120" ${disabled}`)}
        </div>
        <label>โรคประจำตัว / ข้อควรระวัง<input name="medical_note" maxlength="300"
          value="${escape(profile.medical_note || '')}" ${disabled}></label>
        ${canEdit ? '<button type="submit">บันทึกแฟ้มประวัติ</button>' : ''}
      </form>
      <div class="dossier-form">
        <strong>เอกสารสมัครงานและใบอนุญาต</strong>
        <p class="staff-admin-note">ติ๊กเมื่อได้รับเอกสารแล้ว และใส่วันหมดอายุของใบที่ต้องต่ออายุ</p>
        <ul class="dossier-docs">${documents}</ul>
      </div>
      <div class="dossier-form">
        <strong>ของที่เบิกไปจากร้าน</strong>
        <ul class="dossier-assets">${assets}</ul>
        ${canEdit ? `<form id="dossierAssetForm" class="dossier-inline">
          <input name="item" maxlength="80" placeholder="เช่น เสื้อยูนิฟอร์ม x2, กุญแจล็อกเกอร์ #03" required>
          <button type="submit">บันทึกการเบิก</button></form>` : ''}
      </div>
      <div class="dossier-form">
        <strong>ประวัติการทำงาน ปรับค่าแรง และใบเตือน</strong>
        <ul class="dossier-timeline">${timeline}</ul>
        ${canEdit ? `<form id="dossierTimelineForm" class="dossier-inline">
          <select name="kind"><option value="milestone">เหตุการณ์</option>
            <option value="pay_change">ปรับค่าแรง</option><option value="warning">ใบเตือน</option>
            <option value="note">บันทึก</option></select>
          <input name="event_date" type="date">
          <input name="detail" maxlength="300" placeholder="รายละเอียด" required>
          <button type="submit">เพิ่มบันทึก</button></form>` : ''}
      </div>`;
    detail.querySelector('[name="employment_type"]').value = profile.employment_type;
    bindDetail();
  }

  const save = async (action) => {
    try { dossier = await action(); status('บันทึกแล้ว'); renderDetail(); await loadPeople(); }
    catch (error) { status(error.message); }
  };

  function bindDetail() {
    const detail = $('#dossierDetail');
    detail.querySelector('#dossierProfileForm')?.addEventListener('submit', event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      save(() => api(`/api/staff/${selectedId}/dossier`, 'PATCH', Object.fromEntries(form.entries())));
    });
    detail.querySelector('#dossierAssetForm')?.addEventListener('submit', event => {
      event.preventDefault();
      const item = new FormData(event.currentTarget).get('item');
      save(() => api(`/api/staff/${selectedId}/assets`, 'POST', {item}));
    });
    detail.querySelector('#dossierTimelineForm')?.addEventListener('submit', event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      save(() => api(`/api/staff/${selectedId}/timeline`, 'POST', {
        kind: form.get('kind'), detail: form.get('detail'),
        event_date: form.get('event_date') || null}));
    });
    detail.querySelectorAll('[data-asset]').forEach(button => button.addEventListener('click', () => {
      save(() => api(`/api/staff/${selectedId}/assets/${button.dataset.asset}`, 'PATCH',
        {returned: button.dataset.returned !== '1'}));
    }));
    const sendDocument = key => {
      const checkbox = detail.querySelector(`[data-doc="${key}"]`);
      const expiry = detail.querySelector(`[data-expiry="${key}"]`);
      const note = detail.querySelector(`[data-note="${key}"]`);
      save(() => api(`/api/staff/${selectedId}/documents/${key}`, 'PUT', {
        received: checkbox.checked, expires_on: expiry?.value || null, note: note.value}));
    };
    detail.querySelectorAll('[data-doc]').forEach(box =>
      box.addEventListener('change', () => sendDocument(box.dataset.doc)));
    detail.querySelectorAll('[data-expiry]').forEach(input =>
      input.addEventListener('change', () => sendDocument(input.dataset.expiry)));
    detail.querySelectorAll('[data-note]').forEach(input =>
      input.addEventListener('blur', () => { if (input.value !== input.defaultValue) sendDocument(input.dataset.note); }));
  }

  async function openDossier(staffId) {
    selectedId = staffId;
    renderPeople();
    try { dossier = await api(`/api/staff/${staffId}/dossier`); status(''); }
    catch (error) { dossier = null; status(error.message); }
    renderDetail();
  }

  async function loadPeople() {
    const user = auth();
    if (!user) return;
    if (!canEdit) { people = []; renderPeople(); return; }
    try {
      people = (await api(`/api/staff/dossier-summary?branch_id=${user.branch_id}`)).staff;
      renderPeople();
    } catch (error) { status(error.message); }
  }

  async function refresh() {
    const user = auth();
    host.hidden = !user;
    if (!user) { dossier = null; people = []; return; }
    canEdit = ['manager', 'owner'].includes(user.role);
    host.classList.toggle('is-own-file', !canEdit);
    await loadPeople();
    const wanted = canEdit ? (people.some(p => p.id === selectedId) ? selectedId : people[0]?.id) : user.staff_id;
    if (wanted) await openDossier(wanted);
    else renderDetail();
  }

  $('#dossierPeople').addEventListener('click', event => {
    const button = event.target.closest('[data-staff-id]');
    if (button) openDossier(Number(button.dataset.staffId));
  });
  window.addEventListener('poswai:auth-changed', refresh);
  window.addEventListener('poswai:staff-refresh', loadPeople);
  refresh();
})();
