/* Switch motion and child consent, using a disposable backend and fixtures only. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'shixu-settings-motion-')),base='http://127.0.0.1:8803';
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const source="import sys,uvicorn;from pathlib import Path;from tests.workbench_app import make_app;a=make_app(Path(sys.argv[1]));s=uvicorn.Server(uvicorn.Config(a,host='127.0.0.1',port=8803));a.add_api_route('/__test__/stop',lambda:setattr(s,'should_exit',True),methods=['POST']);s.run()";
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',source,folder],{windowsHide:true,stdio:'pipe'});
 let log='',browser;server.stderr.on('data',x=>log+=x);
 const out=path.resolve('runtime/connections-motion-review');fs.mkdirSync(out,{recursive:true});
 try{
  let ready=false;for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error(log);try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],localWrites=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='PUT'&&r.url().endsWith('/api/automation'))localWrites.push(r.postDataJSON());});
  await page.goto(base+'/#connections');await page.waitForFunction(()=>!document.querySelector('#automationToggle')?.disabled);
  const master=page.locator('#automationToggle'),local=page.locator('#automationLocalToggle');
  assert.ok(await local.isDisabled());assert.equal(await local.getAttribute('aria-checked'),'false');assert.equal(await page.locator('#automationLocalStatus').textContent(),'不允许');
  await local.evaluate(el=>el.click());await page.evaluate(()=>saveAutomation('allow_local'));assert.equal(localWrites.length,0);
  const typography=await page.evaluate(()=>['automationTitle','automationLocalTitle'].map(id=>{const s=getComputedStyle(document.getElementById(id));return [s.fontSize,s.fontWeight,s.lineHeight,s.fontFamily]}));
  assert.deepEqual(typography[0],typography[1]);
  const copy={receptionFilterHint:'简短应答移入垃圾桶，可恢复',automationHint:'QQ、微信新通知转待办，存疑留收件箱',automationLocalHint:'需运行 LM Studio，占用本机资源',historyHint:'补收已选群今天的通知，自动整理沿用现有开关',taskReminderHint:'前台卡片，托盘通知；开启后可设时间'};
  for(const [id,value]of Object.entries(copy))assert.equal(await page.locator('#'+id).textContent(),value);
  // Inspect the actual intermediate rendered frame, not just animation names.
  const motion=await page.evaluate(()=>{
   renderReceptionFilter(true);
   const thumb=document.querySelector('#receptionFilterToggle>span'),animation=thumb.getAnimations()[0];
   const frames=animation.effect.getKeyframes();animation.pause();animation.currentTime=190;
   const intermediate=new DOMMatrix(getComputedStyle(thumb).transform).m41;
   const label=document.querySelector('#receptionFilterStatus');
   const result={duration:animation.effect.getTiming().duration,easing:animation.effect.getTiming().easing,frames:frames.map(f=>f.transform),intermediate,text:label.textContent,previous:label.dataset.previous,labelAnimation:getComputedStyle(label.firstElementChild).animationName};
   animation.finish();return result;
  });
  assert.equal(motion.duration,350);assert.match(motion.easing,/1\.35/);assert.ok(motion.frames.includes('translateX(17px)'));assert.ok(motion.intermediate>0&&motion.intermediate<19);assert.equal(motion.text,'已开启');assert.equal(motion.previous,'已关闭');assert.equal(motion.labelAnimation,'settings-status-in');
  await page.waitForTimeout(400);
  assert.ok(await page.locator('#receptionFilterStatus').evaluate(el=>!el.hasAttribute('data-previous')));
  await page.evaluate(()=>renderReceptionFilter(false));await page.waitForTimeout(400);
  await master.click();await page.waitForFunction(()=>!document.querySelector('#automationLocalToggle').disabled);
  assert.equal(await page.locator('#automationLocalStatus').textContent(),'已关闭');
  await local.click();await page.waitForFunction(()=>document.querySelector('#automationLocalToggle').getAttribute('aria-checked')==='true');
  assert.equal(await page.locator('#automationLocalStatus').textContent(),'已开启');
  await page.route('**/api/automation',r=>r.request().method()==='PUT'?r.fulfill({status:503,json:{detail:'测试保存失败'}}):r.continue());
  await master.click();await page.getByText('测试保存失败',{exact:true}).waitFor();assert.equal(await master.getAttribute('aria-checked'),'true');assert.equal(await local.getAttribute('aria-checked'),'true');assert.ok(await local.isEnabled());
  await page.unroute('**/api/automation');
  await master.click();await page.waitForFunction(()=>!document.querySelector('#automationToggle').disabled);
  assert.ok(await local.isDisabled());assert.equal(await local.getAttribute('aria-checked'),'false');
  const disabled=await(await fetch(base+'/api/automation')).json();assert.equal(disabled.allow_local,false);
  await page.reload();await page.waitForFunction(()=>!document.querySelector('#automationToggle')?.disabled);assert.ok(await local.isDisabled());
  await master.click();await page.waitForFunction(()=>!document.querySelector('#automationLocalToggle').disabled);assert.equal(await local.getAttribute('aria-checked'),'false','parent re-enable requires fresh child consent');
  await page.locator('.settings-help summary').click();assert.match(await page.locator('.settings-help').innerText(),/云端会发送新消息文本，可能收费/);
  await page.locator('.settings-help summary').click();
  // Fast state changes cancel old labels and never replay an earlier value.
  await page.evaluate(()=>{const label=document.querySelector('#historyStatus');setSettingsStatus(label,'已开启');setSettingsStatus(label,'已关闭');setSettingsStatus(label,'读取失败');});
  await page.waitForTimeout(400);assert.equal(await page.locator('#historyStatus').textContent(),'读取失败');
  await page.evaluate(()=>renderHistory(historyConfig));
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(300);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);}
  await page.waitForFunction(()=>!document.querySelector('#toastRegion .toast'));
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await page.screenshot({path:out+'/settings-1440.png'});
  await page.evaluate(()=>renderReceptionFilter(true));await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('#receptionFilterToggle>span').evaluate(el=>el.getAnimations().length),0);
  const reduced=await page.evaluate(()=>{renderReceptionFilter(false);return {thumb:document.querySelector('#receptionFilterToggle>span').getAnimations().length,label:document.querySelector('#receptionFilterStatus').classList.contains('is-changing')};});
  assert.equal(reduced.thumb,0);assert.equal(reduced.label,false);
  assert.deepEqual(errors,[]);
  console.log('PASS: 350ms overshoot frames; soft label transition; rapid update cleanup; reduced motion cancellation; child disabled/reset/persistence/re-consent; save rollback; matching typography/copy; 5 widths. Screenshots: '+out);
 }finally{
  if(browser)await browser.close();const exited=server.exitCode===null?new Promise(r=>server.once('exit',r)):Promise.resolve();
  try{await fetch(base+'/__test__/stop',{method:'POST'});}catch{server.kill();}
  await exited;fs.rmSync(folder,{recursive:true,force:true,maxRetries:10,retryDelay:100});
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
