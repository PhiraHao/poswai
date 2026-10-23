/* The one screen: pick a printer, hold the shop's key, print what arrives. */
import {chunks, drawReceipt} from './escpos.js';
import {ble, kind} from './ble.js';
import {Queue} from './queue.js';

const $ = id => document.getElementById(id);
const POLL_MS = 3000;
const RETRY_MS = 15000;

const settings = {
  read() {
    try { return JSON.parse(localStorage.getItem('poswaiPrinter') || '{}'); }
    catch (_) { return {}; }
  },
  write(values) {
    try { localStorage.setItem('poswaiPrinter', JSON.stringify(values)); } catch (_) { /* full */ }
  },
};

let saved = settings.read();
let link = null;          // the open Bluetooth connection
let running = false;
let timer = null;

/* ---- what the shopkeeper sees ----------------------------------------- */
function say(message, bad = false) {
  const list = $('log');
  list.querySelector('.quiet')?.remove();
  const row = document.createElement('li');
  if (bad) row.className = 'bad';
  const when = document.createElement('time');
  when.textContent = new Date().toLocaleTimeString('th-TH', {hour: '2-digit', minute: '2-digit'});
  const what = document.createElement('span');
  what.textContent = message;
  row.append(when, what);
  list.prepend(row);
  while (list.children.length > 40) list.lastElementChild.remove();
}

function lamp(text, state = '') {
  const light = $('lamp');
  light.textContent = text;
  light.className = `lamp ${state}`;
}

function refresh() {
  const ready = Boolean(saved.shop && saved.key && link);
  $('run').disabled = !ready;
  $('testPrint').disabled = !link;
  $('printer').textContent = link ? (link.name || saved.printerName || 'เชื่อมต่อแล้ว')
    : (saved.printerName ? `${saved.printerName} (ยังไม่ได้เชื่อม)` : 'ยังไม่ได้เลือก');
  $('state').textContent = running ? 'กำลังรับงานพิมพ์'
    : !link ? 'เลือกเครื่องพิมพ์ก่อน'
    : !saved.shop || !saved.key ? 'ใส่ชื่อร้านและกุญแจก่อน'
    : 'พร้อมแล้ว กดเริ่มได้เลย';
  $('run').textContent = running ? 'หยุดรับงานพิมพ์' : 'เริ่มรับงานพิมพ์';
  $('run').classList.toggle('stop', running);
}

/* ---- printing ---------------------------------------------------------- */
async function printText(text) {
  const bytes = drawReceipt(text);
  await ble.write(link, chunks(bytes));
}

/* ---- the loop ---------------------------------------------------------- */
async function tick() {
  if (!running) return;
  const queue = new Queue({baseUrl: saved.base, shop: saved.shop, key: saved.key});
  let wait = POLL_MS;
  try {
    const job = await queue.next();
    if (job) {
      for (let copy = 0; copy < Math.max(1, job.copies || 1); copy++) {
        await printText(job.body);
      }
      await queue.done(job.job_id);
      say(`พิมพ์แล้ว: ${job.title || job.job_id}`);
      wait = 200;                       // another one may be waiting behind it
    }
    lamp('กำลังรับงาน', 'on');
  } catch (error) {
    wait = RETRY_MS;
    lamp('ติดปัญหา', 'bad');
    say(error.status === 401
      ? 'กุญแจใช้ไม่ได้ ตรวจกุญแจกับชื่อร้านอีกครั้ง'
      : `ผิดพลาด: ${error.message}`, true);
  }
  if (running) timer = setTimeout(tick, wait);
}

/* ---- buttons ----------------------------------------------------------- */
$('save').addEventListener('click', () => {
  saved = {
    ...saved,
    base: $('base').value.trim() || 'https://poswai.zzaxstudio.com',
    shop: $('shop').value.trim().toLowerCase(),
    key: $('key').value.trim(),
  };
  settings.write(saved);
  say('บันทึกการตั้งค่าแล้ว');
  refresh();
});

$('find').addEventListener('click', async () => {
  const list = $('found');
  list.replaceChildren();
  list.hidden = true;
  try {
    if (kind() === 'web') {
      /* The browser runs the picker itself, so there is no list to draw. */
      link = await ble.pick();
      saved = {...saved, printerName: link.name};
      settings.write(saved);
      say(`เชื่อมกับ ${link.name || 'เครื่องพิมพ์'} แล้ว`);
      refresh();
      return;
    }
    if (kind() === 'none') { say('เครื่องนี้ใช้ Bluetooth ไม่ได้', true); return; }
    list.hidden = false;
    say('กำลังค้นหา… เปิดเครื่องพิมพ์ไว้ใกล้ ๆ');
    await ble.scan(device => {
      const row = document.createElement('li');
      const pick = document.createElement('button');
      pick.textContent = device.name;
      pick.addEventListener('click', async () => {
        try {
          link = {...(await ble.connect(device.id)), name: device.name};
          saved = {...saved, printerId: device.id, printerName: device.name};
          settings.write(saved);
          list.hidden = true;
          say(`เชื่อมกับ ${device.name} แล้ว`);
          refresh();
        } catch (error) { say(error.message, true); }
      });
      row.append(pick);
      list.append(row);
    });
    if (!list.children.length) say('ไม่เจอเครื่องพิมพ์ ลองเปิด-ปิดเครื่องพิมพ์แล้วค้นใหม่', true);
  } catch (error) {
    say(error.message, true);
  }
});

$('testPrint').addEventListener('click', async () => {
  try {
    await printText([
      '   ทดสอบเครื่องพิมพ์',
      '   POS WAI',
      '--------------------------------',
      'กะเพราหมูสับ      x1   ฿50.00',
      'ชาเย็น            x2   ฿50.00',
      '--------------------------------',
      'รวม                    ฿100.00',
      '   ขอบคุณที่ใช้บริการครับ',
    ].join('\n'));
    say('ส่งใบทดสอบแล้ว');
  } catch (error) { say(error.message, true); }
});

$('run').addEventListener('click', () => {
  running = !running;
  if (running) {
    say('เริ่มรับงานพิมพ์');
    lamp('กำลังรับงาน', 'on');
    tick();
  } else {
    clearTimeout(timer);
    lamp('พัก');
    say('หยุดรับงานพิมพ์');
  }
  refresh();
  window.Capacitor?.Plugins?.KeepAwake?.[running ? 'keepAwake' : 'allowSleep']?.();
});

/* ---- opening ----------------------------------------------------------- */
$('base').value = saved.base || 'https://poswai.zzaxstudio.com';
$('shop').value = saved.shop || '';
$('key').value = saved.key || '';
refresh();
if (kind() === 'none') say('เครื่องนี้ไม่มี Bluetooth ที่แอปใช้ได้', true);
