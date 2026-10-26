/* Owns an isolated test service; refuses occupied ports. */
const assert=require('node:assert/strict'),path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
(async()=>{
 const base='http://127.0.0.1:8765';
 try{await fetch(base+'/api/health');throw new Error('Test port 8765 occupied: refusing existing server');}
 catch(e){if(!e.cause||e.cause.code!=='ECONNREFUSED')throw e;}
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-m','tests.run_ui_server'],{windowsHide:true,stdio:'pipe'});
 let log='';server.stderr.on('data',chunk=>log+=chunk);
 try{
  let ready=false;for(let i=0;i<80;i++){if(server.exitCode!==null)throw new Error(log);try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;await new Promise(resolve=>setTimeout(resolve,150));}assert.ok(ready,log);
  for(const file of ['browser_smoke.cjs','browser_workflows.cjs','browser_completed.cjs','browser_providers.cjs']){
   const result=spawnSync(process.execPath,[path.join('tests',file)],{windowsHide:true,stdio:'inherit',env:{...process.env,CAMPUSFLOW_ISOLATED_UI:'1'}});
   if(result.error)throw result.error;assert.equal(result.status,0,file+' failed');
  }
  console.log('PASS: isolated acceptance runner completed all configured suites');
 }finally{if(server.pid)spawnSync('taskkill',['/pid',String(server.pid),'/t','/f'],{windowsHide:true,stdio:'ignore'});}
})().catch(error=>{console.error(error);process.exitCode=1});
