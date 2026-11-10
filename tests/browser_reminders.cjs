/* Real UI and temporary DB. No external model, accounts or Windows notifications. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'shixu-reminders-')),base='http://127.0.0.1:8798';
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.message==='Test port occupied')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-X','utf8','-c',"import sys,uvicorn;from pathlib import Path;from app.main import create_app;p=Path(sys.argv[1]);a=create_app(db_path=p/'db',config_path=p/'config');s=uvicorn.Server(uvicorn.Config(a,host='127.0.0.1',port=8798));a.add_api_route('/__test__/stop',lambda:setattr(s,'should_exit',True),methods=['POST']);s.run()",folder],{windowsHide:true,stdio:'pipe'});
 let browser,log='';server.stderr.on('data',x=>log+=x);
 const request=async(url,method='GET',body)=>{const r=await fetch(base+url,{method,headers:{'Content-Type':'application/json',Origin:base},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();assert.ok(r.ok,JSON.stringify(data));return data;};
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  const fields={title:'核对项目演示清单',deadline:new Date(Date.now()+30*60000).toISOString(),priority:'normal'};
  const draft=await request('/api/messages/manual','POST',{raw_text:'演示用合成消息',fields});
  const task=await request('/api/drafts/'+draft.drafts[0].id+'/confirm','POST',{confirmed:true,fields});
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/#connections');await page.waitForLoadState('networkidle');await page.bringToFront();
  const toggle=page.getByRole('switch',{name:'待办提醒',exact:true});await page.waitForFunction(()=>!document.querySelector('#taskReminderToggle').disabled);
  assert.equal(await toggle.getAttribute('aria-checked'),'false');
  await page.locator('.reminder-preferences summary').click();await page.locator('#taskReminderDaily').uncheck();await page.locator('#taskReminderSave').click();
  await page.waitForFunction(()=>!document.querySelector('#taskReminderSave').disabled);
  await toggle.click();await page.waitForFunction(()=>document.querySelector('#taskReminderToggle').getAttribute('aria-checked')==='true');
  await page.locator('#taskReminderCard').waitFor({state:'visible',timeout:15000});
  assert.match(await page.locator('#taskReminderTasks').innerText(),/核对项目演示清单/);
  assert.equal(await page.locator('#taskReminderTasks li').count(),1);
  fs.mkdirSync('runtime/reminder-review',{recursive:true});await page.screenshot({path:'runtime/reminder-review/foreground.png',fullPage:true});
  await page.locator('#taskReminderSnooze15').click();await page.locator('#taskReminderCard').waitFor({state:'hidden'});
  assert.equal((await request('/api/tasks/'+task.id)).deadline,task.deadline);
  await page.locator('[data-view=tasks]').click();await page.locator('[data-task-id="'+task.id+'"] .task-open').click();
  await page.locator('#individualReminderMode').waitFor();await page.selectOption('#individualReminderMode','off');await page.locator('#individualReminderSave').click();
  await page.waitForFunction(()=>!document.querySelector('#individualReminderSave').disabled);
  assert.equal((await request('/api/reminders/tasks/'+task.id)).mode,'off');
  await page.locator('#closeTaskDetail').click();await page.locator('[data-view=connections]').click();
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(300);
   const overflow=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(el=>[el.tagName,el.id,el.className,el.getBoundingClientRect().width]));
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width+' '+JSON.stringify(overflow));}
  await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'runtime/reminder-review/settings.png',fullPage:true});
  await page.reload();await page.waitForFunction(()=>document.querySelector('#taskReminderStatus').textContent==='已开启');
  assert.deepEqual(errors,[]);console.log('Reminder UI: preferences, due card, snooze, per-task setting, persistence, responsive layout passed');
 }finally{if(browser)await browser.close();const exited=server.exitCode===null?new Promise(r=>server.once('exit',r)):Promise.resolve();try{await fetch(base+'/__test__/stop',{method:'POST'});}catch{server.kill();}await exited;fs.rmSync(folder,{recursive:true,force:true,maxRetries:10,retryDelay:100});}
})().catch(e=>{console.error(e);process.exitCode=1;});
