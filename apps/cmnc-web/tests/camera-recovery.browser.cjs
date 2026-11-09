const {chromium}=require(process.env.CMNC_PLAYWRIGHT_MODULE || 'playwright');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:process.env.CMNC_TEST_CHROMIUM_PATH || undefined,headless:true});try{
 for(const mobile of [false,true]){
  const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1360,height:900}});const page=await context.newPage();let opened=0,closed=0;
  const room={id:1,router_id:1,name:'Fixture',subnet_cidr:'192.168.1.0/24'};
  await page.route('**/api/**',async route=>{const request=route.request();const p=new URL(request.url()).pathname;let data={};
   if(p==='/api/me')data={principal_type:'user',id:1,role:'admin',username:'Fixture',classroom_ids:[1],permissions:['classrooms:read:all','wan:control:all','devices:manage','classrooms:manage']};
   else if(p==='/api/classrooms')data=[room];else if(p==='/api/admin/routers')data=[];else if(p==='/api/build-info')data={version:'fixture'};
   else if(p.endsWith('/dashboard'))data={classroom:room,devices:[],dynamic_devices:[],cameras:[{id:1,name:'Fixture',enabled:true,qualities:['sub'],default_quality:'sub'}]};
   else if(p.endsWith('/camera/sessions')||p.endsWith('/cameras/1/session')||p.endsWith('/cameras/1/sessions')){opened++;data={session_id:`fixture-${opened}`,url:`/api/camera/sessions/fixture-${opened}/hls/index.m3u8`,mode:'hls',quality:'sub'};}
   else if(request.method()==='DELETE'&&p.includes('/camera/sessions/')){closed++;return route.fulfill({status:204});}
   else if(p.endsWith('.m3u8'))return route.fulfill({status:503,json:{detail:'Simulated camera offline'}});
   await route.fulfill({json:data});
  });
  await page.clock.install();await page.goto(process.env.CMNC_CAMERA_TEST_URL || 'http://127.0.0.1:5188');await page.getByRole('button',{name:/Камера: Fixture/}).click();
  await page.locator('video').waitFor();assert.equal(opened,1);
  await page.clock.fastForward(35000);await page.clock.runFor(5001);
  await page.waitForFunction(()=>document.querySelector('video')!==null);
  for(let i=0;i<20&&opened<2;i++)await new Promise(resolve=>setTimeout(resolve,100));
  assert.ok(opened>=2,'Stalled playback must recreate its camera session');assert.ok(closed>=1,'Old session must be released');
  await page.getByRole('button',{name:/Камера: Fixture/}).click();
  for(let i=0;i<20&&closed<2;i++)await new Promise(resolve=>setTimeout(resolve,100));
  assert.ok(closed>=2,'Closing the panel must release the replacement session');
  console.log('PASS',mobile?'mobile':'desktop','offline playback rotates stale session and closing panel releases it');await context.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
