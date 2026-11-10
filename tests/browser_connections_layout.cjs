/* Settings layout against disposable data. No live sources or model requests. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'shixu-settings-ui-')),base='http://127.0.0.1:8802';
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const source="import sys,uvicorn;from pathlib import Path;from tests.workbench_app import make_app;a=make_app(Path(sys.argv[1]));s=uvicorn.Server(uvicorn.Config(a,host='127.0.0.1',port=8802));a.add_api_route('/__test__/stop',lambda:setattr(s,'should_exit',True),methods=['POST']);s.run()";
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',source,folder],{windowsHide:true,stdio:'pipe'});
 let log='',browser;server.stderr.on('data',x=>log+=x);
 const out=path.resolve('runtime/connections-layout-review');fs.mkdirSync(out,{recursive:true});
 try{
  let ready=false;for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error(log);try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/#connections');await page.waitForFunction(()=>!document.querySelector('#taskReminderToggle')?.disabled);
  const card=page.locator('#connectionsView .connection-list');
  assert.equal(await card.locator('.connection-row').count(),8);
  assert.equal(await card.locator('.connection-monogram svg').count(),7);
  assert.match(await card.textContent(),/云端会发送新消息文本，可能收费/);
  const shot=async(name,fullPage=false)=>{await page.waitForFunction(()=>!document.querySelector('#toastRegion .toast'));await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));await page.waitForTimeout(300);await page.screenshot({path:path.join(out,name+'.png'),fullPage});};
  await shot('settings-1440');
  const history=page.locator('.history-help:not(.reminder-preferences)'),reminder=page.locator('.reminder-preferences');
  const layout=async width=>{
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page bounds '+width);
   const problems=await card.locator('.connection-row').evaluateAll(rows=>rows.flatMap(row=>{
    const rect=row.getBoundingClientRect(),items=[...row.children].filter(el=>getComputedStyle(el).display!=='none');
    const rectangles=items.map(el=>el.getBoundingClientRect());
    const overlap=rectangles.some((a,i)=>rectangles.slice(i+1).some(b=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1));
    const outside=rectangles.some(r=>r.left<rect.left-1||r.right>rect.right+1);
    return overlap||outside||row.scrollWidth>row.clientWidth+1?[row.innerText]:[];
   }));assert.deepEqual(problems,[],'row content overlap/bounds '+width);
  };
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(300);await layout(width);
   await history.locator('summary').click();await reminder.locator('summary').click();
   await page.waitForTimeout(300);await layout(width);
   assert.ok(await page.locator('#taskReminderSave').isVisible());
   assert.ok(await page.locator('#taskReminderHistory').isVisible());
   assert.match(await history.innerText(),/北京时间/);
   assert.match(await reminder.innerText(),/完整退出后停止/);
   assert.ok(await page.locator('#taskReminderQuietEnd').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth}),'quiet time field '+width);
   if(width===390||width===1440)await shot('expanded-'+width,true);
   await history.locator('summary').click();await reminder.locator('summary').click();
   if(width===390)await shot('settings-390',true);
  }
  await page.setViewportSize({width:1440,height:1000});
  // Long states and a failed save must remain visible without shifting controls over text.
  await page.locator('#automationToggle').click();await page.waitForFunction(()=>!document.querySelector('#automationToggle').disabled);
  await layout(1440);await shot('enabled-1440');
  await page.route('**/api/inbox/filter',r=>r.request().method()==='PUT'?r.fulfill({status:503,json:{detail:'测试：设置未保存，请稍后重试。'}}):r.continue());
  await page.locator('#receptionFilterToggle').click();await page.getByText('测试：设置未保存，请稍后重试。',{exact:true}).waitFor();await layout(1440);await shot('save-error');
  await page.unroute('**/api/inbox/filter');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('#automationToggle>span').evaluate(e=>getComputedStyle(e).transitionDuration),'0s');
  await reminder.locator('summary').focus();await page.keyboard.press('Enter');assert.equal(await reminder.getAttribute('open'),'');
  await page.locator('#taskReminderLead').focus();await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'taskReminderDaily');
  assert.deepEqual(errors,[]);
  console.log('PASS: 8 settings preserved; 7 local icons; collapsed/expanded 5 widths; no overlap; privacy and help retained; long state/error; keyboard; reduced motion. Screenshots: '+out);
 }finally{
  if(browser)await browser.close();
  const exited=server.exitCode===null?new Promise(r=>server.once('exit',r)):Promise.resolve();
  try{await fetch(base+'/__test__/stop',{method:'POST'});}catch{server.kill();}
  await exited;fs.rmSync(folder,{recursive:true,force:true,maxRetries:10,retryDelay:100});
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
