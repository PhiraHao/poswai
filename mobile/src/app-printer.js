/* The receipt printer, from inside the app.
 *
 * The web page prints through a queue that some other machine collects. The
 * app holds Bluetooth itself, so a till prints straight to the printer on its
 * counter: no computer in the back, no queue. print-agent-ui.js already asks
 * window.poswaiLocalPrinter first and falls back to the queue, so all this file
 * has to do is be a printer worth asking.
 *
 * What makes it usable at a busy till rather than in a demo:
 *  - one job at a time. Two receipts fired together (a pre-bill, then close-
 *    bill a second later) used to interleave their pieces and come out as noise;
 *    every print, connect and change of printer now waits its turn;
 *  - never half a receipt twice. A write that fails before anything reached the
 *    printer is retried on a fresh connection; once part of a receipt is out,
 *    the printer is mid-image and resending would print garbage, so it stops
 *    and offers "พิมพ์ซ้ำ" instead;
 *  - chosen once, remembered by device id, reconnected by itself — including on
 *    iPhone, where the id has to be looked up again after a restart;
 *  - Bluetooth off, permission missing or (only for scanning, only on Android 11
 *    and older) location off is said in Thai with the button that fixes it;
 *  - pieces no bigger than the link's MTU, paced so the printer keeps up.
 *
 * The encoder and the scan/connect plumbing are print-app's own escpos.js and
 * ble.js, proven against the shop's POS58; they are imported, not copied.
 */
