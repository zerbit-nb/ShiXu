/* Deadline reminders are independent of automatic-organization result cards. */
let taskReminderConfig=null,taskReminderSettingsBusy=false,taskReminderPolling=false,taskReminderActionBusy=false;
let taskReminderEvents=[];
const taskReminderOptions=[[0,'截止时'],[15,'提前 15 分钟'],[30,'提前 30 分钟'],[60,'提前 1 小时'],[180,'提前 3 小时'],[1440,'提前 1 天'],[10080,'提前 1 周']];
function reminderOptions(value){
 const options=taskReminderOptions.some(([n])=>n===value)?taskReminderOptions:[...taskReminderOptions,[value,'提前 '+value+' 分钟']];
 return options.map(([n,label])=>'<option value="'+n+'"'+(n===value?' selected':'')+'>'+label+'</option>').join('');
}
function renderTaskReminderSettings(data){
 taskReminderConfig=data;
 setSettingsSwitch($('#taskReminderToggle'),data.enabled);
 setSettingsStatus($('#taskReminderStatus'),data.enabled?'已开启':'已关闭');
 $('#taskReminderLead').innerHTML=reminderOptions(data.lead_minutes);
 $('#taskReminderDaily').checked=data.daily_enabled;$('#taskReminderDailyTime').value=data.daily_time;
 $('#taskReminderQuiet').checked=data.quiet_enabled;$('#taskReminderQuietStart').value=data.quiet_start;$('#taskReminderQuietEnd').value=data.quiet_end;
 $('#taskReminderError').textContent=data.error||'';
 if(!data.enabled){taskReminderEvents=[];renderTaskReminderCard();}
}
async function loadTaskReminderSettings(){
 if(taskReminderSettingsBusy)return;
 taskReminderSettingsBusy=true;
 try{renderTaskReminderSettings(await api('/api/reminders'));$('#taskReminderToggle').disabled=false;}
 catch(error){$('#taskReminderError').textContent=error.message;setSettingsStatus($('#taskReminderStatus'),'读取失败');}
 finally{taskReminderSettingsBusy=false;}
}
async function saveTaskReminderSettings(toggle=false){
 if(taskReminderSettingsBusy||!taskReminderConfig)return;
 const body=toggle?{...taskReminderConfig,enabled:!taskReminderConfig.enabled}:{...taskReminderConfig,
  lead_minutes:Number($('#taskReminderLead').value),daily_enabled:$('#taskReminderDaily').checked,daily_time:$('#taskReminderDailyTime').value,
  quiet_enabled:$('#taskReminderQuiet').checked,quiet_start:$('#taskReminderQuietStart').value,quiet_end:$('#taskReminderQuietEnd').value};
 delete body.error;
 taskReminderSettingsBusy=true;$('#taskReminderToggle').disabled=true;$('#taskReminderSave').disabled=true;
 try{renderTaskReminderSettings(await api('/api/reminders',{method:'PUT',body}));toast('提醒设置已保存');}
 catch(error){$('#taskReminderError').textContent=error.message;}
 finally{taskReminderSettingsBusy=false;$('#taskReminderToggle').disabled=false;$('#taskReminderSave').disabled=false;}
}
function canShowTaskReminders(){return automationForeground()&&!document.querySelector('dialog[open]');}
function renderTaskReminderCard(){
 const card=$('#taskReminderCard');if(!card)return;
 const tasks=[...new Map(taskReminderEvents.flatMap(e=>e.tasks).map(t=>[t.id,t])).values()];
 card.hidden=!tasks.length||!canShowTaskReminders();
 if(card.hidden)return;
 const signature=JSON.stringify(tasks);
 if(card.dataset.signature!==signature){
  card.dataset.signature=signature;
  $('#taskReminderTasks').innerHTML=tasks.map(t=>'<li><div><h3>'+esc(t.title)+'</h3><p>'+esc(displayDeadline(t))+'</p></div><div class="reminder-task-actions"><button class="small-btn" type="button" data-reminder-open="'+esc(t.id)+'">查看</button><button class="small-btn" type="button" data-reminder-complete="'+esc(t.id)+'">完成</button></div></li>').join('');
 }
 $('#taskReminderCount').textContent=tasks.length+' 项待办';
}
async function pollTaskReminders(){
 renderTaskReminderCard();
 if(taskReminderPolling||taskReminderActionBusy||!canShowTaskReminders())return;
 taskReminderPolling=true;
 try{
  if(taskReminderEvents.length){
   const active=await api('/api/reminders/events'),ids=new Set(taskReminderEvents.map(e=>e.id));
   taskReminderEvents=active.events.filter(e=>ids.has(e.id));renderTaskReminderCard();
  }
  const claim=await api('/api/reminders/claim',{method:'POST',body:{channel:'foreground'}});
  if(!claim.claim_id)return;
  if(!canShowTaskReminders()){await api('/api/reminders/delivery/'+claim.claim_id+'/release',{method:'POST'});return;}
  const delivered=await api('/api/reminders/delivery/'+claim.claim_id+'/confirm',{method:'POST'});
  if(!canShowTaskReminders()){await api('/api/reminders/delivery/'+claim.claim_id+'/release',{method:'POST'});return;}
  taskReminderEvents=[...new Map([...taskReminderEvents,...delivered.events].map(e=>[e.id,e])).values()];
  renderTaskReminderCard();
 }catch{/* Durable pending claims recover after their lease; settings retain errors. */}
 finally{taskReminderPolling=false;}
}
async function openTaskReminderHistory(){
 try{const result=await api('/api/reminders/events');taskReminderEvents=result.events;renderTaskReminderCard();if(!result.events.length)toast('暂无待查看的提醒');}
 catch(error){toast(error.message);}
}
async function handleReminderBatch(minutes=null){
 if(taskReminderActionBusy)return;taskReminderActionBusy=true;
 const snapshot=taskReminderEvents.slice();
 try{
  for(const event of snapshot){
   await api('/api/reminders/events/'+encodeURIComponent(event.id)+(minutes===null?'/acknowledge':'/snooze'),{method:'POST',...(minutes===null?{}:{body:{minutes}})});
   taskReminderEvents=taskReminderEvents.filter(e=>e.id!==event.id);
  }
  renderTaskReminderCard();
 }catch(error){$('#taskReminderCardError').textContent=error.message;}
 finally{taskReminderActionBusy=false;}
}
async function loadIndividualReminder(task){
 const target=$('#taskReminderDetail');if(!target)return;
 target.innerHTML='<p class="field-hint">读取提醒设置…</p>';
 try{
  const pref=await api('/api/reminders/tasks/'+encodeURIComponent(task.id));
  if(taskDetailState.id!==task.id||!target.isConnected)return;
  const value=pref.mode==='custom'?String(pref.minutes):pref.mode;
  target.innerHTML='<h3>提醒</h3><label class="sr-only" for="individualReminderMode">此待办的提醒时间</label><div class="individual-reminder-control"><select id="individualReminderMode"><option value="default">跟随全局</option><option value="off">不提醒</option>'+reminderOptions(pref.minutes)+'</select><button class="small-btn" id="individualReminderSave" type="button">保存</button></div><p class="field-hint">'+(task.deadline?(task.deadline.length===10?'仅日期，进入每日回顾':'提前量按截止时间计算'):'无截止时间，不自动提醒')+' · 北京时间</p><p class="form-error" id="individualReminderError" role="alert"></p>';
  $('#individualReminderMode').value=value;
  $('#individualReminderSave').onclick=async()=>{
   const button=$('#individualReminderSave'),choice=$('#individualReminderMode').value;
   button.disabled=true;
   try{await api('/api/reminders/tasks/'+encodeURIComponent(task.id),{method:'PUT',body:{mode:['default','off'].includes(choice)?choice:'custom',minutes:['default','off'].includes(choice)?60:Number(choice)}});toast('此待办的提醒已保存');}
   catch(error){if(taskDetailState.id===task.id)$('#individualReminderError').textContent=error.message;}
   finally{button.disabled=false;}
  };
 }catch(error){if(target.isConnected)target.textContent=error.message;}
}
document.addEventListener('DOMContentLoaded',()=>{
 const row=document.createElement('section');row.className='connection-row reception-filter-row';
 row.innerHTML='<span class="connection-monogram">'+uiIcon('bell')+'</span><div><h2 id="taskReminderTitle">待办提醒</h2><p id="taskReminderHint">前台卡片，托盘通知；开启后可设时间</p><details class="history-help reminder-preferences"><summary>时间设置</summary><div class="reminder-preference-grid"><label for="taskReminderLead">默认提醒</label><select id="taskReminderLead">'+reminderOptions(60)+'</select><label for="taskReminderDaily"><input id="taskReminderDaily" type="checkbox"> 每日回顾</label><input id="taskReminderDailyTime" type="time" value="09:00" aria-label="每日回顾时间"><label for="taskReminderQuiet"><input id="taskReminderQuiet" type="checkbox"> 静音时段</label><div class="reminder-quiet-time"><input id="taskReminderQuietStart" type="time" value="22:00" aria-label="静音开始时间"><span>至</span><input id="taskReminderQuietEnd" type="time" value="08:00" aria-label="静音结束时间"></div></div><p>北京时间。只有日期的待办进入回顾，无日期不自动提醒。仅在拾序运行时提醒，完整退出后停止。系统通知受 Windows 通知设置影响。</p><div class="reminder-settings-actions"><button id="taskReminderSave" class="small-btn" type="button">保存时间</button><button id="taskReminderHistory" class="small-btn" type="button">查看提醒</button></div></details><p id="taskReminderError" class="form-error" role="alert"></p></div><span class="reception-filter-control"><span id="taskReminderStatus">读取中…</span><button id="taskReminderToggle" type="button" class="reception-filter-switch" role="switch" aria-checked="false" aria-labelledby="taskReminderTitle" aria-describedby="taskReminderHint" disabled><span aria-hidden="true"></span></button></span>';
 $('#connectionsView .connection-list').append(row);
 const card=document.createElement('aside');card.id='taskReminderCard';card.className='task-reminder-card';card.hidden=true;card.setAttribute('aria-labelledby','taskReminderCardTitle');
 card.innerHTML='<header><div><h2 id="taskReminderCardTitle">待办提醒</h2><p id="taskReminderCount" role="status"></p></div><button class="close-btn" id="taskReminderDismiss" type="button" aria-label="收起本批提醒">×</button></header><ul id="taskReminderTasks" tabindex="0" aria-label="待提醒任务"></ul><p class="form-error" id="taskReminderCardError" role="alert"></p><footer><button class="small-btn" id="taskReminderSnooze15" type="button">稍后 15 分钟</button><button class="small-btn" id="taskReminderSnooze60" type="button">稍后 1 小时</button></footer>';
 document.body.append(card);
 $('#taskReminderToggle').onclick=()=>saveTaskReminderSettings(true);$('#taskReminderSave').onclick=()=>saveTaskReminderSettings();
 $('#taskReminderHistory').onclick=openTaskReminderHistory;
 $('#taskReminderDismiss').onclick=()=>handleReminderBatch();$('#taskReminderSnooze15').onclick=()=>handleReminderBatch(15);$('#taskReminderSnooze60').onclick=()=>handleReminderBatch(60);
 $('#taskReminderTasks').onclick=async event=>{
  const open=event.target.closest('[data-reminder-open]'),complete=event.target.closest('[data-reminder-complete]');
  if((!open&&!complete)||taskReminderActionBusy)return;
  const button=open||complete;taskReminderActionBusy=true;button.disabled=true;
  try{
   if(open){const id=open.dataset.reminderOpen;if(state.route!=='tasks')await showView('tasks');await openTaskDetail(id);}
   else{await api('/api/tasks/'+encodeURIComponent(complete.dataset.reminderComplete)+'/complete',{method:'POST'});const active=await api('/api/reminders/events');taskReminderEvents=active.events;await loadTasks();updateCount();document.dispatchEvent(new Event('tasks-changed'));}
   renderTaskReminderCard();
  }catch(error){$('#taskReminderCardError').textContent=error.message;}
  finally{taskReminderActionBusy=false;button.disabled=false;}
 };
 document.addEventListener('task-detail-rendered',event=>{loadIndividualReminder(event.detail);renderTaskReminderCard();});
 document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>setTimeout(pollTaskReminders,0)));
 addEventListener('shixu-reminder-open',openTaskReminderHistory);
 addEventListener('focus',pollTaskReminders);addEventListener('blur',renderTaskReminderCard);
 addEventListener('shixu-window-state',()=>{renderTaskReminderCard();pollTaskReminders();});
 document.addEventListener('visibilitychange',()=>{renderTaskReminderCard();pollTaskReminders();});
 loadTaskReminderSettings();pollTaskReminders();setInterval(()=>{pollTaskReminders();if(state.route==='connections'&&!document.hidden&&!taskReminderConfig)loadTaskReminderSettings();},5000);
});
