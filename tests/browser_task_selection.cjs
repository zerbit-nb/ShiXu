/* Current detail stays linked to its list item, using disposable real-backend data. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8789',folder=path.resolve('runtime/task-selection-'+Date.now());fs.mkdirSync(folder,{recursive:true});
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys;from pathlib import Path;from tests.workbench_app import make_app;uvicorn.run(make_app(Path(sys.argv[1])),host='127.0.0.1',port=8789)",folder],{windowsHide:true,stdio:'pipe'});
 let browser,log='';server.stderr.on('data',d=>log+=d);
 try{
  let ready=false;for(let i=0;i<80;i++){if(server.exitCode!==null)throw Error(log);try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1580,height:1028}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()!=='GET')writes.push(r.url());});
  await page.goto(base);const rows=page.locator('#taskList .task-row');await rows.first().waitFor();
  const ids=await rows.evaluateAll(es=>es.slice(0,2).map(e=>e.dataset.taskId));
  const row=id=>page.locator('#taskList [data-task-id="'+id+'"]');
  const current=async id=>{await page.waitForFunction(id=>{const items=[...document.querySelectorAll('#taskList .is-current')];return items.length===1&&items[0].dataset.taskId===id;},id);assert.equal(await row(id).locator('.task-open').getAttribute('aria-current'),'true');};
  await row(ids[0]).hover();await page.waitForTimeout(180);const hover=await row(ids[0]).evaluate(e=>getComputedStyle(e).backgroundColor);
  await row(ids[0]).locator('.task-open').click();await page.locator('#taskDetailTitle').waitFor();await page.mouse.move(1520,80);
  await current(ids[0]);await page.waitForTimeout(180);assert.equal(await row(ids[0]).evaluate(e=>getComputedStyle(e).backgroundColor),hover,'persistent selected background matches hover');
  await row(ids[1]).locator('.task-open').click();await current(ids[1]);assert.equal(await row(ids[0]).locator('.task-open').getAttribute('aria-current'),null);
  await page.locator('#refreshBtn').click();await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));await current(ids[1]);
  await page.locator('[data-detail-action=refresh]').click();await current(ids[1]);
  await page.mouse.move(1520,80);await page.screenshot({path:folder+'/selected-task.png'});
  for(const width of [1024,1440,390,1580]){await page.setViewportSize({width,height:1028});await current(ids[1]);await page.waitForFunction(wide=>document.body.classList.contains('detail-open')===wide,width>=1100);}
  await page.locator('#closeTaskDetail').click();await page.waitForFunction(()=>!document.querySelector('#taskList .is-current'));assert.equal(await page.locator('#taskList [aria-current]').count(),0);
  await row(ids[0]).locator('.task-open').focus();await page.keyboard.press('Enter');await current(ids[0]);await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('#taskList .is-current'));
  await row(ids[1]).locator('.task-open').click();await current(ids[1]);await page.locator('[data-view=messages]').click();await page.waitForFunction(()=>!document.querySelector('#taskDetail').open);assert.equal(await page.locator('#taskList .is-current').count(),0);
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);console.log('PASS: persistent hover-color selection, switching, list/detail refresh, resize modal/panel, close, keyboard, navigation cleanup; zero writes/errors. Screenshot: '+folder);
 }finally{if(browser)await browser.close();if(server.exitCode===null)server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
