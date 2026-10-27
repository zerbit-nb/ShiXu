/* Real browser, isolated DB: relocation, list-only scrolling and return-to-top. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8791',folder=path.resolve('runtime/task-scroll-'+Date.now());fs.mkdirSync(folder,{recursive:true});
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.cause?.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import sys,uvicorn;sys.argv=['fixture',sys.argv[1]];from tests.automation_browser_app import app;uvicorn.run(app,host='127.0.0.1',port=8791)",folder],{windowsHide:true,stdio:'pipe'});
 let browser,log='';server.stderr.on('data',d=>log+=d);
 try{
  let ready=false;for(let i=0;i<80;i++){if(server.exitCode!==null)throw Error(log);try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready,log);
  await fetch(base+'/test/batch',{method:'POST'});
  const ids=await(await fetch(base+'/test/review-scenario',{method:'POST'})).json();
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1580,height:980}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/?desktop=1#tasks');await page.locator('#taskList .task-row').first().waitFor();
  // Populate enough normal rows to place the selected no-deadline task far below the fold.
  await page.evaluate(async()=>{for(const task of state.tasks)if(task.title.includes('份项目材料')||task.title.includes('<img'))await api('/api/automation/tasks/'+task.id+'/viewed',{method:'POST'});await loadTasks();});
  await page.evaluate(()=>showView('connections'));
  await page.bringToFront();await page.evaluate(()=>dispatchEvent(new CustomEvent('shixu-window-state',{detail:true})));
  await page.locator('#automationCard').waitFor();
  const row=page.locator('#taskList [data-task-id="'+ids.unknown+'"]');
  await page.locator('[data-automation-task="'+ids.unknown+'"]').click();
  assert.equal(await page.locator('#tasksView').isVisible(),true,'popup from settings opens task list');
  await page.waitForFunction(id=>document.querySelector('[data-task-group=no_deadline] [data-task-id="'+id+'"]'),ids.unknown);
  await page.waitForFunction(id=>{const r=document.querySelector('#taskList [data-task-id="'+id+'"]').getBoundingClientRect();return r.top>=document.querySelector('.topbar').getBoundingClientRect().bottom&&r.bottom<innerHeight-40;},ids.unknown,{timeout:4000});
  assert.equal(await row.locator('.task-open').getAttribute('aria-current'),'true');
  assert.ok(await page.evaluate(()=>scrollY>1000));
  assert.equal(await page.locator('#taskDetail').evaluate(e=>e.scrollTop),0,'detail panel must not scroll with list');
  const top=page.locator('#taskBackToTop');await top.waitFor();
  const checkTopButton=async()=>{
    const geometry=await top.evaluate(button=>{
      const r=button.getBoundingClientRect(),style=getComputedStyle(button);
      return {x:r.x,right:r.right,width:r.width,height:r.height,radius:parseFloat(style.borderRadius),text:button.textContent.trim(),edge:document.body.classList.contains('detail-open')?document.querySelector('#taskDetail').getBoundingClientRect().left:innerWidth,cards:[...document.querySelectorAll('#taskList .task-row')].map(e=>e.getBoundingClientRect().right)};
    });
    assert.equal(geometry.width,geometry.height,'round button');assert.ok(geometry.radius>=geometry.width/2,'fully circular');
    assert.equal(geometry.text,'','arrow icon only');assert.ok(geometry.edge-geometry.right>=6&&geometry.edge-geometry.right<=16,'right gutter placement');
    assert.ok(geometry.cards.every(right=>right+4<=geometry.x),'button has its own gutter, clear of every task card');
    assert.equal(await top.getAttribute('aria-label'),'回到任务列表顶部');
  };
  await checkTopButton();
  await page.mouse.move(1000,75);await page.screenshot({path:folder+'/located-task.png'});
  // Refresh cannot drag the user back after they choose another scroll position.
  await page.waitForTimeout(900);await page.evaluate(()=>scrollTo({top:700,behavior:'instant'}));await page.locator('[data-detail-action=refresh]').click();
  await page.waitForTimeout(450);assert.ok(Math.abs(await page.evaluate(()=>scrollY)-700)<3,'refresh position: '+await page.evaluate(()=>scrollY));
  await page.evaluate(()=>{window.scrollSamples=[];window.addEventListener('scroll',()=>scrollSamples.push(scrollY));});
  await top.click();await page.waitForFunction(()=>scrollY===0);
  assert.ok(await page.evaluate(()=>scrollSamples.some(y=>y>0&&y<650)),'return must animate through intermediate positions');
  await top.waitFor({state:'hidden'});
  await page.waitForTimeout(120);
  await page.evaluate(()=>scrollTo(0,1000));await top.waitFor();await page.emulateMedia({reducedMotion:'reduce'});
  await top.click();assert.equal(await page.evaluate(()=>scrollY),0,'respect reduced motion');
  await page.evaluate(async()=>{await acknowledgeAutomation(false);showView('messages');});await top.waitFor({state:'hidden'});
  await page.evaluate(()=>showView('tasks'));await page.locator('#taskList .task-row').first().waitFor();
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,1000));await top.waitFor();
  await checkTopButton();
  const bounds=await top.boundingBox();assert.ok(bounds.x>=12&&bounds.x+bounds.width<=390);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:folder+'/mobile-top-button.png'});
  for(const width of [320,768,1024,1200,1580]){await page.setViewportSize({width,height:980});await page.evaluate(()=>scrollTo(0,1000));await top.waitFor();await checkTopButton();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no overflow '+width);}
  await page.setViewportSize({width:1580,height:980});await page.evaluate(()=>scrollTo(0,1000));await top.waitFor();await page.screenshot({path:folder+'/round-button-desktop.png'});
  await top.focus();await page.keyboard.press('Enter');assert.equal(await page.evaluate(()=>scrollY),0,'keyboard return to top');
  assert.deepEqual(errors,[]);console.log('PASS: popup-to-relocated-row positioning/highlight, independent detail scroll, no refresh jump, smooth back-to-top, reduced motion, route visibility and mobile layout. Screenshots: '+folder);
 }finally{if(browser)await browser.close();if(server.exitCode===null)server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
