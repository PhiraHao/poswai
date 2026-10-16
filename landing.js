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
  const openLine = () => window.open(LINE_OA, '_blank', 'noopener');
  const demo = (tab) => {
    if (auth().preview && auth().enterPreview) auth().enterPreview(tab);
    else openLine();
  };
  const actions = {
    login: () => auth().openLogin?.(),
    trial: () => demo('customer'),
    demo: () => demo('customer'),
    home: () => host.scrollTo({ top: 0, behavior: 'smooth' }),
    features: () => host.querySelector('#lpFeatures')?.scrollIntoView({ behavior: 'smooth', block: 'center' }),
    price: openLine, devices: openLine, help: openLine,
    stores: () => demo('customer'),
    'tile-order': () => demo('customer'),
    'tile-staff': () => auth().openLogin?.(),
    'tile-sales': () => auth().openLogin?.(),
  };
  host.addEventListener('click', (event) => {
    const target = event.target.closest('[data-lp]');
    if (!target || !host.contains(target)) return;
    event.preventDefault();
    actions[target.dataset.lp]?.();
  });
})();
