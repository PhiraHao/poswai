/* Shared navigation/chrome, with existing application state and actions intact. */
(() => {
  const logo='<svg aria-hidden="true" viewBox="0 0 32 32"><path d="M5 13h22c0 7-4 12-11 12S5 20 5 13ZM10 28h12M9 8h14M12 4h9"/></svg>';
  document.querySelectorAll('.nav-brand-mark,.brand-symbol').forEach(n=>n.innerHTML=logo);
  document.querySelectorAll('.role-tab').forEach(n=>n.querySelector('small')?.remove());
  document.querySelector('.nav-footer span:last-child').textContent='โหมดตัวอย่าง';
  const branches=document.getElementById('branchSelect');
  [...branches.options].forEach(o=>o.textContent=o.textContent.replace(/^📍\s*/,'').replace(/^🏭\s*/,'').replace('สาขา 1: ','').replace('สาขา 2: ','').replace(' (Central)',''));
  document.querySelectorAll('[id^="topLangBtn"],[id^="langBtn"]').forEach(b=>b.textContent=b.id.endsWith('TH')?'ไทย':b.id.endsWith('EN')?'EN':'中文');
  document.getElementById('netStatusText').textContent='ออนไลน์';
  const badge=document.getElementById('syncQueueBadge');
  badge.firstChild.textContent='รอส่ง ';
  const sync=()=>badge.classList.toggle('is-empty',document.getElementById('syncCount').textContent==='0');sync();
  new MutationObserver(sync).observe(document.getElementById('syncCount'),{childList:true,characterData:true,subtree:true});
  const header=document.querySelector('.sim-topbar');
  const placeNotice=()=>{const notice=header.querySelector(':scope > .preview-notice');if(notice){notice.title='ระบบตัวอย่าง: การขาย การชำระเงิน และการบันทึกข้อมูลจริงยังปิดอยู่';notice.textContent='โหมดตัวอย่าง';document.querySelector('.net-controls').append(notice);}};
  new MutationObserver(placeNotice).observe(header,{childList:true});placeNotice();
  document.querySelectorAll('.module-intro p,.module-state').forEach(n=>n.hidden=true);
})();

