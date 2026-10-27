/* Real local backend, synthetic model and data; no account or cloud services. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const folder=path.resolve('runtime/automation-browser-'+Date.now());fs.mkdirSync(folder,{recursive:true});
 const base='http://127.0.0.1:8787';
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import sys,uvicorn;sys.argv=['fixture',sys.argv[1]];from tests.automation_browser_app import app;uvicorn.run(app,host='127.0.0.1',port=8787)",folder],{windowsHide:true,stdio:'pipe'});
 let browser,log='';server.stderr.on('data',d=>log+=d);
 try{
  for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,150));}
  assert.ok((await fetch(base+'/api/health')).ok,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/?desktop=1#connections');
  const toggle=page.getByRole('switch',{name:'自动整理待办',exact:true}),local=page.getByRole('switch',{name:'允许本地模型自动整理',exact:true});
  await page.waitForFunction(()=>!document.querySelector('#automationToggle')?.disabled);
  assert.equal(await toggle.getAttribute('aria-checked'),'false');assert.equal(await local.getAttribute('aria-checked'),'false');
  await toggle.click();await page.waitForFunction(()=>document.querySelector('#automationStatus').textContent==='等待本地模型许可');
  await local.focus();await page.keyboard.press('Space');await page.waitForFunction(()=>document.querySelector('#automationStatus').textContent==='已开启');
  await page.reload();await page.waitForFunction(()=>document.querySelector('#automationStatus').textContent==='已开启');
  await page.route('**/api/automation',route=>route.request().method()==='PUT'?route.fulfill({status:503,json:{detail:'测试保存失败'}}):route.continue());
  await toggle.click();await page.waitForFunction(()=>document.querySelector('#automationError').textContent==='测试保存失败');assert.equal(await toggle.getAttribute('aria-checked'),'true');await page.unroute('**/api/automation');
  await page.evaluate(()=>loadAutomation());
  assert.ok((await fetch(base+'/test/receive/qq',{method:'POST'})).ok);
  await page.waitForFunction(async()=>{const d=await(await fetch('/api/tasks')).json();return d.tasks.length===1;});
  // Native desktop defaults fail closed until an explicit foreground event.
  assert.equal(await page.locator('#automationCard').isVisible(),false);
  await page.bringToFront();await page.evaluate(()=>dispatchEvent(new CustomEvent('shixu-window-state',{detail:true})));
  await page.locator('#automationCard').waitFor({state:'visible'});
  assert.match(await page.locator('#automationCardSummary').innerText(),/1 项待办/);
  assert.ok(await page.locator('#automationCard').evaluate(el=>el.matches(':modal')),'centered modal panel');
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);
   if([390,1440].includes(width))await page.screenshot({path:folder+'/settings-card-'+width+'.png',fullPage:true});
  }
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.locator('#automationCard').evaluate(el=>getComputedStyle(el).animationName),'none');
  await page.evaluate(()=>dispatchEvent(new CustomEvent('shixu-window-state',{detail:false})));
  assert.equal(await page.locator('#automationCard').isVisible(),false);
  // A genuine background browser tab also suppresses notification presentation.
  const other=await browser.newPage();await other.goto('about:blank');await other.bringToFront();
  await fetch(base+'/test/receive/wechat',{method:'POST'});
  for(let i=0;i<60;i++){if((await(await fetch(base+'/api/automation/notices')).json()).notices.length===2)break;await new Promise(r=>setTimeout(r,150));}
  assert.equal((await(await fetch(base+'/api/automation/notices')).json()).notices.length,2);
  assert.equal(await page.locator('#automationCard').isVisible(),false);
  await page.bringToFront();await page.evaluate(()=>dispatchEvent(new CustomEvent('shixu-window-state',{detail:true})));
  await page.waitForFunction(()=>document.querySelector('#automationCardSummary').textContent.includes('2 项待办'));
  assert.equal(await page.locator('#automationCardTasks [data-automation-task]').count(),2);
  await page.screenshot({path:folder+'/centered-panel-2.png',fullPage:true});
  await page.locator('#automationCardTasks [data-automation-task]').first().click();await page.locator('#taskDetailTitle').waitFor();
  await page.waitForFunction(()=>document.querySelector('#taskDetailTitle').textContent==='提交实验报告');
  assert.equal((await(await fetch(base+'/api/automation/notices')).json()).notices.length,2,'individual detail must not clear all reminders');
  await page.keyboard.press('Escape');await page.locator('#automationCard').waitFor({state:'visible'});
  await page.locator('#automationCardOpen').click();
  await page.waitForFunction(async()=>(await(await fetch('/api/automation/notices')).json()).notices.length===0);
  assert.equal((await(await fetch(base+'/api/automation/notices')).json()).notices.length,0);
  await page.keyboard.press('Escape');await page.reload();await page.waitForFunction(()=>!document.querySelector('#automationToggle').disabled);assert.equal(await page.locator('#automationCard').isVisible(),false);
  await page.bringToFront();await page.evaluate(()=>dispatchEvent(new CustomEvent('shixu-window-state',{detail:true})));
  await page.setViewportSize({width:1580,height:1028});
  assert.ok((await fetch(base+'/test/batch',{method:'POST'})).ok);
  await page.waitForFunction(()=>document.querySelectorAll('#automationCardTasks [data-automation-task]').length===35);
  assert.equal(await page.locator('#automationCardTasks img').count(),0,'message titles escaped');
  await page.waitForTimeout(250);
  const geometry=await page.locator('#automationCard').evaluate(el=>{const b=el.getBoundingClientRect(),s=document.querySelector('#automationCardScroll');return {x:b.x,y:b.y,width:b.width,height:b.height,scroll:s.scrollHeight,client:s.clientHeight};});
  assert.ok(geometry.width<=1061&&geometry.height<=701);
  assert.ok(Math.abs(geometry.x+geometry.width/2-790)<2&&Math.abs(geometry.y+geometry.height/2-514)<2,'centered on whole viewport');
  assert.ok(geometry.scroll>geometry.client,'internal list scrolls');
  await page.screenshot({path:folder+'/centered-panel-35.png'});
  const footer=await page.locator('.automation-panel-footer').boundingBox();
  await page.locator('#automationCardScroll').hover();await page.mouse.wheel(0,650);
  await page.waitForFunction(()=>document.querySelector('#automationCardScroll').scrollTop>0);
  assert.deepEqual(await page.locator('.automation-panel-footer').boundingBox(),footer,'footer stays fixed');
  const top=await page.locator('#automationCardScroll').evaluate(el=>el.scrollTop);await page.waitForTimeout(3200);
  assert.equal(await page.locator('#automationCardScroll').evaluate(el=>el.scrollTop),top,'poll preserves scroll');
  await page.locator('#automationCardOpen').focus();await page.keyboard.press('Tab');
  assert.ok(await page.evaluate(()=>document.querySelector('#automationCard').contains(document.activeElement)),'modal focus trap');
  await page.route('**/api/automation/notices/*/acknowledge',route=>route.fulfill({status:503,json:{detail:'测试确认失败，请重试'}}));
  await page.locator('#automationCardDismiss').click();await page.waitForFunction(()=>document.querySelector('#automationCardError').textContent.includes('测试确认失败'));
  assert.equal((await(await fetch(base+'/api/automation/notices')).json()).total,35,'failed acknowledgement retains all');
  await page.unroute('**/api/automation/notices/*/acknowledge');
  await page.evaluate(()=>document.querySelector('#automationCardError').textContent='');
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:800});await page.waitForTimeout(100);
   assert.ok(await page.locator('#automationCard').evaluate(el=>{const b=el.getBoundingClientRect();return b.x>=0&&b.right<=innerWidth&&b.y>=0&&b.bottom<=innerHeight&&el.scrollWidth<=el.clientWidth;}),'panel fits '+width);
   if(width===390)await page.screenshot({path:folder+'/centered-panel-390.png'});
  }
  await page.keyboard.press('Escape');await page.waitForFunction(()=>document.querySelector('#automationCard').hidden);
  assert.equal((await(await fetch(base+'/api/automation/notices')).json()).total,0);
  assert.deepEqual(errors,[]);console.log('PASS: real backend work without foreground, opt-in + local permission, persistence, failed save, keyboard, native hidden and browser background suppression, return-to-foreground merged cards, detail navigation, durable acknowledgement, 5 widths and reduced motion, no JS errors. Screenshots: '+folder);
 }finally{if(browser)await browser.close();if(server.exitCode===null)server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
