/* Login material lives only in this dialog, never in browser storage. */
const loginLabels={quick_unavailable:'账号已失效，请刷新列表',quick_waiting:'正在使用所选账号登录…',password_timeout:'等待密码登录结果超时',password_waiting:'密码登录处理中，请在手机确认',device_verification:'请在手机 QQ 确认新设备登录',device_scanned:'已扫描，等待手机授权确认',verification_expired:'授权已过期，请重新登录',verification_cancelled:'已取消新设备验证',verification_error:'新设备验证失败，请重新登录',verification_stale:'本次授权已结束，请重新登录',exited:'已退出 NapCat',exiting:'正在退出 NapCat…',exit_failed:'退出未确认，请重试',online:'QQ 已在线',waiting_qrcode:'请使用手机 QQ 扫描二维码',generating_qrcode:'正在生成二维码…',qrcode_scanned:'已扫描，请在手机 QQ 上确认',initializing:'手机已确认，正在初始化 QQ…',reconnecting:'正在重新连接 QQ…',login_error:'登录未完成，请刷新二维码或改用另一种方式',not_running:'NapCat 尚未运行或尚未就绪',not_installed:'请先安装 NapCat',config_error:'NapCat 配置无法读取',auth_failed:'NapCat 管理页需要认证',starting:'NapCat 正在后台启动…',running:'NapCat 已运行',submitted:'已提交，正在等待 QQ 确认',verification_required:'QQ 要求安全验证',rate_limited:'请稍后再试',start_failed:'NapCat 启动失败'};
let loginBusy=false, loginPoll=null, loginGeneration=0, loginVerification=null, loginPaused=false, loginDeviceId=null, loginFailure=null;
async function loginRequest(action,body){
  const response=await fetch('/api/qq/login/'+action,{method:['status','quick/accounts'].includes(action)?'GET':'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  const data=await response.json();
  if(!response.ok&&!data.state)throw new Error('登录服务暂不可用，请检查 拾序 是否运行。');
  return data;
}
function clearDeviceView(){
  loginDeviceId=null;$('#qqDevicePane').hidden=true;$('#qqDeviceQR').removeAttribute('src');$('#qqDeviceQR').hidden=true;
}
async function cancelClosedVerification(data){
  if(['device_verification','device_scanned'].includes(data.state)&&data.verification_id){
    try{await loginRequest('verification/cancel',{verification_id:data.verification_id});}catch{}
  }
}
function renderLogin(data){
  if(data.failure_stage)loginFailure=data;
  if(data.online||['initializing','reconnecting','exited','exiting','exit_failed','device_verification','device_scanned'].includes(data.state))loginFailure=null;
  if(loginFailure&&['waiting_qrcode','generating_qrcode','login_error'].includes(data.state))data={...data,...loginFailure,qr_image:null};
  const deviceState=['device_verification','device_scanned'].includes(data.state);
  if(deviceState&&/^[a-f0-9]{32}$/.test(data.verification_id||''))loginDeviceId=data.verification_id;
  const retryDevice=loginDeviceId&&['not_running','auth_failed','config_error'].includes(data.state);
  if(!deviceState&&!retryDevice)clearDeviceView();
  $('#qqDevicePane').hidden=!loginDeviceId;
  if(deviceState){
    const image=$('#qqDeviceQR');
    if(data.qr_image&&/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(data.qr_image)&&data.qr_image.length<100000){image.src=data.qr_image;image.hidden=false;}
    $('#qqDeviceHint').textContent=data.state==='device_scanned'?'已扫描，请在手机 QQ 确认授权。关闭面板会取消验证。':'手机 QQ 确认或扫码授权，有效期 5 分钟。关闭面板会取消验证。';
    loginVerification=null;
  }
  if(retryDevice)$('#qqDeviceHint').textContent='授权查询失败，正在重试；也可取消后重新登录。';
  if(data.state==='verification_required')loginVerification=data;
  loginPaused=['exited','exiting','exit_failed'].includes(data.state);
  if(data.online||loginPaused)loginVerification=null;
  if(loginVerification&&!data.online&&['waiting_qrcode','login_error'].includes(data.state))data={...data,...loginVerification,qr_image:null};
  if(data.failure_stage||data.state==='quick_unavailable')$('#qqLoginError').textContent=data.message||'登录未完成，请重试。';
  document.dispatchEvent(new CustomEvent('qq-login-state',{detail:{state:data.state}}));
  $('#qqLoginStatus').textContent=loginLabels[data.state]||'正在核对登录状态';
  $('#qqLoginStatus').dataset.state=data.state;
  $('#qqLoginHint').textContent=data.message||({online:'当前账号：'+data.account_id+' · 正在同步接收配置…',initializing:'初始化可能需几分钟，请保持 NapCat 运行。',qrcode_scanned:'请在手机 QQ 中确认登录。'}[data.state]||'关闭面板不会停止后台。');
  const image=$('#qqLoginQR');
  if(data.qr_image&&/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(data.qr_image)&&data.qr_image.length<100000){if(image.src!==data.qr_image)image.src=data.qr_image;image.hidden=false;$('#qqQRPlaceholder').hidden=true;}
  else{image.removeAttribute('src');image.hidden=true;$('#qqQRPlaceholder').hidden=false;$('#qqQRPlaceholder').textContent=data.online?'已连接':data.state==='qrcode_scanned'?'等待手机确认':data.state==='initializing'?'正在初始化':'二维码准备中';}
  $('#qqLoginMethods').hidden=!!data.online||loginPaused||!!loginDeviceId;
  $('#qqStartBackground').hidden=!!loginDeviceId;
  // A running bridge can be offline, awaiting authorization or failing status checks.
  // Keep its existing, path-scoped exit action reachable in all uncertain states.
  $('#qqLogout').hidden=['exited','not_installed'].includes(data.state);
  $('#qqLogout').textContent=data.state==='exit_failed'?'重试退出 NapCat':'退出 NapCat';
  $('#qqExitNote').hidden=$('#qqLogout').hidden;
  $('#qqStartBackground').textContent=loginPaused?'启动并登录':'启动 / 检查后台';
  if(loginPaused){clearQuickAccounts();$('#qqLoginAccount').value='';$('#qqLoginPassword').value='';$('#qqQRPlaceholder').textContent=data.state==='exited'?'已断开连接':'退出尚未确认';}
  const link=$('#qqLoginVerify');link.hidden=true;
  if(data.webui_url){try{const url=new URL(data.webui_url);if(url.protocol==='http:'&&url.hostname==='127.0.0.1'&&!url.username&&!url.password){link.href=url.origin;link.hidden=false;}}catch{}}
  if(data.online){$('#qqLoginPassword').value='';loadBridgeStatus();}
}
function queueLoginPoll(generation){
  clearTimeout(loginPoll);
  if(!$('#qqLoginDialog').open||generation!==loginGeneration||loginPaused)return;
  loginPoll=setTimeout(()=>checkLogin(generation),3000);
}
async function checkLogin(generation=loginGeneration){
  if(!$('#qqLoginDialog').open||generation!==loginGeneration)return;
  if(loginBusy||document.hidden){queueLoginPoll(generation);return;}
  loginBusy=true;
  try{const data=await loginRequest(loginDeviceId?'verification/poll':'status',loginDeviceId?{verification_id:loginDeviceId}:undefined);if(generation===loginGeneration&&$('#qqLoginDialog').open){$('#qqLoginError').textContent=['not_running','auth_failed','config_error','verification_error','verification_stale'].includes(data.state)?(data.message||'登录查询失败，请重试。'):'';renderLogin(data);}else await cancelClosedVerification(data);}
  catch(error){if(generation===loginGeneration){$('#qqLoginError').textContent=error.message;$('#qqLoginQR').hidden=true;$('#qqLoginQR').removeAttribute('src');$('#qqLoginVerify').hidden=true;}}
  finally{loginBusy=false;queueLoginPoll(generation);}
}
async function loginAction(action,button,body){
  if(loginBusy)return;loginVerification=null;loginFailure=null;loginBusy=true;const generation=loginGeneration;setButtonBusy(button,true,action==='start'?'启动中…':action==='refresh'?'刷新中…':'登录中…');$('#qqLoginError').textContent='';
  document.dispatchEvent(new CustomEvent('qq-login-state',{detail:{state:action==='password'?'password_waiting':action==='quick'?'quick_waiting':'starting'}}));
  $('#qqLoginDialog').setAttribute('aria-busy','true');
  if(action==='refresh'||action==='start'){$('#qqLoginQR').hidden=true;$('#qqLoginQR').removeAttribute('src');$('#qqQRPlaceholder').hidden=false;$('#qqQRPlaceholder').textContent=action==='refresh'?'正在刷新二维码…':'正在检查后台…';}
  if(action==='password'){$('#qqLoginStatus').textContent=loginLabels.password_waiting;$('#qqLoginStatus').dataset.state='password_waiting';$('#qqLoginHint').textContent='请在手机 QQ 确认，最多等待 5 分钟。请勿重复提交。';}
  if(action==='quick'){$('#qqLoginStatus').textContent=loginLabels.quick_waiting;$('#qqLoginStatus').dataset.state='quick_waiting';$('#qqLoginHint').textContent='等待 QQ 确认在线…';}
  const controls=$('#qqLoginDialog').querySelectorAll('button:not(#closeQQLogin),input,select');controls.forEach(el=>el.disabled=true);
  try{const data=await loginRequest(action,body);if(generation===loginGeneration&&$('#qqLoginDialog').open)renderLogin(data);else await cancelClosedVerification(data);}
  catch(error){if(generation===loginGeneration){$('#qqLoginError').textContent=error.message;document.dispatchEvent(new CustomEvent('qq-login-state',{detail:{state:'unavailable'}}));}}
  finally{body=null;$('#qqLoginPassword').value='';setButtonBusy(button,false);controls.forEach(el=>el.disabled=false);$('#qqQuickSubmit').disabled=!$('#qqQuickAccount').value;$('#qqLoginDialog').removeAttribute('aria-busy');loginBusy=false;queueLoginPoll(generation);}
}
function selectLoginMode(mode){
  const tabs=[['quick','qqQuickMode','qqQuickPane'],['qr','qqScanMode','qqScanPane'],['password','qqPasswordMode','qqPasswordPane']];
  for(const [name,tab,pane] of tabs){const active=name===mode;$('#'+pane).hidden=!active;$('#'+tab).setAttribute('aria-selected',String(active));$('#'+tab).tabIndex=active?0:-1;}
  $('#qqLoginPassword').value='';
  if(mode==='quick')loadQuickAccounts();
}
document.addEventListener('DOMContentLoaded',()=>{
  $('#qqLoginBtn').onclick=async()=>{clearDeviceView();clearQuickAccounts();$('#qqStartBackground').hidden=false;loginGeneration++;loginVerification=null;loginPaused=false;$('#qqLogout').hidden=true;$('#qqExitNote').hidden=true;$('#qqLoginQR').hidden=true;$('#qqLoginQR').removeAttribute('src');$('#qqLoginVerify').hidden=true;$('#qqQRPlaceholder').hidden=false;$('#qqLoginMethods').hidden=false;$('#qqLoginStatus').textContent='正在检查登录状态…';$('#qqLoginDialog').showModal();$('#qqLoginError').textContent='';selectLoginMode('qr');try{const config=await api('/api/qq/config');$('#qqLoginAccount').value=config.account_id;}catch{}await checkLogin();};
  $('#closeQQLogin').onclick=()=>$('#qqLoginDialog').close();
  $('#qqLoginDialog').addEventListener('close',()=>{const ident=loginDeviceId;clearDeviceView();clearQuickAccounts();if(ident)loginRequest('verification/cancel',{verification_id:ident}).catch(()=>{});loginGeneration++;clearTimeout(loginPoll);$('#qqLoginPassword').value='';$('#qqLoginQR').removeAttribute('src');$('#qqLoginQR').hidden=true;$('#qqLoginVerify').hidden=true;loadBridgeStatus();});
  $('#qqStartBackground').onclick=async()=>{if(loginBusy)return;const wasPaused=loginPaused;loginPaused=false;await loginAction('start',$('#qqStartBackground'));if(wasPaused&&!loginPaused){try{const config=await api('/api/qq/config');$('#qqLoginAccount').value=config.account_id;}catch{}selectLoginMode('qr');await checkLogin();}};
  $('#qqLogout').onclick=exitNapCat;
  $('#qqDeviceCancel').onclick=()=>loginAction('verification/cancel',$('#qqDeviceCancel'),{verification_id:loginDeviceId});
  $('#qqLoginRefresh').onclick=()=>loginAction('refresh',$('#qqLoginRefresh'));
  $('#qqQuickMode').onclick=()=>selectLoginMode('quick');
  $('#qqScanMode').onclick=()=>selectLoginMode('qr');$('#qqPasswordMode').onclick=()=>selectLoginMode('password');
  const modes=[['qqQuickMode','quick'],['qqScanMode','qr'],['qqPasswordMode','password']];
  modes.forEach(([id],index)=>$('#'+id).addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3;
    selectLoginMode(modes[next][1]);$('#'+modes[next][0]).focus();
  }));
  $('#qqPasswordForm').onsubmit=event=>{event.preventDefault();if(loginBusy)return;const body={account_id:$('#qqLoginAccount').value.trim(),password:$('#qqLoginPassword').value};$('#qqLoginPassword').value='';loginAction('password',$('#qqPasswordSubmit'),body);};
});


