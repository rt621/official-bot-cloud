(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const navCard = [...document.querySelectorAll('.el-card')].find(c => c.textContent.includes('功能总览'));
  if (!navCard) return 'nav missing';
  const clickNav = (txt) => { const i = [...navCard.querySelectorAll('div')].find(d => d.textContent.trim() === txt); if (!i) return false; i.click(); return true; };
  const readSw = () => {
    const item = [...document.querySelectorAll('.el-form-item')].find(f => f.textContent.includes('启用举报通道'));
    return item ? (item.querySelector('.el-switch').classList.contains('is-checked') ? 'on' : 'off') : 'missing';
  };
  if (!clickNav('📮 举报通道')) return 'nav fail';
  await sleep(400);
  const before = readSw();
  await fetch('/api/instances/1/plugins/report', { method: 'DELETE', headers: { Authorization: 'Bearer ' + localStorage.getItem('token') } });
  clickNav('🛍️ 插件市场');
  await sleep(400);
  clickNav('📮 举报通道');
  await sleep(300);
  const after = readSw();
  await fetch('/api/instances/1/plugins/report/install', { method: 'POST', headers: { Authorization: 'Bearer ' + localStorage.getItem('token') } });
  clickNav('🛍️ 插件市场');
  await sleep(400);
  clickNav('📮 举报通道');
  await sleep(300);
  const restored = readSw();
  return JSON.stringify({ before: before, afterStop: after, afterRestore: restored });
})()