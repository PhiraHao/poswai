/* เตือนแคชเชียร์เมื่อลูกค้าสั่งเองจาก QR ที่โต๊ะ (23 ต.ค. 69)
 *
 * ออเดอร์แบบนี้เคยขึ้นแต่จอครัว คนหน้าร้านไม่รู้เลยว่าโต๊ะไหนสั่งมา เห็นแค่โต๊ะ
 * เปลี่ยนเป็น "กำลังทาน" เงียบ ๆ ร้านเล็กที่ไม่มีคนยืนเฝ้าจอครัวจึงรู้ตัวอีกทีตอน
 * ลูกค้าเรียกหา
 *
 * ใช้ป้ายแบบเดียวกับปุ่มเรียกพนักงาน (service-call.js) เพื่อให้คนหน้าร้านอ่านที่เดียว
 * นับจากออเดอร์ที่ลูกค้าสั่งเองและยังไม่ปิดบิล — ปิดบิลแล้วป้ายหายเอง ไม่ต้องกดรับทราบ
 */
(() => {
  'use strict';
  const POLL_MS = 20000;
  const $ = id => document.getElementById(id);
  // ใช้แหล่งเดียวกับปุ่มเรียกพนักงาน (service-call.js) จะได้ไม่เพี้ยนกัน
  const branchId = () => window.poswaiAuth?.branchId
    || ((document.querySelector('#branchSelect')?.selectedIndex ?? 0) + 1);
  const signedIn = () => Boolean(window.poswaiAuth?.current);

  const nav = [...document.querySelectorAll('button[onclick]')]
    .find(button => (button.getAttribute('onclick') || '').includes("switchTab('cashier'"));
  if (!nav) return;
  let badge = $('guestOrderBadge');
  if (!badge) {
    badge = document.createElement('span');
    badge.id = 'guestOrderBadge';
    badge.className = 'service-nav-badge';
    badge.hidden = true;
    nav.append(badge);
  }

  let polling = false;
  let lastSeen = 0;
  async function refresh() {
    // หน้าซ่อนอยู่หรือยังไม่ได้เข้าสู่ระบบ = ไม่ต้องถามเซิร์ฟเวอร์ให้เปลือง
    if (polling || document.hidden || !navigator.onLine || !signedIn()) return;
    polling = true;
    try {
      const response = await fetch(`/api/orders/guest-waiting?branch_id=${branchId()}`, {cache: 'no-store'});
      if (!response.ok) return;              // สิทธิ์ไม่ถึงหรือเซิร์ฟเวอร์งอแง: ไม่ต้องรบกวนหน้าจอ
      const orders = (await response.json()).orders || [];
      badge.textContent = String(orders.length);
      badge.hidden = !orders.length;
      if (orders.length > lastSeen && typeof window.showToast === 'function') {
        const latest = orders[0];
        window.showToast(`ลูกค้าสั่งเองที่โต๊ะ ${latest.table_no} · ${latest.order_no}`);
      }
      lastSeen = orders.length;
      await refreshKitchen();
    } catch { /* ออฟไลน์: ป้ายค้างค่าเดิมไว้ ดีกว่าลบทิ้งแล้วคนหน้าร้านนึกว่าไม่มีออเดอร์ */ }
    finally { polling = false; }
  }

  /* สถานะครัวต่อโต๊ะ เพื่อให้การ์ดโต๊ะฝั่งแคชเชียร์พูดภาษาเดียวกับจอครัว
     เดิมโต๊ะที่มียอดค้างขึ้นว่า "ทานอยู่" ทันที ทั้งที่ครัวยังไม่ได้เริ่มทำ
     สถานะตั๋วมีแค่ held / queued / ready — queued คือที่จอครัวเรียกว่ากำลังทำ */
  async function refreshKitchen() {
    try {
      const response = await fetch(`/api/kds?branch_id=${branchId()}`, {cache: 'no-store'});
      if (!response.ok) return;
      const map = {};
      for (const ticket of (await response.json()).tickets || []) {
        const table = String(ticket.table_no ?? '');
        if (!table || ticket.status === 'ready' && map[table]) continue;
        // ยังทำไม่เสร็จสักใบ = ทั้งโต๊ะยังไม่พร้อมเสิร์ฟ จึงให้สถานะที่ "แย่ที่สุด" ชนะ
        const rank = {ready: 0, held: 1, queued: 2};
        const now = ticket.status === 'queued' ? 'cooking' : ticket.status;
        const nowRank = rank[ticket.status] ?? 0;
        const wasRank = rank[map[table] === 'cooking' ? 'queued' : map[table]] ?? -1;
        if (nowRank > wasRank) map[table] = now;
      }
      window.poswaiTableKitchen = map;
      if (typeof window.renderCashierView === 'function') window.renderCashierView();
    } catch { /* ออฟไลน์: คงสถานะเดิมไว้ ดีกว่าแสดงข้อมูลที่เดาเอง */ }
  }

  refresh();
  setInterval(refresh, POLL_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('poswai:order-placed', refresh);
})();
