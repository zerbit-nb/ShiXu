/* Real UI -> real local routes -> simulated per-account NapCat; no real QQ. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const runtimeRoot=path.resolve('runtime');fs.mkdirSync(runtimeRoot,{recursive:true});
 const folder=fs.mkdtempSync(path.join(runtimeRoot,'qq-sync-test-')),base='http://127.0.0.1:8787';
 try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.message==='Test port occupied')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys;from pathlib import Path;from tests.qq_connection_app import make_app;uvicorn.run(make_app(Path(sys.argv[1])),host='127.0.0.1',port=8787)",folder],{windowsHide:true,stdio:'ignore'});
 let browser;
 const get=async url=>(await fetch(base+url)).json();
 const control=async body=>{assert.ok((await fetch(base+'/test/napcat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)})).ok);};
 try{
  let ready=false;for(let i=0;i<80;i++){try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,150));}assert.ok(ready);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.goto(base);await page.waitForLoadState('networkidle');await page.locator('[data-view=qq]').click();
  await page.waitForFunction(()=>document.querySelector('#bridgeStatus').dataset.state==='ready');
  assert.equal(await page.locator('#qqAccount').inputValue(),'23456789');
  assert.equal((await get('/api/qq/config')).account_id,'23456789');
  let report=await get('/test/reporting');assert.equal(report.ours.length,1);assert.ok(report.other_client_preserved&&report.ours[0].token_matches&&report.ours[0].enable);
  assert.equal(report.ours[0].url,base+'/api/qq/events');assert.equal(report.ours[0].format,'array');
  await page.locator('#qqSettingsBtn').click();await page.locator('#qqGroups').fill('87654321\n99887766');await page.locator('#qqToken').fill('unsaved-test-token-1234567890');await page.locator('#closeQQSettings').click();
  await page.locator('#qqLoginBtn').click();await page.waitForFunction(()=>document.querySelector('#qqLoginHint').textContent.includes('接收配置已同步'));
  await control({account:'34567890'});
  await page.waitForFunction(()=>document.querySelector('#qqAccount').value==='34567890');
  await page.waitForFunction(()=>document.querySelector('#qqLoginHint').textContent.includes('34567890')&&document.querySelector('#qqLoginHint').textContent.includes('接收配置已同步'));
  assert.equal((await get('/api/qq/config')).account_id,'34567890');
  assert.equal(await page.locator('#qqGroups').inputValue(),'87654321\n99887766');
  assert.equal(await page.locator('#qqToken').inputValue(),'unsaved-test-token-1234567890');
  report=await get('/test/reporting');assert.equal(report.ours.length,1);assert.ok(report.ours[0].token_matches&&report.other_client_preserved);
  // Third account's HTTP setup fails: show the failure, then retry from this app.
  await control({account:'45678901',reject:true});
  await page.waitForFunction(()=>document.querySelector('#bridgeStatus').dataset.state==='report_mismatch');
  assert.equal(await page.locator('#qqAccount').inputValue(),'45678901');
  assert.match(await page.locator('#qqLoginHint').innerText(),/重试/);
  assert.ok(!(await page.locator('#qqLoginHint').innerText()).includes('接收配置已同步'));
  assert.equal((await get('/test/reporting')).ours.length,0);
  await page.locator('#closeQQLogin').click();await page.waitForFunction(()=>!document.querySelector('#checkBridge').disabled);
  await control({reject:false});await page.locator('#checkBridge').click();
  await page.waitForFunction(()=>document.querySelector('#bridgeStatus').dataset.state==='ready');
  report=await get('/test/reporting');assert.equal(report.ours.length,1);assert.ok(report.ours[0].token_matches);
  const writes=report.writes;await page.waitForFunction(()=>!document.querySelector('#checkBridge').disabled);await page.locator('#checkBridge').click();await page.waitForFunction(()=>!document.querySelector('#checkBridge').disabled);assert.equal((await get('/test/reporting')).writes,writes);
  await page.reload();await page.waitForLoadState('networkidle');await page.waitForFunction(()=>document.querySelector('#qqAccount').value==='45678901');
  assert.equal((await get('/api/tasks')).tasks.length,0);
  for(const width of [390,1440]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);}
  fs.mkdirSync('test-results',{recursive:true});await page.screenshot({path:'test-results/qq-account-sync.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: automatic account switch/persistence, per-account HTTP setup, correct callback/format/token, preserved groups/unsaved edits/other transports, honest failure/retry, idempotence, reload, two widths, clean console. Simulated NapCat only.');
 }finally{
  if(browser)await browser.close();server.kill();await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));
  assert.equal(path.dirname(path.resolve(folder)),runtimeRoot);
  const cleanup=spawnSync(path.resolve('.venv/Scripts/python.exe'),['-c','import shutil,sys;shutil.rmtree(sys.argv[1])',folder],{windowsHide:true,encoding:'utf8'});
  assert.equal(cleanup.status,0,cleanup.stderr);
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
