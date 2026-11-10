/* Temporary backend and synthetic settings only. No real accounts or model. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'shixu-history-')),base='http://127.0.0.1:8797';
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.message==='Test port occupied')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-X','utf8','-c',"import sys,uvicorn;from pathlib import Path;from app.main import create_app;p=Path(sys.argv[1]);a=create_app(db_path=p/'db',config_path=p/'config');s=uvicorn.Server(uvicorn.Config(a,host='127.0.0.1',port=8797));a.add_api_route('/__test__/stop',lambda:setattr(s,'should_exit',True),methods=['POST']);s.run()",folder],{windowsHide:true,stdio:'pipe'});
 let browser,log='';server.stderr.on('data',x=>log+=x);
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  assert.ok((await fetch(base+'/api/health')).ok,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/#connections');await page.waitForLoadState('networkidle');
  const toggle=page.getByRole('switch',{name:'启动补收',exact:true});
  await page.waitForFunction(()=>!document.querySelector('#historyToggle').disabled);
  assert.equal(await toggle.getAttribute('aria-checked'),'false');
  await toggle.click();await page.waitForFunction(()=>document.querySelector('#historyToggle').getAttribute('aria-checked')==='true');
  await page.reload();await page.waitForFunction(()=>document.querySelector('#historyStatus').textContent==='已开启');
  await page.locator('.history-help:not(.reminder-preferences) summary').click();
  assert.match(await page.locator('.history-help:not(.reminder-preferences)').innerText(),/北京时间/);
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:1000});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page overflow '+width);
   assert.ok(await toggle.evaluate(el=>el.closest('.connection-row').scrollWidth<=el.closest('.connection-row').clientWidth),'row overflow '+width);
  }
  await page.setViewportSize({width:1440,height:1000});
  fs.mkdirSync('runtime/history-review',{recursive:true});
  await page.screenshot({path:'runtime/history-review/settings.png',fullPage:true});
  await page.route('**/api/history',route=>route.request().method()==='PUT'?route.fulfill({status:503,json:{detail:'测试保存失败'}}):route.continue());
  await toggle.click();await page.waitForFunction(()=>document.querySelector('#historyError').textContent.includes('测试保存失败'));
  assert.equal(await toggle.getAttribute('aria-checked'),'true');
  await page.unroute('**/api/history');await toggle.focus();await page.keyboard.press('Space');
  await page.waitForFunction(()=>document.querySelector('#historyToggle').getAttribute('aria-checked')==='false');
  assert.equal((await (await fetch(base+'/api/history')).json()).enabled,false);
  assert.equal((await (await fetch(base+'/api/tasks')).json()).tasks.length,0);
  assert.deepEqual(errors,[]);console.log('History settings: persistence, failure, keyboard, responsive layout passed');
 }finally{
  if(browser)await browser.close();
  const exited=server.exitCode===null?new Promise(r=>server.once('exit',r)):Promise.resolve();
  try{await fetch(base+'/__test__/stop',{method:'POST'});}catch{server.kill();}
  await exited;
  fs.rmSync(folder,{recursive:true,force:true,maxRetries:10,retryDelay:100});
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
