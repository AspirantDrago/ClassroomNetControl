const {chromium}=require(process.env.CMNC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.CMNC_TEST_CHROMIUM_PATH||undefined});let count=0;
try{for(const width of [390,1440]){const page=await browser.newPage({viewport:{width,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));let writes=[];
const routers=[1,2].map(id=>({id,name:'Router '+id,api_host:'192.168.'+id+'.1',api_port:80,api_use_ssl:false,api_verify_tls:false,api_username:'cmnc',is_enabled:true,poll_enabled:true,sync_enabled:true,poll_interval_seconds:10,veyon_demo_host:id===1?'192.168.10.11':'cmnc.branch.local',veyon_demo_port:id===1?11400:21400}));
await page.route('**/api/**',async route=>{const req=route.request(),path=new URL(req.url()).pathname;let data={};
if(path==='/api/me')data={principal_type:'user',id:1,role:'superadmin',display_name:'Admin',permissions:['classrooms:read:all','classrooms:manage','devices:manage','wan:control:all']};
else if(path==='/api/classrooms')data=[];
else if(path==='/api/admin/routers/status')data=routers.map(router=>({router,services:[]}));
else if(path==='/api/admin/routers'&&req.method()==='GET')data=routers;
else if(path==='/api/admin/routers'&&req.method()==='POST'){writes.push(req.postDataJSON());data={id:3,...writes.at(-1)};}
else if(path==='/api/admin/routers/2'&&req.method()==='PATCH'){writes.push(req.postDataJSON());data={...routers[1],...writes.at(-1)};}
else if(path.startsWith('/api/admin/veyon/keys/'))data={configured:false,key_name:'CMNC'};
else if(path==='/api/build-info')data={version:'test'};
await route.fulfill({json:data});});
await page.goto(process.env.CMNC_ACTIONS_TEST_URL||'http://127.0.0.1:5188');await page.getByRole('button',{name:'Открыть меню',exact:true}).click();await page.getByRole('button',{name:'MikroTik',exact:true}).click();
await page.getByRole('row').filter({hasText:'Router 2'}).getByRole('button',{name:'Редактировать',exact:true}).click();const modal=page.locator('.routers-modal');assert.equal(await modal.getByLabel('Сервер демонстрации CMNC',{exact:true}).inputValue(),'cmnc.branch.local');assert.equal(await modal.getByLabel('Порт демонстрации CMNC',{exact:true}).inputValue(),'21400');await modal.getByLabel('Сервер демонстрации CMNC',{exact:true}).fill('cmnc.newbranch.local');await modal.getByLabel('Порт демонстрации CMNC',{exact:true}).fill('31400');await modal.getByRole('button',{name:'Сохранить',exact:true}).click();await modal.waitFor({state:'detached'});assert.equal(writes[0].veyon_demo_host,'cmnc.newbranch.local');assert.equal(writes[0].veyon_demo_port,31400);assert.equal(routers[0].veyon_demo_host,'192.168.10.11');
await page.getByRole('button',{name:'Добавить MikroTik',exact:true}).click();assert.equal(await modal.getByLabel('Сервер демонстрации CMNC',{exact:true}).inputValue(),'');assert.equal(await modal.getByLabel('Порт демонстрации CMNC',{exact:true}).inputValue(),'11400');await modal.getByLabel('Название',{exact:true}).fill('New');await modal.getByLabel('Host',{exact:true}).fill('192.168.3.1');await modal.getByLabel('Пароль',{exact:true}).fill('test-only');await modal.getByLabel('Сервер демонстрации CMNC',{exact:true}).fill('192.168.10.11');await modal.getByRole('button',{name:'Сохранить',exact:true}).click();await modal.waitFor({state:'detached'});assert.equal(writes[1].veyon_demo_host,'192.168.10.11');assert.equal(writes[1].veyon_demo_port,11400);assert.deepEqual(errors,[]);await page.close();count++;}
console.log('PASS '+count+' viewport cases: per-router endpoint editing, independent values, create defaults and typed port persistence');}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
