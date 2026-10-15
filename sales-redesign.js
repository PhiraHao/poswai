function foodIconFor(id) { return `/assets/${[8,9,10,12].includes(Number(id)) ? "drink" : Number(id)===11 ? "dessert" : "food"}-icon.svg`; }
/* Sales workspace: visual enhancement around existing ordering and payment actions. */
(() => {
  const $ = (s, root = document) => root.querySelector(s);
  function disclosure(node, title, className = '') {
    if (!node || node.closest('.sales-disclosure')) return;
    const box = document.createElement('details');
    box.className = `sales-disclosure ${className}`;
    const summary = document.createElement('summary');
    summary.textContent = title;
    box.append(summary);
    node.before(box);
    box.append(node);
  }
  function label(selector, value) { const el = $(selector); if (el) el.textContent = value; }
  function enhanceMenu() {
    const grid = $('#customerMenuGrid');
    if (!grid) return;
    grid.classList.toggle('editing-menu', Boolean(state.quickEditMode));
    grid.querySelectorAll('.menu-item').forEach(card => {
      const menu = DEFAULT_MENU.find(m => String(m.id) === card.dataset.menuId);
      if (!menu) return;
      card.draggable = Boolean(state.quickEditMode);
      const media = card.querySelector('img, .menu-emoji');
      if (media) {
        const img = document.createElement('img');
        img.className = 'dish-photo';
        img.alt = menu.name;
        img.loading = 'lazy';
        img.src = foodIconFor(menu.id);
        img.onerror = () => { img.onerror = null; img.src = '/assets/menu-placeholder.svg'; };
        media.replaceWith(img);
      }
      const name = card.querySelector('.menu-name');
      if (name) name.textContent = name.textContent.replace(/^📌\s*/, '');
      const add = card.querySelector('.menu-footer button');
      if (add && !add.disabled) { add.textContent = '+'; add.setAttribute('aria-label', `เลือก ${menu.name}`); add.title = `เลือก ${menu.name}`; }
      const ribbon = card.querySelector('.promo-ribbon');
      if (ribbon) { ribbon.textContent = menu.isComboStep ? 'ชุดสุดคุ้ม' : menu.isStar ? 'ขายดี' : 'โปรโมชัน'; }
    });
  }
  const originalMenu = renderCustomerMenu;
  renderCustomerMenu = function(...args) { const result = originalMenu.apply(this, args); enhanceMenu(); return result; };
  function enhanceCart() {
    const empty = $('#cartItemsContainer > p');
    if (empty) empty.innerHTML = '<svg aria-hidden="true"><use href="/icons.svg#menu"></use></svg><strong>เลือกเมนูที่ชอบได้เลย</strong><span>รายการอาหารจะแสดงที่นี่</span>';
    $('#customerCartPanel')?.classList.toggle('cart-is-empty', state.cart.length === 0);
  }
  const originalCart = renderCart;
  renderCart = function(...args) { const result = originalCart.apply(this, args); enhanceCart(); return result; };
  const customer = $('#view-customer');
  if (customer) {
    const toolbar = customer.querySelector('.liff-header');
    toolbar?.classList.add('order-toolbar');
    const tablePicker = $('#customerTableSelect');
    const cartHeader = $('#customerCartPanel .card-header');
    if (tablePicker && cartHeader) { tablePicker.classList.add('cart-table-picker'); cartHeader.after(tablePicker); }
    const queueButton = $('button[onclick="issueSmartQueue()"]');
    const serviceContent = $('#serviceActions .service-actions-buttons');
    if (queueButton && serviceContent) serviceContent.append(queueButton);
    if (toolbar) toolbar.hidden = true;
    const service = $('#serviceActions');
    if (service) { document.querySelector('#customerCartPanel')?.append(service); service.removeAttribute('open'); const summary = service.querySelector('summary'); if(summary) summary.textContent = 'บริการที่โต๊ะ'; }
    const search = $('#menuSearchInput');
    if (search) { search.placeholder = 'ค้นหาเมนูอาหาร…'; search.closest('.card').classList.add('menu-catalog'); }
    label('#categoryPills button:nth-child(2)', 'ชุดสุดคุ้ม');
    label('#categoryPills button:nth-child(3)', 'ขายดี');
    const title = $('#customerCartPanel .card-title');
    if (title) title.innerHTML = 'ตะกร้า <span class="cart-count"><span id="cartCountLabel">0</span></span>';
    const memberRow = $('#custMemberPhone')?.parentElement.parentElement;
    disclosure(memberRow, 'สมาชิกและคูปอง');
    const note = $('#orderNoteInput');
    if (note) {
      const group = document.createElement('div');
      note.previousElementSibling?.remove();
      note.before(group); group.append(note);
      disclosure(group, 'เพิ่มหมายเหตุ');
    }
    const total = $('#cartTotalLabel');
    if(total) total.previousElementSibling.textContent = 'ยอดรวม';
    label('#customerCartPanel button[onclick="submitOrderFromCustomer()"]', 'ส่งออเดอร์');
    label('#customerCartPanel button[onclick="clearCart()"]', 'ล้าง');
    const bill = $('#customerActiveOrdersList')?.closest('.card');
    disclosure(bill, 'ดูบิลของโต๊ะ');
    label('#customerCheckoutSection > button', 'ชำระด้วยพร้อมเพย์');
    label('button[onclick="issueSmartQueue()"]', 'รับบัตรคิว');
  }
  const cashier = $('#view-cashier');
  if (cashier) {
    cashier.classList.add('sales-cashier');
    const shift = $('#shiftSummaryText')?.closest('.card');
    disclosure(shift, 'กะและลิ้นชักเงินสด');
    const tableCard = $('#cashierTablesGrid')?.closest('.card');
    if (tableCard) { tableCard.classList.add('table-map-panel'); label('#view-cashier .table-map-panel .card-title', 'ผังโต๊ะ'); }
    const tableSetup = $('#newTableZoneInput')?.parentElement;
    disclosure(tableSetup, 'จัดการโต๊ะ');
    const quick = $('#barcodeInput')?.closest('.card');
    disclosure(quick, 'เพิ่มรายการให้โต๊ะ');
    const barcode = $('#barcodeInput'); if (barcode) barcode.placeholder = 'สแกนหรือกรอกรหัสสินค้า';
    const bill = $('#cashierBillDetails')?.closest('.card');
    bill?.classList.add('checkout-panel');
    const title = bill?.querySelector('.card-title');
    if (title) title.innerHTML = 'ชำระเงิน · <span id="selectedTableHeader">โต๊ะ 1</span>';
    const tax = $('#enableVatCheckbox')?.parentElement.parentElement.parentElement;
    disclosure(tax, 'ภาษีและแบ่งชำระ');
    const receipt = $('#thermalReceiptPreview')?.closest('.card');
    disclosure(receipt, 'ใบเสร็จและเครื่องพิมพ์');
    cashier.querySelectorAll('button[disabled]').forEach(btn => { btn.hidden = true; });
    const payment = $('button[onclick="showCashierPromptPayModal()"]')?.parentElement;
    payment?.classList.add('payment-options');
    if (payment?.previousElementSibling) payment.previousElementSibling.textContent = 'ช่องทางชำระเงิน';
    label('button[onclick="showCashierPromptPayModal()"]', 'พร้อมเพย์');
    cashier.querySelectorAll('.payment-options button').forEach(b => {
      if(b.textContent.includes('เงินสด')) b.textContent = 'เงินสด';
      else if(b.textContent.includes('เครดิต')) b.textContent = 'บัตรเครดิต / เดบิต';
      else if(b.textContent.includes('e-Wallet')) b.textContent = 'e-Wallet';
      else if(b.textContent.includes('ใบแจ้งหนี้')) b.textContent = 'พิมพ์ใบแจ้งหนี้';
      else if(b.textContent.includes('ใบกำกับ')) b.textContent = 'ใบกำกับภาษี';
    });
  }
  enhanceMenu(); renderCart();
})();



