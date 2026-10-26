/* Connection overview and shared reception preference; login/capture stay independent. */
let receptionFilterBusy=false,receptionFilterEnabled=false;
function renderReceptionFilter(enabled){
  receptionFilterEnabled=enabled;
  $('#receptionFilterToggle').setAttribute('aria-checked',String(enabled));
  $('#receptionFilterStatus').textContent=enabled?'已开启':'已关闭';
}
async function loadReceptionFilter(){
  if(receptionFilterBusy)return;
  receptionFilterBusy=true;const toggle=$('#receptionFilterToggle');toggle.disabled=true;
  $('#receptionFilterRetry').hidden=true;$('#receptionFilterError').textContent='';
  $('#receptionFilterStatus').textContent='读取中…';
  try{const data=await api('/api/inbox/filter');renderReceptionFilter(data.enabled);toggle.disabled=false;}
  catch(error){$('#receptionFilterStatus').textContent='读取失败';$('#receptionFilterError').textContent=error.message;$('#receptionFilterRetry').hidden=false;}
  finally{receptionFilterBusy=false;}
}
async function saveReceptionFilter(){
  if(receptionFilterBusy)return;
  receptionFilterBusy=true;const toggle=$('#receptionFilterToggle');toggle.disabled=true;toggle.setAttribute('aria-busy','true');
  $('#receptionFilterError').textContent='';$('#receptionFilterStatus').textContent='保存中…';
  try{const data=await api('/api/inbox/filter',{method:'PUT',body:{enabled:!receptionFilterEnabled}});renderReceptionFilter(data.enabled);toast(data.enabled?'接收过滤已开启。':'接收过滤已关闭。');}
  catch(error){renderReceptionFilter(receptionFilterEnabled);$('#receptionFilterError').textContent=error.message;}
  finally{receptionFilterBusy=false;toggle.disabled=false;toggle.removeAttribute('aria-busy');}
}
const connectionRevisions={qq:0,wechat:0};
let connectionsRefreshing=false,qqLoginConnecting=false;
const connectionSnapshots={};
function createConnectionShortcut(source,label){
  const button=document.createElement('button');
  button.type='button';button.className='nav-item';button.dataset.view=source;button.dataset.connection=source;
  button.innerHTML='<span class="connection-name">'+esc(label)+'</span><span class="connection-state" role="status" aria-live="polite">检测中</span>';
  button.onclick=()=>showView(source);$('#connectionShortcuts').append(button);return button;
}
function connectionSummary(source,status){
  const state=status?.state;
  const common={unavailable:['检测失败','danger','无法读取状态，请刷新重试或检查后台。'],unknown:['状态未知','warning','状态未确认，点击查看并重试。'],checking:['待检测','neutral','正在重新检查连接状态。'],connecting:['连接中','warning','正在连接，请完成登录并等待初始化。']};
  if(common[state])return common[state];
  if(source==='qq'){
    const states={ready:['正常','success','QQ 在线，上报配置匹配；可在 QQ 连接页核对最近上报。'],disabled:['已停用','neutral','QQ 消息接收已停用，点击修改设置。'],exited:['已停用','neutral','已退出 NapCat，消息接收已暂停。'],exit_failed:['退出异常','danger','退出尚未确认，请进入 QQ 连接页重试。'],exiting:['退出中','warning','正在退出 NapCat。'],qq_offline:['未登录','warning','QQ 未登录或已离线，点击登录。'],not_running:['未运行','warning','NapCat 未运行或管理页不可达，点击检查。'],not_installed:['未安装','warning','未找到 NapCat，点击查看配置。'],auth_failed:['认证失败','danger','NapCat 管理页认证失败，点击检查。'],account_mismatch:['账号不符','danger','登录 QQ 与接收账号不一致。'],report_disabled:['上报停用','warning','QQ 在线，但 HTTP 上报未启用。'],report_mismatch:['配置异常','danger','HTTP 上报配置不匹配，点击检查。'],config_error:['配置异常','danger','NapCat 配置无法读取，点击检查。']};
    return states[state]||common.unknown;
  }
  if(state==='paused'&&status.reason)return ['配置异常','danger','采集已暂停，请进入微信采集页查看原因。'];
  if(state==='paused'&&(!status.has_account||!status.group_name))return ['未配置','neutral','请设置微信账号和目标群。'];
  const states={paused:['已停用','neutral','采集已暂停，点击手动开始。'],starting:['连接中','warning','正在检查微信和消息读取位置。'],listening:status.gap_possible?['正常','warning','采集运行中，但可能存在消息缺口，点击查看。']:['正常','success','微信采集运行中，等待目标群的新文本。'],waiting:['等待微信','warning','等待电脑微信登录或恢复，点击查看。'],stopping:['暂停中','warning','正在停止采集并清理临时资源。'],error:['采集异常','danger','微信采集异常，点击查看原因并重试。']};
  return states[state]||common.unknown;
}
function renderConnectionSummary(source,status){
  const button=$('[data-connection="'+source+'"]');if(!button)return;
  connectionSnapshots[source]=status;
  const connecting=source==='qq'&&qqLoginConnecting;
  const [label,tone,hint]=connectionSummary(source,connecting?{state:'connecting'}:status);
  $('.connection-state',button).textContent=label;button.dataset.tone=tone;
  button.title=hint;button.setAttribute('aria-label',(source==='qq'?'QQ':'微信')+'：'+label+'，点击查看连接');
}
async function refreshConnections({button}={}){
  if(connectionsRefreshing||document.hidden)return;
  connectionsRefreshing=true;
  const refresh=$('#refreshConnections');setButtonBusy(refresh,true,'检测中…');
  let failed=false;
  try{
    await Promise.all(['qq','wechat'].map(async source=>{
      const revision=connectionRevisions[source],controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),12000);
      try{
        const response=await fetch('/api/'+source+'/status',{signal:controller.signal,cache:'no-store'});
        if(!response.ok)throw new Error('Status unavailable');
        const status=await response.json();
        if(revision===connectionRevisions[source])renderConnectionSummary(source,status);
      }catch{
        failed=true;
        if(revision===connectionRevisions[source])renderConnectionSummary(source,{state:'unavailable'});
      }finally{clearTimeout(timeout);}
    }));
    if(button)toast(failed?'部分状态检测失败，请查看连接页。':'连接状态已更新。');
  }finally{connectionsRefreshing=false;setButtonBusy(refresh,false);}
}
document.addEventListener('connection-status',event=>{
  const {source,status}=event.detail||{};if(!Object.hasOwn(connectionRevisions,source))return;
  connectionRevisions[source]++;renderConnectionSummary(source,status);
});
document.addEventListener('qq-login-state',event=>{
  const pending=['starting','running','generating_qrcode','waiting_qrcode','qrcode_scanned','submitted','password_waiting','quick_waiting','initializing','reconnecting','device_verification','device_scanned','verification_required'];
  qqLoginConnecting=pending.includes(event.detail?.state);
  connectionRevisions.qq++;
  renderConnectionSummary('qq',connectionSnapshots.qq||{state:'checking'});
});
document.addEventListener('DOMContentLoaded',()=>{
  $('#receptionFilterToggle').onclick=saveReceptionFilter;
  $('#receptionFilterRetry').onclick=loadReceptionFilter;
  $('#qqLoginDialog').addEventListener('close',()=>{qqLoginConnecting=false;connectionRevisions.qq++;renderConnectionSummary('qq',connectionSnapshots.qq||{state:'checking'});refreshConnections();});
  $('#refreshConnections').onclick=()=>refreshConnections({button:$('#refreshConnections')});
  refreshConnections();
  setInterval(()=>refreshConnections(),10000);
  document.addEventListener('visibilitychange',()=>{
    if(!document.hidden){for(const source of ['qq','wechat'])renderConnectionSummary(source,{state:'checking'});refreshConnections();}
  });
});
