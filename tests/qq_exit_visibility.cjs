const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
const el=id=>{if(!elements.has(id))elements.set(id,{hidden:false,dataset:{},textContent:'',value:'',removeAttribute(){}});return elements.get(id);};
const context=vm.createContext({$:el,clearQuickAccounts(){},loadBridgeStatus(){},document:{addEventListener(){},dispatchEvent(){}},CustomEvent:class{}});
vm.runInContext(fs.readFileSync('app/static/qq-login.js','utf8'),context);
for(const state of ['waiting_qrcode','initializing','running','start_failed','not_running','auth_failed','config_error','device_verification','online','exit_failed']){
 context.payload={state,online:state==='online'};
 vm.runInContext('renderLogin(payload)',context);
 assert.equal(el('#qqLogout').hidden,false,'Exit unavailable in '+state);
}
for(const state of ['exited','not_installed']){context.payload={state};vm.runInContext('renderLogin(payload)',context);assert.equal(el('#qqLogout').hidden,true,state);}
console.log('PASS: exit entry remains available before QQ login and after startup/status failures');