/* Refined menu order, cart controls and choice dialogs. */
(() => {
  const $ = s => document.querySelector(s);
  const shortName = m => state.lang === 'TH' ? ({101:'เซตอิ่มคุ้ม',102:'ชุดครอบครัว'}[m.id] || m.name) : state.lang === 'EN' ? (m.nameEn || m.name) : (m.nameCn || m.name);
  const previousMenu = renderCustomerMenu;
  function refineCards() {
    const grid = $('#customerMenuGrid');
    if (!grid) return;
    const cards = [...grid.children];
    if (!state.quickEditMode) cards.sort((a,b) => Number(Number(a.dataset.menuId) >= 100) - Number(Number(b.dataset.menuId) >= 100)).forEach(card => grid.append(card));
    cards.forEach(card => {
      const m = DEFAULT_MENU.find(x => String(x.id) === card.dataset.menuId);
      if (!m) return;
      const name = card.querySelector('.menu-name'); if(name) name.textContent = shortName(m);
      if (!state.quickEditMode && !m.origPrice && !m.isComboStep) card.querySelector('.promo-ribbon')?.remove();
    });
  }
  renderCustomerMenu = function(...args) { const result = previousMenu.apply(this,args); refineCards(); return result; };
  const previousCart = renderCart;
  function button(text, accessibleName, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.setAttribute('aria-label', accessibleName); node.addEventListener('click', action); return node;
  }
  function cartRows() {
    const container = $('#cartItemsContainer');
    if (!container || !state.cart.length) return;
    container.replaceChildren();
    state.cart.forEach((item,index) => {
      const menu = DEFAULT_MENU.find(x => x.id === item.id);
      const row = document.createElement('article'); row.className = 'sales-cart-row';
      const photo = document.createElement('img'); photo.alt=''; photo.src=foodIconFor(item.id);
      photo.onerror=()=>{photo.onerror=null;photo.src='/assets/menu-placeholder.svg';};
      const detail = document.createElement('div'); detail.className='sales-cart-detail';
      const title = document.createElement('strong'); title.textContent=menu ? shortName(menu) : item.name;
      const description = document.createElement('small');
      const originalName = menu?.name || '';
      let modifiers = item.name.startsWith(originalName) ? item.name.slice(originalName.length).trim() : (item.name.includes('[') ? item.name.slice(item.name.indexOf('[')) : '');
      if(item.courseMode === 'HOLD') modifiers += `${modifiers ? ' · ' : ''}เสิร์ฟภายหลัง`;
      description.textContent=modifiers.replace(/^[([]|[)\]]$/g,'');
      const controls=document.createElement('div'); controls.className='sales-qty-control';
      const change = delta => {
        if(delta>0 && menu && (menu.soldOut || (typeof menu.quota === 'number' && state.cart.filter(x=>x.id===item.id).reduce((sum,x)=>sum+x.qty,0)>=menu.quota))) { showToast('จำนวนที่เลือกครบตามที่ร้านมีแล้ว'); return; }
        item.qty += delta;
        if(item.qty<=0) state.cart.splice(index,1);
        renderCart();
      };
      controls.append(button('−',`ลด ${title.textContent}`,()=>change(-1)));
      const qty=document.createElement('span'); qty.textContent=String(item.qty); controls.append(qty);
      controls.append(button('+',`เพิ่ม ${title.textContent}`,()=>change(1)));
      detail.append(title); if(modifiers) detail.append(description); detail.append(controls);
      const end=document.createElement('div'); end.className='sales-cart-end';
      const price=document.createElement('strong'); price.textContent=`฿${(item.price*item.qty).toLocaleString('th-TH',{maximumFractionDigits:2})}`;
      const remove=button('×',`ลบ ${title.textContent}`,()=>{state.cart.splice(index,1);renderCart();}); remove.className='sales-remove';
      end.append(price,remove); row.append(photo,detail,end);container.append(row);
    });
  }
  renderCart=function(...args){const result=previousCart.apply(this,args);cartRows();return result;};
  function simplifyDialogs() {
    const labels = document.querySelectorAll('#modifierModalBackdrop .label');
    if(labels[1]) labels[1].textContent='ตัวเลือกเพิ่มเติม';
    if(labels[2]) labels[2].textContent='จังหวะเสิร์ฟ';
    const course=$('#modCourseSelect'); if(course) { course.options[0].textContent='ทำทันที';course.options[1].textContent='เสิร์ฟภายหลัง'; }
    const add=$('#modifierModalBackdrop button[onclick="confirmAddWithModifiers()"]'); if(add)add.textContent='เพิ่มลงตะกร้า';
    const title=$('#modModalMenuTitle'); if(title)title.textContent=title.textContent.replace(/^[^\p{L}\p{N}]+/u,'');
    const group=$('#modModalOptionGroupLabel'); if(group)group.textContent=group.textContent.replace(/^[^\p{L}]+/u,'').replace(/:$/,'');
    const combo=$('#comboModalBackdrop .modal-card');
    if(combo){
      combo.firstElementChild.firstElementChild.textContent='จัดเซตอิ่มคุ้ม · ฿129';
      combo.children[1].textContent='เลือกจานหลักและเครื่องดื่มที่ชอบ';
      const list=combo.querySelectorAll(':scope > label');
      ['จานหลัก','เครื่องดื่ม','ของหวานเพิ่มเติม'].forEach((text,i)=>{if(list[i])list[i].textContent=text;});
      combo.querySelectorAll('option').forEach(o=>{if(o.value==='NONE')o.textContent='ไม่เพิ่มของหวาน';else {const parts=o.value.split('|'); o.textContent=parts[1]+(parts[2]?` (+฿${parts[2]})`:'');}});
      combo.querySelector('button[onclick="confirmAddStepCombo()"]').textContent='เพิ่มเซตลงตะกร้า';
    }
  }
  const previousClick=onClickMenuCard;
  onClickMenuCard=function(...args){const result=previousClick.apply(this,args);simplifyDialogs();return result;};
  refineCards();cartRows();simplifyDialogs();
})();

const cartJump=document.querySelector(".mobile-cart-dock button"); if(cartJump) cartJump.onclick=()=>document.getElementById("customerCartPanel").scrollIntoView({behavior:"instant",block:"start"});
