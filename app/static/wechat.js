/* Explicit local capture controls; receiving never invokes a model or creates tasks. */
let wechatOffset=0,wechatLoading=false,wechatProcessing=false,wechatControlling=false;
let wechatSnapshot='',wechatStatus=null,wechatCanAnalyze=false;
const wechatPageSize=20;
const wechatStates={paused:'已暂停',starting:'准备中',listening:'采集中',waiting:'等待微信',stopping:'暂停中',error:'采集异常',unknown:'状态未确认'};
const wechatMessageStates=messageStatuses;
function renderWechatStatus(status){
  wechatStatus=status;
  document.dispatchEvent(new CustomEvent('connection-status',{detail:{source:'wechat',status}}));
  $('#wechatState').textContent=wechatStates[status.state]||'状态未确认';$('#wechatState').dataset.state=status.state;
  $('#wechatGroup').textContent=status.group_name||'尚未设置目标群';
  $('#wechatStatusHint').textContent=status.message||({paused:'已有消息可继续整理 · 重启后需手动开始',starting:'正在检查微信与读取位置…',listening:'已接收 '+status.received_count+' 条文本',waiting:'等待电脑微信恢复',stopping:'正在停止采集…',error:'请检查电脑微信后重试',unknown:'无法读取采集状态，请刷新重试'}[status.state]||'请刷新重试');
  $('#wechatGap').hidden=!status.gap_possible;
  const active=['starting','listening','waiting','stopping'].includes(status.state);
  $('#wechatStart').disabled=wechatControlling||active||status.state==='unknown'||!status.has_account||!status.group_name;
  $('#wechatStop').disabled=wechatControlling||(!active&&status.state!=='unknown'&&status.state!=='error');
  $('#wechatSettingsBtn').disabled=wechatControlling||active||status.state==='unknown';
}
function wechatMessageHtml(message){
  const actionable=['received','failed'].includes(message.extraction_status);
  let actions='';
  if(actionable)actions='<button class="small-btn" data-wechat-action="analyze" '+(!wechatCanAnalyze?'disabled':'')+'>'+(message.extraction_status==='failed'?'重试分析':'分析通知')+'</button><button class="small-btn" data-wechat-action="manual">手动整理</button><button class="small-btn" data-wechat-action="ignore">忽略</button>';
  if(message.extraction_status==='ready')actions='<button class="small-btn" data-wechat-action="review">核对草稿</button>';
  return '<article class="task-row qq-message" tabindex="-1" data-message-state="'+esc(message.extraction_status)+'" data-wechat-message="'+esc(message.id)+'"><div class="qq-message-head"><div class="task-meta"><span class="meta">'+esc(message.source_group)+'</span><span class="meta">'+esc(message.sender||'发送者未知')+'</span><span class="meta">'+esc(message.sent_at?new Date(message.sent_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'发送时间未知')+'</span></div><span class="message-state">'+esc(wechatMessageStates[message.extraction_status]||'状态未知')+'</span></div><h3 class="task-title">'+esc(message.raw_text.slice(0,100))+'</h3><details class="task-details"><summary>查看完整原文</summary><div class="source-content">'+esc(message.raw_text)+'</div></details><div class="draft-actions">'+actions+'</div></article>';
}
async function loadWechatInbox({button}={}){
  if(wechatLoading||wechatProcessing||wechatControlling)return false;
  wechatLoading=true;const started=performance.now();if(button)setButtonBusy(button,true,'刷新中…');
  $('#wechatMessages').setAttribute('aria-busy','true');
  $('#wechatPrev').disabled=true;$('#wechatNext').disabled=true;
  try{
    const [status,config]=await Promise.all([api('/api/wechat/status'),api('/api/config')]);
    wechatCanAnalyze=true;
    $('#wechatDestination').textContent=config.provider==='local'?'本地分析 · 不自动调用模型':'分析时发送所选原文及发送时间至 '+(providerLabels[config.provider]||'所选服务商')+'，可能产生费用；不自动分析。';
    let data=await api('/api/wechat/messages?limit='+wechatPageSize+'&offset='+wechatOffset);
    if(wechatOffset&&wechatOffset>=data.total){wechatOffset=Math.max(0,Math.floor((data.total-1)/wechatPageSize)*wechatPageSize);data=await api('/api/wechat/messages?limit='+wechatPageSize+'&offset='+wechatOffset);}
    renderWechatStatus(status);
    const snapshot=JSON.stringify([data.messages,wechatCanAnalyze]);
    if(snapshot!==wechatSnapshot){
      const focus=document.activeElement?.closest('[data-wechat-message]')?.dataset.wechatMessage;
      $('#wechatMessages').innerHTML=data.messages.length?data.messages.map(wechatMessageHtml).join(''):'<div class="empty"><strong>暂无微信消息</strong><span>设置账号和群，开始采集后等待新文本。</span></div>';
      wechatSnapshot=snapshot;
      if(focus)Array.from($('#wechatMessages').children).find(card=>card.dataset.wechatMessage===focus)?.focus({preventScroll:true});
    }
    $('#wechatPage').textContent=data.total?'第 '+(Math.floor(wechatOffset/wechatPageSize)+1)+' 页 · 共 '+data.total+' 条':'0 条消息';
    $('#wechatPrev').disabled=wechatOffset===0;$('#wechatNext').disabled=wechatOffset+wechatPageSize>=data.total;
    $('#wechatInboxError').textContent='';if(button)toast('微信收件箱已刷新。');return true;
  }catch(error){
    wechatCanAnalyze=false;wechatSnapshot='';$('#wechatMessages').querySelectorAll('[data-wechat-action="analyze"]').forEach(b=>b.disabled=true);
    renderWechatStatus({...wechatStatus,state:'unknown',message:'无法读取状态，请刷新重试。'});
    $('#wechatInboxError').textContent='刷新失败：'+error.message;if(button)toast('微信刷新失败，请重试。');return false;
  }finally{
    if(button){await new Promise(resolve=>setTimeout(resolve,Math.max(0,400-(performance.now()-started))));setButtonBusy(button,false);}
    $('#wechatMessages').setAttribute('aria-busy','false');wechatLoading=false;
  }
}
async function controlWechat(action){
  if(wechatControlling||wechatLoading)return;
  wechatControlling=true;const button=$(action==='start'?'#wechatStart':'#wechatStop');
  setButtonBusy(button,true,action==='start'?'启动中…':'暂停中…');
  renderWechatStatus(wechatStatus||{state:'unknown'});$('#wechatControlError').textContent='';
  try{
    const status=await api('/api/wechat/'+action,{method:'POST'});renderWechatStatus(status);
    toast(action==='start'?'已发起采集，请查看状态。':'采集已暂停。');
  }catch(error){$('#wechatControlError').textContent=error.message;}
  finally{
    setButtonBusy(button,false);wechatControlling=false;await loadWechatInbox();
  }
}
async function processWechatMessage(event){
  const button=event.target.closest('[data-wechat-action]');if(!button||wechatProcessing||wechatLoading)return;
  const card=button.closest('[data-wechat-message]'),action=button.dataset.wechatAction;
  if(action==='analyze'&&!wechatCanAnalyze)return;
  wechatProcessing=true;setButtonBusy(button,true,action==='analyze'?'分析中…':'处理中…');card.querySelectorAll('button').forEach(b=>b.disabled=true);$('#wechatInboxError').textContent='';
  let error='';
  try{
    if(action==='review')await reviewMessageDrafts(await api('/api/messages/'+card.dataset.wechatMessage));
    else{
      captureDrafts();
      const result=await api('/api/wechat/messages/'+card.dataset.wechatMessage+'/process',{method:'POST',body:{action}});
      if(result.error)throw new Error(result.error);
      if(result.drafts.length){await reviewMessageDrafts(result.message);toast('草稿已生成，请核对。');}
      else toast(action==='ignore'?'已忽略这条消息。':'这条消息无需行动。');
    }
  }catch(e){error=e.message;}
  finally{
    setButtonBusy(button,false);wechatProcessing=false;wechatSnapshot='';await loadWechatInbox();
    if(error)$('#wechatInboxError').textContent=error;
  }
}
function initializeWechat(){
  const nav=createConnectionShortcut('wechat','微信');
  $('#refreshWechat').onclick=()=>loadWechatInbox({button:$('#refreshWechat')});
  $('#wechatStart').onclick=()=>controlWechat('start');$('#wechatStop').onclick=()=>controlWechat('stop');
  $('#wechatPrev').onclick=()=>{if(wechatLoading||wechatProcessing)return;wechatOffset=Math.max(0,wechatOffset-wechatPageSize);loadWechatInbox();};
  $('#wechatNext').onclick=()=>{if(wechatLoading||wechatProcessing)return;wechatOffset+=wechatPageSize;loadWechatInbox();};
  $('#wechatMessages').onclick=processWechatMessage;
  $('#wechatSettingsBtn').onclick=()=>{
    $('#wechatGroupInput').value=wechatStatus?.group_name||'';$('#wechatAccount').value='';
    $('#wechatAccountHint').textContent=wechatStatus?.has_account?'已保存微信号摘要；修改设置时请重新填写微信号。':'仅保存微信号摘要，不保存密码。';
    $('#wechatSettingsError').textContent='';$('#wechatSettingsDialog').showModal();
  };
  $('#closeWechatSettings').onclick=()=>$('#wechatSettingsDialog').close();
  $('#wechatSettingsDialog').addEventListener('close',()=>$('#wechatAccount').value='');
  $('#wechatForm').onsubmit=async event=>{
    event.preventDefault();const button=$('#saveWechat');if(button.disabled)return;
    setButtonBusy(button,true,'保存中…');$('#wechatSettingsError').textContent='';
    try{
      await api('/api/wechat/config',{method:'PUT',body:{group_name:$('#wechatGroupInput').value.trim(),account_alias:$('#wechatAccount').value.trim()}});
      $('#wechatAccount').value='';$('#wechatSettingsDialog').close();toast('设置已保存，请手动开始采集。');await loadWechatInbox();
    }catch(error){$('#wechatSettingsError').textContent=error.message;}
    finally{setButtonBusy(button,false);}
  };
  setInterval(()=>{if(!$('#wechatView').hidden&&!document.hidden&&!document.querySelector('dialog[open]'))loadWechatInbox();},5000);
}
document.addEventListener('DOMContentLoaded',initializeWechat);