(() => {
  'use strict';
  const BLE = window.Capacitor?.Plugins?.BluetoothLe;
  if (!document.documentElement.classList.contains('poswai-app') || !BLE) return;

  const KEY = 'poswai.app.printer';
  const SCAN_MS = 9000;
  const CONNECT_MS = 6000;      // a printer that is on answers in a second or two
  const PAUSE_MS = 12;          // between pieces on Android, where each write is acknowledged
  const IOS = window.Capacitor?.getPlatform?.() === 'ios';
  /* Android 12 and later scan without location; older versions need location
     switched on to see anything at all. Connecting to a known printer never does. */
  const ANDROID_VERSION = Number((/Android (\d+)/.exec(navigator.userAgent) || [])[1]) || 0;
  const SCAN_NEEDS_LOCATION = !IOS && ANDROID_VERSION > 0 && ANDROID_VERSION < 12;

  /* The choice of printer lives in two places. localStorage answers at once,
     which `ready` needs; but the web view writes it to disk some seconds later,
     so a shop that picked its printer and swiped the app shut straight away
     came back to a till that had forgotten it. Preferences commits to the
     phone's own storage immediately and restores the fast copy on start. */
  const PREFS = window.Capacitor?.Plugins?.Preferences;
  const remembered = () => { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; } };
  const remember = (value) => {
    try { value ? localStorage.setItem(KEY, JSON.stringify(value)) : localStorage.removeItem(KEY); } catch { /* */ }
    (value ? PREFS?.set({key: KEY, value: JSON.stringify(value)}) : PREFS?.remove({key: KEY}))?.catch(() => {});
  };
  /* The roll width belongs to the printer: kept with it, 58mm unless the
     shop says otherwise or the printer's own name says 80 (POS80, XP-80…). */
  const paperOf = (saved) => (Number(saved?.paper) === 80 ? 80 : 58);
  const guessPaper = (name) => (/(^|[^0-9])80([^0-9]|$)/.test(String(name || '')) ? 80 : 58);
  let restoring = Boolean(PREFS);
  const restored = (PREFS?.get({key: KEY}) || Promise.resolve({})).then(({value}) => {
    if (value && !remembered()) { try { localStorage.setItem(KEY, value); } catch { /* */ } }
    // A printer chosen before this copy existed gets one now.
    else if (!value && remembered()) PREFS.set({key: KEY, value: JSON.stringify(remembered())}).catch(() => {});
  }).catch(() => {}).finally(() => { restoring = false; });

  let parts = null;
  const load = async () => {
    if (!parts) {
      const [escpos, bluetooth] = await Promise.all([import('/print/escpos.js'), import('/print/ble.js')]);
      parts = {escpos, ble: bluetooth.ble};
    }
    return parts;
  };

  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  /* The plugin's native side takes a write only as a hex string ("1b2a00…");
     its JS wrapper converts for you, but this file calls the plugin directly,
     and a DataView arrives on the native side as nothing — "value required". */
  const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');

  /** The plugin speaks English; a cashier should not have to. */
  const thai = (error) => {
    const text = String(error?.message || error || '');
    if (/[฀-๿]/.test(text)) return text;
    if (/timeout/i.test(text)) return 'เครื่องพิมพ์ไม่ตอบ ตรวจว่าเปิดเครื่องอยู่และวางใกล้มือถือ';
    if (/not connected|disconnect/i.test(text)) return 'การเชื่อมต่อกับเครื่องพิมพ์หลุด';
    if (/133|GATT_ERROR|Connection failed/i.test(text)) return 'ต่อเครื่องพิมพ์ไม่ติด ปิดแล้วเปิดเครื่องพิมพ์ใหม่ แล้วลองอีกครั้ง';
    if (/not found|unknown device/i.test(text)) return 'หาเครื่องพิมพ์ที่เลือกไว้ไม่เจอ ลองค้นหาใหม่';
    if (/permission|denied|unauthori/i.test(text)) return 'แอปยังไม่ได้รับอนุญาตให้ใช้ Bluetooth';
    if (/powered off|disabled|not enabled/i.test(text)) return 'Bluetooth ของมือถือปิดอยู่';
    return 'พิมพ์ไม่สำเร็จ ลองอีกครั้ง';
  };

  // ----------------------------------------------------------- one at a time
  /* Every print, connect and change of printer runs through here, in order. */
  let line = Promise.resolve();
  const inTurn = (job) => {
    const run = line.catch(() => {}).then(job);
    line = run;
    return run;
  };

  // ------------------------------------------------------------- readiness
  /* initialize() once: on iOS each call builds a new Bluetooth manager, and a
     printer found by the old one cannot be connected by the new. */
  let initialized = null;
  const initialize = () => {
    initialized ??= Promise.race([
      BLE.initialize({androidNeverForLocation: true}),
      wait(10000).then(() => { throw new Error('Bluetooth ของมือถือไม่ตอบ ลองปิดแล้วเปิด Bluetooth ใหม่'); }),
    ]).catch((error) => { initialized = null; throw error; });
    return initialized;
  };

  /** null when this phone can reach a printer; otherwise what to say and how to fix it. */
  const blocker = async ({scanning = false} = {}) => {
    try { await initialize(); }
    catch { return {text: 'แอปยังไม่ได้รับอนุญาตให้ใช้ Bluetooth กดอนุญาตแล้วลองใหม่'}; }
    if (!(await BLE.isEnabled().catch(() => ({value: true}))).value) {
      return IOS
        ? {text: 'Bluetooth ของไอโฟนปิดอยู่ เปิดได้ที่ศูนย์ควบคุม (ปัดลงจากมุมขวาบน)'}
        : {text: 'Bluetooth ของมือถือปิดอยู่', fix: {label: 'เปิด Bluetooth', run: () => BLE.requestEnable()}};
    }
    if (scanning && SCAN_NEEDS_LOCATION) {
      const location = await BLE.isLocationEnabled().catch(() => ({value: true}));
      if (!location.value) {
        return {text: 'มือถือรุ่นนี้ต้องเปิด "ตำแหน่ง" ไว้ระหว่างค้นหาเครื่องพิมพ์ (เลือกเครื่องเสร็จแล้วปิดได้)',
          fix: {label: 'ไปเปิดตำแหน่ง', run: () => BLE.openLocationSettings()}};
      }
    }
    return null;
  };

  // --------------------------------------------------------------- the link
  let link = null;
  let piece = 180;
  let dropped = null;           // the disconnect listener for the current link
  let sheet = null;             // the printer sheet, once opened (declared here for the listener)
  const scan = {active: false, generation: 0};

  const forgetLink = async ({disconnect = true} = {}) => {
    const old = link;
    link = null;
    await Promise.resolve(dropped?.remove()).catch(() => {});
    dropped = null;
    if (disconnect && old) await BLE.disconnect({deviceId: old.id}).catch(() => {});
  };

  /* Only call from inside inTurn(). */
  const connect = async (device) => {
    const {ble} = await load();
    const problem = await blocker();
    if (problem) throw new Error(problem.text);
    await forgetLink();
    // iOS only connects to an id its Bluetooth manager has seen this session.
    if (IOS) await BLE.getDevices({deviceIds: [device.id]}).catch(() => {});
    /* Android's stack often refuses the first connection after the app was
       closed and reopened (GATT status 133) while it is still tearing down the
       last one. A short pause and another try is the known cure; nothing has
       been sent yet, so trying again cannot print anything twice. */
    let opened = null;
    for (let attempt = 1; !opened; attempt += 1) {
      try {
        opened = await ble.connect(device.id, {timeout: CONNECT_MS});
      } catch (error) {
        const flaky = /133|GATT_ERROR|Connection failed/i.test(String(error?.message || error));
        if (!flaky || attempt >= 3) throw error;
        await BLE.disconnect({deviceId: device.id}).catch(() => {});
        await wait(600 * attempt);
      }
    }
    /* The plugin asks for the largest MTU; what the printer agreed to is what
       one write may carry, less the three bytes of ATT header. */
    const mtu = (await BLE.getMtu({deviceId: device.id}).catch(() => ({value: 23}))).value || 23;
    piece = Math.max(20, Math.min(180, mtu - 3));
    link = {...opened, name: device.name};
    // A printer switched off, or asleep, drops the link without a word to us.
    // addListener hands back a listener handle that is awaitable but not a full Promise.
    dropped = await Promise.resolve(BLE.addListener(`disconnected|${device.id}`, () => {
      if (link?.id === device.id) link = null;
      if (sheet?.hasAttribute('data-open') && !scan.active) render();
    })).catch(() => null);
    return link;
  };

  const ensureLink = async () => {
    if (link) return link;
    const saved = remembered();
    if (!saved) throw new Error('ยังไม่ได้เลือกเครื่องพิมพ์ เลือกได้ที่ เพิ่มเติม → เครื่องพิมพ์ใบเสร็จ');
    return connect(saved);
  };

  /** Write one receipt; a failure carries how many pieces had already gone out. */
  const send = async (text) => {
    const {escpos} = await load();
    const pieces = escpos.chunks(escpos.drawReceipt(text, {paper: paperOf(remembered())}), piece);
    let sent = 0;
    try {
      for (const bytes of pieces) {
        /* On iOS a without-response write returns at once without waiting for
           room in the radio's queue, so every eighth piece goes with response
           as a checkpoint. A channel that cannot take without-response gets
           with-response every time. */
        const checkpoint = !link.withoutResponse || (IOS && link.withResponse && sent % 8 === 7);
        const write = checkpoint ? BLE.write : BLE.writeWithoutResponse;
        await write.call(BLE, {deviceId: link.id, service: link.service, characteristic: link.write, value: hex(bytes)});
        sent += 1;
        if (!checkpoint) await wait(IOS ? PAUSE_MS * 2 : PAUSE_MS);
      }
    } catch (error) {
      error.sent = sent;
      throw error;
    }
  };

  let lastFailed = null;        // the receipt that did not come out, for "พิมพ์ซ้ำ"
  let lastError = '';

  const PARTIAL = 'ใบเสร็จออกไม่ครบ การเชื่อมต่อหลุดระหว่างพิมพ์ ฉีกส่วนที่ออกมาทิ้งแล้วกดพิมพ์ซ้ำ';
  /** Send once; a failure after some pieces went out becomes the "torn receipt" error. */
  const attempt = async (text) => {
    try {
      await send(text);
    } catch (error) {
      await forgetLink();
      if (error.sent) throw Object.assign(new Error(PARTIAL, {cause: error}), {sent: error.sent});
      throw error;
    }
  };

  const print = (text, {test = false} = {}) => inTurn(async () => {
    await restored;
    try {
      await ensureLink();
      try {
        await attempt(text);
      } catch (first) {
        /* Nothing reached the printer: almost always a link that went stale
           while the till sat idle, so one fresh connection is safe. Once some
           of the receipt is out the printer is in the middle of an image, and
           sending it again from the top would print half of it twice and then
           noise. That one stops and is offered for reprinting instead. */
        if (first.sent) throw first;
        await ensureLink();
        await attempt(text);
      }
      if (lastFailed === text) lastFailed = null;
    } catch (error) {
      // A test page is not a receipt anyone is waiting for.
      if (!test) lastFailed = text;
      // The plugin's own words, kept for whoever helps the shop find out why.
      const cause = error?.cause || error;
      lastError = `${cause?.message || cause}${error?.sent ? ` (after ${error.sent} pieces)` : ''}`;
      throw new Error(thai(error));
    }
  });

  window.poswaiLocalPrinter = {
    /* Ready means "send it here": a remembered printer is connected on demand,
       so a till that restarted does not quietly fall back to the queue.
       print-agent-ui.js shows the one toast when this throws. */
    get ready() { return Boolean(link || remembered() || restoring); },
    /* At the till the receipt stays on screen with its own "ส่งไปเครื่องพิมพ์"
       button, which sends this same text again: that is the way to reprint. */
    print: (text) => print(text).catch((error) => {
      throw new Error(`${error.message} · กด "ส่งไปเครื่องพิมพ์" เพื่อพิมพ์ใบนี้อีกครั้ง`);
    }),
  };

  // --------------------------------------------------------------- the sheet
  let scrim = null;
  let busy = false;             // a printer row is being connected

  const el = (tag, props = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children.filter(Boolean));
    return node;
  };

  /* A scan has a generation: whatever a finished or abandoned scan still has
     in flight checks it is current before touching the sheet. */
  const endScan = () => {
    scan.generation += 1;
    if (scan.active) BLE.stopLEScan().catch(() => {});
    scan.active = false;
  };

  const close = () => {
    endScan();
    sheet?.removeAttribute('data-open');
    scrim?.removeAttribute('data-open');
  };

  const status = () => {
    const saved = remembered();
    if (link) return {tone: 'ok', title: link.name || 'เครื่องพิมพ์', text: 'เชื่อมต่ออยู่ · ใบเสร็จจะออกที่เครื่องนี้'};
    if (saved) return {tone: 'idle', title: saved.name, text: `กระดาษ ${paperOf(saved)} มม. · จำไว้แล้ว · จะเชื่อมให้เองตอนสั่งพิมพ์`};
    return {tone: 'none', title: 'ยังไม่ได้เลือกเครื่องพิมพ์', text: 'กดค้นหา แล้วเลือกเครื่องพิมพ์ Bluetooth ของร้าน'};
  };

  const button = (label, className, onClick) => {
    const node = el('button', {type: 'button', className, textContent: label});
    node.addEventListener('click', onClick);
    return node;
  };

  function render(message) {
    if (!sheet) return;
    const found = scan.active ? [...(sheet.querySelector('.app-printer-list')?.children || [])] : [];
    const now = status();
    const manage = window.POSWAI_APP.printer.mayManage();
    const actions = el('div', {className: 'app-printer-actions'});
    if (lastFailed && remembered()) {
      actions.append(button('พิมพ์ใบล่าสุดซ้ำ', 'app-printer-primary', (event) => reprint(event.currentTarget)));
    }
    if (manage) {
      const find = button(scan.active ? 'กำลังค้นหา…' : (remembered() ? 'ค้นหาเครื่องอื่น' : 'ค้นหาเครื่องพิมพ์'),
        `${lastFailed ? 'app-printer-secondary' : 'app-printer-primary'} app-printer-find`, startScan);
      find.disabled = scan.active || busy;
      actions.append(find);
    }
    if (remembered()) {
      if (manage) {
        const paper = el('div', {className: 'app-printer-paper', role: 'group'},
          el('span', {textContent: 'ขนาดกระดาษ'}));
        paper.setAttribute('aria-label', 'ขนาดกระดาษ');
        for (const mm of [58, 80]) {
          const choice = button(`${mm} มม.`, paperOf(remembered()) === mm ? 'is-on' : '', () => {
            remember({...remembered(), paper: mm});
            render({text: `ตั้งเป็นกระดาษ ${mm} มม. แล้ว ลองพิมพ์ใบทดสอบดูได้เลย`});
          });
          choice.setAttribute('aria-pressed', String(paperOf(remembered()) === mm));
          paper.append(choice);
        }
        actions.append(paper);
      }
      actions.append(button('พิมพ์ใบทดสอบ', 'app-printer-secondary', (event) => testPrint(event.currentTarget)));
      if (manage) {
        actions.append(button('เลิกใช้เครื่องนี้', 'app-printer-quiet', () => inTurn(async () => {
          endScan();
          await forgetLink();
          remember(null);
          lastFailed = null;
          render();
        })));
      }
    }
    const fix = message?.fix
      ? button(message.fix.label, '', async () => { await message.fix.run().catch(() => {}); render(); })
      : null;
    sheet.replaceChildren(...[
      el('div', {className: 'app-sheet-grip'}),
      el('h2', {textContent: 'เครื่องพิมพ์ใบเสร็จ'}),
      el('div', {className: `app-printer-status is-${now.tone}`},
        el('span', {className: 'app-printer-dot'}),
        el('div', {}, el('strong', {textContent: now.title}), el('small', {textContent: now.text}))),
      message ? el('p', {className: 'app-printer-message', textContent: message.text}, fix) : null,
      !manage && !remembered()
        ? el('p', {className: 'app-printer-hint', textContent: 'ให้แคชเชียร์ ผู้จัดการ หรือเจ้าของร้านเป็นคนเลือกเครื่องพิมพ์'})
        : null,
      el('div', {className: 'app-printer-list'}, ...found),
      actions,
    ].filter(Boolean));
  }

  const list = () => sheet?.querySelector('.app-printer-list');

  const choose = (device, row) => {
    if (busy) return;
    busy = true;
    endScan();
    for (const other of sheet.querySelectorAll('.app-printer-list button')) other.disabled = true;
    row.lastChild.textContent = `${device.name} · กำลังเชื่อม…`;
    inTurn(async () => {
      try {
        await connect(device);
        remember({id: device.id, name: device.name, paper: guessPaper(device.name)});
        navigator.vibrate?.(15);
        busy = false;
        render({text: `เชื่อมกับ ${device.name} แล้ว ลองพิมพ์ใบทดสอบได้เลย`});
      } catch (error) {
        busy = false;
        render({text: `เชื่อมไม่สำเร็จ: ${thai(error)}`});
      }
    });
  };

  async function startScan() {
    const problem = await blocker({scanning: true});
    if (problem) { render(problem); return; }
    endScan();
    const generation = scan.generation;
    const current = () => scan.generation === generation;
    scan.active = true;
    render();
    list()?.append(el('p', {className: 'app-printer-hint', textContent: 'เปิดเครื่องพิมพ์ไว้ใกล้ ๆ รายชื่อจะขึ้นมาเอง'}));
    const seen = new Set();
    const listener = await BLE.addListener('onScanResult', (result) => {
      const name = result.device?.name || result.localName;
      const id = result.device?.deviceId;
      if (!current() || !name || !id || seen.has(id)) return;
      seen.add(id);
      const row = el('button', {type: 'button', className: 'app-sheet-item'}, el('span', {textContent: name}));
      row.addEventListener('click', () => choose({id, name}, row));
      list()?.append(row);
    });
    try {
      await BLE.requestLEScan({allowDuplicates: false});
      await wait(SCAN_MS);
    } catch (error) {
      if (current()) render({text: `ค้นหาไม่สำเร็จ: ${thai(error)}`});
    } finally {
      await listener.remove();
      if (current()) {
        await BLE.stopLEScan().catch(() => {});
        scan.active = false;
        const again = sheet?.querySelector('.app-printer-find');
        if (again) { again.disabled = busy; again.textContent = 'ค้นหาอีกครั้ง'; }
        if (!seen.size) list()?.replaceChildren(el('p', {className: 'app-printer-hint',
          textContent: 'ไม่เจอเครื่องพิมพ์ ลองปิดแล้วเปิดเครื่องพิมพ์ แล้วกดค้นหาอีกครั้ง'}));
      }
    }
  }

  const TEST_RECEIPT = [
    '      ทดสอบเครื่องพิมพ์', '         POS WAI',
    '--------------------------------',
    'กะเพราหมูสับ ไข่ดาว     x1   ฿65.00',
    'ชาไทยเย็น              x2   ฿70.00',
    '--------------------------------',
    'รวม                       ฿135.00',
    '', '      ขอบคุณที่ใช้บริการ',
  ].join('\n');

  const run = async (node, text, done, options) => {
    node.disabled = true;
    node.textContent = 'กำลังพิมพ์…';
    try {
      await print(text, options);
      render({text: done});
    } catch (error) {
      render({text: error.message});
    }
  };
  const testPrint = (node) => run(node, TEST_RECEIPT, 'ส่งใบทดสอบแล้ว ดูที่เครื่องพิมพ์ได้เลย', {test: true});
  const reprint = (node) => run(node, lastFailed, 'พิมพ์ใบล่าสุดซ้ำแล้ว');

  const open = () => {
    if (!sheet) {
      sheet = el('div', {className: 'app-sheet app-printer-sheet'});
      sheet.setAttribute('role', 'dialog');
      sheet.setAttribute('aria-modal', 'true');
      sheet.setAttribute('aria-label', 'เครื่องพิมพ์ใบเสร็จ');
      scrim = el('div', {className: 'app-sheet-scrim'});
      scrim.addEventListener('click', close);
      document.body.append(sheet, scrim);
      document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
    }
    render();
    sheet.setAttribute('data-open', '');
    scrim.setAttribute('data-open', '');
  };

  window.POSWAI_APP.printer = {
    open,
    close,
    isOpen: () => Boolean(sheet?.hasAttribute('data-open')),
    get lastError() { return lastError; },
    /* The till's printer belongs to the till: a waiter or the kitchen may print
       through it, but choosing or forgetting it is the cashier's or above. */
    mayManage: () => ['cashier', 'manager', 'owner'].includes(window.poswaiAuth?.current?.role),
  };
})();
