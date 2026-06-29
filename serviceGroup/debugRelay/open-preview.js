const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const page = await browser.newPage();
  page.on('console', msg => console.log('[console]', msg.type(), msg.text().slice(0, 300)));
  page.on('pageerror', err => console.log('[pageerror]', err.message));
  console.log('goto preview');
  await page.goto('http://127.0.0.1:7456', { waitUntil: 'domcontentloaded', timeout: 30000 });
  console.log('url', page.url());
  console.log('title', await page.title());
  await new Promise(r => setTimeout(r, 15000));
  console.log('done wait');
  await browser.disconnect();
})();
