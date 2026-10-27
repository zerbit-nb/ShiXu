/* Explicit management of completed history. */
const completedManager={active:false,busy:false,selected:new Map(),operation:null,trigger:null};
function visibleTasks(){
 const query=$('#taskSearch').value.trim().toLocaleLowerCase();
 const showAutomatic=state.route==='tasks'&&['pending','all'].includes(state.filter);
 return (state.tasks||[]).filter(t=>(showAutomatic||t.status!=='pending'||!t.automation_pending||taskDetailState.viewed.has(t.id))&&[t.title,t.description,t.location,t.source_group].some(v=>String(v||'').toLocaleLowerCase().includes(query)));
}
function completedSelectionHtml(task){
 if(!completedManager.active||state.filter!=='completed')return '';
 return '<label class="task-selection"><input type="checkbox" data-select-task="'+esc(task.id)+'" aria-label="选择：'+esc(task.title)+'" '+(completedManager.selected.has(task.id)?'checked':'')+' '+(completedManager.busy?'disabled':'')+'></label>';
}
function updateCompletedControls(tasks=visibleTasks()){
 if(!$('#completedControls'))return;
 const completed=state.filter==='completed';
 $('.reminder-choice').hidden=completed;$('#completedControls').hidden=!completed;
 if(!completed){completedManager.active=false;completedManager.selected.clear();}
 const eligible=tasks.filter(t=>t.status==='completed');
 for(const [id,version] of completedManager.selected){if(!eligible.some(t=>t.id===id&&t.version===version))completedManager.selected.delete(id);}
 $('#manageCompleted').textContent=completedManager.active?'退出管理':'管理';
 $('#manageCompleted').setAttribute('aria-expanded',String(completedManager.active));
 $('#completedActions').hidden=!completedManager.active;
 $('#selectedCompletedCount').textContent='已选 '+completedManager.selected.size+' 条';
 const ready=state.tasksLoaded&&!completedManager.busy;
 $('#manageCompleted').disabled=!ready;
 $('#selectAllCompleted').disabled=!ready||!eligible.length;
 $('#selectAllCompleted').checked=eligible.length>0&&completedManager.selected.size===eligible.length;
 $('#selectAllCompleted').indeterminate=completedManager.selected.size>0&&completedManager.selected.size<eligible.length;
 for(const id of ['restoreCompleted','deleteCompleted'])$('#'+id).disabled=!ready||!completedManager.selected.size;
 $('#clearCompleted').disabled=!ready||!(state.tasks||[]).some(t=>t.status==='completed');
 $('#taskList').classList.toggle('is-managing',completedManager.active);
}
function setCompletedBusy(busy){
 completedManager.busy=busy;
 if(busy)closeTaskSearch();
 $('#clearTaskSearch').disabled=busy;
 for(const selector of ['[data-filter]','#refreshBtn','#taskSearch','[data-select-task]','#cancelCompletedDelete','#confirmCompletedDelete'])document.querySelectorAll(selector).forEach(e=>e.disabled=busy);
 $('#completedDeleteDialog').setAttribute('aria-busy',String(busy));updateCompletedControls();
}
function completedTargets(all=false){
 return (state.tasks||[]).filter(t=>t.status==='completed'&&(all||completedManager.selected.get(t.id)===t.version)).map(t=>({id:t.id,version:t.version}));
}
async function applyCompletedOperation(action,targets){
 if(completedManager.busy||!targets.length)return;
 setCompletedBusy(true);$('#completedError').textContent='';$('#completedDeleteError').textContent='';
 const button=action==='delete'?$('#confirmCompletedDelete'):$('#restoreCompleted');setButtonBusy(button,true,action==='delete'?'删除中…':'恢复中…');
 try{
  const result=await api('/api/completed-tasks/manage',{method:'POST',body:{action,confirmed:true,tasks:targets}});
  completedManager.selected.clear();$('#completedDeleteDialog').close();
  await loadTasks();await updateCount();toast((action==='delete'?'已删除 ':'已恢复 ')+result.affected+' 条任务'+(action==='restore'?'，可在未完成中查看。':'。'));
 }catch(error){if($('#completedDeleteDialog').open)$('#completedDeleteError').textContent=error.message;else $('#completedError').textContent=error.message;}
 finally{setButtonBusy(button,false);setCompletedBusy(false);}
}
function requestCompletedDeletion(all){
 const targets=completedTargets(all);if(!state.tasksLoaded||!targets.length||completedManager.busy)return;
 completedManager.operation=targets;completedManager.trigger=document.activeElement;
 $('#completedDeleteTitle').textContent=all?'清空已完成任务？':'删除所选任务？';
 $('#completedDeleteDescription').textContent=all?'将删除全部 '+targets.length+' 条已完成任务，包括被搜索隐藏的记录。未完成和已取消任务不受影响。':'将删除所选 '+targets.length+' 条已完成任务。其他任务不受影响。';
 $('#completedDeleteError').textContent='';$('#completedDeleteDialog').showModal();$('#cancelCompletedDelete').focus();
}
function initializeCompletedManagement(){
 const controls=document.createElement('div');controls.id='completedControls';controls.className='completed-controls';controls.hidden=true;
 controls.innerHTML='<button id="manageCompleted" class="small-btn" type="button" aria-controls="completedActions" aria-expanded="false">管理</button><div id="completedActions" class="completed-actions" hidden><label class="select-all"><input id="selectAllCompleted" type="checkbox">全选当前列表</label><span id="selectedCompletedCount" role="status">已选 0 条</span><button id="restoreCompleted" class="small-btn" type="button">恢复所选</button><button id="deleteCompleted" class="small-btn danger-button" type="button">删除所选</button><button id="clearCompleted" class="small-btn danger-button" type="button">清空已完成</button></div><p id="completedError" class="form-error" role="alert"></p>';
 $('.task-toolbar').after(controls);
 const dialog=document.createElement('dialog');dialog.id='completedDeleteDialog';dialog.setAttribute('aria-labelledby','completedDeleteTitle');dialog.setAttribute('aria-describedby','completedDeleteDescription completedDeleteWarning');
 dialog.innerHTML='<div class="settings-form"><h2 id="completedDeleteTitle">删除所选任务？</h2><p id="completedDeleteDescription" class="dialog-copy"></p><p id="completedDeleteWarning" class="delete-warning">不可恢复。将删除任务、关联与变更历史，保留原始通知。</p><p id="completedDeleteError" class="form-error" role="alert"></p><div class="settings-actions"><button id="cancelCompletedDelete" class="button secondary" type="button">取消</button><button id="confirmCompletedDelete" class="button danger-button" type="button">确认删除</button></div></div>';document.body.append(dialog);
 $('#manageCompleted').onclick=()=>{completedManager.active=!completedManager.active;completedManager.selected.clear();renderTaskList();};
 $('#taskList').addEventListener('change',event=>{const input=event.target.closest('[data-select-task]');if(!input||completedManager.busy)return;const task=(state.tasks||[]).find(t=>t.id===input.dataset.selectTask&&t.status==='completed');if(!task)return;if(input.checked)completedManager.selected.set(task.id,task.version);else completedManager.selected.delete(task.id);updateCompletedControls();});
 $('#selectAllCompleted').onchange=event=>{completedManager.selected.clear();if(event.target.checked)for(const task of visibleTasks())if(task.status==='completed')completedManager.selected.set(task.id,task.version);renderTaskList();};
 $('#restoreCompleted').onclick=()=>applyCompletedOperation('restore',completedTargets());
 $('#deleteCompleted').onclick=()=>requestCompletedDeletion(false);$('#clearCompleted').onclick=()=>requestCompletedDeletion(true);
 $('#cancelCompletedDelete').onclick=()=>dialog.close();$('#confirmCompletedDelete').onclick=()=>applyCompletedOperation('delete',completedManager.operation||[]);
 dialog.addEventListener('cancel',event=>{if(completedManager.busy)event.preventDefault();});
 dialog.addEventListener('close',()=>{completedManager.operation=null;completedManager.trigger?.focus();});updateCompletedControls();
}
