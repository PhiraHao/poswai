/* Printing straight from the device the shop is already holding.

   Inside the POS WAI app this page gets Bluetooth, which a page in Safari
   never does, so the till can drive the receipt printer itself: no computer
   in the back, no second app, no queue to wait on. The queue stays for the
   other way round — a phone at the counter printing for a printer that some
   other device is holding.

   The encoder and the Bluetooth plumbing are the same files the standalone
   print app uses, served from /print/, so there is one copy of each. */
(() => {
  const inApp = () => Boolean(window.Capacitor?.Plugins?.BluetoothLe);
  const inChrome = () => Boolean(navigator.bluetooth);
  if (!inApp() && !inChrome()) return;          // a plain browser: the queue it is

  const auth = () => window.poswaiAuth || {};
  const mayPrint = () => ['cashier', 'manager', 'owner'].includes(auth().current?.role);
  const REMEMBERED = 'poswaiLocalPrinter';

  let parts = null;                             // the two modules, loaded once
  let link = null;

  const load = async () => {
    if (!parts) {
      const [escpos, bluetooth] = await Promise.all([
        import('/print/escpos.js'), import('/print/ble.js'),
      ]);
      parts = {escpos, ble: bluetooth.ble, kind: bluetooth.kind};
    }
    return parts;
  };

  const remember = value => {
    try {
      if (value) localStorage.setItem(REMEMBERED, JSON.stringify(value));
      else localStorage.removeItem(REMEMBERED);
    } catch (_) { /* private browsing */ }
  };
  const remembered = () => {
    try { return JSON.parse(localStorage.getItem(REMEMBERED) || 'null'); }
    catch (_) { return null; }
  };

  const style = document.createElement('style');
  style.textContent = [
    '.pdirect{display:flex;align-items:center;gap:10px;flex-wrap:wrap;',
    'border:1px solid #e9edf2;border-radius:12px;padding:11px 13px;margin:10px 0 0}',
    '.pdirect strong{font-size:.9rem}.pdirect small{display:block;color:#6b7280;font-size:.76rem}',
    '.pdirect .who{flex:1;min-width:150px}',
  ].join('');
  document.head.append(style);

  const box = document.createElement('div');
  box.className = 'pdirect';
  box.hidden = true;
  const who = document.createElement('div');
  who.className = 'who';
  const title = document.createElement('strong');
  title.textContent = 'เครื่องพิมพ์ของเครื่องนี้';
  const note = document.createElement('small');
  who.append(title, note);
  const connect = document.createElement('button');
  connect.type = 'button';
  connect.className = 'btn btn-sm btn-primary';
  const test = document.createElement('button');
  test.type = 'button';
  test.className = 'btn btn-sm btn-outline';
  test.textContent = 'พิมพ์ใบทดสอบ';
  box.append(who, connect, test);

  const show = () => {
    note.textContent = link
      ? `${link.name || 'เชื่อมต่อแล้ว'} · ใบเสร็จจะออกที่เครื่องนี้ทันที`
      : 'เชื่อมเครื่องพิมพ์ Bluetooth แล้วสั่งพิมพ์ได้จากเครื่องนี้เลย ไม่ต้องมีคอมในร้าน';
    connect.textContent = link ? 'เปลี่ยนเครื่องพิมพ์' : 'เชื่อมเครื่องพิมพ์';
    test.disabled = !link;
  };

  const print = async text => {
    const {escpos, ble} = await load();
    await ble.write(link, escpos.chunks(escpos.drawReceipt(text)));
  };

  connect.addEventListener('click', async () => {
    const was = connect.textContent;
    connect.disabled = true;
    connect.textContent = 'กำลังค้นหา…';
    try {
      const {ble, kind} = await load();
      if (kind() === 'web') {
        link = await ble.pick();
      } else {
        /* In the app the scan hands back a list; the first printer-shaped
           thing the shop picks is almost always the only one switched on. */
        const found = [];
        await ble.scan(device => found.push(device));
        if (!found.length) throw new Error('ไม่เจอเครื่องพิมพ์ ลองเปิด-ปิดเครื่องพิมพ์แล้วลองใหม่');
        const names = found.map((device, index) => `${index + 1}. ${device.name}`).join('\n');
        const answer = prompt(`เจอเครื่องเหล่านี้ พิมพ์หมายเลขที่จะใช้\n\n${names}`, '1');
        const chosen = found[Number(answer) - 1];
        if (!chosen) return;
        link = {...(await ble.connect(chosen.id)), name: chosen.name};
      }
      remember({name: link.name});
      window.showToast?.(`✅ เชื่อมกับ ${link.name || 'เครื่องพิมพ์'} แล้ว`);
    } catch (error) {
      window.showToast?.(`⚠️ ${error.message}`);
    } finally {
      connect.disabled = false;
      connect.textContent = was;
      show();
    }
  });

  test.addEventListener('click', async () => {
    try {
      await print([
        '   ทดสอบเครื่องพิมพ์', '   POS WAI',
        '--------------------------------',
        'กะเพราหมูสับ      x1   ฿50.00',
        '--------------------------------',
        'รวม                     ฿50.00',
        '   ขอบคุณที่ใช้บริการครับ',
      ].join('\n'));
      window.showToast?.('✅ ส่งใบทดสอบแล้ว');
    } catch (error) { window.showToast?.(`⚠️ ${error.message}`); }
  });

  /* What the rest of the page asks before falling back to the queue. */
  window.poswaiLocalPrinter = {
    get ready() { return Boolean(link); },
    print,
  };

  const mount = () => {
    const panel = document.querySelector('.prn-panel #prnList');
    if (panel && box.parentElement !== panel.parentElement) panel.before(box);
    box.hidden = !mayPrint();
    if (!box.hidden && !link && remembered()) {
      note.textContent = `${remembered().name} · กดเชื่อมเครื่องพิมพ์อีกครั้งเพื่อใช้งาน`;
    }
  };

  window.addEventListener('poswai:auth-changed', () => { mount(); show(); });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { mount(); show(); });
  } else { mount(); show(); }
})();
