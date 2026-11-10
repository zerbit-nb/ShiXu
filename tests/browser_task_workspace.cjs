/* Task-home layout review. Disposable fixtures; no real accounts or model calls. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'shixu-task-ui-')),base='http://127.0.0.1:8801';
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const source="import sys,uvicorn;from pathlib import Path;from tests.workbench_app import make_app;a=make_app(Path(sys.argv[1]));s=uvicorn.Server(uvicorn.Config(a,host='127.0.0.1',port=8801));a.add_api_route('/__test__/stop',lambda:setattr(s,'should_exit',True),methods=['POST']);s.run()";
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',source,folder],{windowsHide:true,stdio:'pipe'});
 let log='',browser;server.stderr.on('data',x=>log+=x);
 const out=path.resolve('runtime/ui-task-redesign');fs.mkdirSync(out,{recursive:true});
 try{
  let ready=false;for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error(log);try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const tasks=page.locator('#tasksView'),rows=page.locator('#taskList .task-row');
  const shot=async name=>{await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await page.waitForTimeout(300);await page.screenshot({path:path.join(out,name+'.png')});};
  await page.goto(base);await rows.first().waitFor();
  assert.equal(await tasks.getAttribute('data-page'),'tasks');
  await shot('tasks-1440');
  const first=rows.first(),id=await first.getAttribute('data-task-id');
  const neutral=await first.evaluate(e=>getComputedStyle(e).backgroundColor);
  await first.locator('.task-open').click();await page.locator('#taskReminderDetail select').waitFor();
  await page.waitForTimeout(300);await page.mouse.move(1420,60);
  assert.equal(await first.locator('.task-open').getAttribute('aria-current'),'true');
  assert.notEqual(await first.evaluate(e=>getComputedStyle(e).backgroundColor),neutral,'selected task remains distinguishable after pointer leaves');
  await shot('detail-1440');
  await page.locator('#closeTaskDetail').click();await page.waitForTimeout(300);
  // Controls must be operable and stay separate even when the toolbar wraps.
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(300);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no page overflow '+width);
   const overlap=await page.locator('.task-toolbar').evaluate(toolbar=>{
    const selectors=['.task-search','.filters','.reminder-choice','#refreshBtn'];
    const rects=selectors.map(s=>toolbar.querySelector(s)?.getBoundingClientRect()).filter(Boolean);
    return rects.some((a,i)=>rects.slice(i+1).some(b=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1));
   });assert.equal(overlap,false,'toolbar overlap '+width);
   await page.locator('[data-filter=no_deadline]').focus();await page.keyboard.press('Enter');
   await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));
   assert.match(await page.locator('#taskList').innerText(),/选修课程/);
   await page.locator('[data-view=tasks]').click();await rows.first().waitFor();
   // A long title may wrap but must never cover its deadline or menu.
   const long=rows.filter({hasText:'长标题测试'});
   assert.ok(await long.evaluate(row=>{
    const a=row.getBoundingClientRect();
    return [...row.querySelectorAll('.task-copy,.deadline-block,.task-actions')].every(el=>{const r=el.getBoundingClientRect();return r.left>=a.left&&r.right<=a.right+1;});
   }),'long task content stays in row '+width);
   if(width===390)await shot('tasks-390');
   await page.locator('#taskList [data-task-id="'+id+'"] .task-open').click();await page.locator('#taskReminderDetail select').waitFor();await page.waitForTimeout(300);
   assert.ok(await page.locator('#taskDetail').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;}),'detail bounds '+width);
   if(width===390)await shot('detail-390');
   await page.keyboard.press('Escape');await page.waitForTimeout(300);
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#taskSearch').fill('不存在的测试任务');await page.locator('#taskPageTitle').click();await shot('empty-search');
  await page.locator('#clearTaskSearch').click();await page.locator('#taskPageTitle').click();
  await rows.first().locator('summary').click();assert.ok(await rows.first().locator('details').getAttribute('open')!==null);
  await rows.first().locator('.more-trigger').click();await page.getByRole('menuitem',{name:'编辑',exact:true}).waitFor();await page.keyboard.press('Escape');
  // Shared task routes and unrelated pages must not inherit this prototype.
  for(const route of ['upcoming','completed','messages','connections','tasks']){
   await page.locator('[data-view='+route+']').click();await page.waitForTimeout(300);
   assert.equal(await page.evaluate(()=>!!document.querySelector('#tasksView[data-page="tasks"]:not([hidden])')),route==='tasks','scope '+route);
  }
  await rows.first().waitFor();
  await page.route('**/api/tasks?*',r=>r.fulfill({status:503,json:{detail:'测试读取失败'}}));
  await page.locator('#refreshBtn').click();await page.getByText('任务读取失败',{exact:true}).waitFor();await shot('load-error');
  assert.match(await page.locator('#taskList').innerText(),/测试读取失败.*刷新/);
  await page.unroute('**/api/tasks?*');await page.locator('#refreshBtn').click();await rows.first().waitFor();
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await rows.first().evaluate(e=>getComputedStyle(e).transitionDuration),'0s');
  assert.deepEqual(errors,[]);
  console.log('PASS: task-home-only scope; toolbar separation; 5 widths; long titles; selected task; detail and reminder controls; keyboard filters; materials and menu; empty/error recovery; reduced motion. Screenshots: '+out);
 }finally{
  if(browser)await browser.close();
  const exited=server.exitCode===null?new Promise(r=>server.once('exit',r)):Promise.resolve();
  try{await fetch(base+'/__test__/stop',{method:'POST'});}catch{server.kill();}
  await exited;fs.rmSync(folder,{recursive:true,force:true,maxRetries:10,retryDelay:100});
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
