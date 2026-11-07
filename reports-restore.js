/* Keep the executive report's original detail accessible in the redesigned layout. */
(() => {
  const report = document.querySelector('#view-analytics');
  const tablist = report?.querySelector('.people-tabs');
  if (!tablist || report.querySelector('#report-details-panel')) return;
  const q = (selector, root = report) => root.querySelector(selector);
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const card = (title, rows) => {
    const box = element('section', 'card report-detail-card');
    box.append(element('h2', 'report-detail-heading', title));
    for (const [label, value] of rows) {
      const row = element('div', 'report-detail-row');
      row.append(element('span', '', label), element('strong', '', value));
      box.append(row);
    }
    return box;
  };
  const panel = element('section', 'people-panel report-details-panel');
  panel.id = 'report-details-panel';
  panel.role = 'tabpanel';
  panel.hidden = true;
  const button = element('button', '', 'ข้อมูลเชิงลึก');
  button.type = 'button';
  button.id = 'report-details-tab';
  button.role = 'tab';
  button.tabIndex = -1;
  button.setAttribute('aria-selected', 'false');
  button.setAttribute('aria-controls', panel.id);
  panel.setAttribute('aria-labelledby', button.id);
  const activate = (next) => {
    const buttons = [...tablist.querySelectorAll('[role="tab"]')];
    const panels = [...report.querySelectorAll(':scope > .people-panel')];
    buttons.forEach((item, index) => {
      const selected = index === next;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      if (panels[index]) panels[index].hidden = !selected;
    });
  };
  button.addEventListener('click', () => activate([...tablist.children].indexOf(button)));
  tablist.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    const index = tabs.indexOf(event.target);
    if (index < 0) return;
    const next = event.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length
      : event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'Home' ? 0 : tabs.length - 1;
    event.preventDefault(); event.stopImmediatePropagation();
    tabs[next].click(); tabs[next].focus();
  }, {capture: true});
  [...tablist.querySelectorAll('[role="tab"]')].forEach(tab => {
    tab.addEventListener('click', () => { panel.hidden = true; }, {capture: true});
  });
  button.addEventListener('keydown', event => {
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    const index = tabs.indexOf(button);
    const next = event.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length
      : event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'Home' ? 0
      : event.key === 'End' ? tabs.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault(); tabs[next].click(); tabs[next].focus();
  });
  tablist.append(button);
  report.append(panel);

  const summary = element('p', 'report-detail-intro', 'รายละเอียดเป้าหมาย ต้นทุน ลูกค้า และคำแนะนำจัดกะจากรายงานตัวอย่าง');
  panel.append(summary);
  const grid = element('div', 'report-details-grid');
  grid.append(
    card('เป้าหมายและลูกค้า', [
      ['ยอดขายเทียบเป้ารายวัน', '฿4,850 / ฿6,000 · 80.8%'],
      ['ลูกค้าประจำ / ลูกค้าใหม่', '68% / 32%'],
      ['ยอดเฉลี่ยต่อบิล / ต่อท่าน', '฿285 / ฿142'],
      ['มูลค่าลูกค้าตลอดความสัมพันธ์', '฿4,620 (ตัวอย่าง)']
    ]),
    card('ต้นทุนและของเสีย', [
      ['ต้นทุนวัตถุดิบขายจริง', '฿1,555 · 32.1%'],
      ['ของเสียและของทิ้ง', '฿135 · 2.8%'],
      ['ต้นทุนรวม', '฿1,690 · 34.8%'],
      ['กรอบเป้าต้นทุน', '30–35%']
    ]),
    card('การเตรียมกำลังคน', [
      ['จันทร์–พฤหัส · กะกลางวัน', 'ครัว 2 · แคชเชียร์ 1 · เสิร์ฟ 1'],
      ['ช่วง 14:00–16:30 น.', 'ลดคนตามปริมาณงานเพื่อลด OT'],
      ['ศุกร์–อาทิตย์ · 17:30–21:00 น.', 'ครัว 3 · บาร์ 1 · แคชเชียร์ 1 · เสิร์ฟ 2'],
      ['ยอดขายช่วงกะเย็น', 'ประมาณการสูงกว่าปกติ 38%']
    ]),
    card('จุดที่ควรติดตาม', [
      ['เวลาครัวช่วงปกติ / ช่วงพีก', '5.8 / 11.4 นาทีต่อจาน'],
      ['เตาทอดช่วง 12:00–13:00 น.', '14.5 นาทีต่อจาน'],
      ['ข้อเสนอแนะ', 'เตรียมหมูกรอบก่อน 11:15 น.'],
      ['เมนูที่ต้องดูแล', 'ดาวเด่น · ทำกำไร · ขายช้า · ของเสีย']
    ])
  );
  panel.append(grid);

  const actions = element('div', 'report-detail-actions');
  const exportButton = element('button', 'btn btn-sm btn-outline', 'ดาวน์โหลดข้อมูลตัวอย่าง CSV');
  exportButton.type = 'button';
  exportButton.addEventListener('click', () => {
    const rows = [['หมวด', 'รายการ', 'ค่า']];
    grid.querySelectorAll('.report-detail-card').forEach(box => {
      const group = q('.report-detail-heading', box)?.textContent || '';
      box.querySelectorAll('.report-detail-row').forEach(row => {
        rows.push([group, row.firstElementChild?.textContent || '', row.lastElementChild?.textContent || '']);
      });
    });
    const escape = value => `"${String(value).replaceAll('"', '""')}"`;
    const csv = '\uFEFF' + rows.map(row => row.map(escape).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
    const anchor = element('a'); anchor.href = url; anchor.download = 'poswai-report-sample.csv';
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  actions.append(exportButton, element('span', 'report-detail-note', 'ข้อมูลในหน้านี้เป็นตัวอย่าง ยังไม่เชื่อมยอดขายจริง'));
  panel.append(actions);
  const integrations = element('details', 'people-disclosure report-integrations');
  integrations.append(element('summary', '', 'ส่งรายงานเข้า LINE'));
  const integrationBody = element('div', 'report-integration-body');
  integrationBody.append(element('p', '', 'ฟังก์ชันแจ้งยอดช่วงเร่งด่วนและสรุปปิดร้านยังรอข้อมูลยอดขายจริง'));
  for (const text of ['แจ้งยอดช่วงเร่งด่วน', 'ส่งสรุปปิดร้าน']) {
    const pending = element('button', 'btn btn-sm btn-outline', text + ' · ยังไม่พร้อม');
    pending.type = 'button'; pending.disabled = true; integrationBody.append(pending);
  }
  integrations.append(integrationBody); panel.append(integrations);
})();
