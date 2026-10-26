/* All data, model calls and capture controls are isolated test fixtures. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'campusflow-wechat-ui-')),base='http://127.0.0.1:8778';
 try{await fetch(base+'/api/health');throw new Error('Test port occupied');}catch(e){if(e.message==='Test port occupied')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys; from pathlib import Path; from tests.wechat_browser_app import make_app; uvicorn.run(make_app(Path(sys.argv[1])),host='127.0.0.1',port=8778)",folder],{windowsHide:true,stdio:'pipe'});
 let log='',browser;server.stderr.on('data',data=>log+=data);
 const get=async url=>(await fetch(base+url)).json();
 try{
  let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,150));}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,executablePath:process.env.CAMPUSFLOW_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.setDefaultTimeout(12000);
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  let mode='empty';
  await page.route('**/api/wechat/messages?*',async route=>{
    if(mode==='empty')return route.fulfill({json:{messages:[],total:0}});
    if(mode==='failure')return route.fulfill({status:503,json:{detail:'测试读取失败，请重试。'}});
    await new Promise(r=>setTimeout(r,150));return route.continue();
  });
  await page.goto(base);await page.waitForLoadState('networkidle');await page.locator('[data-view=wechat]').click();
  await page.getByText('暂无微信消息',{exact:true}).waitFor();assert.equal(await page.locator('#wechatStart').isEnabled(),false);
  assert.equal((await get('/api/tasks')).tasks.length,0);assert.equal((await get('/api/drafts')).drafts.length,0);
  await page.locator('#wechatSettingsBtn').click();await page.locator('#wechatAccount').fill('browser-test-account');await page.locator('#wechatGroupInput').fill('测试微信群');await page.locator('#saveWechat').click();
  await page.waitForFunction(()=>document.querySelector('#wechatStart').disabled===false);assert.equal(await page.locator('#wechatAccount').inputValue(),'');
  assert.ok(!JSON.stringify(await get('/api/wechat/config')).includes('browser-test-account'));
  await page.locator('#wechatStart').click();await page.waitForFunction(()=>document.querySelector('#wechatState').textContent==='采集中');assert.equal(await page.locator('#wechatSettingsBtn').isEnabled(),false);
  await page.locator('#wechatStop').click();await page.waitForFunction(()=>document.querySelector('#wechatState').textContent==='已暂停');
  mode='normal';await page.locator('#refreshWechat').click();assert.equal(await page.locator('#refreshWechat').getAttribute('aria-busy'),'true');await page.waitForFunction(()=>!document.querySelector('#refreshWechat').disabled);
  assert.equal(await page.locator('[data-wechat-message]').count(),20);assert.match(await page.locator('#wechatPage').innerText(),/共 25 条/);
  const first=page.locator('[data-wechat-message]').first();await first.locator('summary').click();await page.locator('#refreshWechat').click();await page.waitForFunction(()=>!document.querySelector('#refreshWechat').disabled);assert.equal(await first.locator('details').getAttribute('open'),'');
  await page.locator('#wechatNext').click();await page.waitForFunction(()=>document.querySelectorAll('[data-wechat-message]').length===5);
  assert.equal(await page.locator('#wechatMessages img').count(),0);assert.match(await page.locator('#wechatMessages').innerText(),/<img src=x onerror=alert\(1\)>/);
  await page.locator('[data-wechat-message]').filter({hasText:'请核对材料'}).locator('[data-wechat-action=manual]').click();await page.locator('.draft-card').waitFor();assert.equal((await get('/api/tasks')).tasks.length,0);
  await page.locator('.draft-card [data-field=title]').fill('微信手动核对测试');await page.locator('[data-action=check]').click();await page.waitForFunction(()=>document.querySelectorAll('.draft-card').length===0);assert.equal((await get('/api/tasks')).tasks.length,1);
  await page.locator('[data-view=wechat]').click();await page.waitForFunction(()=>!document.querySelector('#wechatMessages').getAttribute('aria-busy')||document.querySelector('#wechatMessages').getAttribute('aria-busy')==='false');
  await page.locator('[data-wechat-message]').filter({hasText:'bad'}).locator('[data-wechat-action=analyze]').click();await page.waitForFunction(()=>document.querySelector('#wechatInboxError').textContent.includes('JSON'));assert.equal(await page.locator('[data-wechat-message]').filter({hasText:'bad'}).getByRole('button',{name:'重试分析'}).count(),1);
  await page.locator('[data-wechat-message]').filter({hasText:'bad'}).locator('[data-wechat-action=ignore]').click();await page.waitForFunction(()=>document.querySelector('#wechatMessages').textContent.includes('已忽略'));
  await page.locator('[data-wechat-message]').filter({hasText:'闲聊'}).locator('[data-wechat-action=analyze]').click();await page.waitForFunction(()=>document.querySelector('#wechatMessages').textContent.includes('无需行动'));
  await page.locator('#wechatPrev').click();await page.waitForFunction(()=>document.querySelectorAll('[data-wechat-message]').length===20);
  await page.locator('[data-wechat-action=analyze]').first().click();await page.waitForFunction(()=>document.querySelectorAll('.draft-card').length===2);assert.equal((await get('/api/tasks')).tasks.length,1);
  await page.locator('.draft-card [data-field=title]').first().fill('保留未保存编辑');
  await page.locator('[data-view=wechat]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-wechat-action=review]').length>0);await page.locator('[data-wechat-action=review]').first().click();assert.equal(await page.locator('.draft-card [data-field=title]').first().inputValue(),'保留未保存编辑');assert.equal(await page.locator('.draft-card').count(),2);
  await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.draft-card').length===2);
  await page.locator('[data-view=wechat]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-wechat-message]').length===20);
  mode='failure';await page.locator('#refreshWechat').click();await page.waitForFunction(()=>document.querySelector('#wechatState').textContent==='状态未确认');assert.match(await page.locator('#wechatInboxError').innerText(),/测试读取失败/);assert.equal(await page.locator('#wechatStart').isEnabled(),false);
  assert.equal(errors.pop(),'Failed to load resource: the server responded with a status of 503 (Service Unavailable)');
  mode='normal';await page.waitForFunction(()=>!document.querySelector('#refreshWechat').disabled);await page.locator('#refreshWechat').click();await page.waitForFunction(()=>document.querySelector('#wechatState').textContent==='已暂停');await page.waitForFunction(()=>!document.querySelector('#refreshWechat').disabled);assert.equal(await page.locator('[data-wechat-action=analyze]').first().isEnabled(),true);
  await page.route('**/api/wechat/start',route=>route.fulfill({status:409,json:{detail:'测试启动失败，请检查微信。'}}));await page.locator('#wechatStart').click();await page.waitForFunction(()=>document.querySelector('#wechatControlError').textContent.includes('测试启动失败'));assert.equal(await page.locator('#wechatState').innerText(),'已暂停');assert.equal(errors.pop(),'Failed to load resource: the server responded with a status of 409 (Conflict)');await page.unroute('**/api/wechat/start');
  await fetch(base+'/api/config',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({provider:'deepseek',llm_model:''})});await page.locator('#refreshWechat').click();await page.waitForFunction(()=>document.querySelector('#wechatDestination').textContent.includes('DeepSeek'));assert.match(await page.locator('#wechatDestination').innerText(),/可能产生费用/);
  fs.mkdirSync('test-results',{recursive:true});
  for(const width of [320,390,768,1440]){
    await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow at '+width);
    if(width===390||width===1440)await page.screenshot({path:'test-results/wechat-inbox-'+width+'.png',fullPage:true});
    await page.locator('#wechatSettingsBtn').click();assert.ok(await page.evaluate(()=>document.querySelector('#wechatSettingsDialog').getBoundingClientRect().right<=innerWidth),'dialog overflow '+width);await page.locator('#closeWechatSettings').click();
  }
  await page.emulateMedia({reducedMotion:'reduce'});await page.locator('[data-view=qq]').click();await page.waitForFunction(()=>document.querySelector('#qqStatus').textContent==='已停用');assert.equal(await page.locator('#wechatView').isVisible(),false);
  await page.locator('[data-view=tasks]').click();await page.getByRole('heading',{name:'微信手动核对测试'}).waitFor();assert.equal(await page.locator('#qqView').isVisible(),false);
  assert.deepEqual(errors,[]);
  console.log('PASS: isolated WeChat inbox, controls, config privacy, refresh feedback, paging, escaping, manual confirmation, analysis/failure/ignore/review/reload, editable draft preservation, error recovery, cloud notice, 4 widths, reduced motion, QQ/task navigation, clean unexpected console. No real model/capture/group messages.');
 }finally{
  if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});
  if(path.dirname(folder)===os.tmpdir()&&path.basename(folder).startsWith('campusflow-wechat-ui-'))try{fs.rmSync(folder,{recursive:true,force:true,maxRetries:10,retryDelay:100});}catch(error){console.warn('Test cleanup failed:',error.code);}
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
