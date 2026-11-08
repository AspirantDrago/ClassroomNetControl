const {chromium}=require(process.env.CMNC_PLAYWRIGHT_MODULE || 'playwright');const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CMNC_TEST_CHROMIUM_PATH || undefined,headless:true});
 try{for(const [role,mobile] of [['teacher',false],['admin',true],['superadmin',false]]){
  const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1400,height:1000}});const page=await context.newPage();const actions=[];
  const classroom={id:1,router_id:1,name:'Тест',subnet_cidr:'192.168.1.0/24',vlan_id:1};
  const device={id:1,classroom_id:1,mac_address:'00:11:22:33:44:55',inventory_name:'PC-01',static_ip:'192.168.1.10',row_index:1,column_index:1,wan_allowed:true,wan_protected:false,online:true};
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{const req=route.request();const p=new URL(req.url()).pathname;let data={};
   if(p==='/api/me')data={principal_type:'user',id:1,role,username:'Test',permissions:['classrooms:read:all','wan:control:all','devices:manage','classrooms:manage']};
   else if(p==='/api/classrooms')data=[classroom];else if(p.endsWith('/dashboard'))data={classroom,devices:[device],dynamic_devices:[],cameras:[]};
   else if(p==='/api/admin/routers')data=[];else if(p==='/api/build-info')data={version:'test'};
   else if(p.endsWith('/veyon/action')){actions.push(req.postDataJSON());data={accepted:true};}
   else if(p.includes('/veyon/frame'))return route.fulfill({status:503,json:{detail:'fixture'}});
   await route.fulfill({json:data});
  });
  await page.goto(process.env.CMNC_ACTIONS_TEST_URL || 'http://127.0.0.1:5188/');await page.locator('.device-open-button').click();
  await page.getByRole('tab',{name:'Действия',exact:true}).click();const panel=page.locator('#device-actions-panel');
  await panel.getByRole('button',{name:'Разбудить',exact:true}).waitFor();
  if(role!=='teacher')await panel.getByRole('button',{name:'Выполнить команду',exact:true}).waitFor();
  assert.equal(await panel.getByRole('button',{name:'Выполнить команду',exact:true}).count(),role==='teacher'?0:1);
  assert.equal(await panel.getByRole('button',{name:'Установить обновления и выключить',exact:true}).count(),role==='teacher'?0:1);
  await panel.getByRole('button',{name:'Выключить по истечению времени',exact:true}).click();
  let dialog=page.locator('dialog');await dialog.getByLabel('Часы',{exact:true}).fill('1');await dialog.getByLabel('Минуты',{exact:true}).fill('1');await dialog.getByLabel('Секунды',{exact:true}).fill('1');await dialog.getByRole('button',{name:'ОК',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('dialog'));assert.equal(actions.at(-1).seconds,3661);
  await panel.getByRole('button',{name:'Залогиниться',exact:true}).click();dialog=page.locator('dialog');await dialog.getByLabel('Логин',{exact:true}).fill('TEST\\user');await dialog.getByLabel('Пароль',{exact:true}).fill('temporary-fixture');await dialog.getByRole('button',{name:'ОК',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('dialog'));assert.equal(actions.at(-1).action,'login');
  await panel.getByRole('button',{name:'Разлогиниться',exact:true}).click();dialog=page.locator('dialog');await dialog.getByRole('button',{name:'Отмена',exact:true}).click();assert.equal(actions.at(-1).action,'login');
  await panel.getByRole('button',{name:'Сообщение',exact:true}).click();await page.locator('dialog textarea').fill('First\nSecond');await page.locator('dialog').getByRole('button',{name:'ОК',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('dialog'));assert.equal(actions.at(-1).text,'First\nSecond');
  await page.screenshot({path:require('node:path').join(require('node:os').tmpdir(),`actions-${role}.png`),fullPage:true});assert.deepEqual(errors,[]);
  console.log('PASS',role,mobile?'mobile':'desktop','groups, role visibility, timer, login, confirmation cancellation, multiline message');await context.close();
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
