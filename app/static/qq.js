let qqOffset=0, qqLoading=false, qqProcessing=false, bridgeLoading=false, bridgeQueued=false, qqAccountRevision=0;
const qqPageSize=20;
const qqStatuses=messageStatuses;
function qqStatusText(config){
  if(config.session_paused){$('#qqStatus').textContent='已暂停';$('#qqConnection').textContent='群消息接收已暂停；已有消息可继续整理。';return;}
  $('#qqStatus').textContent=config.enabled?'已启用':'已停用';
  $('#qqConnection').textContent=config.enabled?(config.last_event_at?'最近上报：'+new Date(config.last_event_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'等待群消息，可检查连接状态。'):'接收已停用；已有消息可继续整理。';
}
async function loadQQSettings(){
  const revision=qqAccountRevision,config=await api('/api/qq/config');
  $('#qqEnabled').checked=config.enabled;if(revision===qqAccountRevision)$('#qqAccount').value=config.account_id;$('#qqGroups').value=config.group_ids.join('\n');
  $('#qqToken').value='';$('#qqToken').type='password';$('#showQQToken').textContent='显示本次输入';
  $('#qqTokenStatus').textContent=config.has_token?'Token 已加密保存，留空保留；保存后自动同步上报。':'登录后自动生成并配置，无需手动复制。';qqStatusText(config);
}
function qqMessageHtml(m){
  const actionable=['received','failed'].includes(m.extraction_status);
  const actions=actionable?'<button class="small-btn" data-qq-action="analyze">'+(m.extraction_status==='failed'?'重试分析':'分析通知')+'</button><button class="small-btn" data-qq-action="manual">手动整理</button><button class="small-btn" data-qq-action="ignore">忽略</button>':'';
  return '<article class="task-row qq-message" data-message-state="'+esc(m.extraction_status)+'" data-qq-message="'+esc(m.id)+'"><div class="qq-message-head"><div class="task-meta"><span class="meta">'+esc(m.source_group)+'</span><span class="meta">'+esc(m.sender||'发送者未知')+'</span><span class="meta">'+esc(m.sent_at?new Date(m.sent_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'发送时间未知')+'</span></div><span class="message-state">'+esc(qqStatuses[m.extraction_status]||m.extraction_status)+'</span></div><h3 class="task-title">'+esc(m.raw_text.slice(0,100))+'</h3><details class="task-details"><summary>查看完整原文</summary><div class="source-content">'+esc(m.raw_text)+'</div></details><div class="draft-actions">'+actions+'</div></article>';
}
async function loadQQInbox(options = {}){
  if(qqLoading||qqProcessing)return false;qqLoading=true;
  const button=options.button, started=performance.now();if(button)setButtonBusy(button,true,'刷新中…');
  try{
    const [config,data]=await Promise.all([api('/api/qq/config'),api('/api/qq/inbox?limit='+qqPageSize+'&offset='+qqOffset)]);
    qqStatusText(config);$('#qqInboxError').textContent='';
    $('#qqMessages').innerHTML=data.messages.length?data.messages.map(qqMessageHtml).join(''):'<div class="empty"><strong>还没有收到消息</strong>请连接 NapCat，等待群消息。</div>';
    $('#qqPage').textContent=data.total?'第 '+(Math.floor(qqOffset/qqPageSize)+1)+' 页 · 共 '+data.total+' 条':'0 条消息';
    $('#qqPrev').disabled=qqOffset===0;$('#qqNext').disabled=qqOffset+qqPageSize>=data.total;
    const configModel=await api('/api/config');
    $('#qqDestination').textContent=configModel.provider==='local'?'本地分析 · 不自动调用模型':'分析时发送所选原文与发送时间到 '+providerLabels[configModel.provider]+'，可能产生费用；不自动分析。';
      if(button)toast('QQ 收件箱已刷新。');return true;
  }catch(e){$('#qqInboxError').textContent='收件箱读取失败：'+e.message;if(button)toast('收件箱刷新失败，请重试。');return false;}finally{if(button){await new Promise(resolve=>setTimeout(resolve,Math.max(0,400-(performance.now()-started))));setButtonBusy(button,false);}qqLoading=false;}
}
async function processQQMessage(event){
  const button=event.target.closest('[data-qq-action]');if(!button||qqProcessing)return;
  const card=button.closest('[data-qq-message]');qqProcessing=true;
  setButtonBusy(button,true,button.dataset.qqAction==='analyze'?'分析中…':'处理中…');card.querySelectorAll('button').forEach(b=>b.disabled=true);$('#qqInboxError').textContent='';
  try{
    captureDrafts();
    const result=await api('/api/qq/messages/'+card.dataset.qqMessage+'/process',{method:'POST',body:{action:button.dataset.qqAction}});
    if(result.error)$('#qqInboxError').textContent=result.error;
    else if(result.drafts.length){
      state.messages.set(result.message.id,result.message);state.drafts.push(...result.drafts);renderDrafts();showView('inbox');$('#draftSection').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});toast('草稿已生成，请核对。');
    }else toast(button.dataset.qqAction==='ignore'?'已忽略这条消息。':'这条消息没有需要行动的任务。');
  }catch(e){$('#qqInboxError').textContent=e.message;}
  finally{setButtonBusy(button,false);qqProcessing=false;const error=$('#qqInboxError').textContent;await loadQQInbox();if(error)$('#qqInboxError').textContent=error;}
}
async function initializeQQ(){
  const nav=createConnectionShortcut('qq','QQ');
  $('#qqSettingsBtn').onclick=()=>$('#qqSettingsDialog').showModal();$('#closeQQSettings').onclick=()=>$('#qqSettingsDialog').close();
  $('#qqCallback').textContent=location.origin+'/api/qq/events';
  $('#qqForm').onsubmit=async e=>{
    e.preventDefault();const button=$('#saveQQ');if(button.disabled)return;setButtonBusy(button,true,'保存中…');$('#qqError').textContent='';
    try{const config=await api('/api/qq/config',{method:'PUT',body:{enabled:$('#qqEnabled').checked,account_id:$('#qqAccount').value.trim(),group_ids:$('#qqGroups').value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean),token:$('#qqToken').value||null}});qqStatusText(config);await loadQQSettings();await loadBridgeStatus();toast('QQ 接收设置已保存。');$('#qqSettingsDialog').close();}
    catch(error){$('#qqError').textContent=error.message;}finally{setButtonBusy(button,false);}
  };
  $('#generateQQToken').onclick=()=>{const values=crypto.getRandomValues(new Uint8Array(24));$('#qqToken').value=Array.from(values,v=>v.toString(16).padStart(2,'0')).join('');$('#qqTokenStatus').textContent='已生成，保存后自动同步上报。';}; // taste-skill-ignore: cryptographic token byte encoding, not visual numbering
  $('#showQQToken').onclick=()=>{const input=$('#qqToken');input.type=input.type==='password'?'text':'password';$('#showQQToken').textContent=input.type==='password'?'显示本次输入':'隐藏本次输入';};
  $('#refreshQQ').onclick=()=>{loadQQInbox({button:$('#refreshQQ')});loadBridgeStatus();};$('#checkBridge').onclick=()=>loadBridgeStatus({button:$('#checkBridge')});$('#qqMessages').onclick=processQQMessage;
  $('#qqPrev').onclick=()=>{qqOffset=Math.max(0,qqOffset-qqPageSize);loadQQInbox();};$('#qqNext').onclick=()=>{qqOffset+=qqPageSize;loadQQInbox();};
  setInterval(()=>{if(!$('#qqView').hidden&&!document.hidden){loadQQInbox();loadBridgeStatus();}},10000);
}
document.addEventListener('DOMContentLoaded',initializeQQ);


