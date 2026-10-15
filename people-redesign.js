/* Staff and reporting workspaces: retain existing controls and data bindings. */
(() => {
  const $ = (s, r=document) => r.querySelector(s);
  const all = (s, r=document) => [...r.querySelectorAll(s)];
  function title(card, text) {
    const t=$('.card-title',card); if(t) t.textContent=text;
    const header=$('.card-header',card);
    if(header) all('.card-title + div',header).forEach(n=>n.remove());
  }
  function details(label, nodes) {
    const d=document.createElement('details'); d.className='people-disclosure';
    const s=document.createElement('summary'); s.textContent=label; d.append(s);
    nodes.forEach(n=>n&&d.append(n)); return d;
  }
  function tabs(host, entries) {
    const nav=document.createElement('div'); nav.className='people-tabs'; nav.setAttribute('role','tablist');
    const panels=[];
    entries.forEach(([label,nodes],i)=>{
      const panel=document.createElement('div'); panel.className='people-panel'; panel.id=host.id+'-panel-'+i;
      panel.setAttribute('role','tabpanel'); panel.hidden=i!==0;
      const btn=document.createElement('button'); btn.type='button'; btn.textContent=label;
      btn.id=panel.id+'-tab'; btn.setAttribute('role','tab'); btn.setAttribute('aria-controls',panel.id);
      btn.setAttribute('aria-selected',String(i===0)); btn.tabIndex=i===0?0:-1; panel.setAttribute('aria-labelledby',btn.id);
      btn.addEventListener('click',()=>{panels.forEach((p,j)=>{p.hidden=j!==i;nav.children[j].setAttribute('aria-selected',String(j===i));nav.children[j].tabIndex=j===i?0:-1;});});
      btn.addEventListener('keydown',e=>{let next;if(e.key==='ArrowRight')next=(i+1)%entries.length;if(e.key==='ArrowLeft')next=(i+entries.length-1)%entries.length;if(e.key==='Home')next=0;if(e.key==='End')next=entries.length-1;if(next!==undefined){e.preventDefault();nav.children[next].click();nav.children[next].focus();}});
      nodes.forEach(n=>n&&panel.append(n)); panels.push(panel);nav.append(btn);
    }); host.append(nav,...panels);
  }
  const staff=$('#view-staff');
  if(staff) {
    staff.classList.add('people-workspace');
    const intro=$('.module-intro p',staff);if(intro)intro.textContent='จัดการทีมและเวลาทำงาน';
    const cards=all('.grid-2 > div > .card',staff);
    if(cards.length===5){
      const [attendance,approval,roster,commission,audit]=cards;
      title(attendance,'ลงเวลาและยื่นใบลา');title(approval,'คำขอลา');title(roster,'ตารางกะ');title(commission,'คอมมิชชัน');title(audit,'ประวัติกิจกรรม');
      all('.card-header .badge',attendance).forEach(n=>n.remove());
      const select=$('#staffSelect');const label=select.previousElementSibling;if(label)label.textContent='พนักงาน';
      all('button',attendance).forEach(b=>{if(b.getAttribute('onclick')?.includes('recordAttendance')) b.textContent=b.getAttribute('onclick').includes('Clock-In')?'เข้างาน':'ออกงาน';});
      const leave=$('#leaveTypeSelect').parentElement.parentElement.parentElement;
      if(leave?.parentElement===attendance){const heading=leave.firstElementChild;if(heading&&!heading.querySelector('input,select'))heading.remove();attendance.append(details('ยื่นคำขอลา',[leave]));}
      const check=$('button',approval);if(check){check.textContent='ทดลองตรวจการขาดงาน';approval.append(details('เครื่องมือทดลอง',[check]));}
      const pin=$('button',roster);if(pin){pin.textContent='ทดสอบสิทธิ์ POS';roster.append(details('ตรวจสิทธิ์การใช้งาน',[pin]));}
      all('th',roster).forEach((n,i)=>n.textContent=['พนักงาน','กะทำงาน','สถานะ','สิทธิ์ POS'][i]);
      const mode=$('#commissionRuleSelect');mode.options[0].textContent='แบ่งกองกลาง 3%';mode.options[1].textContent='รายบุคคล 3%';
      const formula=$('#commissionPoolFormulaBox');commission.append(details('วิธีคำนวณ',[formula]));
      const main=document.createElement('div');main.className='people-attendance-layout';main.append(roster,attendance);
      const old=$(':scope > .grid-2',staff);
      const payroll=document.createElement('div');payroll.className='people-payroll card';
      payroll.innerHTML=`<div class="card-header"><div><div class="card-title">ประวัติและสรุปเงินพนักงาน</div><p class="people-payroll-subtitle">เข้างาน · ลางาน · โอที · คอมมิชชัน</p></div></div>
        <div class="people-payroll-toolbar"><label>พนักงาน<select id="payrollStaffSelect" class="input"></select></label><label>เดือน<input id="payrollMonth" class="input" type="month"></label><button id="payrollRefresh" class="btn btn-outline" type="button">ดูข้อมูล</button></div>
        <details class="people-disclosure people-payroll-access"><summary>เชื่อมต่อข้อมูลจริงของผู้จัดการ</summary><label>รหัสเข้าถึงรายงาน<input id="payrollManagerToken" class="input" type="password" autocomplete="off" placeholder="รหัสผู้จัดการ"></label><p>ใช้รหัสสำหรับรายงานนี้เท่านั้น ระบบไม่เก็บรหัสไว้ในเครื่อง</p></details>
        <div id="payrollSource" class="people-payroll-source"></div><div id="payrollSummary" class="people-payroll-summary"></div><div id="payrollHistory" class="people-payroll-history"></div>`;
      audit.classList.add('people-audit-card');
      tabs(staff,[['ภาพรวมทีม',[main]],['คำขอลา',[approval]],['คอมมิชชัน',[commission]],['ประวัติและเงินเดือน',[payroll,audit]]]);old.remove();
      const sample=document.createElement('div');sample.className='people-sample';sample.textContent='ข้อมูลตัวอย่าง • การลงเวลาและใบลายังไม่เปิดใช้งานจริง';staff.insertBefore(sample,$('.people-tabs',staff));
      const short=()=>{
        all('#staffShiftRosterBody .badge').forEach(n=>{const t=n.textContent;n.textContent=t.includes('completed')?'เข้างานแล้ว':t.includes('scheduled')?'รอเข้างาน':t.includes('on_leave')?'ลา':t.includes('absent')?'ขาดงาน':t.includes('ระงับ')?'ระงับ':'ใช้งานได้';});
        const requests=$('#managerLeaveFlexContainer');if(!requests.children.length){const empty=document.createElement('div');empty.className='people-empty';empty.textContent='ยังไม่มีคำขอลา';requests.append(empty);}
        all(':scope > div:not(.people-empty)',requests).forEach(card=>{
          if(card.dataset.compact)return;card.dataset.compact='true';
          const heading=$('strong',card);if(heading)heading.textContent=heading.textContent.replace('💬 LINE Flex Message: ','');
          const badge=$('.badge',card);if(badge)badge.textContent=badge.textContent.includes('Pending')?'รออนุมัติ':badge.textContent.includes('Approved')?'อนุมัติแล้ว':'ไม่อนุมัติ';
          all('button',card).forEach(b=>b.textContent=b.getAttribute('onclick')?.includes("'approved'")?'อนุมัติ':'ปฏิเสธ');
          const description=card.children[1];
          if(description?.children.length>=3){const extra=[...description.children].slice(1);description.append(details('รายละเอียดคำขอ',extra));}
        });
      };short();
      // Re-run after existing rendering without replacing application functions.
      let queued=false;const ob=new MutationObserver(()=>{if(queued)return;queued=true;queueMicrotask(()=>{ob.disconnect();short();ob.observe($('#staffShiftRosterBody'),{childList:true});ob.observe($('#managerLeaveFlexContainer'),{childList:true});queued=false;});});
      ob.observe($('#staffShiftRosterBody'),{childList:true});ob.observe($('#managerLeaveFlexContainer'),{childList:true});
      setupPayroll(payroll);
    }
  }
  function setupPayroll(host) {
    const staffSelect=$('#payrollStaffSelect',host),monthInput=$('#payrollMonth',host),token=$('#payrollManagerToken',host);
    const mainStaff=$('#staffSelect');staffSelect.replaceChildren(...[...mainStaff.options].map(o=>new Option(o.textContent,o.value)));
    staffSelect.value=mainStaff.value;
    const now=new Date();monthInput.value=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
    const money=n=>`฿${Number(n||0).toLocaleString('th-TH',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
    const hours=n=>`${Number(n||0).toLocaleString('th-TH',{maximumFractionDigits:2})} ชม.`;
    const date=s=>{if(!s)return '—';const d=new Date(s);return Number.isNaN(d.getTime())?s:d.toLocaleDateString('th-TH',{day:'numeric',month:'short',year:'numeric'});};
    const time=s=>s?String(s).slice(11,16):'—';
    const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const leaveName={sick:'ลาป่วย',personal:'ลากิจ',vacation:'ลาพักร้อน',swap_shift:'สลับกะ'};
    const statusName={pending:'รออนุมัติ',approved:'อนุมัติ',rejected:'ไม่อนุมัติ',cancelled:'ยกเลิก'};
    let report=null,source='demo';
    function makePreview() {
      const staff=typeof state==='undefined'?[]:state.staffStats;
      return staff.map((s,i)=>{
        const month=monthInput.value;
        // Explicit sample records keep the preview useful without implying real payroll.
        const currentMonth=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
        const attendance=[3,5,8,10,12,15,17,19,22,24].filter(day=>month<currentMonth||(month===currentMonth&&day<=now.getDate())).map((day,j)=>{
          const dd=String(day).padStart(2,'0');const total=8+(j===2||j===6?2:0);
          return {date:`${month}-${dd}`,clock_in:`${month}-${dd}T08:00:00`,clock_out:`${month}-${dd}T${String(8+total).padStart(2,'0')}:00:00`,regular_hours:8,ot_hours:total-8};
        });
        const leave=(typeof state==='undefined'?[]:state.leaveRequests).filter(l=>l.staffId===s.id).map(l=>({type:l.leaveType,start_date:l.startDate||l.date||`${month}-20`,end_date:l.endDate||l.startDate||`${month}-20`,status:l.status||'pending'})).filter(l=>l.start_date.startsWith(month)||l.end_date.startsWith(month));
        const regular=attendance.reduce((n,a)=>n+a.regular_hours,0),ot=attendance.reduce((n,a)=>n+a.ot_hours,0);
        const hourly=[120,85,75,90][i]||75;
        const eligible=s.shiftStatus!=='on_leave'&&s.shiftStatus!=='absent';
        const pool=state.shift.totalSalesToday*.03;
        const divisor=Math.max(1,staff.filter(x=>x.shiftStatus!=='on_leave'&&x.shiftStatus!=='absent').length);
        const commission=eligible?(($('#commissionRuleSelect')?.value||'POOLED')==='POOLED'?pool/divisor:s.sales*.03):0;
        return {id:i+1,name:s.name,role:s.role,hourly_rate:hourly,regular_hours:regular,ot_hours:ot,work_days:attendance.length,attendance,leave,commission_records:[],commission,base_pay:regular*hourly,ot_pay:ot*hourly*1.5,total_pay:regular*hourly+ot*hourly*1.5+commission};
      });
    }
    function render() {
      const id=Number(staffSelect.value.replace('ST',''));
      const person=report?.find(s=>s.id===id);
      $('#payrollSource',host).textContent=source==='demo'?'ข้อมูลตัวอย่างเพื่อดูรูปแบบรายงาน • ยังไม่ใช่เงินเดือนจริง':'ข้อมูลจากระบบ • ยอดก่อนหักภาษี ประกันสังคม และรายการอื่น';
      if(!person){$('#payrollSummary',host).replaceChildren();$('#payrollHistory',host).textContent='ยังไม่มีข้อมูลพนักงานสำหรับเดือนนี้';return;}
      const cards=[['วันทำงาน',`${person.work_days||0} วัน`],['ชั่วโมงปกติ',hours(person.regular_hours)],['โอที',hours(person.ot_hours)],['ค่าแรง',money(person.base_pay)],['ค่าโอที',money(person.ot_pay)],['คอมมิชชัน',money(person.commission)],['รวมก่อนหัก',money(person.total_pay)]];
      $('#payrollSummary',host).innerHTML=cards.map(([label,value],i)=>`<div class="people-payroll-stat${i===6?' people-payroll-total':''}"><span>${label}</span><strong>${value}</strong></div>`).join('');
      const rows=[...person.attendance.map(a=>({day:a.date,type:'ลงเวลา',description:`${time(a.clock_in)}–${time(a.clock_out)} · ปกติ ${hours(a.regular_hours)}`,ot:a.ot_hours?`โอที ${hours(a.ot_hours)}`:'—'})),...person.leave.map(l=>({day:l.start_date,type:'ลา',description:`${leaveName[l.type]||esc(l.type)} · ${statusName[l.status]||esc(l.status)}`,ot:l.end_date&&l.end_date!==l.start_date?`ถึง ${date(l.end_date)}`:'—'})),...person.commission_records.map(c=>({day:c.date,type:'คอมมิชชัน',description:money(c.amount),ot:'—'}))].sort((a,b)=>String(b.day).localeCompare(String(a.day)));
      $('#payrollHistory',host).innerHTML=`<div class="people-payroll-history-title">รายการย้อนหลัง <span>${rows.length} รายการ</span></div><div class="people-payroll-ledger">${rows.length?rows.map(r=>`<div class="people-payroll-row"><span>${date(r.day)}</span><b>${esc(r.type)}</b><span>${esc(r.description)}</span><em>${esc(r.ot)}</em></div>`).join(''):'<div class="people-empty">ยังไม่มีประวัติในเดือนนี้</div>'}</div><p class="people-payroll-note">ตัวอย่างการคำนวณ: 8 ชั่วโมงแรก × อัตรารายชั่วโมง; เวลาเกิน 8 ชั่วโมง × อัตรารายชั่วโมง × 1.5; รวมคอมมิชชันที่บันทึกแล้ว อัตราและกติกาต้องตั้งตามนโยบายร้านก่อนจ่ายเงินจริง</p>`;
    }
    async function load(){
      if(typeof state==='undefined'||state.previewOnly||!token.value.trim()){report=makePreview();source='demo';render();return;}
      try{
        const response=await fetch(`/api/staff/payroll?month=${encodeURIComponent(monthInput.value)}&branch_id=1`,{headers:{'X-Manager-Report-Token':token.value.trim()},cache:'no-store'});
        if(!response.ok)throw new Error(response.status===403?'รหัสผู้จัดการไม่ถูกต้อง':response.status===503?'ยังไม่ได้ตั้งค่ารหัสรายงานบนเซิร์ฟเวอร์':`โหลดข้อมูลไม่สำเร็จ (${response.status})`);
        report=(await response.json()).staff;source='live';render();
      }catch(e){report=null;$('#payrollSource',host).textContent=e.message;$('#payrollSummary',host).replaceChildren();$('#payrollHistory',host).replaceChildren();}
    }
    staffSelect.addEventListener('change',render);monthInput.addEventListener('change',load);$('#payrollRefresh',host).addEventListener('click',load);mainStaff.addEventListener('change',()=>{staffSelect.value=mainStaff.value;render();});
    report=makePreview();render();
  }
  const report=$('#view-analytics');
  if(report){
    report.classList.add('people-workspace','report-workspace');
    const children=[...report.children];
    const toolbar=children[1],kpis=children[2],channels=children[3],matrix=children[4],operations=children[5];
    if(toolbar&&kpis&&channels&&matrix&&operations){
      toolbar.className='report-toolbar';toolbar.removeAttribute('style');
      const benchmark=$('#benchmarkModeSelect');benchmark.options[0].textContent='เทียบสัปดาห์ก่อน';benchmark.options[1].textContent='เทียบเมื่อวาน';benchmark.removeAttribute('style');
      const label=document.createElement('span');label.textContent='ช่วงเปรียบเทียบ';const actions=document.createElement('div');actions.className='report-toolbar-controls';actions.append(label,benchmark);toolbar.replaceChildren(actions);
      kpis.classList.add('report-kpis');
      all('.stat-card',kpis).forEach((n,i)=>{
        n.removeAttribute('style');const head=n.firstElementChild;head.firstElementChild.textContent=['ยอดขายรวม','ต้นทุนรวม','ส่วนต่างยอดขาย − ต้นทุน'][i];
        all('.badge',head).forEach(b=>{if(!b.id)b.remove();});
        const sub=n.lastElementChild;if(sub&&!sub.classList.contains('stat-val')){const d=details('รายละเอียด',[sub]);n.append(d);}
      });
      // The displayed difference excludes operating expenses; do not label it net profit.
      const profit=$('#kpiNetProfit small');if(profit)profit.remove();
      const channelCards=all('.card',channels);title(channelCards[0],'ยอดขายตามช่องทาง');title(channelCards[1],'วิธีชำระเงิน');
      channelCards.forEach(c=>all('.card-header .badge',c).forEach(n=>n.remove()));
      const channelNames=['ทานที่ร้าน','ซื้อกลับบ้าน','GrabFood','LINE MAN','ช่องทางอื่น'];
      const payNames=['PromptPay','เงินสด','บัตรเครดิต / เดบิต','e-Wallet'];
      channelCards.forEach((c,i)=>all('.bar-row',c).forEach((r,j)=>{r.firstElementChild.textContent=(i?payNames:channelNames)[j];}));
      title(matrix,'ประสิทธิภาพเมนู');matrix.classList.add('report-menu-matrix');
      all('th',matrix).forEach((n,i)=>n.textContent=['เมนู','ต้นทุน / ราคา','กำไรต่อจาน','จำนวนขาย','กลุ่ม','คำแนะนำ'][i]);
      all('tbody tr',matrix).forEach(row=>{const name=$('td strong',row);if(name)name.textContent=name.textContent.replace(/[\p{Extended_Pictographic}\uFE0F]/gu,'').trim();const cell=row.lastElementChild;if(cell){const inner=[...cell.childNodes];cell.replaceChildren(details('ดูคำแนะนำ',inner));}const badge=$('.badge',row);if(badge){const t=badge.textContent;badge.textContent=t.includes('Stars')?'ขายดี · กำไรสูง':t.includes('Puzzles')?'กำไรสูง · ขายน้อย':t.includes('Dogs')?'ควรทบทวน':'ขายดี · กำไรต่ำ';}});
      const opCards=all('.card',operations);title(opCards[0],'ช่วงเวลาขายดี');title(opCards[1],'ความเร็วครัวและกำลังคน');
      const speedBody=opCards[1]?.lastElementChild;
      if(speedBody){
        speedBody.replaceChildren();
        const metrics=document.createElement('div');metrics.className='report-speed-metrics';
        [['ช่วงปกติ','5.8','นาที / จาน'],['ช่วงขายดี','11.4','นาที / จาน'],['เตาทอด','14.5','นาที / จาน']].forEach(([label,value,unit])=>{const box=document.createElement('div');const caption=document.createElement('span');caption.textContent=label;const val=document.createElement('strong');val.textContent=value;const small=document.createElement('small');small.textContent=unit;box.append(caption,val,small);metrics.append(box);});
        const recommendation=document.createElement('p');recommendation.className='report-insight';recommendation.textContent='เตาทอดใช้เวลานานช่วง 12:00–13:00 น. ควรเตรียมหมูกรอบก่อน 11:15 น.';
        const roster=document.createElement('p');roster.textContent='วันธรรมดา: ครัว 2 • แคชเชียร์ 1 • เสิร์ฟ 1 คน\nศุกร์–อาทิตย์ กะเย็น: ครัว 3 • บาร์ 1 • แคชเชียร์ 1 • เสิร์ฟ 2 คน';roster.style.whiteSpace='pre-line';roster.style.lineHeight='2';
        speedBody.append(metrics,recommendation,details('คำแนะนำจัดกะ (ตัวอย่าง)',[roster]));
      }
      operations.classList.add('report-operations');
      all('.heatmap-cell',operations).forEach(n=>n.textContent=n.textContent.replace('🔥 ',''));
      const intro=$('.module-intro p',report);if(intro)intro.textContent='ภาพรวมและแนวโน้มของร้าน';
      tabs(report,[['ภาพรวม',[kpis,channels]],['เมนู',[matrix]],['การให้บริการ',[operations]]]);
      const notice=document.createElement('div');notice.className='people-sample';notice.textContent='ข้อมูลตัวอย่าง • ยังไม่ใช่ยอดขายหรือผลประกอบการจริง';toolbar.before(notice);
    }
  }
})();
