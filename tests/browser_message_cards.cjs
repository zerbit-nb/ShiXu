/* Message recommendation layout: isolated Chromium and synthetic messages only. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8784',folder=fs.mkdtempSync(path.join(os.tmpdir(),'cf-cards-'));
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys;from pathlib import Path;from tests.workbench_app import make_app;uvicorn.run(make_app(Path(sys.argv[1])),host='127.0.0.1',port=8784)",folder],{windowsHide:true,stdio:'ignore'});
 let browser;
 try{
  let ready=false;for(let i=0;i<80;i++){try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.locator('[data-view=messages]').click();await page.locator('[data-inbox-message]').first().waitFor();
  const out='runtime/message-card-review';fs.mkdirSync(out,{recursive:true});
  await page.locator('[data-inbox-source=wechat]').click();await page.locator('#inboxStatus').selectOption('pending');
  const card=page.locator('[data-inbox-message]').first();await card.locator('[data-inbox-action=manual]').waitFor();
  if(process.env.CAMPUSFLOW_CARD_BASELINE){await card.screenshot({path:out+'/before-card.png'});console.log('PASS: baseline card captured');return;}
  assert.equal(await page.locator('[data-inbox-action=ignore]').count(),0,'remove duplicate ignore action');
  assert.deepEqual(await card.locator('[data-inbox-action]').allTextContents(),['删除','手动整理','分析通知']);
  assert.equal(await card.locator('.message-heading .message-state').count(),0);
  assert.match(await card.locator('.message-footer .message-state').innerText(),/待处理/);
  assert.match(await card.locator('[data-inbox-action=trash]').getAttribute('title'),/垃圾桶.*恢复/);
  const id=await card.getAttribute('data-inbox-message');
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(200);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);
   const sizes=await card.locator('[data-inbox-action]').evaluateAll(els=>els.map(e=>({height:e.getBoundingClientRect().height,radius:getComputedStyle(e).borderRadius,font:getComputedStyle(e).fontSize})));
   assert.ok(sizes.every(s=>s.height===sizes[0].height&&s.radius===sizes[0].radius&&s.font===sizes[0].font),'consistent controls '+width);
   assert.ok(await card.locator('.message-footer').evaluate(e=>{const r=e.getBoundingClientRect();return [...e.querySelectorAll('button')].every(b=>{const a=b.getBoundingClientRect();return a.left>=r.left&&a.right<=r.right+1;});}),'buttons within footer '+width);
   if(width===1440){assert.ok(await card.evaluate(e=>e.querySelector('.message-state').getBoundingClientRect().right<e.querySelector('.message-actions').getBoundingClientRect().left));await card.screenshot({path:out+'/after-card-1440.png'});}
   if(width===390)await card.screenshot({path:out+'/after-card-390.png'});
  }
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await card.locator('[data-inbox-action=analyze]').evaluate(e=>getComputedStyle(e).transitionDuration),'0s');
  await card.locator('summary').focus();await page.keyboard.press('Enter');assert.ok(await card.locator('details').getAttribute('open')!==null);await page.keyboard.press('Tab');
  assert.ok(await card.locator('[data-inbox-action=trash]').evaluate(e=>e===document.activeElement),'keyboard access');
  await page.keyboard.press('Enter');await page.waitForFunction(id=>!document.querySelector('[data-inbox-message="'+id+'"]'),id);
  await page.locator('[data-inbox-source=trash]').click();const trashed=page.locator('[data-inbox-message="'+id+'"]');await trashed.waitFor();
  assert.deepEqual(await trashed.locator('[data-inbox-action]').allTextContents(),['恢复到收件箱']);await trashed.locator('[data-inbox-action=restore]').click();await page.waitForFunction(()=>document.querySelector('#inboxCount').textContent==='共 0 条消息');
  await page.locator('[data-inbox-source=all]').click();await page.locator('#inboxStatus').selectOption('failed');await page.locator('[data-inbox-action=analyze]').first().waitFor();assert.match(await page.locator('.message-state').first().innerText(),/分析失败/);
  const received=(await (await fetch(base+'/api/inbox?source=wechat&status=pending')).json()).messages[0];
  await page.route('**/api/inbox?*',r=>r.fulfill({json:{total:1,messages:[{...received,extraction_status:'extracting'}]}}));
  await page.locator('#refreshInbox').click();await page.waitForFunction(()=>document.querySelector('.message-state')?.textContent.includes('正在分析'));
  assert.ok(await page.locator('[data-inbox-action=trash]').isDisabled());assert.equal(await page.locator('[data-inbox-action=analyze]').count(),0);
  assert.deepEqual(errors,[]);console.log('PASS: recommendation card footer hierarchy, consistent buttons at 5 widths, no ignore, recoverable delete, keyboard access, failure/analyzing states and reduced motion; synthetic data.');
 }finally{if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});fs.rmSync(folder,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
