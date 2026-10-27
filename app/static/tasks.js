/* Task presentation, grouping and actions; persistence remains in existing APIs. */
function taskHtml(task) {
  const reminders={overdue:'已逾期',soon:'即将截止',today:'今日到期'};
  const statuses={pending:'未完成',completed:'已完成',cancelled:'已取消'};
  return `<article class="task-row ${esc(task.reminder||'')} ${esc(task.status)}" data-task-id="${esc(task.id)}"><div class="task-main">${completedSelectionHtml(task)}<button class="task-check" data-task-action="${task.status==='pending'?'complete':'reopen'}" aria-label="${task.status==='pending'?'完成':'恢复'}" title="${task.status==='pending'?'完成任务':'恢复任务'}">${task.status==='completed'?uiIcon('check'):''}</button><div class="task-copy"><h3 class="task-title"><button class="task-open" data-open-task="${esc(task.id)}">${esc(task.title)}</button></h3>${task.description?`<p class="task-desc">${esc(task.description)}</p>`:''}<div class="task-meta"><span class="meta">${priorityLabel[task.priority]} · ${statuses[task.status]}</span>${task.location?`<span class="meta">${esc(task.location)}</span>`:''}<span class="meta">${esc(task.source_group||'手动导入')}</span></div></div><div class="deadline-block"><span class="deadline ${esc(task.reminder||'')}">${task.reminder?`${reminders[task.reminder]} · `:''}${esc(displayDeadline(task))}</span><small>截止时间</small></div><div class="task-actions"><button class="small-btn more-trigger" popovertarget="menu-${esc(task.id)}" aria-label="更多操作：${esc(task.title)}" aria-haspopup="menu" aria-expanded="false">⋯</button><div class="action-menu" id="menu-${esc(task.id)}" popover role="menu"><button role="menuitem" class="small-btn" data-task-action="edit">编辑</button><button class="small-btn" data-task-action="history">变更历史</button><button class="small-btn" data-task-action="source" data-message="${esc(task.message_id)}">原文</button>${task.status==='pending'?'<button class="small-btn" data-task-action="cancel">取消</button>':''}<button class="small-btn" data-task-action="delete">删除</button></div></div></div>
    ${(task.materials.length||task.format_requirement||task.submit_method||task.target_audience)?`<details class="task-details"><summary>材料与提交要求</summary>${task.materials.length?`<div>材料：${esc(task.materials.join('、'))}</div>`:''}${task.format_requirement?`<div>格式：${esc(task.format_requirement)}</div>`:''}${task.submit_method?`<div>提交方式：${esc(task.submit_method)}</div>`:''}${task.target_audience?`<div>面向对象：${esc(task.target_audience)}</div>`:''}</details>`:''}</article>`;
}
async function loadTasks(options = {}) {
  const button = options.button || null;
  if (button?.disabled) return;
  if (button) setButtonBusy(button, true, '刷新中…');
  const request=state.taskRequest=(state.taskRequest||0)+1;
  const started=performance.now();
  state.tasksLoaded=false;state.tasksError=false;updateCompletedControls();renderTaskSearch();
  $('#taskList').setAttribute('aria-busy','true');
  if(!$('#taskList').children.length)$('#taskList').innerHTML='<div class="skeleton" aria-label="正在读取待办"><div></div><div></div></div>';
  try{
    const data=await api(`/api/tasks?view=${state.filter}&remind_hours=${reminderHours}`);
    if(request!==state.taskRequest)return;state.tasks=data.tasks;state.tasksLoaded=true;renderTaskList();
    const urgent=data.tasks.filter(t=>t.reminder&&(state.route!=='upcoming'||taskDayGroup(t)!=='overdue'));$('#reminderStrip').hidden=!urgent.length;
    $('#reminderStrip').textContent=`${urgent.length} 条任务需关注 · 仅在应用打开时提醒`;
    if (button) toast('待办已刷新。');
  }catch(error){if(request!==state.taskRequest)return;state.tasksLoaded=false;state.tasksError=true;updateCompletedControls();renderTaskSearch();$('#taskResultCount').textContent='读取失败';$('#taskList').innerHTML=`<div class="empty"><strong>任务读取失败</strong>${esc(error.message)}，请点击刷新。</div>`;if(button)toast('待办刷新失败，请重试。');}
  finally { if(request===state.taskRequest)$('#taskList').removeAttribute('aria-busy');if (button) { await new Promise(resolve=>setTimeout(resolve, Math.max(0,400-(performance.now()-started)))); setButtonBusy(button, false); } }
}
async function updateCount(){try{const {tasks}=await api('/api/tasks?view=pending');$('#pendingCount').textContent=tasks.length;}catch(error){toast(error.message);}}
async function showSource(id){
  const message=await api(`/api/messages/${id}`);
  $('#sourceContent').innerHTML=`<div class="source-meta">${esc(message.source_group||'手动导入')}${message.sender?' · '+esc(message.sender):''} · ${esc(message.sent_at||'发送时间未知')}</div><div class="source-content">${esc(message.raw_text)}</div>`;
  $('#sourceDialog').showModal();
}
async function showTaskSources(id){$('#sourceTitle').textContent='消息来源';
  const {messages}=await api(`/api/tasks/${id}/sources`);
  $('#sourceContent').innerHTML=messages.map((message,index)=>`<section><h3>${index===0?'初始通知':'关联通知'}</h3><div class="source-meta">${esc(message.source_group||'来源未填写')}${message.sender?' · '+esc(message.sender):''} · ${esc(message.sent_at||'发送时间未知')}</div><div class="source-content">${esc(message.raw_text)}</div></section>`).join('');
  $('#sourceDialog').showModal();
}
async function showTaskHistory(id){$('#sourceTitle').textContent='通知变更历史';
  const {history}=await api('/api/tasks/'+id+'/history');
  const statuses={pending:'未完成',completed:'已完成',cancelled:'已取消'};
  let html='<p>期限更新与取消记录</p>';
  for(const entry of history){
    html+='<section class="history-entry"><h4>'+(entry.action==='cancel'?'确认取消任务':'确认更新期限')+'</h4><p>确认时间：'+esc(new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'medium'}).format(new Date(entry.confirmed_at)))+'</p>';
    html+='<p>'+(entry.action==='cancel'?esc(statuses[entry.before.status])+' → '+esc(statuses[entry.after.status]):esc(entry.before.deadline||'无确定期限')+' → '+esc(entry.after.deadline||'无确定期限'))+'</p>';
    html+='<p>旧期限表达：'+esc(entry.before.deadline_text||'未填写')+'<br>新期限表达：'+esc(entry.after.deadline_text||'未填写')+'</p><p>变更来源：'+esc(entry.message.source_group||'来源未填写')+' · '+esc(entry.message.sent_at||'发送时间未知')+'</p><div class="source-content">'+esc(entry.message.raw_text)+'</div></section>';
  }
  $('#sourceContent').innerHTML=html+(history.length?'':'<p>暂无通知变更记录。</p>');
  $('#sourceDialog').showModal();
}
async function taskAction(event){
  const row=event.target.closest('#taskList [data-task-id]');
  if(row&&!event.target.closest('[data-task-action],.more-trigger,.task-selection,details,[popover]')&&!completedManager.active){await openTaskDetail(row.dataset.taskId);return;}
  const button=event.target.closest('[data-task-action]');if(!button||button.disabled||completedManager.busy||completedManager.active)return;
  const id=button.closest('[data-task-id]').dataset.taskId,action=button.dataset.taskAction;const menu=button.closest('[popover]');if(menu)menu.hidePopover();
  setButtonBusy(button,true,['source','history','edit'].includes(action)?'读取中…':'处理中…');
  try{
    if(action==='source'){state.dialogTask=id;await showTaskSources(id);return;}
    if(action==='history'){state.dialogTask=id;await showTaskHistory(id);return;}
    if(action==='edit'){state.dialogTask=id;state.editing=id;const task=await api(`/api/tasks/${id}`);$('#editFields').innerHTML=editor(task);$('#editError').textContent='';$('#editDialog').showModal();return;}
    if(action==='delete'){if(!confirm('确认删除待办？原始消息仍会保留。'))return;await api(`/api/tasks/${id}`,{method:'DELETE'});}
    else await api(`/api/tasks/${id}/${action}`,{method:'POST'});
    await loadTasks();updateCount();document.dispatchEvent(new Event('tasks-changed'));toast(action==='complete'?'已完成，可在“已完成”中恢复。':action==='reopen'?'待办已恢复。':action==='cancel'?'待办已取消。':'待办已删除。');
  }catch(error){toast(error.message);}finally{setButtonBusy(button,false);}
}
// Calendar grouping follows the same Beijing-time day boundaries as the API.
function taskDayGroup(task){
  if(!task.deadline)return 'no_deadline';
  if(task.reminder==='overdue')return 'overdue';
  const day=task.deadline.slice(0,10);
  const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const offset=(Date.parse(day+'T00:00:00+08:00')-Date.parse(today+'T00:00:00+08:00'))/86400000;
  if(offset<0)return 'overdue';
  if(offset===0)return 'today';
  return offset<7?'week':'later';
}
function orderedTasks(tasks){
  return [...tasks].sort((a,b)=>{
    // Date-only deadlines have no promised time; place them after timed entries that day.
    const key=t=>!t.deadline?Infinity:Date.parse(t.deadline.length===10?t.deadline+'T23:59:59+08:00':t.deadline);
    return key(a)-key(b)||String(b.created_at).localeCompare(String(a.created_at));
  });
}
function taskGroupHtml(label,tasks,{key,collapsed=false,query=''}={}){
  if(!tasks.length)return '';
  const title='<span>'+esc(label)+'</span><b>'+tasks.length+'</b>';
  const rows='<div class="task-group-rows">'+orderedTasks(tasks).map(taskHtml).join('')+'</div>';
  return collapsed?'<details class="task-group history-group" data-task-group="'+esc(key)+'" '+(query?'open':'')+'><summary>'+title+'</summary>'+rows+'</details>':'<section class="task-group" data-task-group="'+esc(key)+'"><h2 class="task-group-title">'+title+'</h2>'+rows+'</section>';
}
function renderTaskList(){
  renderTaskSearch();
  const query=$('#taskSearch').value.trim().toLocaleLowerCase();
  const tasks=visibleTasks().filter(t=>state.route!=='upcoming'||(t.deadline&&taskDayGroup(t)!=='overdue'));
  updateCompletedControls(tasks);
  const pending=tasks.filter(t=>t.status==='pending'),completed=tasks.filter(t=>t.status==='completed'),cancelled=tasks.filter(t=>t.status==='cancelled');
  const counts=state.filter==='all'?tasks.length+' 条记录 · 未完成 '+pending.length+' · 已完成 '+completed.length+' · 已取消 '+cancelled.length:tasks.length+(state.filter==='completed'?' 条完成记录':' 条待办');
  $('#taskResultCount').textContent=counts+(query?' · 当前列表搜索':'');
  $('#completionNotice').hidden=!['all','completed'].includes(state.filter);
  if(!tasks.length){
    const title=query?'没有找到匹配的任务':state.filter==='pending'?'当前没有未完成任务':state.filter==='completed'?'暂无完成记录':'当前筛选下没有任务';
    const hint=query?'试试更短的关键词，或切换筛选条件。':state.filter==='pending'?'已完成任务可在“已完成”中查看或恢复。':state.filter==='completed'?'完成任务后会显示在此。':'试试其他筛选条件，或导入一条通知。';
    $('#taskList').innerHTML='<div class="empty"><strong>'+title+'</strong><span>'+hint+'</span></div>';return;
  }
  const automatic=state.route==='tasks'&&['pending','all'].includes(state.filter)?pending.filter(t=>t.automation_pending&&!taskDetailState.viewed.has(t.id)):[];
  const automaticIds=new Set(automatic.map(t=>t.id));
  const regular=pending.filter(t=>!automaticIds.has(t.id));
  let html=taskGroupHtml('自动整理',automatic,{key:'automatic'});
  for(const [key,label] of [['overdue','已逾期'],['today','今天'],['week','未来 7 天'],['later','稍后'],['no_deadline','时间待定']]){
    html+=taskGroupHtml(label,regular.filter(t=>taskDayGroup(t)===key),{key});
  }
  html+=taskGroupHtml('已完成',completed,{key:'completed',collapsed:state.filter==='all',query});
  html+=taskGroupHtml('已取消',cancelled,{key:'cancelled',collapsed:state.filter==='all',query});
  $('#taskList').innerHTML=html;
  syncTaskDetailSelection();
}
function scrollTaskListToTop(){
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){window.scrollTo({top:0,behavior:'instant'});return;}
  const from=scrollY,started=performance.now(),events=['wheel','touchstart','pointerdown','keydown'];
  let frame;
  const stop=()=>{cancelAnimationFrame(frame);events.forEach(name=>removeEventListener(name,stop));};
  const step=now=>{
    const progress=Math.min(1,(now-started)/320);
    window.scrollTo({top:from*Math.pow(1-progress,3),behavior:'instant'});
    if(progress<1)frame=requestAnimationFrame(step);else stop();
  };
  events.forEach(name=>addEventListener(name,stop,{passive:true}));
  frame=requestAnimationFrame(step);
}
function initializeWorkbench(){
  const backToTop=$('#taskBackToTop');
  const updateBackToTop=()=>{backToTop.hidden=$('#tasksView').hidden||scrollY<240;};
  backToTop.onclick=scrollTaskListToTop;
  addEventListener('scroll',updateBackToTop,{passive:true});
  new MutationObserver(updateBackToTop).observe($('#tasksView'),{attributes:true,attributeFilter:['hidden']});
  updateBackToTop();
  const list=$('#taskList');for(const id of ['editDialog','sourceDialog'])$('#'+id).addEventListener('close',()=>{const row=[...list.querySelectorAll('[data-task-id]')].find(r=>r.dataset.taskId===state.dialogTask);row?.querySelector('.more-trigger')?.focus();});
  list.addEventListener('toggle',event=>{
    const menu=event.target;if(!menu.matches('.action-menu'))return;
    const trigger=menu.parentElement.querySelector('[popovertarget]');
    trigger.setAttribute('aria-expanded',String(event.newState==='open'));
    if(event.newState!=='open')return;
    menu.querySelectorAll('button').forEach(b=>b.setAttribute('role','menuitem'));
    const rect=trigger.getBoundingClientRect();
    menu.style.left=Math.max(8,Math.min(innerWidth-menu.offsetWidth-8,rect.right-menu.offsetWidth))+'px';
    menu.style.top=Math.max(8,Math.min(innerHeight-menu.offsetHeight-8,rect.bottom+6))+'px';
    menu.querySelector('button').focus();
  },true);
  list.addEventListener('keydown',event=>{
    const menu=event.target.closest('.action-menu');if(!menu)return;
    const items=[...menu.querySelectorAll('button')],index=items.indexOf(document.activeElement);
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();items[event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length].focus();}
    if(event.key==='Escape'){event.preventDefault();menu.hidePopover();menu.parentElement.querySelector('[popovertarget]').focus();}
    if(event.key==='Tab')menu.hidePopover();
  });
  const dismissMenus=()=>document.querySelectorAll('.action-menu:popover-open').forEach(m=>m.hidePopover());
  addEventListener('resize',dismissMenus);addEventListener('scroll',event=>{if(!event.target.closest?.('.action-menu'))dismissMenus();},true);

  initializeTaskSearch();
}

