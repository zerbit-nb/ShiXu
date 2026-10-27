/* Background work belongs to the backend; this controller only presents opt-in and unread results. */
let automationConfig=null,automationSaving=false,automationPolling=false,automationNoticeBusy=false;
let automationNotices=[],automationNoticeRevision=0,automationSettingsRevision=0;
let automationProcessing=0,automationTaskSignature='';
const automationDesktop=new URLSearchParams(location.search).get('desktop')==='1';
let automationNativeVisible=!automationDesktop;
function automationForeground(){return !document.hidden&&document.hasFocus()&&automationNativeVisible;}
function renderAutomation(data){
  automationConfig=data;
  $('#automationToggle').setAttribute('aria-checked',String(data.enabled));
  $('#automationLocalToggle').setAttribute('aria-checked',String(data.allow_local));
  const labels={disabled:'已关闭',local_disabled:'等待本地模型许可',unconfigured:'待配置模型',ready:'已开启'};
  $('#automationStatus').textContent=data.error?'需要检查':labels[data.state]||'状态未知';
  $('#automationLocalStatus').textContent=data.allow_local?'允许':'不允许';
  $('#automationError').textContent=data.error||'';
  syncAutomationPrivacy();
}
function syncAutomationPrivacy(){
  const automatic=automationConfig?.enabled;
  $('.sidebar-note p').textContent=automatic?'原文与待办保存在本机；自动整理使用所选模型。':'原文与待办保存在本机；云端仅发送主动分析的消息。';
  if(modelConfig)$('#destinationNotice').textContent=modelConfig.provider==='local'?'本地模型 · 通知在本机处理':providerLabels[modelConfig.provider]+(automatic?' · 自动整理已开启，新消息文本将发送至该服务':' · 分析时发送所选原文与发送时间');
}
async function loadAutomation(){
  if(!$('#automationToggle'))return;
  if(automationSaving)return;
  automationSaving=true;
  ++automationSettingsRevision;
  const controls=[$('#automationToggle'),$('#automationLocalToggle')];controls.forEach(b=>b.disabled=true);
  $('#automationRetry').hidden=true;
  try{renderAutomation(await api('/api/automation'));controls.forEach(b=>b.disabled=false);}
  catch(error){$('#automationStatus').textContent='读取失败';$('#automationError').textContent=error.message;$('#automationRetry').hidden=false;}
  finally{automationSaving=false;}
}
async function saveAutomation(field){
  if(automationSaving||!automationConfig)return;
  automationSaving=true;
  ++automationSettingsRevision;
  const controls=[$('#automationToggle'),$('#automationLocalToggle')];controls.forEach(b=>{b.disabled=true;b.setAttribute('aria-busy','true');});
  $('#automationStatus').textContent='保存中…';$('#automationError').textContent='';
  const body={enabled:automationConfig.enabled,allow_local:automationConfig.allow_local};body[field]=!body[field];
  try{renderAutomation(await api('/api/automation',{method:'PUT',body}));toast('自动整理设置已保存。');}
  catch(error){renderAutomation(automationConfig);$('#automationError').textContent=error.message;}
  finally{automationSaving=false;controls.forEach(b=>{b.disabled=false;b.removeAttribute('aria-busy');});}
}
function hideAutomationNotice(){
  const card=$('#automationCard');
  if(card.open)card.close();
  card.hidden=true;
}
function renderAutomationNotice(){
  const card=$('#automationCard');
  if(!automationForeground()||document.querySelector('dialog[open]:not(#automationCard),.action-menu:popover-open')||!automationNotices.length){hideAutomationNotice();return;}
  const tasks=automationNotices.flatMap(n=>n.tasks.map(t=>({...t,source:n.source}))),sources=[...new Set(automationNotices.map(n=>sourceName(n.source)))];
  $('#automationCardSummary').textContent='来自'+sources.join('、')+' · '+tasks.length+' 项待办';
  $('#automationCardTotal').textContent=tasks.length+' 项';
  $('#automationCardProcessing').hidden=!automationProcessing;
  $('#automationCardProcessing').textContent=automationProcessing?'另有 '+automationProcessing+' 条消息正在整理…':'';
  const signature=JSON.stringify(tasks);
  if(signature!==automationTaskSignature){
    const scroll=$('#automationCardScroll'),top=scroll.scrollTop,focused=document.activeElement?.dataset.automationTask;
    $('#automationCardTasks').innerHTML=tasks.map(t=>{
      const deadline=t.deadline?new Date(t.deadline).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):t.deadline_text||'时间待定';
      const status=({completed:'已完成',cancelled:'已取消',deleted:'已删除'})[t.status]||'未完成';
      return '<li class="automation-task"><div class="automation-task-content"><div class="automation-task-heading"><h3>'+esc(t.title)+'</h3><span class="automation-task-status">'+status+'</span></div>'+(t.description?'<p class="automation-task-description">'+esc(t.description)+'</p>':'')+'<div class="automation-task-meta"><span>'+esc(sourceName(t.source)+(t.source_group?' · '+t.source_group:''))+'</span><span>截止 '+esc(deadline)+'</span>'+(t.location?'<span>'+esc(t.location)+'</span>':'')+'</div></div><button type="button" class="button secondary automation-task-open" data-automation-task="'+esc(t.id)+'"'+(t.status==='deleted'?' disabled':'')+' aria-label="查看'+esc(t.title)+'详情">查看详情</button></li>';
    }).join('');
    automationTaskSignature=signature;scroll.scrollTop=top;
    if(focused)[...$('#automationCardTasks').querySelectorAll('[data-automation-task]')].find(b=>b.dataset.automationTask===focused)?.focus({preventScroll:true});
  }
  card.hidden=false;
  if(!card.open)card.showModal();
}
async function pollAutomationNotices(){
  renderAutomationNotice();
  if(automationPolling||automationNoticeBusy||!automationForeground())return;
  automationPolling=true;
  const revision=automationNoticeRevision,settingsRevision=automationSettingsRevision;
  try{
    const data=await api('/api/automation/notices');
    const notices=data.notices.slice();
    while(notices.length<data.total){
      const next=await api('/api/automation/notices?offset='+notices.length);
      if(!next.notices.length)break;
      notices.push(...next.notices);
    }
    if(revision!==automationNoticeRevision)return;
    automationProcessing=data.processing_count||0;
    if(JSON.stringify(notices)!==JSON.stringify(automationNotices)){
      automationNotices=notices;
      if(automationNotices.length){updateCount();if(!$('#tasksView').hidden)loadTasks();}
    }
    renderAutomationNotice();
    if(state.route==='connections'&&!automationSaving){
      const config=await api('/api/automation');
      if(settingsRevision===automationSettingsRevision&&!automationSaving)renderAutomation(config);
    }
  }catch{/* Keep unread results on the server for the next foreground refresh. */}
  finally{automationPolling=false;}
}
async function acknowledgeAutomation(open){
  if(automationNoticeBusy)return;
  automationNoticeBusy=true;++automationNoticeRevision;const snapshot=automationNotices.slice();
  const buttons=[$('#automationCardOpen'),$('#automationCardDismiss')];buttons.forEach(b=>b.disabled=true);$('#automationCardError').textContent='';
  try{
    for(const notice of snapshot)await api('/api/automation/notices/'+encodeURIComponent(notice.id)+'/acknowledge',{method:'POST'});
    automationNotices=automationNotices.filter(n=>!snapshot.some(s=>s.id===n.id));renderAutomationNotice();
    if(open)showView('tasks');
  }catch(error){$('#automationCardError').textContent=error.message;}
  finally{automationNoticeBusy=false;buttons.forEach(b=>b.disabled=false);}
}
document.addEventListener('DOMContentLoaded',()=>{
  const row=document.createElement('section');row.className='connection-row reception-filter-row';
  row.innerHTML='<span class="connection-monogram">'+uiIcon('settings')+'</span><div><h2 id="automationTitle">自动整理待办</h2><p id="automationHint">明确通知自动创建；不确定、疑似重复或变更留在收件箱。仅处理开启后的 QQ、微信新消息。</p><p class="field-hint">收起到托盘时继续处理，打开界面后显示提醒。使用云端模型会自动发送新消息文本，可能产生费用；AI 结果仍需留意核对。</p><p id="automationError" class="form-error" role="alert"></p></div><span class="reception-filter-control"><span id="automationStatus" role="status">读取中…</span><button id="automationToggle" type="button" class="reception-filter-switch" role="switch" aria-checked="false" aria-labelledby="automationTitle" aria-describedby="automationHint" disabled><span aria-hidden="true"></span></button><button id="automationRetry" type="button" class="small-btn" hidden>重试</button></span>';
  const local=document.createElement('section');local.className='connection-row reception-filter-row automation-local-row';
  local.innerHTML='<div><h2 id="automationLocalTitle">允许本地模型自动整理</h2><p id="automationLocalHint">使用 LM Studio 时单独许可。需保持本地模型服务运行，会占用计算资源。</p></div><span class="reception-filter-control"><span id="automationLocalStatus" role="status">读取中…</span><button id="automationLocalToggle" type="button" class="reception-filter-switch" role="switch" aria-checked="false" aria-labelledby="automationLocalTitle" aria-describedby="automationLocalHint" disabled><span aria-hidden="true"></span></button></span>';
  $('#connectionsView .connection-list').append(row,local);
  $('#automationToggle').onclick=()=>saveAutomation('enabled');$('#automationLocalToggle').onclick=()=>saveAutomation('allow_local');$('#automationRetry').onclick=loadAutomation;
  $('#automationCardDismiss').onclick=()=>acknowledgeAutomation(false);$('#automationCardOpen').onclick=()=>acknowledgeAutomation(true);
  $('#automationCard').addEventListener('cancel',event=>{event.preventDefault();acknowledgeAutomation(false);});
  $('#automationCard').addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const controls=[...$('#automationCard').querySelectorAll('button:not(:disabled),[tabindex="0"]')].filter(el=>el.getClientRects().length);
    const first=controls[0],last=controls[controls.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  });
  $('#automationCardTasks').onclick=async event=>{
    const button=event.target.closest('[data-automation-task]');if(!button||button.disabled)return;
    hideAutomationNotice();
    try{
      if(state.route!=='tasks'||!['pending','all'].includes(state.filter)||$('#taskSearch').value){
        $('#taskSearch').value='';await showView('tasks');
      }
      await openTaskDetail(button.dataset.automationTask);
    }
    catch(error){renderAutomationNotice();$('#automationCardError').textContent=error.message;}
  };
  document.querySelectorAll('dialog:not(#automationCard)').forEach(dialog=>dialog.addEventListener('close',()=>setTimeout(renderAutomationNotice,0)));
  document.addEventListener('visibilitychange',()=>{renderAutomationNotice();if(automationForeground())pollAutomationNotices();});
  addEventListener('focus',()=>pollAutomationNotices());addEventListener('blur',()=>renderAutomationNotice());
  addEventListener('shixu-window-state',event=>{automationNativeVisible=event.detail===true;renderAutomationNotice();if(automationForeground())pollAutomationNotices();});
  loadAutomation();pollAutomationNotices();setInterval(pollAutomationNotices,3000);
});