async function exitNapCat(){
  if(loginBusy)return;
  if(!confirm('退出 NapCat？\n将停止本项目连接与群消息接收，保留待办、历史和接收配置。普通桌面 QQ 不受影响。重新连接需点击“启动并登录”。'))return;
  clearTimeout(loginPoll);loginGeneration++;const generation=loginGeneration;loginBusy=true;loginPaused=true;loginVerification=null;clearDeviceView();
  const button=$('#qqLogout'),controls=$('#qqLoginDialog').querySelectorAll('button:not(#closeQQLogin),input');
  setButtonBusy(button,true,'退出中…');controls.forEach(el=>el.disabled=true);$('#qqLoginDialog').setAttribute('aria-busy','true');$('#qqLoginError').textContent='';
  try{
    const data=await loginRequest('logout');
    if(generation!==loginGeneration)return;
    if(data.state!=='exited'){
      $('#qqLoginError').textContent=data.message||'退出失败，无法确认 NapCat 已停止。';
      renderLogin({...data,state:'exit_failed',online:null,account_id:'',qr_image:null});
      return;
    }
    renderLogin(data);toast('已退出 NapCat，群消息接收已暂停。');
  }catch(error){
    if(generation===loginGeneration){$('#qqLoginError').textContent='退出失败，后台状态未确认，请重试。';renderLogin({state:'exit_failed',message:'QQ 可能仍在线，请重试退出。'});}
  }finally{
    setButtonBusy(button,false);controls.forEach(el=>el.disabled=false);$('#qqLoginDialog').removeAttribute('aria-busy');loginBusy=false;
    if(generation===loginGeneration&&loginPaused)button.textContent=$('#qqLoginStatus').dataset.state==='exit_failed'?'重试退出 NapCat':'退出 NapCat';
    loadBridgeStatus();loadQQInbox();
  }
}
