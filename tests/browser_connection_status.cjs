/* Disposable server and mocked connection states; never logs in or starts capture. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8782',folder=fs.mkdtempSync(path.join(os.tmpdir(),'cf-status-'));
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys;from pathlib import Path;from tests.workbench_app import make_app;uvicorn.run(make_app(Path(sys.argv[1])),host='127.0.0.1',port=8782)",folder],{windowsHide:true,stdio:'ignore'});
 let browser;
 try{
  let ready=false;for(let i=0;i<80;i++){try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  let qq={state:'ready'},wx={state:'listening',has_account:true,group_name:'测试群'},failQQ=false,delayQQ=0,qqCalls=0,wxCalls=0;
  const mutations=[];page.on('request',r=>{if(r.method()!=='GET')mutations.push(r.url());});
  await page.route('**/api/qq/status',async route=>{qqCalls++;const data={...qq},fail=failQQ;await new Promise(r=>setTimeout(r,delayQQ));await route.fulfill({status:fail?503:200,json:fail?{detail:'fixture failure'}:data});});
  await page.route('**/api/wechat/status',route=>{wxCalls++;return route.fulfill({json:wx});});
  await page.goto(base);await page.waitForLoadState('networkidle');
  assert.equal(await page.locator('#connectionShortcuts [data-connection=qq]').count(),1,'QQ global status entry must exist');
  const q=page.locator('[data-connection=qq]'),w=page.locator('[data-connection=wechat]'),refresh=page.locator('#refreshConnections');
  const expectStatus=async(el,text,tone)=>{await page.waitForFunction(({selector,text})=>document.querySelector(selector+' .connection-state')?.textContent===text,{selector:'[data-connection='+await el.getAttribute('data-connection')+']',text});assert.equal(await el.getAttribute('data-tone'),tone);};
  await expectStatus(q,'正常','success');await expectStatus(w,'正常','success');assert.match(await q.getAttribute('title'),/上报配置/);
  for(const [state,label,tone] of [['disabled','已停用','neutral'],['qq_offline','未登录','warning'],['not_running','未运行','warning'],['report_mismatch','配置异常','danger'],['auth_failed','认证失败','danger'],['exited','已停用','neutral'],['exit_failed','退出异常','danger'],['future','状态未知','warning']]){qq={state};await refresh.click();await expectStatus(q,label,tone);}
  for(const [state,label,tone] of [['paused','已停用','neutral'],['starting','连接中','warning'],['waiting','等待微信','warning'],['stopping','暂停中','warning'],['error','采集异常','danger'],['listening','正常','success']]){wx={state,has_account:true,group_name:'测试群'};await refresh.click();await expectStatus(w,label,tone);}
  wx={state:'paused',has_account:false};await refresh.click();await expectStatus(w,'未配置','neutral');
  qq={state:'ready'};wx={state:'listening',has_account:true,group_name:'测试群'};await refresh.click();await expectStatus(q,'正常','success');
  failQQ=true;await refresh.click();await expectStatus(q,'检测失败','danger');await expectStatus(w,'正常','success');
  failQQ=false;delayQQ=500;await refresh.click();assert.ok(await refresh.isDisabled());await expectStatus(q,'正常','success');await page.waitForFunction(()=>!document.querySelector('#refreshConnections').disabled);delayQQ=0;
  // A slow periodic response must not overwrite a newer action result.
  delayQQ=600;qq={state:'ready'};await refresh.click();await page.waitForTimeout(100);await page.evaluate(()=>document.dispatchEvent(new CustomEvent('connection-status',{detail:{source:'qq',status:{state:'exited'}}})));await expectStatus(q,'已停用','neutral');await page.waitForTimeout(700);await expectStatus(q,'已停用','neutral');delayQQ=0;
  qq={state:'qq_offline'};const before=qqCalls;await page.waitForFunction(count=>document.querySelector('[data-connection=qq] .connection-state')?.textContent==='未登录',before,{timeout:20000});assert.ok(qqCalls>before,'periodic refresh on task page');
  assert.deepEqual(mutations,[],'global status must remain read-only');
  await q.click();assert.ok(await page.locator('#qqView').isVisible());await w.click();assert.ok(await page.locator('#wechatView').isVisible());
  await page.locator('[data-view=inbox]').click();
  fs.mkdirSync('runtime/connection-status-review',{recursive:true});
  qq={state:'qq_offline'};await refresh.click();await expectStatus(q,'未登录','warning');
  const textColors=await page.locator('.connection-state').evaluateAll(elements=>elements.map(e=>getComputedStyle(e).color));assert.equal(textColors[0],textColors[1],'status text should share neutral color');
  const nameColors=await page.locator('.connection-name').evaluateAll(elements=>elements.map(e=>getComputedStyle(e).color));assert.equal(nameColors[0],nameColors[1],'platform names should share color');
  for(const entry of [q,w]){assert.equal(await entry.locator('img,.connection-avatar').count(),0);assert.ok(await entry.evaluate(e=>{const name=e.querySelector('.connection-name').getBoundingClientRect(),state=e.querySelector('.connection-state').getBoundingClientRect();return name.right<=state.left;}),'name/status order');}
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(250);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);for(const el of [q,w,refresh])assert.ok(await el.isVisible());assert.ok(await q.locator('.connection-state').evaluate(e=>e.scrollWidth<=e.clientWidth),'status clipped '+width);if(width===390||width===1440){await page.screenshot({path:'runtime/connection-status-review/status-'+width+'.png',fullPage:true});await page.locator('.connection-overview').screenshot({path:'runtime/connection-status-review/overview-'+width+'.png'});}}
  assert.deepEqual(errors,[]);console.log('PASS: global QQ/WeChat states, unknown/error/independent failure/recovery, busy feedback, stale response protection, periodic refresh outside connection pages, read-only behavior, navigation and 5 widths. Mocked connections only.');
 }finally{if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});fs.rmSync(folder,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