async function loadBridgeStatus(options = {}){
  if(bridgeLoading){bridgeQueued=true;return;}bridgeLoading=true;const button=$('#checkBridge'),started=performance.now(),generation=loginGeneration;setButtonBusy(button,true,'配置 / 检查中…');
  try{
    // The overview stays read-only. Connection-page checks explicitly reconcile
    // the authenticated NapCat identity and its per-account reporting settings.
    const synced=await loginRequest('sync');
    if(generation!==loginGeneration){bridgeQueued=true;return;}
    if(synced.receiver){
      qqAccountRevision++;$('#qqAccount').value=synced.receiver.account_id;
      qqStatusText(synced.receiver);
      if(!$('#qqToken').value)$('#qqTokenStatus').textContent='Token 已加密保存，留空保留；保存后自动同步上报。';
    }
    const observed=await api('/api/qq/status');
    if(generation!==loginGeneration){bridgeQueued=true;return;}
    const status={...observed,...synced,label:synced.label||synced.message||observed.label,hint:synced.hint||synced.message||observed.hint};
    if($('#qqLoginDialog').open&&$('#qqLoginStatus').dataset.state==='online'){
      $('#qqLoginHint').textContent=synced.receiver?'当前账号：'+synced.receiver.account_id+' · '+(synced.state==='ready'?'接收配置已同步':status.hint):status.hint;
    }
    document.dispatchEvent(new CustomEvent('connection-status',{detail:{source:'qq',status}}));
    $('#bridgeStatus').innerHTML='<strong>'+esc(status.label)+'</strong><p>'+esc(status.hint)+'</p><div class="task-meta"><span class="meta">已接收 '+esc(status.received_count)+' 条</span><span class="meta">最近消息：'+esc(status.last_message_at?new Date(status.last_message_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'尚未收到')+'</span></div>';
    $('#bridgeStatus').dataset.state=status.state;$('#bridgeChecked').textContent='检查时间：'+new Date(status.checked_at).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai'});
    const link=$('#bridgeWebUI');link.hidden=true;
    if(status.webui_url){const url=new URL(status.webui_url);if(url.protocol==='http:'&&url.hostname==='127.0.0.1'&&!url.username&&!url.password){link.href=url.origin;link.hidden=false;}}
      if(options.button)toast('连接检查完成：'+status.label);
  }catch(error){
    if(generation!==loginGeneration){bridgeQueued=true;return;}
    document.dispatchEvent(new CustomEvent('connection-status',{detail:{source:'qq',status:{state:'unavailable'}}}));
    $('#bridgeStatus').dataset.state='unavailable';$('#bridgeStatus').textContent='无法检查连接：'+error.message;$('#bridgeWebUI').hidden=true;$('#bridgeChecked').textContent='检查失败 · 状态未确认';if(options.button)toast('连接检查失败，请重试。');
    if($('#qqLoginDialog').open&&$('#qqLoginStatus').dataset.state==='online')$('#qqLoginHint').textContent='QQ 已在线，接收配置尚未确认，请点击“检查连接”重试。';
  }finally{await new Promise(resolve=>setTimeout(resolve,Math.max(0,400-(performance.now()-started))));setButtonBusy(button,false);bridgeLoading=false;if(bridgeQueued){bridgeQueued=false;loadBridgeStatus();}}
}
