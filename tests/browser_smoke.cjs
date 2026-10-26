/* Requires Playwright in NODE_PATH or installed locally. Runs only against a test DB. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  assert.equal(process.env.CAMPUSFLOW_ISOLATED_UI, '1', 'Use tests/browser_acceptance.cjs');
  const browser = await chromium.launch({headless:true, executablePath:process.env.CAMPUSFLOW_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try {
    // This port exclusively uses the temporary browser-test database.
    const base='http://127.0.0.1:8765';
    const initial=await (await fetch(`${base}/api/tasks`)).json();
    for(const task of initial.tasks)await fetch(`${base}/api/tasks/${task.id}`,{method:'DELETE'});
    const initialDrafts=await (await fetch(`${base}/api/drafts`)).json();
    for(const draft of initialDrafts.drafts)await fetch(`${base}/api/drafts/${draft.id}/discard`,{method:'POST'});
    await page.goto('http://127.0.0.1:8765/#inbox');
    await page.waitForLoadState('networkidle');
    assert.match(await page.title(), /拾序/);
    await page.locator('#rawText').fill('请明天 20:00 前提交材料，同时参加会议。');
    await page.locator('#sentAt').fill('2026-10-10T12:00');
    await page.locator('#sourceGroup').fill('课程群');
    await page.getByRole('button',{name:'分析通知',exact:false}).click();
    await page.locator('.draft-card').first().waitFor();
    assert.equal(await page.locator('.draft-card').count(),2);
    await page.reload();await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('.draft-card').count(),2);
    const first=page.locator('.draft-card').first();
    await first.locator('[data-field="title"]').fill('提交成绩单');
    await first.locator('.editor-more summary').click();
    await first.locator('[data-field="materials"]').fill('成绩单\n申请表');
    await first.getByRole('button',{name:'核对并创建',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.draft-card').length===1);
    await page.locator('.draft-card').getByRole('button',{name:'丢弃'}).click();
    await page.getByRole('button',{name:/待办中心/}).click();
    await page.locator('.task-row').waitFor();
    assert.match(await page.locator('.task-row').innerText(),/提交成绩单/);
    await page.locator('.more-trigger').click();
    await page.getByRole('menuitem',{name:'编辑',exact:true}).click();
    await page.locator('#editDialog').waitFor({state:'visible'});
    await page.locator('#editDialog [data-field="day"]').fill('2026-10-12');
    await page.locator('#editDialog [data-field="time"]').fill('');
    await page.locator('#editDialog .editor-more summary').click();
    await page.locator('#editDialog [data-field="location"]').fill('线上');
    await page.getByRole('button',{name:'保存修改'}).click();
    await page.locator('#editDialog').waitFor({state:'hidden'});
    await page.waitForFunction(()=>document.querySelector('.task-row')?.innerText.includes('仅日期'));
    await page.locator('.more-trigger').click();
    await page.getByRole('menuitem',{name:'原文',exact:true}).click();
    await page.locator('#sourceDialog').waitFor({state:'visible'});
    assert.match(await page.locator('#sourceContent').innerText(),/请明天/);
    await page.locator('#closeSource').click();
    await page.getByRole('button',{name:'完成',exact:true}).click();
    await page.getByRole('tab',{name:'已完成',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.task-row.completed'));
    await page.reload();await page.waitForLoadState('networkidle');
    await page.getByRole('button',{name:/待办中心/}).click();
    await page.getByRole('tab',{name:'已完成',exact:true}).click();
    await page.locator('.task-row.completed').waitFor();
    page.once('dialog',dialog=>dialog.accept());
    await page.locator('.more-trigger').click();
    await page.getByRole('menuitem',{name:'删除',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.task-row').length===0);
    await page.locator('[data-view="inbox"]').click();
    await page.locator('#rawText').fill('bad');await page.locator('#queueBtn').click();
    await page.locator('#rawText').fill('通知');
    await page.getByRole('button',{name:'分析通知',exact:false}).click();
    await page.locator('.failure-entry').waitFor();
    assert.equal(await page.locator('.draft-card').count(),2);
    assert.match(await page.locator('.failure-entry').innerText(),/JSON/);
    for(const width of [320,768,1024,1440]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow at ${width}`);
    }
    await page.setViewportSize({width:1440,height:1000});
    fs.mkdirSync('test-results',{recursive:true});
    await page.screenshot({path:'test-results/browser-inbox.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('Browser smoke passed: extract, restore, confirm, edit, source, complete, delete, batch failure, responsive sizes; no page errors.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
