const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  for (const p of pages) {
    console.log('PAGE', p.url());
  }
  const page = pages.find(p => p.url().includes('7456')) || pages[0];
  page.on('console', m => {
    const t = m.text();
    if (t.includes('INIT version') || t.includes('DebugPlugin') || t.includes('SceneBridge') || t.includes('PerfBridge') || t.includes('RELOAD-VERIFY')) {
      console.log('[browser]', m.type(), t.slice(0, 300));
    }
  });
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  await new Promise(r => setTimeout(r, 5000));
  await browser.disconnect();
})();
