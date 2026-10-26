/* Real browser + disposable DB: never opens live account data or capture processes. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8783',folder=fs.mkdtempSync(path.join(os.tmpdir(),'cf-trash-'));
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys;from pathlib import Path;from tests.workbench_app import make_app;uvicorn.run(make_app(Path(sys.argv[1])),host='127.0.0.1',port=8783)",folder],{windowsHide:true,stdio:'ignore'});
 let browser;
 const json=async url=>{const r=await fetch(base+url);assert.ok(r.ok);return r.json();};
 try{
  let ready=false;for(let i=0;i<80;i++){try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.locator('[data-view=messages]').click();await page.locator('[data-inbox-message]').first().waitFor();
  assert.deepEqual(await page.locator('[data-inbox-source]').allTextContents(),['全部','QQ','微信','手动导入','垃圾桶']);
  const initial=await json('/api/inbox?limit=100'),tasks=await json('/api/tasks'),drafts=await json('/api/drafts');
  const row=initial.messages.find(m=>m.source==='wechat'&&m.extraction_status==='ignored'),id=row.id,card=()=>page.locator('[data-inbox-message="'+id+'"]');
  await page.locator('[data-inbox-source=wechat]').click();await page.locator('#inboxStatus').selectOption('ignored');await card().waitFor();
  const trashURL='**/api/inbox/'+id+'/trash';
  await page.route(trashURL,async route=>{await new Promise(r=>setTimeout(r,500));await route.continue();});
  await card().locator('[data-inbox-action=trash]').click();await page.waitForTimeout(80);assert.ok(await card().locator('[data-inbox-action=trash]').isDisabled(),'busy feedback');
  await page.waitForFunction(id=>!document.querySelector('[data-inbox-message="'+id+'"]'),id);await page.unroute(trashURL);
  await page.locator('[data-inbox-source=trash]').click();await card().waitFor();assert.equal(await page.locator('#inboxStatus').inputValue(),'all');
  assert.equal(await card().locator('[data-inbox-action=analyze],[data-inbox-action=manual],[data-inbox-action=review],[data-inbox-action=trash]').count(),0);
  assert.match(await card().innerText(),/已忽略/);await card().locator('summary').click();assert.match(await card().innerText(),/无需处理的活动闲聊/);
  const out='runtime/inbox-trash-review';fs.mkdirSync(out,{recursive:true});await page.waitForTimeout(450);await page.screenshot({path:out+'/trash-1440.png',fullPage:false});
  await page.reload();await page.locator('[data-view=messages]').click();await page.locator('[data-inbox-source=trash]').click();await card().waitFor();
  const restoreURL='**/api/inbox/'+id+'/restore';await page.route(restoreURL,r=>r.fulfill({status:503,json:{detail:'测试恢复失败，请重试'}}));
  await card().locator('[data-inbox-action=restore]').click();await page.waitForFunction(()=>document.querySelector('#inboxError').textContent.includes('测试恢复失败'));assert.ok(await card().isVisible());
  assert.equal((await json('/api/inbox?folder=trash')).total,1);await page.unroute(restoreURL);
  await card().locator('[data-inbox-action=restore]').click();await page.waitForFunction(()=>document.querySelector('#inboxCount').textContent==='共 0 条消息');
  await page.locator('[data-inbox-source=wechat]').click();await page.locator('#inboxStatus').selectOption('ignored');await card().waitFor();
  await page.route(trashURL,r=>r.fulfill({status:409,json:{detail:'测试移入失败，请重试'}}));await card().locator('[data-inbox-action=trash]').click();await page.waitForFunction(()=>document.querySelector('#inboxError').textContent.includes('测试移入失败'));assert.ok(await card().isVisible());await page.unroute(trashURL);
  await page.locator('[data-inbox-source=all]').click();await page.locator('#inboxStatus').selectOption('all');await page.locator('#inboxNext').click();await page.waitForFunction(()=>document.querySelector('#inboxPage').textContent==='第 2 页');
  const linked=initial.messages.find(m=>m.task_count),linkedCard=page.locator('[data-inbox-message="'+linked.id+'"]');await linkedCard.waitFor();await linkedCard.locator('[data-inbox-action=trash]').click();
  await page.locator('[data-inbox-source=trash]').click();await linkedCard.waitFor();await linkedCard.locator('[data-inbox-task]').first().click();await page.locator('#taskDetailTitle').waitFor();await page.locator('#closeTaskDetail').click();
  assert.deepEqual(await json('/api/tasks'),tasks);assert.deepEqual(await json('/api/drafts'),drafts);
  await linkedCard.locator('[data-inbox-action=restore]').click();await page.waitForFunction(()=>document.querySelector('#inboxCount').textContent==='共 0 条消息');
  await page.locator('[data-inbox-source=all]').click();await page.locator('[data-inbox-message]').first().waitFor();assert.equal((await json('/api/inbox')).total,initial.total);
  // Remove the only item on the last page: list should return to the previous page.
  const all=(await json('/api/inbox?limit=100')).messages;for(const m of all.slice(31))assert.ok((await fetch(base+'/api/inbox/'+m.id+'/trash',{method:'POST'})).ok);
  await page.locator('#refreshInbox').click();await page.locator('#inboxNext').click();await page.waitForFunction(()=>document.querySelector('#inboxPage').textContent==='第 2 页');assert.equal(await page.locator('[data-inbox-message]').count(),1);
  await page.locator('[data-inbox-action=trash]').click();await page.waitForFunction(()=>document.querySelector('#inboxPage').textContent==='第 1 页');assert.equal(await page.locator('[data-inbox-message]').count(),30);
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:900});await page.locator('[data-inbox-source=trash]').click();await page.waitForFunction(()=>!document.querySelector('#unifiedMessages').hasAttribute('aria-busy'));await page.waitForTimeout(150);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);assert.ok(await page.locator('[data-inbox-source=trash]').isVisible());
   if(width===390)await page.screenshot({path:out+'/trash-390.png',fullPage:false});
   await page.locator('[data-inbox-source=all]').click();await page.waitForFunction(()=>!document.querySelector('#unifiedMessages').hasAttribute('aria-busy'));
  }
  assert.deepEqual(errors,[]);console.log('PASS: trash tab, busy feedback, source/status reset, move/restore, reload persistence, failures remain visible, raw text and linked task access, business data protection, last-page fallback and 5 viewport widths. Synthetic data only.');
 }finally{if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});fs.rmSync(folder,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
