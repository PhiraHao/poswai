/* POS WAI landing page. auth-ui.js decides when it shows; this file draws it and
   wires its buttons to the real actions. Markup is generated from the mockup geometry. */
(() => {
  const host = document.querySelector('.poswai-landing');
  if (!host) return;
  const LINE_OA = 'https://line.me/R/ti/p/@151jbyje';
  host.classList.add('lp');
  host.innerHTML = "<div class=\"lp-frame\"><div class=\"lp-stage\">\n  <div class=\"lp-head\">\n    <a class=\"lp-a lp-logo\" href=\"/\" aria-label=\"POS WAI หน้าแรก\"><img src=\"/assets/landing/logo.webp\" alt=\"POS WAI\" width=\"168\" height=\"104\"></a>\n    <button type=\"button\" class=\"lp-a lp-btn-login\" data-lp=\"login\"><span class=\"lp-t lp-t-btn-login\">เข้าสู่ระบบ</span></button>\n    <button type=\"button\" class=\"lp-a lp-btn-trial\" data-lp=\"trial\"><span class=\"lp-t lp-t-btn-trial\">ทดลองใช้ฟรี</span></button>\n  </div>\n  <nav class=\"lp-navrow\" aria-label=\"เมนูหลัก\"><button type=\"button\" class=\"lp-nav-hit is-active\" data-lp=\"home\" style=\"left:323px;width:74px\">หน้าแรก</button><span class=\"lp-t lp-t-nav-home\" aria-hidden=\"true\">หน้าแรก</span><button type=\"button\" class=\"lp-nav-hit\" data-lp=\"features\" style=\"left:428px;width:61px\">ฟีเจอร์</button><span class=\"lp-t lp-t-nav-features\" aria-hidden=\"true\">ฟีเจอร์</span><button type=\"button\" class=\"lp-nav-hit\" data-lp=\"price\" style=\"left:520px;width:49px\">ราคา</button><span class=\"lp-t lp-t-nav-price\" aria-hidden=\"true\">ราคา</span><button type=\"button\" class=\"lp-nav-hit\" data-lp=\"devices\" style=\"left:600px;width:72px\">อุปกรณ์</button><span class=\"lp-t lp-t-nav-devices\" aria-hidden=\"true\">อุปกรณ์</span><button type=\"button\" class=\"lp-nav-hit\" data-lp=\"stores\" style=\"left:703px;width:121px\">ร้านค้าตัวอย่าง</button><span class=\"lp-t lp-t-nav-stores\" aria-hidden=\"true\">ร้านค้าตัวอย่าง</span><button type=\"button\" class=\"lp-nav-hit\" data-lp=\"help\" style=\"left:855px;width:81px\">ช่วยเหลือ</button><span class=\"lp-t lp-t-nav-help\" aria-hidden=\"true\">ช่วยเหลือ</span><i class=\"lp-a lp-underline\" aria-hidden=\"true\"></i></nav>\n\n  <section class=\"lp-heroblock\" aria-labelledby=\"lpHeadline\">\n    <div class=\"lp-card lp-hero\" aria-hidden=\"true\"><img src=\"/assets/landing/hero-bg.webp\" alt=\"\" width=\"878\" height=\"651\"></div>\n    <i class=\"lp-a lp-badge\"><img class=\"lp-a lp-badge-icon\" src=\"/assets/landing/badge-icon.webp\" alt=\"\" width=\"44\" height=\"39\"><span class=\"lp-t lp-t-badge\">ระบบ POS สำหรับร้านอาหาร</span></i>\n    <h1 id=\"lpHeadline\" style=\"margin:0;font-size:inherit\"><span class=\"lp-t lp-t-line1\">เปิดร้านให้ไว</span><span class=\"lp-t lp-t-line2\">บริหารให้ว้าว</span></h1>\n    <img class=\"lp-a lp-swoosh\" src=\"/assets/landing/swoosh.webp\" alt=\"\" width=\"249\" height=\"22\">\n    <p class=\"lp-t lp-t-sub\">จากหน้าร้านถึงครัว ไปจนถึงยอดขาย จบใน POS WAI</p>\n    <img class=\"lp-a lp-mascot\" src=\"/assets/landing/hero-mascot.webp\" alt=\"น้อง POS WAI\" width=\"369\" height=\"453\">\n    <button type=\"button\" class=\"lp-a lp-cta\" data-lp=\"demo\"><span class=\"lp-t lp-t-cta\">ดูระบบ POS WAI</span><i class=\"lp-a lp-cta-arrow\"><svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M9 5l7 7-7 7\" fill=\"none\" stroke=\"#fff\" stroke-width=\"3.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></svg></i></button>\n    <div class=\"lp-feats\">\n      <div class=\"lp-feat\"><img class=\"lp-a lp-disc-1\" src=\"/assets/landing/feat-fast.webp\" alt=\"\" width=\"64\" height=\"64\"><strong class=\"lp-t lp-t-f1-title\">ใช้งานง่าย</strong><span class=\"lp-t lp-t-f1-sub\">เริ่มได้ทันที</span></div>\n      <i class=\"lp-a lp-divider lp-divider-1\" aria-hidden=\"true\"></i>\n      <div class=\"lp-feat\"><img class=\"lp-a lp-disc-2\" src=\"/assets/landing/feat-chef.webp\" alt=\"\" width=\"66\" height=\"66\"><strong class=\"lp-t lp-t-f2-title\">ครบทุกฟังก์ชัน</strong><span class=\"lp-t lp-t-f2-sub\">สำหรับร้านอาหาร</span></div>\n      <i class=\"lp-a lp-divider lp-divider-2\" aria-hidden=\"true\"></i>\n      <div class=\"lp-feat\"><img class=\"lp-a lp-disc-3\" src=\"/assets/landing/feat-chart.webp\" alt=\"\" width=\"66\" height=\"66\"><strong class=\"lp-t lp-t-f3-title\">ดูแลธุรกิจได้ทุกที่</strong><span class=\"lp-t lp-t-f3-sub\">ทั้งหน้าร้านและออนไลน์</span></div>\n    </div>\n  </section>\n\n  <div class=\"lp-shows\">\n    <div class=\"lp-card lp-show-pos\"><img src=\"/assets/landing/card-pos.webp\" alt=\"รับออเดอร์หน้าร้าน ใช้งานง่าย เร็ว ครบทุกเมนู บนแท็บเล็ต POS WAI\" width=\"752\" height=\"387\"></div>\n    <div class=\"lp-card lp-show-kitchen\"><img src=\"/assets/landing/card-kitchen.webp\" alt=\"ส่งออเดอร์เข้าครัว อัปเดตสถานะแบบเรียลไทม์\" width=\"403\" height=\"260\"></div>\n    <div class=\"lp-card lp-show-sales\"><img src=\"/assets/landing/card-sales.webp\" alt=\"ดูยอดขายและรายงาน เข้าใจธุรกิจได้ในพริบตา\" width=\"340\" height=\"257\"></div>\n  </div>\n\n  <div class=\"lp-tiles\" id=\"lpFeatures\">\n    <button type=\"button\" class=\"lp-card lp-tile lp-tile-order\" data-lp=\"tile-order\"><strong class=\"lp-t lp-t-t1-title\">สั่งอาหาร</strong><span class=\"lp-t lp-t-t1-sub1\">รับออเดอร์ได้ทั้งหน้าร้าน</span><span class=\"lp-t lp-t-t1-sub2\">และเดลิเวอรี เมนูสวย ใช้งานง่าย</span></button>\n    <button type=\"button\" class=\"lp-card lp-tile lp-tile-staff\" data-lp=\"tile-staff\"><strong class=\"lp-t lp-t-t2-title\">จัดการพนักงาน</strong><span class=\"lp-t lp-t-t2-sub1\">กำหนดสิทธิ์การใช้งาน</span><span class=\"lp-t lp-t-t2-sub2\">เช็กเวลาและประสิทธิภาพทีมได้ง่าย</span></button>\n    <button type=\"button\" class=\"lp-card lp-tile lp-tile-sales\" data-lp=\"tile-sales\"><strong class=\"lp-t lp-t-t3-title\">ดูยอดขาย</strong><span class=\"lp-t lp-t-t3-sub1\">สรุปรายงานครบถ้วน</span><span class=\"lp-t lp-t-t3-sub2\">ดูได้ทุกที่ ทุกเวลา</span></button>\n  </div>\n</div></div>";

  const fit = () => {
    const k = Math.min(window.innerWidth / 1672, 1.15);
    host.style.setProperty('--lp-k', String(window.innerWidth >= 1100 ? k : 1));
  };
  fit();
  window.addEventListener('resize', fit);

  const auth = () => window.poswaiAuth || {};
  /* The sample shop is a real shop on the server that refuses every change, so the
     tour shows the working screens without touching anyone's sales. */
  const sample = (tab) => {
    try { if (tab) sessionStorage.setItem('poswaiSampleTab', tab); } catch (_) { /* private browsing */ }
    location.href = '/?shop=demo';
  };
  try {
    const wanted = sessionStorage.getItem('poswaiSampleTab');
    if (wanted) {
      sessionStorage.removeItem('poswaiSampleTab');
      window.addEventListener('poswai:shop-ready', () => {
        setTimeout(() => document.querySelector(`.role-tab[onclick*="switchTab('${wanted}'"]`)?.click(), 60);
      }, { once: true });
    }
  } catch (_) { /* private browsing */ }

  /* Reference panels. Everything the top menu promises is answered on this page. */
  const PANELS = {
    price: ['ราคา', `
      <p class="lp-panel-lead">ทดลองใช้ฟรี 30 วันเต็ม ไม่ต้องผูกบัตร ยกเลิกเมื่อไหร่ก็ได้ ข้อมูลของร้านเป็นของร้าน</p>
      <div class="lp-plans">
        <article><h3>เริ่มต้น</h3><strong>ฟรี</strong><span>30 วันแรก</span>
          <ul><li>ทุกฟีเจอร์ ไม่จำกัด</li><li>1 สาขา พนักงานไม่จำกัด</li><li>รับออเดอร์ผ่าน QR ที่โต๊ะ</li></ul></article>
        <article class="lp-plan-main"><h3>ร้านเดียว</h3><strong>399 บาท</strong><span>ต่อเดือน</span>
          <ul><li>ทุกอย่างในแพ็กเริ่มต้น</li><li>รายงานยอดขายย้อนหลัง</li><li>สมาชิกและแต้มสะสม</li><li>ช่วยเหลือทาง LINE ในเวลาทำการ</li></ul></article>
        <article><h3>หลายสาขา</h3><strong>คุยกันได้</strong><span>ตามจำนวนสาขา</span>
          <ul><li>ทุกอย่างในแพ็กร้านเดียว</li><li>รวมรายงานทุกสาขา</li><li>ช่วยตั้งระบบให้ตอนเริ่ม</li></ul></article>
      </div>
      <p class="lp-panel-note">ราคานี้เป็นราคาแนะนำช่วงเปิดตัว ร้านที่เปิดใช้ในช่วงนี้ได้ราคานี้ตลอดอายุการใช้งาน</p>`],
    devices: ['อุปกรณ์ที่ใช้ได้', `
      <p class="lp-panel-lead">POS WAI ทำงานบนเบราว์เซอร์ ไม่ต้องลงโปรแกรม เครื่องที่ร้านมีอยู่แล้วใช้ได้เลย</p>
      <div class="lp-devices">
        <article><h3>แท็บเล็ตและมือถือ</h3><p>Android 8 ขึ้นไป หรือ iPad/iPhone iOS 14 ขึ้นไป เปิดผ่าน Chrome หรือ Safari แล้วกดเพิ่มลงหน้าจอหลัก ใช้เหมือนแอปได้เลย</p></article>
        <article><h3>คอมพิวเตอร์</h3><p>Windows, Mac หรือ Chromebook ใช้ Chrome, Edge หรือ Safari รุ่นปัจจุบัน เหมาะกับเครื่องแคชเชียร์และจอครัว</p></article>
        <article><h3>เครื่องพิมพ์ใบเสร็จ</h3><p>พิมพ์ผ่านหน้าต่างพิมพ์ของเบราว์เซอร์ ใช้ได้กับเครื่องพิมพ์ความร้อน 58 มม. และ 80 มม. ที่ต่อกับเครื่องนั้น</p></article>
        <article><h3>ลูกค้าสแกนสั่ง</h3><p>พิมพ์ QR ของแต่ละโต๊ะจากหน้าตั้งค่า ลูกค้าสแกนด้วยกล้องมือถือ เปิดเมนูได้ทันที ไม่ต้องโหลดแอป</p></article>
        <article><h3>อินเทอร์เน็ตหลุด</h3><p>หน้ารับออเดอร์ยังเปิดใช้ได้ รายการที่ค้างจะส่งขึ้นระบบให้เองเมื่อเน็ตกลับมา</p></article>
      </div>`],
    help: ['ช่วยเหลือ', `
      <p class="lp-panel-lead">เริ่มใช้งานได้ใน 10 นาที ทำตามลำดับนี้</p>
      <ol class="lp-steps">
        <li><strong>เปิดร้าน</strong> กดปุ่ม "ทดลองใช้ฟรี" ตั้งรหัสร้านและ PIN เจ้าของร้าน</li>
        <li><strong>ใส่เมนู</strong> เข้าแท็บ สต็อก กรอกชื่อเมนูและราคา ใส่สูตรวัตถุดิบถ้าต้องการให้ตัดสต็อกเอง</li>
        <li><strong>เพิ่มพนักงาน</strong> กดชื่อคุณมุมขวาบน เลือกเพิ่มพนักงาน ระบบจะให้รหัสพนักงานมาแจ้งเขา</li>
        <li><strong>ติด QR ที่โต๊ะ</strong> สร้าง QR รายโต๊ะจากหน้าตั้งค่าโต๊ะ แล้วพิมพ์ไปติด</li>
        <li><strong>เปิดขาย</strong> ออเดอร์เข้าจอครัวอัตโนมัติ แคชเชียร์รับเงินและปิดบิลได้ทันที</li>
      </ol>
      <h3 class="lp-panel-subtitle">คำถามที่พบบ่อย</h3>
      <dl class="lp-faq">
        <dt>ลืม PIN ทำอย่างไร</dt><dd>ให้เจ้าของร้านหรือผู้จัดการตั้ง PIN ใหม่ให้ในหน้าพนักงาน ถ้าลืม PIN เจ้าของร้าน ให้ทักหาทีมงานพร้อมรหัสร้าน</dd>
        <dt>ข้อมูลร้านปนกับร้านอื่นไหม</dt><dd>ไม่ปน แต่ละร้านเก็บข้อมูลแยกคนละชุด เข้าถึงได้เฉพาะคนที่มีรหัสร้านและ PIN ของร้านนั้น</dd>
        <dt>ย้ายข้อมูลจากระบบเดิมได้ไหม</dt><dd>ได้ ส่งไฟล์เมนูเดิมมาให้ทีมงานทาง LINE เราช่วยนำเข้าให้</dd>
        <dt>ยกเลิกแล้วข้อมูลหายไหม</dt><dd>แจ้งก่อนยกเลิก เราส่งไฟล์ข้อมูลร้านคุณกลับให้</dd>
      </dl>
      <p class="lp-panel-note">ติดปัญหาเร่งด่วน ทักทีมงานทาง LINE ได้ทุกวัน <a href="${LINE_OA}" target="_blank" rel="noopener">เปิดแชท LINE</a></p>`],
  };
  const panel = document.createElement('div');
  panel.className = 'lp-panel';
  panel.hidden = true;
  panel.innerHTML = `<div class="lp-panel-card" role="dialog" aria-modal="true" aria-labelledby="lpPanelTitle">
    <div class="lp-panel-head"><h2 id="lpPanelTitle" tabindex="-1"></h2>
    <button type="button" class="lp-panel-close" aria-label="ปิด">✕</button></div>
    <div class="lp-panel-body"></div></div>`;
  host.append(panel);
  const closePanel = () => { panel.hidden = true; };
  const openPanel = name => {
    const [title, body] = PANELS[name];
    panel.querySelector('#lpPanelTitle').textContent = title;
    panel.querySelector('.lp-panel-body').innerHTML = body;
    panel.hidden = false;
    panel.querySelector('#lpPanelTitle').focus();
  };
  panel.querySelector('.lp-panel-close').addEventListener('click', closePanel);
  panel.addEventListener('click', event => { if (event.target === panel) closePanel(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) closePanel(); });

  const actions = {
    login: () => auth().openLogin?.(),
    trial: () => auth().openSignup?.(),
    demo: () => sample('customer'),
    home: () => host.scrollTo({ top: 0, behavior: 'smooth' }),
    features: () => host.querySelector('#lpFeatures')?.scrollIntoView({ behavior: 'smooth', block: 'center' }),
    price: () => openPanel('price'),
    devices: () => openPanel('devices'),
    help: () => openPanel('help'),
    stores: () => sample('customer'),
    'tile-order': () => sample('customer'),
    'tile-staff': () => sample('staff'),
    'tile-sales': () => sample('analytics'),
  };
  host.addEventListener('click', (event) => {
    const target = event.target.closest('[data-lp]');
    if (!target || !host.contains(target)) return;
    event.preventDefault();
    actions[target.dataset.lp]?.();
  });
})();
