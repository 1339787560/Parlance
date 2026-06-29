const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const page = await browser.newPage();
  page.on('console', m => {
    const t = m.text();
    if (t.includes('INIT version') || t.includes('DebugPlugin') || t.includes('SceneBridge') || t.includes('PerfBridge') || t.includes('RELOAD-VERIFY')) {
      console.log('[B]', m.type(), t.slice(0, 300));
    }
  });
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  await page.goto('http://127.0.0.1:7456', { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('loaded');
  await new Promise(r => setTimeout(r, 25000));
  console.log('done');
  await browser.disconnect();
})();
