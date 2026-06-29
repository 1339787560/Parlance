const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: false,
    args: ['--remote-debugging-port=9222','--user-data-dir=C:\\Users\\admin\\AppData\\Local\\Temp\\cocos-preview-verify','--no-sandbox'],
  });
  const page = await browser.newPage();
  console.log('goto preview');
  await page.goto('http://127.0.0.1:7456', { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('loaded, keep open');
  // Keep alive
  await new Promise(r => setTimeout(r, 120000));
  await browser.close();
})();
