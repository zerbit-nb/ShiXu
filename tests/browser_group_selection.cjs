/* Isolated real browser/API checks. Discovery responses are synthetic; no client is started. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'shixu-groups-')),base='http://127.0.0.1:8796';
  try{await fetch(base+'/api/health');throw Error('Test port occupied');}catch(e){if(e.message==='Test port occupied')throw e;}
  const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',"import uvicorn,sys;from pathlib import Path;from tests.wechat_browser_app import make_app;uvicorn.run(make_app(Path(sys.argv[1])),host='127.0.0.1',port=8796)",folder],{windowsHide:true,stdio:'ignore'});
  let browser;
  const get=async url=>(await fetch(base+url)).json();
  async function checkSettingsScroll(page,prefix){
    const dialog=page.locator('#'+prefix+'SettingsDialog'),form=page.locator('#'+prefix+'Form');
    const guide=form.locator('.connection-guide');
    for(const viewport of [{width:1440,height:1000},{width:1264,height:640},{width:390,height:568},{width:320,height:568}]){
      await page.setViewportSize(viewport);
      await guide.evaluate(el=>{el.open=false;});await form.evaluate(el=>{el.scrollTop=0;});
      const before=await page.locator('#'+prefix+'GroupSearch').boundingBox();
      await guide.evaluate(el=>{el.open=true;});
      const after=await page.locator('#'+prefix+'GroupSearch').boundingBox();
      assert.ok(Math.abs(before.width-after.width)<1,prefix+' controls must not shift when scrollbar appears');
      const metrics=await form.evaluate(el=>{
        const f=el.getBoundingClientRect(),d=el.closest('dialog').getBoundingClientRect();
        return {left:f.left-d.left,right:d.right-f.right,top:f.top-d.top,bottom:d.bottom-f.bottom,
          overflow:getComputedStyle(el).overflowY,outerOverflow:getComputedStyle(el.closest('dialog')).overflowY,
          height:d.height,scrollable:el.scrollHeight>el.clientHeight,wide:el.scrollWidth>el.clientWidth};
      });
      assert.equal(metrics.outerOverflow,'hidden',prefix+' outer frame must not own scrollbar');
      assert.equal(metrics.overflow,'auto',prefix+' content should scroll internally');
      assert.ok(Math.min(metrics.left,metrics.right,metrics.top,metrics.bottom)>=8,prefix+' scrollbar must be inset within rounded frame');
      assert.ok(metrics.height<=viewport.height-46,prefix+' dialog must fit short viewport');
      assert.equal(metrics.wide,false,prefix+' content must not scroll horizontally');
      if(viewport.height===568)assert.ok(metrics.scrollable,prefix+' expanded help must be scrollable');
      if(viewport.width===1264){
        const bounds=await form.boundingBox();
        await page.mouse.move(bounds.x+48,bounds.y+48);await page.mouse.wheel(0,300);
        await page.waitForFunction(id=>document.getElementById(id).scrollTop>0,prefix+'Form');
        await form.evaluate(el=>{el.scrollTop=0;});
        const list=page.locator('#'+prefix+'GroupResults'),listBox=await list.boundingBox();
        await page.mouse.move(listBox.x+80,listBox.y+60);await page.mouse.wheel(0,200);
        await page.waitForFunction(id=>document.getElementById(id).scrollTop>0,prefix+'GroupResults');
        assert.equal(await form.evaluate(el=>el.scrollTop),0,prefix+' list wheel must not scroll the form');
        await list.evaluate(el=>{el.scrollTop=0;});
      }
      await form.evaluate(el=>{el.scrollTop=el.scrollHeight;});
      const helpBox=await guide.boundingBox(),formBox=await form.boundingBox();
      assert.ok(helpBox.y+helpBox.height<=formBox.y+formBox.height+1,prefix+' help end must be reachable');
      if(viewport.width===1264){
        await form.evaluate(el=>{el.scrollTop=0;});
        await dialog.screenshot({path:'test-results/group-selection/'+prefix+'-settings-expanded-scroll.png'});
      }
    }
    await guide.evaluate(el=>{el.open=false;});await form.evaluate(el=>{el.scrollTop=0;});
    await page.setViewportSize({width:1440,height:1000});
  }
  try{
    let ready=false;for(let i=0;i<100;i++){try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(r=>setTimeout(r,100));}assert.ok(ready,'test server unavailable');
    browser=await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],executablePath:process.env.CAMPUSFLOW_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(12000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    let delay=0,fail=false,reads=0;
    const groups=[{id:'100@chatroom',name:'项目协作群'},{id:'200@chatroom',name:'项目协作群'},
      {id:'300@chatroom',name:'活动通知群'},{id:'400@chatroom',name:'<img src=x onerror=alert(1)>'},
      {id:'500@chatroom',name:'这是一个比较长的群聊名称用于检查胶囊在窄屏下的换行和布局'}];
    await page.route('**/api/wechat/groups',async route=>{
      reads++;const wait=delay;await new Promise(r=>setTimeout(r,wait));
      await route.fulfill({status:fail?409:200,json:fail?{detail:'当前微信账号不匹配，请检查后重试。'}:{groups}});
    });
    await page.route('**/api/qq/groups?*',route=>route.fulfill({json:{account_id:'12345678',groups:[{id:'87654321',name:'产品协作群'},{id:'99887766',name:'技术交流群'},...Array.from({length:8},(_,i)=>({id:String(11000000+i),name:'项目通知群 '+(i+1)}))]}}));
    await page.route('**/api/qq/login/sync',route=>route.fulfill({json:{state:'disabled',label:'QQ 接收已停用',hint:'测试环境'}}));
    await page.goto(base+'/#wechat');await page.waitForLoadState('networkidle');
    await page.locator('#wechatSettingsBtn').click();await page.locator('#wechatAccount').fill('demo-wechat');
    await page.locator('#saveWechat').click();await page.locator('#wechatSettingsError').getByText('请至少选择一个接收群聊。').waitFor();
    await page.locator('#wechatGroupsRefresh').click();await page.locator('#wechatGroupResults button').first().waitFor();
    assert.equal(await page.locator('#wechatGroupResults img').count(),0,'group names must be escaped');
    assert.equal(await page.locator('#wechatGroupResults button').count(),5);
    await page.locator('#wechatGroupSearch').fill('项目');assert.equal(await page.locator('#wechatGroupResults button').count(),2);
    await page.locator('#wechatGroupResults button').first().click();
    await page.locator('#wechatGroupSearch').fill('项目');await page.locator('#wechatGroupSearch').press('ArrowDown');await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.querySelectorAll('#wechatGroupPicker .group-chip').length===2);
    assert.equal(await page.locator('#wechatGroupPicker .group-chip').count(),2,'same names may represent different groups');
    assert.equal(await page.locator('#wechatGroupCount').innerText(),'已选 2 / 20');
    assert.equal(await page.locator('#wechatGroupResults [aria-checked=true]').count(),2,'selected rows remain checked');
    await page.locator('#wechatGroupResults button').last().click();
    assert.equal(await page.locator('#wechatGroupPicker .group-chip').count(),1,'checked row can be deselected');
    await page.locator('#wechatGroupResults button').last().click();
    await page.locator('#wechatGroupSearch').fill('活动');await page.locator('#wechatGroupResults button').click();
    const chip=page.locator('#wechatGroupPicker .group-chip').first();const before=(await chip.boundingBox()).width;
    await chip.hover();await chip.getByRole('button').waitFor();assert.equal((await chip.boundingBox()).width,before,'hover must not change width');
    await chip.getByRole('button').click();assert.equal(await page.locator('#wechatGroupPicker .group-chip').count(),2);
    await page.locator('#saveWechat').click();await page.locator('#wechatSettingsDialog').waitFor({state:'hidden'});
    assert.deepEqual((await get('/api/wechat/config')).groups.map(g=>g.id),['200@chatroom','300@chatroom']);
    assert.ok(!JSON.stringify(await get('/api/wechat/status')).includes('demo-wechat'));
    const saved=fs.readFileSync(path.join(folder,'wechat.local.json'),'utf8');assert.ok(!saved.includes('demo-wechat'));
    await page.reload();await page.waitForLoadState('networkidle');await page.locator('#wechatSettingsBtn').click();
    await page.waitForFunction(()=>document.querySelector('#wechatAccount').value==='demo-wechat');
    assert.equal(await page.locator('#wechatGroupPicker .group-chip').count(),2,'selection survives reload');
    delay=250;await page.locator('#wechatGroupsRefresh').click();await page.locator('#wechatAccount').fill('other-wechat');
    await page.waitForTimeout(350);assert.equal(await page.locator('#wechatGroupPicker .group-chip').count(),0);assert.equal(await page.locator('#wechatGroupResults button').count(),0,'stale account results are discarded');
    delay=0;fail=true;await page.locator('#wechatGroupsRefresh').click();await page.locator('#wechatGroupPicker .is-error').waitFor();assert.match(await page.locator('#wechatGroupPicker .is-error').innerText(),/账号不匹配/);
    await page.locator('#closeWechatSettings').click();
    await page.locator('#wechatSettingsBtn').click();await page.waitForFunction(()=>document.querySelector('#wechatAccount').value==='demo-wechat');
    fail=false;await page.locator('#wechatGroupsRefresh').click();await page.locator('#wechatGroupResults button').first().waitFor();
    for(const width of [320,390,768,1440]){
      await page.setViewportSize({width,height:1000});await page.locator('#wechatGroupSearch').fill('长的');
      if(await page.locator('#wechatGroupResults button').count())await page.locator('#wechatGroupResults button').click();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page overflow at '+width);
      const box=await page.locator('#wechatGroupPicker').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width,'picker overflow at '+width);
      await page.locator('#wechatGroupSearch').fill('群');
      const row=await page.locator('#wechatGroupPicker .group-search-row').boundingBox(),results=await page.locator('#wechatGroupResults').boundingBox();
      assert.ok(Math.abs(row.width-results.width)<1,'dropdown width must match search');
      await page.locator('#saveWechat').focus();assert.ok(await page.locator('#wechatGroupResults').isVisible(),'inline checklist stays visible after focus leaves search');
      if(width===390||width===1440){await page.locator('#wechatGroupSearch').fill('');fs.mkdirSync('test-results/group-selection',{recursive:true});await page.locator('#wechatSettingsDialog').screenshot({path:'test-results/group-selection/wechat-settings-'+width+'.png'});}
    }
    await page.locator('#clearWechatGroups').click();
    assert.equal(await page.locator('#wechatGroupCount').innerText(),'已选 0 / 20');
    assert.equal(await page.locator('#wechatGroupPicker .group-chip').count(),0);
    assert.equal(await page.locator('#wechatGroupResults [aria-checked=true]').count(),0);
    assert.ok(await page.locator('#clearWechatGroups').isDisabled());
    assert.deepEqual((await get('/api/wechat/config')).groups.map(g=>g.id),['200@chatroom','300@chatroom'],'clear does not persist until save');
    groups.push(...Array.from({length:21},(_,i)=>({id:(600+i)+'@chatroom',name:'数量测试群 '+i})));
    await page.locator('#wechatGroupsRefresh').click();await page.locator('#wechatGroupSearch').fill('数量测试');
    for(let i=0;i<20;i++)await page.locator('#wechatGroupResults button').nth(i).click();
    await page.locator('#wechatGroupResults button').nth(20).click();
    assert.equal(await page.locator('#wechatGroupCount').innerText(),'已选 20 / 20');
    assert.match(await page.locator('#wechatGroupPicker .is-error').innerText(),/最多选择 20/);
    await page.locator('#clearWechatGroups').click();
    groups.splice(0,groups.length,{id:'100@chatroom',name:'项目协作群'},{id:'200@chatroom',name:'产品交流群'},{id:'300@chatroom',name:'活动通知群'},{id:'400@chatroom',name:'设计交流'},...Array.from({length:8},(_,i)=>({id:(700+i)+'@chatroom',name:'项目通知群 '+(i+1)})));
    await page.locator('#wechatGroupsRefresh').click();await page.locator('#wechatGroupSearch').fill('');
    await page.locator('#wechatGroupResults button').nth(0).click();await page.locator('#wechatGroupResults button').nth(1).click();
    await page.locator('#wechatSettingsTitle').click();
    for(const width of [390,1440]){await page.setViewportSize({width,height:1000});await page.locator('#wechatSettingsDialog').screenshot({path:'test-results/group-selection/wechat-settings-'+width+'.png'});}
    await checkSettingsScroll(page,'wechat');
    await page.locator('#wechatGroupSearch').press('Escape');await page.locator('#wechatSettingsDialog').waitFor({state:'hidden'});
    await fetch(base+'/api/qq/config',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({account_id:'12345678',enabled:false,group_ids:['87654321']})});
    await page.locator('[data-view=qq]').click();await page.locator('#qqSettingsBtn').click();
    await page.locator('#qqGroupsRefresh').click();await page.locator('#qqGroupResults button').first().waitFor();
    assert.match(await page.locator('#qqGroupPicker .group-chip-name').innerText(),/产品协作群/);
    assert.equal(await page.locator('#qqGroupCount').innerText(),'已选 1 / 100');
    assert.equal(await page.locator('#qqGroupResults [aria-checked=true]').count(),1);
    await page.locator('#qqGroupSearch').fill('技术');await page.locator('#qqGroupSearch').press('ArrowDown');await page.keyboard.press('Enter');
    assert.equal(await page.locator('#qqGroupCount').innerText(),'已选 2 / 100');
    await page.locator('#qqGroupResults button').click();assert.equal(await page.locator('#qqGroupCount').innerText(),'已选 1 / 100');
    await page.locator('#qqGroupResults button').click();await page.locator('#qqGroupSearch').fill('');
    for(const width of [320,390,768,1440]){
      await page.setViewportSize({width,height:1000});await page.locator('#qqSettingsTitle').click();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'QQ overflow at '+width);
      const row=await page.locator('#qqGroupPicker .group-search-row').boundingBox(),results=await page.locator('#qqGroupResults').boundingBox();
      assert.ok(Math.abs(row.width-results.width)<1,'QQ list width must match search');
      assert.ok(await page.locator('#qqGroupResults').isVisible(),'QQ checklist stays visible on blur');
      if(width===390||width===1440)await page.locator('#qqSettingsDialog').screenshot({path:'test-results/group-selection/qq-settings-'+width+'.png'});
    }
    await checkSettingsScroll(page,'qq');
    await page.locator('#saveQQ').click();await page.locator('#qqSettingsDialog').waitFor({state:'hidden'});
    assert.deepEqual((await get('/api/qq/config')).group_ids,['87654321','99887766']);
    await page.locator('#qqSettingsBtn').click();await page.locator('#clearQQGroups').click();
    assert.equal(await page.locator('#qqGroupCount').innerText(),'已选 0 / 100');
    assert.equal(await page.locator('#qqGroups').inputValue(),'');assert.ok(await page.locator('#clearQQGroups').isDisabled());
    assert.deepEqual((await get('/api/qq/config')).group_ids,['87654321','99887766'],'QQ clear is not persisted without save');
    await page.locator('#closeQQSettings').click();
    await page.locator('#qqSettingsBtn').click();await page.locator('#qqAccount').fill('22345678');
    assert.equal(await page.locator('#qqGroupPicker .group-chip').count(),0);assert.equal(await page.locator('#qqGroups').inputValue(),'');
    assert.equal(await page.locator('#qqGroupCount').innerText(),'已选 0 / 100');
    await page.locator('#closeQQSettings').click();
    assert.equal((await get('/api/wechat/messages')).total,25);assert.equal((await get('/api/tasks')).tasks.length,0);assert.equal((await get('/api/wechat/status')).state,'paused');
    assert.ok(reads>=3);assert.deepEqual(errors,[]);
    console.log('PASS: encrypted recall, group selection/persistence, QQ account switch, search/keyboard/clear, limits, stale results, 4 widths, expanded help, short viewports, inset scrolling, stable widths, independent mouse-wheel scrolling, no data deletion or capture start.');
  }finally{
    if(browser)await browser.close();if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});
    if(path.dirname(folder)===os.tmpdir()&&path.basename(folder).startsWith('shixu-groups-'))fs.rmSync(folder,{recursive:true,force:true,maxRetries:10,retryDelay:100});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
