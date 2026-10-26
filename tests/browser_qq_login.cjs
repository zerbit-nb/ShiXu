/* Controlled QQ login UI acceptance. Never sends credentials to a real QQ service. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'campusflow-login-')),base='http://127.0.0.1:8772';
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.message==='Test port occupied')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-c',"import uvicorn,sys; from app.main import create_app; uvicorn.run(create_app(db_path=sys.argv[1],config_path=sys.argv[2]),host='127.0.0.1',port=8772)",path.join(folder,'test.sqlite'),path.join(folder,'config.json')],{windowsHide:true,stdio:'pipe'});
 let browser,log='';server.stderr.on('data',x=>log+=x);
 try{
  let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,150));}assert.ok(ready,log);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  let state='waiting_qrcode',passwordMode='submitted',starts=0,refreshes=0,statusCalls=0,exits=0,exitFailure=false,devicePolls=0,cancels=0,deviceResult='device_verification',delayPassword=false,quickCalls=0,quickFailure=false,quickListFailure=false,quickRows=[{account_id:'12345678',nickname:'<b>测试账号</b>'},{account_id:'87654321',nickname:'备用账号'}];
  const qr='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK1sAAAAASUVORK5CYII=';
  const ident='a'.repeat(32);
  const device=()=>({state:deviceResult,online:false,verification_id:ident,qr_image:['device_verification','device_scanned'].includes(deviceResult)?qr:null});
  const data=()=>({state,verification_id:['device_verification','device_scanned','verification_expired','verification_cancelled'].includes(state)?ident:undefined,online:state==='online',account_id:state==='online'?'12345678':'',account_mismatch:state==='online',qr_image:['waiting_qrcode','device_verification','device_scanned'].includes(state)?qr:null,webui_url:'http://127.0.0.1:6099'});
  await page.route('**/api/qq/login/**',async route=>{
   const action=new URL(route.request().url()).pathname.split('/').pop();
   if(action==='sync')return route.fulfill({json:{state:state==='online'?'ready':state==='exited'?'exited':'qq_offline',label:state==='online'?'QQ 在线，上报配置匹配':'QQ 未登录',hint:state==='online'?'接收配置已同步':'点击登录',receiver:state==='online'?{enabled:true,account_id:'12345678',group_ids:['87654321'],has_token:true}:undefined}});
   if(action==='accounts'){await new Promise(r=>setTimeout(r,250));return route.fulfill({json:quickListFailure?{state:'not_running',message:'NapCat 尚未运行'}:{state:'quick_accounts',accounts:quickRows}});}
   if(action==='quick'){quickCalls++;assert.equal(route.request().postDataJSON().account_id,'12345678');await new Promise(r=>setTimeout(r,250));return route.fulfill({json:quickFailure?{state:'login_error',message:'快速登录未完成，请重试',failure_stage:'quick_login'}:{state:'submitted',online:false,message:'等待 QQ 初始化'}});}
   if(action==='poll'){devicePolls++;return route.fulfill({json:device()});}
   if(action==='cancel'){cancels++;state='verification_cancelled';return route.fulfill({json:{state,online:false,qr_image:null}});}
   if(action==='logout'){exits++;if(exitFailure)return route.fulfill({status:503,json:{state:'exit_failed',message:'无法确认后台已停止，请重试'}});state='exited';return route.fulfill({json:{state:'exited',online:false,account_id:'',qr_image:null,message:'已退出 NapCat'}});}
   if(action==='start'){if(state==='exited')state='waiting_qrcode';starts++;await new Promise(r=>setTimeout(r,250));return route.fulfill({json:{state:'running',message:'后台已启动'}});}
   if(action==='refresh'){refreshes++;return route.fulfill({json:data()});}
   if(action==='password'){assert.equal(route.request().postDataJSON().password,'test-only-password');assert.equal(route.request().postDataJSON().account_id,'12345678');if(delayPassword)await new Promise(r=>setTimeout(r,500));if(passwordMode==='password_timeout')return route.fulfill({status:503,json:{state:'password_timeout',message:'等待 NapCat 返回密码登录结果已超时',failure_stage:'password_submit'}});if(passwordMode==='device_verification'){state=passwordMode;deviceResult=passwordMode;return route.fulfill({json:device()});}return route.fulfill({json:{state:passwordMode,message:passwordMode==='verification_required'?'请在管理页完成安全验证':'等待确认',webui_url:'http://127.0.0.1:6099'}});}
   statusCalls++;return route.fulfill({json:data()});
  });
  await page.goto(base);await page.waitForLoadState('networkidle');await page.locator('[data-view=qq]').click();await page.locator('#qqLoginBtn').click();
  await page.waitForFunction(()=>document.querySelector('[data-connection=qq] .connection-state').textContent==='连接中');
  await page.locator('#qqLogout').waitFor({state:'visible'});
  page.once('dialog',d=>d.dismiss());await page.locator('#qqLogout').click();assert.equal(exits,0);
  page.once('dialog',d=>d.accept());await page.locator('#qqLogout').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='exited');
  assert.equal(exits,1);await page.locator('#qqStartBackground').click();await page.locator('#qqLoginQR').waitFor({state:'visible'});
  exits=0;starts=0;

  await page.locator('#qqQuickMode').click();await page.waitForFunction(()=>document.querySelector('#qqQuickAccount').options.length===3);
  assert.equal(quickCalls,0);assert.equal(await page.locator('#qqQuickSubmit').isDisabled(),true);assert.equal(await page.locator('#qqQuickAccount b').count(),0);
  await page.locator('#qqQuickAccount').selectOption('12345678');assert.equal(await page.locator('#qqQuickSubmit').isDisabled(),false);
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:900});assert.ok(await page.locator('#qqLoginDialog').evaluate(el=>el.scrollWidth<=el.clientWidth),'quick overflow '+width);}
  await page.locator('#qqQuickSubmit').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='submitted');assert.equal(quickCalls,1);
  assert.equal(await page.locator('[data-connection=qq] .connection-state').innerText(),'连接中');
  state='initializing';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='initializing');assert.equal(await page.locator('[data-connection=qq] .connection-state').innerText(),'连接中');state='online';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='online');assert.equal(await page.locator('#qqLoginMethods').isVisible(),false);
  await page.locator('#closeQQLogin').click();state='waiting_qrcode';await page.locator('#qqLoginBtn').click();await page.locator('#qqQuickMode').click();await page.waitForFunction(()=>document.querySelector('#qqQuickAccount').options.length===3);
  quickFailure=true;await page.locator('#qqQuickAccount').selectOption('12345678');await page.locator('#qqQuickSubmit').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='login_error');await page.waitForTimeout(3300);assert.match(await page.locator('#qqLoginError').innerText(),/快速登录未完成/);quickFailure=false;
  quickRows=[];await page.locator('#qqQuickRefresh').click();await page.waitForFunction(()=>document.querySelector('#qqQuickHint').textContent.includes('没有可快速登录'));assert.equal(await page.locator('#qqQuickSubmit').isDisabled(),true);
  quickListFailure=true;await page.locator('#qqQuickRefresh').click();await page.waitForFunction(()=>document.querySelector('#qqQuickError').textContent.includes('NapCat'));assert.equal(await page.locator('#qqQuickSubmit').isDisabled(),true);
  quickListFailure=false;quickRows=[{account_id:'12345678',nickname:'测试账号'}];await page.locator('#qqQuickRefresh').click();await page.waitForFunction(()=>document.querySelector('#qqQuickAccount').value==='12345678');assert.equal(await page.locator('#qqQuickSubmit').isDisabled(),false);
  await page.locator('#qqQuickMode').focus();await page.keyboard.press('End');assert.equal(await page.locator('#qqPasswordMode').getAttribute('aria-selected'),'true');await page.keyboard.press('Home');assert.equal(await page.locator('#qqQuickMode').getAttribute('aria-selected'),'true');await page.locator('#qqScanMode').click();
  assert.equal(starts,0);await page.locator('#qqStartBackground').click();await page.waitForFunction(()=>!document.querySelector('#qqStartBackground').disabled);
  assert.equal(starts,1);await page.locator('#qqLoginQR').waitFor({state:'visible'});
  assert.match(await page.locator('#qqLoginStatus').innerText(),/手机 QQ/);
  await page.locator('#qqLoginRefresh').click();await page.waitForFunction(()=>!document.querySelector('#qqLoginDialog').hasAttribute('aria-busy'));assert.equal(refreshes,1);
  await page.locator('#qqScanMode').focus();await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#qqPasswordMode').getAttribute('aria-selected'),'true');
  await page.locator('#qqLoginAccount').fill('12345678');await page.locator('#qqLoginPassword').fill('test-only-password');await page.locator('#qqPasswordSubmit').click();
  assert.equal(await page.locator('#qqLoginPassword').inputValue(),'');await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='submitted');
  passwordMode='password_timeout';delayPassword=true;await page.locator('#qqLoginPassword').fill('test-only-password');await page.locator('#qqPasswordSubmit').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='password_waiting');await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='password_timeout');delayPassword=false;
  await page.waitForTimeout(3300);assert.equal(await page.locator('#qqLoginStatus').getAttribute('data-state'),'password_timeout');assert.match(await page.locator('#qqLoginError').innerText(),/超时/);
  passwordMode='verification_required';await page.locator('#qqLoginPassword').fill('test-only-password');await page.locator('#qqPasswordSubmit').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='verification_required');
  await page.waitForTimeout(3300);assert.equal(await page.locator('#qqLoginStatus').getAttribute('data-state'),'verification_required');assert.ok(await page.locator('#qqLoginVerify').isVisible());
  // New-device authorization is independent from the ordinary login QR.
  const submitDevice=async()=>{await page.locator('#qqLoginPassword').fill('test-only-password');await page.locator('#qqPasswordSubmit').click();await page.locator('#qqDeviceQR').waitFor({state:'visible'});};
  passwordMode='device_verification';await submitDevice();
  assert.equal(await page.locator('#qqLoginMethods').isVisible(),false);assert.equal(await page.locator('#qqLoginPassword').inputValue(),'');
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:900});assert.ok(await page.locator('#qqLoginDialog').evaluate(el=>el.scrollWidth<=el.clientWidth),'device overflow '+width);}
  deviceResult='device_scanned';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='device_scanned');assert.ok(devicePolls>0);
  deviceResult='submitted';state='initializing';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='submitted');assert.equal(await page.locator('#qqDeviceQR').getAttribute('src'),null);
  await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='initializing');assert.equal(await page.locator('#qqLogout').isVisible(),true);
  state='online';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='online');assert.equal(await page.locator('#qqDevicePane').isVisible(),false);
  await page.locator('#closeQQLogin').click();state='waiting_qrcode';await page.locator('#qqLoginBtn').click();await page.locator('#qqLoginQR').waitFor({state:'visible'});await page.locator('#qqPasswordMode').click();await page.locator('#qqLoginAccount').fill('12345678');
  await submitDevice();await page.locator('#qqDeviceCancel').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='verification_cancelled');assert.equal(cancels,1);assert.ok(await page.locator('#qqLoginMethods').isVisible());
  await submitDevice();deviceResult='verification_expired';state='verification_expired';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='verification_expired');assert.ok(await page.locator('#qqLoginMethods').isVisible());assert.equal(await page.locator('#qqDeviceQR').getAttribute('src'),null);
  await submitDevice();await page.locator('#closeQQLogin').click();await page.waitForTimeout(300);assert.equal(cancels,2);const savedPolls=devicePolls;await page.waitForTimeout(3300);assert.equal(devicePolls,savedPolls);
  state='waiting_qrcode';await page.locator('#qqLoginBtn').click();await page.locator('#qqLoginQR').waitFor({state:'visible'});await page.locator('#qqPasswordMode').click();await page.locator('#qqLoginAccount').fill('12345678');
  delayPassword=true;await page.locator('#qqLoginPassword').fill('test-only-password');await page.locator('#qqPasswordSubmit').click();await page.locator('#closeQQLogin').click();await page.waitForTimeout(900);assert.equal(cancels,3);delayPassword=false;
  state='waiting_qrcode';await page.locator('#qqLoginBtn').click();await page.locator('#qqLoginQR').waitFor({state:'visible'});
  await page.locator('#qqScanMode').click();await page.locator('#qqLoginRefresh').click();await page.locator('#qqLoginQR').waitFor({state:'visible'});
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page overflow '+width);assert.ok(await page.locator('#qqLoginDialog').evaluate(el=>el.scrollWidth<=el.clientWidth),'dialog overflow '+width);}
  await page.emulateMedia({reducedMotion:'reduce'});fs.mkdirSync('test-results',{recursive:true});await page.screenshot({path:'test-results/qq-login-desktop.png'});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'test-results/qq-login-mobile.png'});
  state='qrcode_scanned';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='qrcode_scanned');assert.equal(await page.locator('#qqLoginQR').getAttribute('src'),null);
  state='initializing';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='initializing');
  state='online';await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='online');assert.equal(await page.locator('#qqLoginMethods').isVisible(),false);await page.waitForFunction(()=>document.querySelector('#qqLoginHint').textContent.includes('接收配置已同步'));assert.equal(await page.locator('#qqAccount').inputValue(),'12345678');
  await page.keyboard.press('Escape');assert.equal(await page.locator('#qqLoginDialog').isVisible(),false);const calls=statusCalls;await page.waitForTimeout(3300);assert.equal(statusCalls,calls);
  await page.locator('#qqLoginBtn').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='online');await page.locator('#closeQQLogin').click();assert.equal(await page.locator('#qqLoginPassword').inputValue(),'');
  await page.locator('#qqLoginBtn').click();await page.locator('#qqLogout').waitFor({state:'visible'});
  page.once('dialog',d=>d.dismiss());await page.locator('#qqLogout').click();assert.equal(exits,0);
  exitFailure=true;page.once('dialog',d=>d.accept());await page.locator('#qqLogout').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='exit_failed');assert.match(await page.locator('#qqLoginError').innerText(),/无法确认/);assert.equal(await page.locator('#qqLoginMethods').isVisible(),false);
  exitFailure=false;page.once('dialog',d=>d.accept());await page.locator('#qqLogout').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='exited');assert.equal(await page.locator('#qqLogout').isVisible(),false);assert.ok(!(await page.locator('#qqLoginHint').innerText()).includes('12345678'));
  const stoppedCalls=statusCalls;await page.waitForTimeout(3300);assert.equal(statusCalls,stoppedCalls);
  await page.locator('#closeQQLogin').click();const oldStarts=starts;await page.locator('#qqLoginBtn').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='exited');assert.equal(starts,oldStarts);
  await page.locator('#qqStartBackground').click();await page.locator('#qqLoginQR').waitFor({state:'visible'});assert.equal(starts,oldStarts+1);assert.equal(await page.locator('#qqLogout').isVisible(),true);
  passwordMode='submitted';await page.locator('#qqPasswordMode').click();await page.locator('#qqLoginAccount').fill('12345678');await page.locator('#qqLoginPassword').fill('test-only-password');await page.locator('#qqPasswordSubmit').click();await page.waitForFunction(()=>document.querySelector('#qqLoginStatus').dataset.state==='submitted');assert.equal(await page.locator('#qqLoginPassword').inputValue(),'');await page.locator('#closeQQLogin').click();
  assert.deepEqual(errors.filter(e=>!e.includes('status of 503')),[]);assert.equal(errors.filter(e=>e.includes('status of 503')).length,2);assert.equal((await (await fetch(base+'/api/tasks')).json()).tasks.length,0);
  console.log('PASS: quick account recognition/no automatic login/selection/refresh/empty/failure/retry/online/keyboard/widths, password waiting and persistent timeout after status polls, new-device confirmation/second submission/initialization/online, cancel/expiry/close/in-flight close cleanup, verification widths, explicit background start, exit confirmation/cancel/failure/retry, persistent exited state, QR/password relogin, QR refresh, keyboard tabs, password clearing, persistent verification hint, scan/initializing/online, mismatch, close/reopen, stopped polling, five widths, reduced motion, clean console, no task changes');
 }finally{if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});}
})().catch(e=>{console.error(e);process.exitCode=1});

