/* Isolated visual and interaction acceptance. Never writes to the running user DB. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'campusflow-polish-')),base='http://127.0.0.1:8773';
 try{await fetch(base+'/api/health');throw new Error('test port occupied');}catch(e){if(e.message==='test port occupied')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-c',"import uvicorn,sys; from app.main import create_app; from app.config import Settings; from tests.test_api import LocalModelStub; uvicorn.run(create_app(Settings(),db_path=sys.argv[1],config_path=sys.argv[2],llm=LocalModelStub()),host='127.0.0.1',port=8773)",path.join(folder,'db.sqlite'),path.join(folder,'config.json')],{windowsHide:true,stdio:'pipe'});
 let log='',browser;server.stderr.on('data',x=>log+=x);
 const delay=ms=>new Promise(r=>setTimeout(r,ms));
 try{
  let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok){ready=true;break}}catch{}await delay(150);}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
  const request=async(url,body)=>{const r=await fetch(base+url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});assert.equal(r.ok,true,await r.clone().text());return r.json();};
  const day=n=>{const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());return new Date(Date.parse(today+'T12:00:00+08:00')+n*86400000).toISOString().slice(0,10);};
  const add=async(title,deadline,status='pending')=>{const r=await request('/api/messages/manual',{raw_text:title,source_group:'课程通知群'});const task=await request('/api/drafts/'+r.drafts[0].id+'/confirm',{confirmed:true,duplicate_reviewed:true,fields:{...r.drafts[0].fields,title,deadline,deadline_precision:deadline?(deadline.length===10?'date_only':'datetime'):'unknown'}});if(status!=='pending')await request('/api/tasks/'+task.id+'/'+(status==='completed'?'complete':'cancel'));return task;};
  const first=await add('已逾期的材料提交',day(-1)+'T18:00:00+08:00');
  const due=await add('今天仅日期截止',day(0));
  await add('稍后需要办理的事项',day(12));await add('尚待通知时间的活动',null);
  await add('未来七天仅日期',day(2));await add('未来七天上午提交',day(2)+'T09:00:00+08:00');await add('未来七天下午提交',day(2)+'T15:00:00+08:00');
  await add('已完成的历史记录',day(-10),'completed');await add('已经取消的安排',day(-2),'cancelled');
  await page.goto(base);await page.waitForLoadState('networkidle');await page.locator('[data-view=tasks]').click();await page.waitForFunction(()=>document.querySelector('#taskList').getAttribute('aria-busy')===null);
  assert.equal(await page.locator('[data-filter=pending]').getAttribute('aria-selected'),'true');assert.equal(await page.locator('.task-row.completed').count(),0);
  assert.deepEqual(await page.locator('[data-task-group]').evaluateAll(es=>es.map(e=>e.dataset.taskGroup)),['overdue','today','week','later','no_deadline']);
  assert.deepEqual(await page.locator('[data-task-group=week] .task-title').allTextContents(),['未来七天上午提交','未来七天下午提交','未来七天仅日期']);
  for(const [filter,count] of [['today',1],['week',4],['no_deadline',1]]){await page.locator('[data-filter='+filter+']').click();await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));assert.equal(await page.locator('.task-row').count(),count,filter);}
  await page.locator('[data-filter=pending]').click();await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));
  for(const hours of ['2','24','48']){await page.locator('#reminderHours').selectOption(hours);await page.waitForFunction(value=>localStorage.getItem('campusflow-reminder-hours')===value,hours);await page.waitForFunction(()=>!document.querySelector('#taskList').hasAttribute('aria-busy'));}
  await page.waitForTimeout(250);await page.screenshot({path:'test-results/task-groups-desktop.png',fullPage:true});
  await page.locator('[data-task-id="'+first.id+'"] [data-task-action=complete]').click();await page.waitForFunction(id=>!document.querySelector('[data-task-id="'+id+'"]'),first.id);assert.match(await page.locator('#toastRegion').innerText(),/已完成/);
  await page.locator('[data-filter=completed]').click();await page.locator('.task-row.completed').first().waitFor();assert.equal(await page.locator('.task-row.completed').count(),2);assert.match(await page.locator('#completionNotice').innerText(),/不会定时自动删除/);
  await page.locator('#refreshBtn').click();await page.waitForFunction(()=>!document.querySelector('#refreshBtn').disabled);assert.equal(await page.locator('.task-row.completed').count(),2);
  await page.locator('[data-task-id="'+first.id+'"] [data-task-action=reopen]').click();await page.waitForFunction(id=>!document.querySelector('[data-task-id="'+id+'"]'),first.id);
  await page.locator('[data-filter=pending]').click();await page.locator('[data-task-id="'+first.id+'"]').waitFor();
  await page.locator('[data-filter=all]').click();await page.locator('[data-task-group=completed] > summary').waitFor();assert.equal(await page.locator('[data-task-group=completed]').getAttribute('open'),null);assert.equal(await page.locator('[data-task-group=cancelled]').getAttribute('open'),null);
  await page.locator('#taskSearch').fill('已完成的历史记录');assert.equal(await page.locator('[data-task-group=completed]').getAttribute('open'),'');assert.equal(await page.locator('.task-row.completed').isVisible(),true);await page.locator('#refreshBtn').click();await page.waitForFunction(()=>!document.querySelector('#refreshBtn').disabled);assert.equal(await page.locator('.task-row.completed').count(),1);
  await page.locator('#taskSearch').fill('');await page.locator('[data-task-group=completed] > summary').click();await page.locator('[data-task-group=cancelled] > summary').click();
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'groups overflow '+width);}
  await page.setViewportSize({width:390,height:1000});await page.evaluate(()=>window.scrollTo(0,0));await page.emulateMedia({reducedMotion:'reduce'});assert.ok(await page.locator('.skip-link').evaluate(e=>e.getBoundingClientRect().bottom<=0),'skip link must stay hidden without keyboard focus');await page.screenshot({path:'test-results/task-groups-mobile.png',fullPage:true});assert.equal((await (await fetch(base+'/api/tasks')).json()).tasks.length,9);assert.deepEqual(errors,[]);
  console.log('PASS: default pending, deadline grouping and timed/date-only ordering, completed retained across refresh, restore, collapsed history, searchable completed records, five widths, no deletion or page errors');
 }finally{if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});}
})().catch(e=>{console.error(e);process.exitCode=1});

