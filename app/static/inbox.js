/* Unified read model; explicit processing still goes to each platform's own endpoint. */
const inboxState={source:'all',status:'all',offset:0,size:30,request:0,busy:false,snapshot:'',messages:new Map()};
function unifiedMessageHtml(m){
  const inTrash=inboxState.source==='trash';
  const actionable=['received','failed'].includes(m.extraction_status)&&['qq','wechat'].includes(m.source);
  const analyze=actionable||(m.source==='manual'&&m.extraction_status==='failed');
  const button=(action,label,primary=false,attributes='')=>'<button type="button" class="'+(primary?'button primary':'small-btn')+' message-action'+(action==='trash'?' message-delete':'')+'" data-inbox-action="'+action+'"'+attributes+'>'+label+'</button>';
  let actions='';
  if(inTrash)actions=button('restore','恢复到收件箱',true);
  else{
    actions=button('trash','删除',false,' title="移入垃圾桶，可恢复"'+(m.extraction_status==='extracting'?' disabled':''));
    if(actionable)actions+=button('manual','手动整理');
    if(analyze)actions+=button('analyze',m.extraction_status==='failed'?'重试分析':'分析通知',true);
    if(m.pending_draft_count>0)actions+=button('review','核对草稿',!analyze);
  }
  const linked=(m.tasks||[]).length?'<div class="message-linked"><span>关联待办</span>'+m.tasks.map(t=>'<button class="text-button" data-inbox-task="'+esc(t.id)+'">'+esc(t.title)+'</button>').join('')+'</div>':'';
  const label=m.task_count?'已关联 '+m.task_count+' 条待办':(m.extraction_status==='ready'?(m.pending_draft_count?'待核对草稿':'已提取'):messageStatuses[m.extraction_status]||m.extraction_status);
  const tone=inTrash?'neutral':m.task_count?'success':m.extraction_status==='failed'?'danger':['received','pending','extracting'].includes(m.extraction_status)||m.pending_draft_count>0?'warning':'neutral';
  return '<article class="message-item" data-inbox-message="'+esc(m.id)+'"><div class="message-body"><div class="message-heading"><span class="platform-label '+esc(m.source==='qq'?'qq':m.source==='wechat'?'wechat':'manual')+'">'+esc(sourceName(m.source))+'</span><strong>'+esc(m.source_group||'来源未填写')+'</strong></div><div class="source-meta">'+esc(m.sender||'发送人未知')+' · '+esc(messageTime(m.sent_at))+'</div><p class="message-preview">'+esc(m.raw_text.slice(0,160))+'</p><details class="message-original"><summary>来源原文</summary><div class="source-content">'+esc(m.raw_text)+'</div><p class="field-hint">接收 / 导入于 '+esc(messageTime(m.created_at))+'</p></details>'+linked+'</div><div class="message-footer"><span class="message-state" data-tone="'+tone+'"><span class="message-state-dot" aria-hidden="true"></span>'+esc(label)+'</span><div class="message-actions">'+actions+'</div></div></article>';
}
async function loadUnifiedInbox({button}={}){
  if(inboxState.busy)return;
  const request=++inboxState.request,started=performance.now();if(button)setButtonBusy(button,true,'刷新中…');
  const root=$('#unifiedMessages');root.setAttribute('aria-busy','true');root.querySelectorAll('button').forEach(b=>b.disabled=true);if(!root.children.length)root.innerHTML='<div class="skeleton" aria-label="正在读取消息"><div></div><div></div></div>';$('#inboxError').textContent='';
  try{
    const query=new URLSearchParams({source:inboxState.source==='trash'?'all':inboxState.source,folder:inboxState.source==='trash'?'trash':'inbox',status:inboxState.status,offset:inboxState.offset,limit:inboxState.size});
    const [data,config]=await Promise.all([api('/api/inbox?'+query),api('/api/config')]);if(request!==inboxState.request)return;
    if(inboxState.offset&&inboxState.offset>=data.total){inboxState.offset=Math.max(0,Math.floor((data.total-1)/inboxState.size)*inboxState.size);return loadUnifiedInbox();}
    inboxState.messages=new Map(data.messages.map(m=>[m.id,m]));
    const snapshot=JSON.stringify([data.messages,inboxState.source,inboxState.status]);
    if(snapshot!==inboxState.snapshot){root.innerHTML=data.messages.length?data.messages.map(unifiedMessageHtml).join(''):(inboxState.source==='trash'?'<div class="empty"><strong>当前没有垃圾桶消息</strong><span>移入的消息会保留在这里，可随时恢复。</span></div>':'<div class="empty"><strong>当前没有消息</strong><span>切换筛选，或在“设置与连接”中管理接收。</span></div>');inboxState.snapshot=snapshot;}
    $('#inboxCount').textContent='共 '+data.total+' 条消息';$('#inboxPage').textContent=data.total?'第 '+(Math.floor(inboxState.offset/inboxState.size)+1)+' 页':'';
    $('#inboxPrev').disabled=inboxState.offset===0;$('#inboxNext').disabled=inboxState.offset+inboxState.size>=data.total;
    $('#inboxDestination').textContent=inboxState.source==='trash'?'可恢复消息，关联待办不受影响。':config.provider==='local'?'本地分析 · 不自动调用模型':'仅分析所选原文与发送时间，将发送至 '+(providerLabels[config.provider]||'所选模型')+'，可能产生费用；不自动分析。';
    if(button)toast('消息已刷新。');
  }catch(error){if(request!==inboxState.request)return;$('#inboxError').textContent='消息读取失败：'+error.message;root.innerHTML='<div class="empty"><strong>未能读取消息</strong><span>请点击刷新重试。</span></div>';inboxState.snapshot='';$('#inboxCount').textContent='读取失败';$('#inboxPrev').disabled=true;$('#inboxNext').disabled=true;}
  finally{if(request===inboxState.request){root.removeAttribute('aria-busy');if(!inboxState.busy)root.querySelectorAll('button').forEach(b=>b.disabled=b.dataset.inboxAction==='trash'&&inboxState.messages.get(b.closest('[data-inbox-message]')?.dataset.inboxMessage)?.extraction_status==='extracting');}if(button){await new Promise(r=>setTimeout(r,Math.max(0,350-(performance.now()-started))));setButtonBusy(button,false);}}
}
async function processInboxMessage(e){
  const taskButton=e.target.closest('[data-inbox-task]');if(taskButton){if(!inboxState.busy)await openTaskDetail(taskButton.dataset.inboxTask);return;}
  const button=e.target.closest('[data-inbox-action]');if(!button||inboxState.busy)return;
  const card=button.closest('[data-inbox-message]'),message=inboxState.messages.get(card.dataset.inboxMessage),action=button.dataset.inboxAction;
  if(!message)return;inboxState.busy=true;++inboxState.request;setButtonBusy(button,true);card.querySelectorAll('button').forEach(b=>b.disabled=true);$('#inboxError').textContent='';
  let error='';
  try{
    captureDrafts();
    if(action==='trash'||action==='restore'){
      await api('/api/inbox/'+encodeURIComponent(message.id)+'/'+action,{method:'POST'});
      toast(action==='trash'?'已删除，可在垃圾桶中恢复。':'消息已恢复到收件箱。');
    }
    else if(action==='review')await reviewMessageDrafts(message);
    else{
      const url=message.source==='manual'?'/api/messages/'+message.id+'/retry':'/api/'+message.source+'/messages/'+message.id+'/process';
      const result=await api(url,{method:'POST',body:{action}});
      if(result.error)throw new Error(result.error);
      if(result.drafts.length){state.messages.set(message.id,result.message);const ids=new Set(state.drafts.map(d=>d.id));state.drafts.push(...result.drafts.filter(d=>!ids.has(d.id)));renderDrafts();showView('inbox');$('#draftSection').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});toast('草稿已生成，请核对。');}
      else toast(action==='ignore'?'消息已忽略。':'这条消息无需行动。');
    }
  }catch(e){error=e.message;}
  finally{setButtonBusy(button,false);inboxState.busy=false;inboxState.snapshot='';await loadUnifiedInbox();if(error)$('#inboxError').textContent=error;}
}
document.addEventListener('DOMContentLoaded',()=>{
  const reset=()=>{inboxState.offset=0;inboxState.snapshot='';loadUnifiedInbox();};
  document.querySelectorAll('[data-inbox-source]').forEach(b=>b.onclick=()=>{if(inboxState.busy)return;if(b.dataset.inboxSource==='trash'||inboxState.source==='trash'){inboxState.status='all';$('#inboxStatus').value='all';}inboxState.source=b.dataset.inboxSource;document.querySelectorAll('[data-inbox-source]').forEach(el=>{el.classList.toggle('active',el===b);el.setAttribute('aria-selected',String(el===b));});reset();});
  $('#inboxStatus').onchange=()=>{if(inboxState.busy){$('#inboxStatus').value=inboxState.status;return;}inboxState.status=$('#inboxStatus').value;reset();};
  $('#refreshInbox').onclick=()=>loadUnifiedInbox({button:$('#refreshInbox')});$('#inboxConnections').onclick=()=>showView('connections');
  $('#inboxPrev').onclick=()=>{if(inboxState.busy)return;inboxState.offset=Math.max(0,inboxState.offset-inboxState.size);loadUnifiedInbox();};
  $('#inboxNext').onclick=()=>{if(inboxState.busy)return;inboxState.offset+=inboxState.size;loadUnifiedInbox();};
  $('#unifiedMessages').onclick=processInboxMessage;
  setInterval(()=>{if(!$('#messagesView').hidden&&!document.hidden&&!document.querySelector('dialog[open]')&&!$('#unifiedMessages').contains(document.activeElement)&&!$('#unifiedMessages details[open]'))loadUnifiedInbox();},10000);
});
