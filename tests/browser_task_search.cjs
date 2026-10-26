/* Real Chromium + isolated data, no real messages, cloud requests or capture. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8785',folder=fs.mkdtempSync(path.join(os.tmpdir(),'cf-search-'));
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys;from pathlib import Path;from tests.workbench_app import make_app;uvicorn.run(make_app(Path(sys.argv[1])),host='127.0.0.1',port=8785)",folder],{windowsHide:true,stdio:'ignore'});
 let browser;
 try{
  let ready=false;for(let i=0;i<80;i++){try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()!=='GET')writes.push(r.url());});
  await page.goto(base);await page.locator('.task-row').first().waitFor();
  const out='runtime/task-search-review';fs.mkdirSync(out,{recursive:true});const search=page.locator('#taskSearch'),panel=page.locator('#taskSearchPanel'),options=()=>page.locator('#taskSearchResults [role=option]');
  if(process.env.CAMPUSFLOW_SEARCH_BASELINE){await page.screenshot({path:out+'/before.png'});console.log('PASS: baseline search captured');return;}
  assert.equal(await search.getAttribute('role'),'combobox');await search.focus();await panel.waitFor();assert.equal(await options().count(),5);assert.ok(await page.locator('#clearTaskSearch').isHidden());
  await search.fill('课程');await page.waitForFunction(()=>document.querySelectorAll('#taskSearchResults [role=option]').length===4);assert.equal(await page.locator('.task-row').count(),4);
  await search.fill('教学楼不存在');await page.getByText('没有找到匹配的任务',{exact:true}).first().waitFor();assert.equal(await options().count(),0);await page.screenshot({path:out+'/search-empty.png'});
  await page.locator('#clearTaskSearch').click();assert.equal(await search.inputValue(),'');assert.ok(await search.evaluate(e=>e===document.activeElement));assert.equal(await options().count(),5);
  await search.fill('学生服务中心');assert.equal(await options().count(),1);assert.match(await options().first().innerText(),/志愿服务/);
  await page.keyboard.press('ArrowDown');const active=await search.getAttribute('aria-activedescendant');assert.ok(active);assert.equal(await page.locator('#'+active).getAttribute('aria-selected'),'true');
  await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('#taskDetailTitle')&&!document.querySelector('#taskDetailTitle').textContent.includes('正在读取'));assert.match(await page.locator('#taskDetailTitle').innerText(),/志愿服务/);assert.ok(await panel.isHidden());
  await page.locator('#closeTaskDetail').click();assert.ok(await search.evaluate(e=>e===document.activeElement));await search.fill('软件工程');await options().first().click();await page.waitForFunction(()=>document.querySelector('#taskDetailTitle')&&!document.querySelector('#taskDetailTitle').textContent.includes('正在读取'));await page.keyboard.press('Escape');
  await page.locator('#clearTaskSearch').click();await page.keyboard.press('ArrowUp');assert.ok(await search.getAttribute('aria-activedescendant'));await page.keyboard.press('Escape');assert.ok(await panel.isHidden());assert.equal(await search.inputValue(),'');
  await search.click();await panel.waitFor();await page.locator('#taskPageTitle').click();assert.ok(await panel.isHidden());
  await search.fill('<img src=x>');assert.equal(await page.locator('#taskSearchPanel img').count(),0);await page.locator('#clearTaskSearch').click();
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:1000});await search.click();await panel.waitFor();await page.waitForTimeout(200);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);
   assert.ok(await panel.evaluate(e=>{const p=e.getBoundingClientRect(),s=e.closest('.task-search').getBoundingClientRect();return Math.abs(p.left-s.left)<0.5&&Math.abs(p.right-s.right)<0.5;}),'search and panel edges align '+width);
   assert.ok(await panel.evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;}),'panel bounds '+width);
   assert.ok(await panel.evaluate(e=>{const r=e.getBoundingClientRect();return document.elementFromPoint(r.left+20,r.top+25)?.closest('#taskSearchPanel')===e;}),'not hidden below list '+width);
   if(width===390||width===1440){
    assert.ok(await panel.evaluate(e=>e.querySelector('.task-search-scope').getBoundingClientRect().bottom<=e.getBoundingClientRect().bottom),'scope fully visible '+width);
    await page.screenshot({path:out+'/search-'+width+'.png'});
    if(width===1440){
     const clip=await page.locator('.task-search').evaluate(e=>{const a=e.getBoundingClientRect(),b=document.querySelector('#taskSearchPanel').getBoundingClientRect();return {x:Math.min(a.left,b.left)-10,y:a.top-10,width:Math.max(a.right,b.right)-Math.min(a.left,b.left)+20,height:b.bottom-a.top+20};});
     await page.screenshot({path:out+'/search-detail.png',clip});
    }
   }
   await page.keyboard.press('Escape');
  }
  // IME confirmation must not open a task while Chinese composition is active.
  await search.click();await search.dispatchEvent('compositionstart');await page.keyboard.press('Enter');assert.ok(await page.locator('#taskDetail').isHidden());await search.dispatchEvent('compositionend');
  await page.setViewportSize({width:1440,height:550});await search.click();await panel.waitFor();assert.ok(await panel.evaluate(e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}));await page.keyboard.press('Escape');await page.setViewportSize({width:1440,height:1000});
  await page.emulateMedia({reducedMotion:'reduce'});await search.click();assert.equal(await panel.evaluate(e=>getComputedStyle(e).animationName),'none');
  await page.locator('[data-view=completed]').click();await page.locator('.task-row.completed').waitFor();await search.click();await panel.waitFor();assert.equal(await options().count(),1);assert.match(await options().first().innerText(),/复盘/);await page.keyboard.press('Escape');
  await page.locator('[data-view=upcoming]').click();await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));await search.click();await panel.waitFor();assert.ok(!(await options().allTextContents()).some(t=>t.includes('阶段报告')));
  await page.locator('[data-view=tasks]').click();await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));
  await page.route('**/api/tasks?*',async r=>{await new Promise(resolve=>setTimeout(resolve,600));await r.continue();});
  await page.locator('#refreshBtn').click();await search.focus();await panel.waitFor();assert.equal(await options().count(),0);assert.match(await page.locator('#taskSearchFeedback').innerText(),/正在读取/);await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));await options().first().waitFor();await page.unroute('**/api/tasks?*');
  await page.route('**/api/tasks?*',r=>r.fulfill({status:503,json:{detail:'测试读取失败'}}));await page.locator('#refreshBtn').click();await page.waitForFunction(()=>document.querySelector('#taskList').textContent.includes('任务读取失败'));await search.focus();assert.equal(await options().count(),0);assert.match(await page.locator('#taskSearchFeedback').innerText(),/读取失败/);
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);console.log('PASS: search panel, live scoped filtering, clear/focus, keyboard + click detail, dismiss, escaped text, 5 widths/z-index, reduced motion, completed/upcoming scopes and no stale loading/error results; read-only synthetic fixtures.');
 }finally{if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});fs.rmSync(folder,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
