/* Review workflows against the service owned by browser_acceptance.cjs. */
const {chromium}=require('playwright'),assert=require('node:assert/strict');
(async()=>{
 assert.equal(process.env.CAMPUSFLOW_ISOLATED_UI,'1','Use tests/browser_acceptance.cjs');
 const base='http://127.0.0.1:8765';
 const json=async url=>(await fetch(base+url)).json();
 const tasks=async()=>(await json('/api/tasks')).tasks;
 for(const task of await tasks())await fetch(base+'/api/tasks/'+task.id,{method:'DELETE'});
 for(const draft of (await json('/api/drafts')).drafts)await fetch(base+'/api/drafts/'+draft.id+'/discard',{method:'POST'});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(base+'/#inbox');await page.waitForLoadState('networkidle');
  const card=page.locator('.draft-card');
  const manual=async(text,day='2026-10-15',time='20:00')=>{
   await page.locator('[data-view=inbox]').click();await page.locator('#rawText').fill(text);
   await page.locator('#sourceGroup').fill('测试课程群');await page.locator('#manualBtn').click();await card.waitFor();
   await card.locator('[data-field=title]').fill('提交数据库实验报告');
   await card.locator('[data-field=day]').fill(day);await card.locator('[data-field=time]').fill(time);
  };
  const check=async()=>{await card.locator('[data-action=check]').click();};
  const consumed=async()=>{await page.waitForFunction(()=>document.querySelectorAll('.draft-card').length===0);};
  await manual('请于2026年10月15日20:00前提交数据库实验报告。');
  await card.locator('[data-field=title]').fill('');await check();assert.match(await card.locator('.field-error').innerText(),/任务标题/);assert.equal((await tasks()).length,0);
  await card.locator('[data-field=title]').fill('提交数据库实验报告');await card.locator('[data-field=day]').fill('');await check();assert.match(await card.locator('.field-error').innerText(),/同时选择日期/);
  await card.locator('[data-field=day]').fill('2026-10-15');await card.locator('.editor-more summary').click();
  await card.locator('[data-field=materials]').fill(['实验报告','源代码'].join(String.fromCharCode(10)));await card.locator('[data-field=target_audience]').fill('计算机学院大二学生');
  await card.locator('[data-field=format_requirement]').fill('PDF');await card.locator('[data-field=submit_method]').fill('教学平台');await card.locator('[data-field=priority]').selectOption('high');
  await check();await consumed();let task=(await tasks())[0];assert.deepEqual(task.materials,['实验报告','源代码']);assert.equal(task.target_audience,'计算机学院大二学生');assert.equal(task.submit_method,'教学平台');assert.equal(task.format_requirement,'PDF');assert.equal(task.priority,'high');
  const id=task.id;
  await manual('再次提醒：请于2026年10月15日20:00前提交数据库实验报告。');await check();await card.locator('[data-action=link]').waitFor();
  await card.locator('[data-action=match-source]').click();await page.locator('#sourceDialog').waitFor({state:'visible'});assert.match(await page.locator('#sourceContent').innerText(),/数据库实验报告/);await page.locator('#closeSource').click();
  await card.locator('[data-action=link]').click();await consumed();assert.equal((await tasks()).length,1);assert.equal((await json('/api/tasks/'+id+'/sources')).messages.length,2);assert.equal((await json('/api/tasks/'+id+'/history')).history.length,0);
  await manual('数据库实验报告截止时间由2026年10月15日20:00延期至2026年10月17日21:00。','2026-10-17','21:00');await check();await card.locator('[data-action=apply-deadline]').waitFor();
  await card.locator('[data-field=day]').fill('2026-10-18');await card.locator('[data-action=apply-deadline]').click();await page.waitForFunction(()=>document.querySelector('.field-error')?.textContent.includes('重新核对'));assert.match(await card.locator('.field-error').innerText(),/重新核对/);assert.equal((await tasks())[0].deadline,'2026-10-15T20:00:00+08:00');
  await card.locator('[data-field=day]').fill('2026-10-17');await check();await card.locator('[data-action=apply-deadline]').click();await consumed();assert.equal((await tasks()).length,1);assert.equal((await tasks())[0].deadline,'2026-10-17T21:00:00+08:00');
  await manual('取消本次数据库实验报告提交，同学们无需再提交。','','');await check();await card.locator('[data-action=apply-cancel]').waitFor();await card.locator('[data-action=apply-cancel]').click();await consumed();
  assert.equal((await tasks())[0].status,'cancelled');assert.deepEqual((await json('/api/tasks/'+id+'/history')).history.map(entry=>entry.action),['deadline','cancel']);
  await page.locator('[data-view=tasks]').click();await page.locator('[data-filter=all]').click();await page.locator('[data-task-group=cancelled] > summary').waitFor();await page.locator('[data-task-group=cancelled] > summary').click();await page.locator('[data-task-action=reopen]').click();await page.locator('.task-row.pending').waitFor();
  await manual('同题报告需要独立提交一份，请核对后保留第二项。','2026-10-17','21:00');await check();await card.locator('[data-action=create-anyway]').waitFor();await card.locator('[data-action=create-anyway]').click();await consumed();assert.equal((await tasks()).length,2);
  await page.locator('#rawText').fill('');await page.locator('#queueBtn').click();assert.match(await page.locator('#extractError').innerText(),/先填写/);
  for(let i=0;i<20;i++){await page.locator('#rawText').fill('队列测试 '+i);await page.locator('#queueBtn').click();}
  assert.equal(await page.locator('.batch-entry').count(),19);assert.match(await page.locator('#extractError').innerText(),/队列已满/);
  while(await page.locator('.batch-entry').count())await page.locator('[data-remove]').first().click();
  await page.locator('#rawText').fill('bad');await page.locator('#queueBtn').click();await page.locator('#rawText').fill('闲聊');await page.locator('#queueBtn').click();await page.locator('#rawText').fill('通知');await page.locator('#extractForm button[type=submit]').click();
  await page.locator('.failure-entry').waitFor();await page.waitForFunction(()=>document.querySelectorAll('.draft-card').length===2);assert.equal((await tasks()).length,2);
  await page.getByRole('button',{name:'重试这条消息'}).click();await page.waitForFunction(()=>document.querySelector('.failure-entry button')&&!document.querySelector('.failure-entry button').disabled);assert.equal(await page.locator('.failure-entry').count(),1);assert.match(await page.locator('.failure-entry').innerText(),/JSON/);
  // Explicit mocked recovery only exercises rendering; backend recovery is covered by pytest.
  await page.route('**/api/messages/*/retry',async route=>{
   const failed=await json('/api/messages/'+route.request().url().split('/').at(-2));
   await route.fulfill({json:{message:failed,drafts:[],error:null}});
  });
  await page.getByRole('button',{name:'重试这条消息'}).click();await page.waitForFunction(()=>document.querySelectorAll('.failure-entry').length===0);await page.unroute('**/api/messages/*/retry');assert.equal(await card.count(),2);
  assert.deepEqual(errors,[]);console.log('PASS: manual title/time validation and all fields, duplicate source/link, stale review protection, deadline update and cancellation history, reopen and deliberate duplicate creation, batch queue limit/remove/failure/retry; no page errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
