/**
 * 刷新 preview 页面，等待 DebugPlugin 重新初始化，然后抓 5 秒 perf 数据
 */
const puppeteer = require('puppeteer-core');

(async () => {
    const browser = await puppeteer.connect({
        browserURL: 'http://127.0.0.1:7456',
        defaultViewport: null,
    });

    const pages = await browser.pages();
    console.log(`[puppeteer] 找到 ${pages.length} 个页面`);
    for (const p of pages) {
        const url = p.url();
        console.log(`  page: ${url.substring(0, 100)}`);
    }

    // 找 preview 页面（包含游戏 iframe）
    let previewPage = pages.find(p => p.url().includes('7456') || p.url().includes('preview'));
    if (!previewPage && pages.length > 0) {
        previewPage = pages[0];
    }
    if (!previewPage) {
        console.log('[puppeteer] 未找到 preview 页面');
        await browser.disconnect();
        return;
    }

    console.log('[puppeteer] 刷新 preview 页面...');
    await previewPage.reload({ waitUntil: 'networkidle2', timeout: 30000 });
    console.log('[puppeteer] 页面已刷新，等待 5 秒让插件初始化...');
    await new Promise(r => setTimeout(r, 5000));

    await browser.disconnect();
    console.log('[puppeteer] 完成，现在用 diagnose-perf.py 检查数据');
})();
