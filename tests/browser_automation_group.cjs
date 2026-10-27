/* Temporary review grouping uses real APIs and disposable synthetic tasks only. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8790',folder=path.resolve('runtime/automation-group-'+Date.now());fs.mkdirSync(folder,{recursive:true});
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import sys,uvicorn;sys.argv=['fixture',sys.argv[1]];from tests.automation_browser_app import app;uvicorn.run(app,host='127.0.0.1',port=8790)",folder],{windowsHide:true,stdio:'pipe'});
 let browser,log='';server.stderr.on('data',d=>log+=d);
 try{
  let ready=false;for(let i=0;i<80;i++){if(server.exitCode!==null)throw Error(log);try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1580,height:1028}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const ids=await(await fetch(base+'/test/review-scenario',{method:'POST'})).json();
  await page.goto(base+'/?desktop=1#tasks');
  const temporary=page.locator('[data-task-group=automatic]'),row=id=>page.locator('#taskList [data-task-id="'+id+'"]');
  await temporary.waitFor();assert.equal(await temporary.locator('.task-row').count(),4);assert.equal(await page.locator('.task-group').first().getAttribute('data-task-group'),'automatic');
  assert.equal(await page.locator('.task-row').count(),5);assert.equal(await page.locator('[data-filter]').filter({hasText:'自动整理'}).count(),0);
  await page.bringToFront();await page.evaluate(()=>dispatchEvent(new CustomEvent('shixu-window-state',{detail:true})));await page.locator('#automationCard').waitFor();
  await page.locator('#automationCardDismiss').click();await page.locator('#automationCard').waitFor({state:'hidden'});assert.equal(await temporary.locator('.task-row').count(),4,'popup dismissal is independent');
  for(const filter of ['today','week','no_deadline']){await page.locator('[data-filter='+filter+']').click();await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));assert.equal(await temporary.count(),0);assert.equal(await page.locator('.task-row').count(),0,'unviewed tasks not mixed into '+filter);}
  await page.locator('[data-filter=all]').click();await temporary.waitFor();assert.equal(await temporary.locator('.task-row').count(),4);
  await page.locator('[data-filter=pending]').click();await temporary.waitFor();
  await page.locator('#taskSearch').fill('无期限');assert.equal(await temporary.locator('.task-row').count(),1);await page.locator('#clearTaskSearch').click();await page.locator('#taskPageTitle').click();
  await page.screenshot({path:folder+'/automatic-before.png'});
  await page.route('**/api/tasks/'+ids.today+'/sources',r=>r.fulfill({status:503,json:{detail:'测试原文读取失败'}}));
  await row(ids.today).locator('.task-open').click();await page.getByText('来源读取失败：测试原文读取失败。请重试。',{exact:true}).waitFor();assert.equal(await temporary.locator('.task-row').count(),4);
  await page.unroute('**/api/tasks/'+ids.today+'/sources');await page.locator('#closeTaskDetail').click();
  await page.route('**/api/automation/tasks/'+ids.overdue+'/viewed',r=>r.fulfill({status:503,json:{detail:'测试查看状态保存失败'}}));
  await row(ids.overdue).locator('.task-open').click();await page.waitForFunction(()=>document.querySelector('#detailReviewError')?.textContent.includes('测试查看状态保存失败'));assert.equal(await temporary.locator('.task-row').count(),4);
  await page.unroute('**/api/automation/tasks/'+ids.overdue+'/viewed');await page.locator('[data-detail-action=refresh]').click();
  await page.waitForFunction(id=>document.querySelector('[data-task-group=overdue] [data-task-id="'+id+'"]'),ids.overdue);
  assert.equal(await temporary.locator('.task-row').count(),3);assert.equal(await row(ids.overdue).getAttribute('class').then(v=>v.includes('is-current')),true);assert.equal(await page.locator('.task-row').count(),5);
  await page.screenshot({path:folder+'/automatic-after-view.png'});await page.locator('#closeTaskDetail').click();
  await row(ids.today).locator('.task-open').focus();await page.keyboard.press('Enter');await page.waitForFunction(id=>document.querySelector('[data-task-group=today] [data-task-id="'+id+'"]'),ids.today);await page.keyboard.press('Escape');
  await page.reload();await temporary.waitFor();assert.equal(await temporary.locator('.task-row').count(),2,'viewing persists over reload');
  await page.locator('[data-filter=today]').click();await row(ids.today).waitFor();assert.equal(await page.locator('.task-row').count(),1);
  await page.locator('[data-filter=pending]').click();await temporary.waitFor();await row(ids.week).locator('[data-task-action=complete]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-task-group=automatic] .task-row').length===1);
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no overflow '+width);}
  await page.setViewportSize({width:390,height:900});await page.screenshot({path:folder+'/automatic-390.png'});
  await row(ids.unknown).locator('.task-open').click();await page.waitForFunction(id=>document.querySelector('[data-task-group=no_deadline] [data-task-id="'+id+'"]'),ids.unknown);assert.equal(await temporary.count(),0,'empty temporary group removed');await page.locator('#closeTaskDetail').click();
  assert.deepEqual(errors,[]);console.log('PASS: top temporary group, no duplicate rows/tabs, independent popup dismissal, filters/search, source/write failure retention, individual review persistence, correct time groups and selection, keyboard/modal view, completion, 5 widths. Screenshots: '+folder);
 }finally{if(browser)await browser.close();if(server.exitCode===null)server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
