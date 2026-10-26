const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  try{
    await page.goto('http://127.0.0.1:8000');await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('#rawText').count(),1);
    assert.match(await page.locator('#modelStatus').innerText(),/LM Studio/);
    await page.keyboard.press('Tab');
    assert.ok(await page.evaluate(()=>document.activeElement!==document.body));
    fs.mkdirSync('test-results',{recursive:true});
    await page.screenshot({path:'test-results/preview.png'});
    await page.getByRole('button',{name:'打开设置'}).click();
    assert.equal(await page.locator('#modelId').inputValue(),'qwen3.8-27b');
    await page.screenshot({path:'test-results/settings.png'});
    assert.deepEqual(errors,[]);
    console.log('Running application verified: page, configured local candidate, keyboard focus, settings, screenshots, clean console. No production task data modified.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
