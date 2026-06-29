const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  for (const p of pages) {
    console.log('PAGE', p.url());
    console.log('TITLE', await p.title().catch(e=>'ERR:'+e.message));
  }
  await browser.disconnect();
})();
