/* Disposable backend + real browser. No live accounts or capture workers. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8786',folder=fs.mkdtempSync(path.join(os.tmpdir(),'cf-reception-filter-'));
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys;from pathlib import Path;from app.main import create_app;root=Path(sys.argv[1]);uvicorn.run(create_app(db_path=root/'db.sqlite',config_path=root/'config.json'),host='127.0.0.1',port=8786)",folder],{windowsHide:true,stdio:'pipe'});
 let browser,log='';server.stderr.on('data',x=>log+=x);
 try{
  for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,150));}
  assert.ok((await fetch(base+'/api/health')).ok,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const config=async()=>{const r=await fetch(base+'/api/inbox/filter');assert.ok(r.ok);return r.json();};
  const tasks=await (await fetch(base+'/api/tasks')).json(),drafts=await (await fetch(base+'/api/drafts')).json();
  await page.goto(base+'/#connections');
  const toggle=page.getByRole('switch',{name:'接收过滤'});await toggle.waitFor();
  await page.waitForFunction(()=>!document.querySelector('#receptionFilterToggle').disabled);
  assert.equal(await toggle.getAttribute('aria-checked'),'false');assert.equal(await page.locator('#receptionFilterStatus').innerText(),'已关闭');
  const copy=await page.locator('#connectionsView').innerText();assert.ok(!copy.includes('消息连接各自独立，任务统一整理。'));assert.ok(!copy.includes('仅在主动分析时调用模型；草稿需核对后创建待办。'));
  assert.deepEqual(await page.locator('#connectionsView .connection-row h2').allTextContents(),['QQ','微信','模型服务','接收过滤','自动整理','本地自动整理']);
  await page.route('**/api/inbox/filter',async route=>{if(route.request().method()==='PUT'){await new Promise(r=>setTimeout(r,500));}await route.continue();});
  await toggle.click();await page.waitForFunction(()=>document.querySelector('#receptionFilterStatus').textContent==='保存中…');assert.ok(await toggle.isDisabled());
  await page.waitForFunction(()=>document.querySelector('#receptionFilterToggle').getAttribute('aria-checked')==='true');assert.deepEqual(await config(),{enabled:true});
  await page.unroute('**/api/inbox/filter');await page.reload();await page.waitForFunction(()=>document.querySelector('#receptionFilterStatus').textContent==='已开启');
  await page.route('**/api/inbox/filter',route=>route.request().method()==='PUT'?route.fulfill({status:503,json:{detail:'测试保存失败，请重试。'}}):route.continue());
  await toggle.click();await page.waitForFunction(()=>document.querySelector('#receptionFilterError').textContent.includes('测试保存失败'));assert.equal(await toggle.getAttribute('aria-checked'),'true');assert.deepEqual(await config(),{enabled:true});
  await page.unroute('**/api/inbox/filter');await toggle.focus();await page.keyboard.press('Space');await page.waitForFunction(()=>document.querySelector('#receptionFilterToggle').getAttribute('aria-checked')==='false');assert.deepEqual(await config(),{enabled:false});
  await page.locator('[data-view=tasks]').click();
  await page.route('**/api/inbox/filter',route=>route.fulfill({status:503,json:{detail:'测试读取失败，请重试。'}}));
  await page.locator('[data-view=connections]').click();await page.locator('#receptionFilterRetry').waitFor();assert.ok(await toggle.isDisabled());assert.match(await page.locator('#receptionFilterError').innerText(),/测试读取失败/);
  await page.unroute('**/api/inbox/filter');await page.locator('#receptionFilterRetry').click();await page.waitForFunction(()=>!document.querySelector('#receptionFilterToggle').disabled);assert.equal(await page.locator('#receptionFilterRetry').isVisible(),false);
  const output='runtime/reception-filter-review';fs.mkdirSync(output,{recursive:true});
  await toggle.click();await page.waitForFunction(()=>document.querySelector('#receptionFilterStatus').textContent==='已开启');
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(150);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page overflow '+width);
   assert.ok(await toggle.evaluate(el=>{const row=el.closest('.connection-row');return row.scrollWidth<=row.clientWidth;}),'filter row overflow '+width);
   const control=await toggle.boundingBox();assert.ok(control.width>=40&&control.height>=24);
   if([390,1440].includes(width))await page.screenshot({path:output+'/settings-'+width+'.png',fullPage:true});
  }
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await toggle.evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
  await page.locator('[data-open-connection=qq]').click();assert.ok(await page.locator('#qqView').isVisible());await page.locator('[data-view=connections]').click();
  await page.locator('[data-open-connection=wechat]').click();assert.ok(await page.locator('#wechatView').isVisible());await page.locator('[data-view=connections]').click();
  await page.locator('#connectionModelBtn').click();assert.ok(await page.locator('#settingsDialog').isVisible());await page.keyboard.press('Escape');
  assert.deepEqual(await (await fetch(base+'/api/tasks')).json(),tasks);assert.deepEqual(await (await fetch(base+'/api/drafts')).json(),drafts);assert.deepEqual(errors,[]);
  console.log('PASS: default off, same settings layout, requested copy removed, real save and reload persistence, loading/failed save rollback/read failure retry, keyboard switch, five widths, reduced motion, connection navigation and model dialog, no task/draft changes or JS errors');
 }finally{if(browser)await browser.close();if(server.exitCode===null)server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
