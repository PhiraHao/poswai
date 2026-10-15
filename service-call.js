/* Table service requests: visible customer action and cashier inbox. */
(() => {
  const storageKey = 'poswaiServiceCalls';
  const $ = selector => document.querySelector(selector);
  const branchId = () => window.poswaiAuth?.branchId || (($('#branchSelect')?.selectedIndex ?? 0) + 1);
  const localCalls = () => {
    try { return JSON.parse(localStorage.getItem(storageKey) || '[]'); }
    catch { return []; }
  };
  const saveLocal = calls => localStorage.setItem(storageKey, JSON.stringify(calls.slice(-100)));
  const messageTime = value => {
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? '' : date.toLocaleTimeString('th-TH', {hour:'2-digit', minute:'2-digit'});
  };
  const cashier = $('#view-cashier');
  const cart = $('#customerCartPanel');
  if (!cashier || !cart) return;
  const configReady = fetch('/api/config').then(response => response.json()).then(config => {
    if (config.preview_only) state.previewOnly = true;
  }).catch(() => {});

  const callButton = document.createElement('button');
  callButton.type = 'button';
  callButton.className = 'service-call-primary';
  callButton.textContent = 'เรียกพนักงาน';
  callButton.addEventListener('click', () => sendTableServiceCall('เรียกพนักงานที่โต๊ะ'));
  const searchRow = $('#menuSearchInput')?.parentElement;
  if (searchRow) searchRow.append(callButton);
  else cart.prepend(callButton);

  const inbox = document.createElement('section');
  inbox.id = 'cashierServiceInbox';
  inbox.className = 'service-inbox card';
  inbox.setAttribute('aria-live', 'polite');
  cashier.querySelector('.grid-2')?.before(inbox);

  let remoteCalls = [];
  let polling = false;
  let lastCount = 0;
  function renderCalls() {
    const branch = branchId();
    const calls = [...remoteCalls.filter(call => call.branch_id === branch)];
    const known = new Set(calls.map(call => call.event_id));
    for (const call of localCalls()) {
      if (call.branch_id === branch && !known.has(call.event_id)) calls.push(call);
    }
    calls.sort((a,b) => String(b.created_at).localeCompare(String(a.created_at)));
    inbox.replaceChildren();
    const heading = document.createElement('div');
    heading.className = 'service-inbox-heading';
    const title = document.createElement('strong');
    title.textContent = `คำขอจากโต๊ะ ${calls.length ? `· ${calls.length}` : ''}`;
    heading.append(title);
    inbox.append(heading);
    if (!calls.length) {
      const empty = document.createElement('p');
      empty.className = 'service-inbox-empty';
      empty.innerHTML = '<img src="/assets/mascot-wave.webp" alt="" loading="lazy"><span>ยังไม่มีคำขอจากลูกค้า</span>';
      inbox.append(empty);
    }
    for (const call of calls) {
      const row = document.createElement('div');
      row.className = 'service-request';
      const text = document.createElement('div');
      const label = document.createElement('strong');
      label.textContent = `โต๊ะ ${call.table_no} · ${call.call_type}`;
      const time = document.createElement('small');
      time.textContent = `${messageTime(call.created_at)}${call.local_only ? ' · ตัวอย่าง' : call.queued ? ' · รอซิงก์' : ''}`;
      text.append(label, time);
      const done = document.createElement('button');
      done.type = 'button';
      done.textContent = 'รับทราบ';
      done.addEventListener('click', () => acknowledge(call, done));
      row.append(text, done);
      inbox.append(row);
    }
    const badge = $('#cashierServiceBadge');
    if (badge) { badge.textContent = String(calls.length); badge.hidden = !calls.length; }
    if (calls.length > lastCount && document.body.dataset.activeTab === 'cashier') {
      inbox.classList.add('service-inbox-new');
      setTimeout(() => inbox.classList.remove('service-inbox-new'), 1300);
    }
    lastCount = calls.length;
  }

  const nav = [...document.querySelectorAll('button[onclick]')].find(button => button.getAttribute('onclick').includes("switchTab('cashier'"));
  if (nav) {
    const badge = document.createElement('span');
    badge.id = 'cashierServiceBadge';
    badge.className = 'service-nav-badge';
    badge.hidden = true;
    nav.append(badge);
  }

  async function refreshRemote() {
    await configReady;
    if (state.previewOnly || !navigator.onLine || polling || document.hidden) return;
    polling = true;
    try {
      const response = await fetch(`/api/service-calls?branch_id=${branchId()}`, {cache:'no-store'});
      if (response.ok) {
        remoteCalls = (await response.json()).calls || [];
        const remoteIds = new Set(remoteCalls.map(call => call.event_id));
        saveLocal(localCalls().filter(call => call.queued && !remoteIds.has(call.event_id)));
        renderCalls();
      }
    } catch { /* Offline calls remain visible locally until reconnection. */ }
    finally { polling = false; }
  }

  window.sendTableServiceCall = async function(callType) {
    await configReady;
    const call = {
      event_id: crypto.randomUUID(), branch_id: branchId(),
      table_no: String(state.customerTable), call_type: String(callType),
      created_at: new Date().toISOString(), local_only: Boolean(state.previewOnly),
      queued: !navigator.onLine || !state.isOnline
    };
    saveLocal([...localCalls(), call]);
    renderCalls();
    if (state.previewOnly) {
      showToast(`ตัวอย่าง: ส่งคำขอจากโต๊ะ ${call.table_no} ไปหน้าแคชเชียร์แล้ว`);
      return;
    }
    try {
      const result = await apiMutation('/api/service-calls', {
        event_id:call.event_id, branch_id:call.branch_id,
        table_no:call.table_no, call_type:call.call_type
      });
      if (result.queued) {
        saveLocal(localCalls().map(item => item.event_id === call.event_id ? {...item, queued:true} : item));
        showToast(`บันทึกคำขอโต๊ะ ${call.table_no} ไว้แล้ว จะส่งเมื่อออนไลน์`);
      } else {
        saveLocal(localCalls().filter(item => item.event_id !== call.event_id));
        showToast(`แจ้งพนักงานสำหรับโต๊ะ ${call.table_no} แล้ว`);
        await refreshRemote();
      }
      renderCalls();
    } catch (error) {
      saveLocal(localCalls().filter(item => item.event_id !== call.event_id));
      renderCalls();
      showToast(`ส่งคำขอไม่สำเร็จ: ${error.message}`);
    }
  };

  async function acknowledge(call, button) {
    button.disabled = true;
    if (!call.local_only && !call.queued) {
      try {
        const response = await fetch(`/api/service-calls/${encodeURIComponent(call.event_id)}/acknowledge`, {method:'POST'});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      } catch {
        button.disabled = false;
        showToast('รับทราบไม่สำเร็จ กรุณาลองอีกครั้ง');
        return;
      }
    }
    if (call.queued) {
      state.offlineSyncQueue = state.offlineSyncQueue.filter(event => event.id !== call.event_id && event.payload?.event_id !== call.event_id);
      persistSyncQueue();
    }
    saveLocal(localCalls().filter(item => item.event_id !== call.event_id));
    remoteCalls = remoteCalls.filter(item => item.event_id !== call.event_id);
    renderCalls();
  }

  const oldCashierRender = window.renderCashierView;
  window.renderCashierView = function(...args) {
    const result = oldCashierRender.apply(this, args);
    renderCalls();
    return result;
  };
  window.addEventListener('storage', event => { if (event.key === storageKey) renderCalls(); });
  window.addEventListener('online', refreshRemote);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshRemote(); });
  setInterval(() => { if (document.body.dataset.activeTab === 'cashier') refreshRemote(); }, 5000);
  renderCalls();
  refreshRemote();
})();
