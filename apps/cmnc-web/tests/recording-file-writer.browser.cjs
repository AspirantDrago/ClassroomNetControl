const { chromium } = require(process.env.CMNC_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ executablePath:process.env.CMNC_TEST_CHROMIUM_PATH || undefined, headless:true });
  try {
    const context = await browser.newContext();
    await context.addInitScript(() => {
      window.recordingTest = {parts:[], closed:false, aborted:false, filename:null};
      Object.defineProperty(window, 'showSaveFilePicker', {value: async options => {
        window.recordingTest.filename = options.suggestedName;
        return {createWritable:async () => ({
          write: async blob => {await new Promise(resolve=>setTimeout(resolve,20)); window.recordingTest.parts.push(blob);},
          close: async () => {window.recordingTest.closed=true;},
          abort: async () => {window.recordingTest.aborted=true;},
        })};
      }});
      const supported = MediaRecorder.isTypeSupported.bind(MediaRecorder);
      MediaRecorder.isTypeSupported = type => type.includes('vp8') && supported(type);
    });
    const page = await context.newPage();
    await page.route('**/api/**', async route => route.fulfill({contentType:'image/svg+xml', body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="green"/></svg>'}));
    await page.goto(`${process.env.CMNC_RECORDING_TEST_URL || 'http://127.0.0.1:5188'}/?veyon_device=1&veyon_device_name=PC-01&veyon_classroom_name=TikTok`);
    await page.waitForFunction(()=>!Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='Запись')?.disabled);
    const start=async()=>{
      await page.getByRole('button',{name:'Запись',exact:true}).click();
      assert.match(await page.getByRole('dialog').textContent(), /WebM \/ VP8/);
      await page.getByRole('button',{name:'Начать запись'}).click();
      await page.getByRole('timer').waitFor();
    };
    await start(); await page.waitForTimeout(1200);
    await page.getByRole('button',{name:'Завершить',exact:true}).click();
    await page.waitForFunction(()=>window.recordingTest.closed);
    const result=await page.evaluate(async()=>{
      const test=window.recordingTest;
      const blob=new Blob(test.parts,{type:'video/webm'});
      const video=document.createElement('video');video.src=URL.createObjectURL(blob);
      await new Promise((resolve,reject)=>{video.onloadedmetadata=resolve;video.onerror=reject;});
      const dimensions=[video.videoWidth,video.videoHeight];URL.revokeObjectURL(video.src);
      return {filename:test.filename,size:blob.size,dimensions};
    });
    assert.match(result.filename,/^TikTok_PC-01_.*\.webm$/);assert.ok(result.size>500);assert.deepEqual(result.dimensions,[640,480]);
    await start(); await page.waitForTimeout(400);
    await page.getByRole('button',{name:'Отмена',exact:true}).click();
    await page.waitForFunction(()=>window.recordingTest.aborted);
    await page.getByRole('button',{name:'Запись',exact:true}).waitFor();
    // Verify that the recording limit also closes a direct file writer.
    await page.evaluate(()=>{window.recordingTest.closed=false;});
    await start(); await page.waitForTimeout(500);
    // Existing active recording is automatically saved on the configured limit.
    await page.waitForFunction(()=>window.recordingTest.closed,{timeout:10000});
    console.log('PASS direct file writer, codec fallback to VP8, playable recording, cancellation/abort, automatic file close');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
