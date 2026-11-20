/* Shared navigation/chrome, with existing application state and actions intact. */
(() => {
  const brand=document.querySelector('.nav-brand');
  if(brand) brand.innerHTML='<img class="brand-wordmark" src="/assets/brand-logo.webp" alt="POS WAI"><img class="brand-mini-mark" src="/assets/brand-mark.webp" alt="POS WAI">';
  document.querySelectorAll('.brand-symbol').forEach(n=>n.innerHTML='<img src="/assets/brand-mark.webp" alt="">');
  document.querySelectorAll('.role-tab').forEach(n=>n.querySelector('small')?.remove());
  document.querySelector('.nav-footer span:last-child').textContent='โหมดตัวอย่าง';
  const branches=document.getElementById('branchSelect');
  [...branches.options].forEach(o=>o.textContent=o.textContent.replace(/^📍\s*/,'').replace(/^🏭\s*/,'').replace('สาขา 1: ','').replace('สาขา 2: ','').replace(' (Central)',''));
  document.querySelectorAll('[id^="topLangBtn"],[id^="langBtn"]').forEach(b=>b.textContent=b.id.endsWith('TH')?'ไทย':b.id.endsWith('EN')?'EN':'中文');
  const languageButtons=[...document.querySelectorAll('[id^="topLangBtn"]')];
  const languagePicker=languageButtons[0]?.parentElement;
  if(languagePicker){
    languagePicker.classList.add('compact-language-picker');
    const updateLanguagePicker=()=>{
      const current=state.lang || 'TH';
      languageButtons.forEach(button=>{
        const selected=button.id.endsWith(current);
        button.classList.toggle('selected-language',selected);
        button.setAttribute('aria-label',selected?`ภาษาปัจจุบัน ${button.textContent} กดเพื่อเลือกภาษา`:`เปลี่ยนเป็นภาษา ${button.textContent}`);
        button.setAttribute('aria-expanded',selected?String(languagePicker.classList.contains('open')):'false');
      });
      languageButtons.filter(button=>!button.classList.contains('selected-language')).forEach((button,index)=>button.style.top=`calc(100% + ${index*34+3}px)`);
    };
    languagePicker.addEventListener('click',event=>{
      const button=event.target.closest('button');
      if(!button)return;
      if(button.classList.contains('selected-language'))languagePicker.classList.toggle('open');
      else languagePicker.classList.remove('open');
      updateLanguagePicker();
    });
    document.addEventListener('click',event=>{if(!languagePicker.contains(event.target)){languagePicker.classList.remove('open');updateLanguagePicker();}});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'){languagePicker.classList.remove('open');updateLanguagePicker();}});
    updateLanguagePicker();
  }
  const branchClock=document.createElement('time');
  branchClock.className='branch-clock';
  branchClock.setAttribute('aria-label','วันที่และเวลาปัจจุบัน');
  branches.after(branchClock);
  const updateBranchClock=()=>{
    const now=new Date();
    branchClock.dateTime=now.toISOString();
    branchClock.textContent=new Intl.DateTimeFormat('th-TH',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(now);
  };
  updateBranchClock();
  setInterval(updateBranchClock,30000);
  document.getElementById('netStatusText').textContent='ออนไลน์';
  const badge=document.getElementById('syncQueueBadge');
  badge.firstChild.textContent='รอส่ง ';
  const sync=()=>badge.classList.toggle('is-empty',document.getElementById('syncCount').textContent==='0');sync();
  new MutationObserver(sync).observe(document.getElementById('syncCount'),{childList:true,characterData:true,subtree:true});
  const header=document.querySelector('.sim-topbar');
  const placeNotice=()=>{const notice=header.querySelector(':scope > .preview-notice');if(notice){notice.title=notice.textContent;const exit=notice.querySelector('.preview-notice-exit');notice.textContent=exit?'ร้านตัวอย่าง':'โหมดตัวอย่าง';if(exit)notice.append(exit);document.querySelector('.net-controls').append(notice);}};
  new MutationObserver(placeNotice).observe(header,{childList:true});placeNotice();
  document.querySelectorAll('.module-intro p,.module-state').forEach(n=>n.hidden=true);
})();

