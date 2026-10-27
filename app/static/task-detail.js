/* Task/source detail; successful viewing persists only the automatic review marker. */
const taskDetailState={id:null,generation:0,trigger:null,busy:false,viewed:new Set(),reviewing:new Set()};
async function markTaskDetailViewed(task,generation){
  if(!task.automation_pending||taskDetailState.viewed.has(task.id)||taskDetailState.reviewing.has(task.id))return;
  taskDetailState.reviewing.add(task.id);
  try{
    await api('/api/automation/tasks/'+encodeURIComponent(task.id)+'/viewed',{method:'POST'});
    taskDetailState.viewed.add(task.id);
    for(const item of state.tasks||[])if(item.id===task.id)item.automation_pending=false;
    if(state.tasksLoaded)renderTaskList();
  }catch(error){
    if(generation===taskDetailState.generation&&$('#taskDetail').open)$('#detailReviewError').textContent=error.message+' 点击“重新读取详情”重试。';
  }finally{taskDetailState.reviewing.delete(task.id);}
}
function syncTaskDetailSelection(){
  const current=$('#taskDetail')?.open?taskDetailState.id:null;
  document.querySelectorAll('#taskList .task-row').forEach(row=>{
    const selected=row.dataset.taskId===current;
    row.classList.toggle('is-current',selected);
    const trigger=row.querySelector('.task-open');
    if(selected)trigger?.setAttribute('aria-current','true');
    else trigger?.removeAttribute('aria-current');
  });
}
function revealCurrentTask(generation){
  // Wait for the side panel's padding transition before measuring the reclassified row.
  setTimeout(()=>{
    const dialog=$('#taskDetail');
    if(generation!==taskDetailState.generation||!dialog.open||dialog.matches(':modal')||$('#tasksView').hidden)return;
    const row=[...document.querySelectorAll('#taskList .task-row')].find(el=>el.dataset.taskId===taskDetailState.id);
    if(!row)return;
    const group=row.closest('details.task-group');if(group)group.open=true;
    const rect=row.getBoundingClientRect(),header=$('.topbar').getBoundingClientRect().bottom+16;
    if(rect.top<header||rect.bottom>innerHeight-72){
      const offset=header+Math.max(0,(innerHeight-header-72-rect.height)/2);
      window.scrollTo({top:Math.max(0,scrollY+rect.top-offset),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    }
  },240);
}
function closeTaskDetail(){const dialog=$('#taskDetail');if(dialog?.open)dialog.close();document.body.classList.remove('detail-open');syncTaskDetailSelection();}
function detailSourceHtml(messages){
  const available=(messages||[]).filter(Boolean);
  if(!available.length)return '<p class="field-hint">暂无关联原文</p>';
  return available.map((m,i)=>'<section class="detail-source"><div class="source-heading"><span class="platform-label">'+esc(sourceName(m.source))+'</span><span>'+esc(m.source_group||'来源未填写')+'</span></div><div class="source-meta">'+esc(m.sender||'发送人未知')+' · 发送于 '+esc(messageTime(m.sent_at))+'</div><div class="source-content">'+esc(m.source==='manual'&&m.raw_text==='手动创建的待办'?'暂无关联原文（手动创建）':m.raw_text?.trim()?m.raw_text:'暂无关联原文')+'</div><p class="field-hint">接收 / 导入于 '+esc(messageTime(m.created_at))+(i===0?' · 初始来源':' · 关联来源')+'</p></section>').join('');
}
async function openTaskDetail(id,{refresh=false}={}){
  const dialog=$('#taskDetail');const generation=++taskDetailState.generation;taskDetailState.id=id;
  if(!refresh){taskDetailState.trigger=document.activeElement;$('#taskDetailContent').innerHTML='<h2 id="taskDetailTitle">正在读取任务…</h2><div class="skeleton"><div></div><div></div></div>';if(!dialog.open){if(innerWidth>=1100){dialog.show();document.body.classList.add('detail-open');}else dialog.showModal();}dialog.scrollTop=0;$('#closeTaskDetail').focus({preventScroll:true});}
  syncTaskDetailSelection();
  try{
    const task=await api('/api/tasks/'+id);if(generation!==taskDetailState.generation)return;
    const results=await Promise.allSettled([api('/api/tasks/'+id+'/sources'),api('/api/tasks/'+id+'/history')]);
    if(generation!==taskDetailState.generation||!dialog.open)return;
    const [sources,history]=results;
    const statuses={pending:'未完成',completed:'已完成',cancelled:'已取消'};
    const fields=[['截止时间',displayDeadline(task)],['优先级',priorityLabel[task.priority]],['地点',task.location],['期限原文',task.deadline_text],['提交材料',(task.materials||[]).join('、')],['格式要求',task.format_requirement],['提交方式',task.submit_method],['面向对象',task.target_audience]];
    let html='<div class="detail-title"><span class="detail-status '+esc(task.status)+'">'+esc(statuses[task.status]||task.status)+'</span><h2 id="taskDetailTitle">'+esc(task.title)+'</h2>'+(task.description?'<p class="detail-description">'+esc(task.description)+'</p>':'')+'</div>';
    html+='<div class="detail-actions"><button class="button primary" data-detail-action="'+(task.status==='pending'?'complete':'reopen')+'">'+(task.status==='pending'?'完成任务':'恢复任务')+'</button><button class="button secondary" data-detail-action="edit">编辑待办</button></div><p id="detailActionError" class="form-error" role="alert"></p>';
    html+='<dl class="detail-fields">'+fields.filter(([,value])=>value).map(([name,value])=>'<div><dt>'+esc(name)+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl>';
    html+='<section class="detail-sources"><h3>来源消息 <span>'+(sources.status==='fulfilled'?sources.value.messages.filter(Boolean).length:'')+'</span></h3>'+(sources.status==='fulfilled'?detailSourceHtml(sources.value.messages):'<p class="form-error">来源读取失败：'+esc(sources.reason.message)+'。请重试。</p>')+'</section>';
    html+='<details class="detail-history"><summary>通知变更历史</summary>';
    if(history.status==='rejected')html+='<p class="form-error">历史读取失败：'+esc(history.reason.message)+'</p>';
    else html+=history.value.history.length?history.value.history.map(h=>'<div class="history-entry"><strong>'+esc(h.action==='cancel'?'取消任务':'更新期限')+'</strong><p>'+esc(h.action==='cancel'?'已确认取消':(h.before.deadline||'未确定')+' → '+(h.after.deadline||'未确定'))+'</p><small>'+esc(messageTime(h.confirmed_at))+'</small></div>').join(''):'<p class="field-hint">暂无通知变更记录。</p>';
    html+='</details><p id="detailReviewError" class="form-error" role="alert"></p><button class="small-btn" data-detail-action="refresh">重新读取详情</button>';
    $('#taskDetailContent').innerHTML=html;
    if(sources.status==='fulfilled')await markTaskDetailViewed(task,generation);
    if(!refresh)revealCurrentTask(generation);
  }catch(error){if(generation!==taskDetailState.generation)return;$('#taskDetailContent').innerHTML='<h2 id="taskDetailTitle">无法读取任务</h2><p class="form-error">'+esc(error.message)+'</p><button class="small-btn" data-detail-action="refresh">重试</button>';}
}
document.addEventListener('DOMContentLoaded',()=>{
  const dialog=$('#taskDetail');$('#closeTaskDetail').onclick=closeTaskDetail;
  dialog.addEventListener('close',()=>{if(dialog.open)return;++taskDetailState.generation;taskDetailState.id=null;syncTaskDetailSelection();document.body.classList.remove('detail-open');const button=taskDetailState.trigger;if(button?.isConnected)button.focus({preventScroll:true});else $('#taskSearch')?.focus({preventScroll:true});});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&dialog.open&&!document.querySelector('#editDialog[open],#sourceDialog[open]')){e.preventDefault();closeTaskDetail();}});
  dialog.addEventListener('click',async e=>{
    const button=e.target.closest('[data-detail-action]');if(!button||taskDetailState.busy)return;
    const id=taskDetailState.id,action=button.dataset.detailAction;
    if(action==='refresh'){await openTaskDetail(id,{refresh:true});return;}
    taskDetailState.busy=true;setButtonBusy(button,true);
    try{
      if(action==='edit'){const task=await api('/api/tasks/'+id);state.editing=id;state.dialogTask=id;$('#editFields').innerHTML=editor(task);$('#editError').textContent='';$('#editDialog').showModal();}
      else {await api('/api/tasks/'+id+'/'+action,{method:'POST'});await loadTasks();updateCount();await openTaskDetail(id,{refresh:true});toast(action==='complete'?'任务已完成。':'任务已恢复。');}
    }catch(error){$('#detailActionError').textContent=error.message;}
    finally{setButtonBusy(button,false);taskDetailState.busy=false;}
  });
  document.addEventListener('tasks-changed',()=>{if(dialog.open&&taskDetailState.id)openTaskDetail(taskDetailState.id,{refresh:true});});
  let lastWide=innerWidth>=1100;addEventListener('resize',()=>{const wide=innerWidth>=1100;if(dialog.open&&wide!==lastWide){const id=taskDetailState.id;closeTaskDetail();openTaskDetail(id);}lastWide=wide;});
});
