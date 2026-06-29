const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes('7456')) || pages[0];
  page.on('console', msg => console.log('[console]', msg.type(), msg.text().slice(0, 300)));
  page.on('pageerror', err => console.log('[pageerror]', err.message));
  console.log('url', page.url(), 'title', await page.title());
  console.log('readyState', await page.evaluate(() => document.readyState).catch(e=>'ERR '+e.message));
  console.log('bodyText', await page.evaluate(() => document.body.innerText.slice(0,500)).catch(e=>'ERR '+e.message));
  console.log('wait 20s');
  await new Promise(r => setTimeout(r, 20000));
  console.log('readyState2', await page.evaluate(() => document.readyState).catch(e=>'ERR '+e.message));
  await browser.disconnect();
})();
