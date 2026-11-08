const { chromium } = require(process.env.CMNC_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const artifacts = await fs.mkdtemp(path.join(require('node:os').tmpdir(), 'cmnc-recording-'));
  const browser = await chromium.launch({ executablePath: process.env.CMNC_TEST_CHROMIUM_PATH || undefined, headless: true });
  try {
    for (const mobile of [false, true]) {
      const context = await browser.newContext({ viewport: mobile ? {width: 390, height: 844} : {width: 1360, height: 900}, isMobile: mobile, hasTouch: mobile, acceptDownloads: true });
      await context.addInitScript(() => { Object.defineProperty(window, 'showSaveFilePicker', {value: undefined}); });
      const page = await context.newPage();
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      const jpeg = await page.evaluate(() => {
        const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
        const ctx = canvas.getContext('2d'); ctx.fillStyle = '#15803d'; ctx.fillRect(0, 0, 640, 480);
        ctx.fillStyle = 'white'; ctx.font = '30px sans-serif'; ctx.fillText('Recording fixture', 60, 200);
        return canvas.toDataURL('image/jpeg').split(',')[1];
      });
      const requests = [];
      await page.route('**/api/**', async route => {
        requests.push(new URL(route.request().url()));
        await route.fulfill({contentType: 'image/jpeg', body: Buffer.from(jpeg, 'base64')});
      });
      await page.goto(`${process.env.CMNC_RECORDING_TEST_URL || 'http://127.0.0.1:5188'}/?veyon_device=1&veyon_device_name=PC-01&veyon_classroom_name=TikTok`);
      await page.getByRole('button', {name:'Запись', exact:true}).waitFor();
      await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(node => node.textContent === 'Запись')?.disabled);
      async function start() {
        await page.getByRole('button', {name:'Запись', exact:true}).click();
        const modal = page.getByRole('dialog'); await modal.waitFor();
        await modal.locator('select').nth(1).selectOption('15');
        await page.screenshot({path: path.join(artifacts, `settings-${mobile ? 'mobile' : 'desktop'}.png`)});
        await modal.getByRole('button', {name:'Начать запись'}).click();
        await page.getByRole('timer').waitFor();
        await page.waitForFunction(() => !document.querySelector('.device-recording-controls button')?.disabled);
      }
      await start();
      await page.waitForTimeout(1200);
      await page.getByRole('button', {name:'Пауза', exact:true}).click();
      const paused = await page.getByRole('timer').textContent();
      await page.waitForTimeout(1300);
      assert.equal(await page.getByRole('timer').textContent(), paused, 'Paused timer must not advance');
      await page.getByRole('button', {name:'Продолжить'}).click();
      await page.waitForTimeout(700);
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', {name:'Завершить', exact:true}).click();
      const download = await downloadPromise;
      assert.match(download.suggestedFilename(), /^TikTok_PC-01_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.webm$/);
      const filename = path.join(artifacts, `recording-${mobile ? 'mobile' : 'desktop'}.webm`);
      await download.saveAs(filename);
      assert.ok((await fs.stat(filename)).size > 1000);
      const videoBytes = (await fs.readFile(filename)).toString('base64');
      const metadata = await page.evaluate(async bytes => {
        const blob = await (await fetch(`data:video/webm;base64,${bytes}`)).blob();
        const video = document.createElement('video'); video.muted = true; video.src = URL.createObjectURL(blob);
        await new Promise((resolve, reject) => { video.onloadedmetadata = resolve; video.onerror = reject; });
        const dimensions = [video.videoWidth, video.videoHeight];
        if (!Number.isFinite(video.duration) || video.duration <= 0) throw new Error('Missing WebM duration');
        const duration = video.duration;
        await new Promise((resolve, reject) => {
          video.onseeked = resolve; video.onerror = reject;
          video.currentTime = duration / 2;
          setTimeout(() => reject(new Error('WebM seeking timed out')), 3000);
        });
        await video.play();
        await new Promise(resolve => setTimeout(resolve, 150));
        const result = {dimensions, time: video.currentTime, duration};
        video.pause(); URL.revokeObjectURL(video.src); return result;
      }, videoBytes);
      assert.deepEqual(metadata.dimensions, [640, 480]);
      assert.ok(metadata.time > metadata.duration / 2, 'Recorded video must seek and play');
      assert.ok(requests.some(url => url.searchParams.get('width') === '1920' && url.searchParams.get('quality') === '95'));
      await page.getByRole('button', {name:'Запись', exact:true}).waitFor();
      await start(); await page.waitForTimeout(500);
      let cancelledDownloads = 0;
      const cancelledDownload = () => cancelledDownloads++;
      page.on('download', cancelledDownload);
      await page.getByRole('button', {name:'Отмена', exact:true}).click();
      await page.getByRole('button', {name:'Запись', exact:true}).waitFor();
      await page.waitForTimeout(300);
      page.off('download', cancelledDownload);
      assert.equal(cancelledDownloads, 0, 'Cancel must not save a file');
      const chunks = await page.evaluate(async () => {
        const req = indexedDB.open('cmnc-screen-recordings', 1);
        const db = await new Promise(resolve => {req.onsuccess = () => resolve(req.result);});
        const count = db.transaction('chunks').objectStore('chunks').count();
        return new Promise(resolve => {count.onsuccess = () => {db.close(); resolve(count.result);};});
      });
      assert.equal(chunks, 0, 'Completed and cancelled chunks must be removed');
      await start();
      const automaticDownload = await page.waitForEvent('download', {timeout: 12000});
      await automaticDownload.saveAs(path.join(artifacts, `automatic-${mobile ? 'mobile' : 'desktop'}.webm`));
      await page.getByRole('button', {name:'Запись', exact:true}).waitFor();
      assert.deepEqual(errors, []);
      console.log('PASS', mobile ? 'mobile' : 'desktop', 'record, quality, pause/resume, playable WebM, naming, cancellation, disk cleanup, automatic time limit');
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
