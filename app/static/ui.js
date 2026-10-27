function field(name, label, value, {wide = false, textarea = false} = {}) {
  const id = `field-${name}-${crypto.randomUUID()}`;
  return `<div class="field ${wide?'wide':''}"><label for="${id}">${label}</label>${textarea ? `<textarea id="${id}" data-field="${name}">${esc(value)}</textarea>` : `<input id="${id}" data-field="${name}" value="${esc(value)}">`}</div>`;
}
function editor(fields) {
  const day = fields.deadline?.slice(0,10) || '';
  const time = fields.deadline?.includes('T') ? fields.deadline.slice(11,16) : '';
  const dayId = crypto.randomUUID(), timeId = crypto.randomUUID(), priorityId = crypto.randomUUID();
  return `<section class="editor-group"><h4>任务与期限</h4><div class="fields-grid">${field('title','任务标题（必填）',fields.title,{wide:true})}
    <div class="field"><label for="${dayId}">截止日期（可留空）</label><input id="${dayId}" data-field="day" type="date" value="${esc(day)}"><small class="field-hint">时刻留空则仅保存日期。</small></div>
    <div class="field"><label for="${timeId}">截止时刻（可留空）</label><input id="${timeId}" data-field="time" type="time" value="${esc(time)}"><small class="field-hint">北京时间（UTC+8）</small></div>
    ${field('description','任务说明',fields.description,{wide:true,textarea:true})}
    ${field('deadline_text','原文中的期限表达',fields.deadline_text)}
<div class="field"><label for="${priorityId}">重要程度</label><select id="${priorityId}" data-field="priority">${Object.entries(priorityLabel).map(([key,label])=>`<option value="${key}" ${fields.priority===key?'selected':''}>${label}</option>`).join('')}</select></div>    </div></section><details class="editor-more"><summary>材料、地点与提交要求</summary><div class="fields-grid">${field('location','地点',fields.location)}${field('target_audience','面向对象',fields.target_audience)}
    ${field('materials','提交材料（每行一项）',(fields.materials||[]).join('\n'),{textarea:true})}
    ${field('format_requirement','格式要求',fields.format_requirement)}${field('submit_method','提交方式',fields.submit_method)}
    </div></details>`;
}
function readEditor(root, validate = true) {
  const value = name => $(`[data-field="${name}"]`,root).value.trim();
  if (validate && !value('title')) throw new Error('请填写任务标题。');
  if (validate && value('time') && !value('day')) throw new Error('填写时刻时，请同时选择日期。');
  const deadline = value('day') ? (value('time') ? `${value('day')}T${value('time')}:00+08:00` : value('day')) : null;
  const fields = {deadline, deadline_precision: deadline ? (deadline.length===10?'date_only':'datetime') : 'unknown', materials:value('materials').split('\n').map(v=>v.trim()).filter(Boolean)};
  for (const name of ['title','description','deadline_text','location','target_audience','format_requirement','submit_method','priority']) fields[name]=value(name)||null;
  return fields;
}
function captureDrafts() {
  for (const card of document.querySelectorAll('[data-draft-id]')) {
    const draft = state.drafts.find(d=>d.id===card.dataset.draftId);
    if (draft) draft.fields=readEditor(card, false);
  }
}
function renderDrafts() {
  $('#draftSection').hidden=!state.drafts.length;document.dispatchEvent(new Event('drafts-rendered'));
  $('#draftCount').textContent=`${state.drafts.length} 条候选`;$('#reviewStepLabel').textContent=state.drafts.length?`${state.drafts.length} 条候选待核对`:'确认任务与期限';$('#reviewStep').classList.toggle('ready',Boolean(state.drafts.length));
  $('#draftList').innerHTML=state.drafts.map((draft,index)=>{
    const title=draft.fields.title==='请填写任务标题'?'':draft.fields.title;
    const message=state.messages.get(draft.message_id);
    return `<article class="draft-card" data-draft-id="${esc(draft.id)}"><div class="draft-top"><span class="draft-index">${index+1}</span><div><h3>${esc(title||'手动整理')}</h3><p class="task-desc">核对后创建，或丢弃。</p></div></div>
      ${draft.warnings.length?`<div class="draft-warning"><strong>需要核对</strong>${draft.warnings.map(w=>`<div>${esc(w)}</div>`).join('')}</div>`:''}
      <div class="draft-review"><aside class="review-source"><h4>原始通知</h4><p class="source-meta">${esc(message?.source_group||'手动导入')}</p><pre class="source-preview">${esc(message?.raw_text||'正在读取原文…')}</pre></aside><div class="review-editor">${editor({...draft.fields,title})}</div></div><div class="duplicate-panel" aria-live="polite"></div><p class="field-error" role="alert"></p>
      <div class="draft-actions"><button class="button secondary" data-action="discard">丢弃</button><button class="button primary" data-action="check">核对并创建</button></div></article>`;
  }).join('');
}
function matchingHtml(matches, fields) {
  const statuses={pending:'未完成',completed:'已完成',cancelled:'已取消'};
  let html='<strong>发现疑似重复或变更通知</strong><p>核对下方差异。更新仅修改期限；关联原文不改已有字段。取消需确认。</p>';
  if(!matches.length)html+='<p class="change-warning">未找到可关联任务。延期或取消通知请先查已有待办；仅独立任务可新建。</p>';
  for (const m of matches) {
    html+='<div class="duplicate-entry"><h4>'+esc(m.task.title)+'</h4><p>'+esc(statuses[m.task.status])+' · '+esc(m.task.source_group||'来源未填写')+'</p><p>匹配依据：'+esc(m.reasons.join('、'))+'；差异：'+esc(m.differences.join('、')||'暂无')+'</p>';
    html+='<div class="deadline-comparison"><div><strong>已有期限</strong><p>'+esc(m.task.deadline||'无确定期限')+'</p><p>'+esc(m.task.deadline_text||'原表达未填写')+'</p></div><div><strong>本次候选期限</strong><p>'+esc(fields.deadline||'待核对：请先填写日期')+'</p><p>'+esc(fields.deadline_text||'原表达未填写')+'</p></div></div>';
    if(m.change_kind==='cancel')html+='<p class="change-warning">原文可能含取消要求，请确认指向这项任务。</p>';
    html+='<div class="draft-actions"><button class="small-btn" data-action="match-source" data-target="'+esc(m.task.id)+'">查看已有原文</button><button class="small-btn" data-action="link" data-target="'+esc(m.task.id)+'">只关联原文</button>';
    if(m.task.status==='pending'&&m.change_kind==='cancel')html+='<button class="button secondary" data-action="apply-cancel" data-target="'+esc(m.task.id)+'">确认取消此任务</button>';
    if(m.task.status==='pending'&&fields.deadline&&fields.deadline!==m.task.deadline&&m.change_kind!=='cancel')html+='<button class="button primary" data-action="apply-deadline" data-target="'+esc(m.task.id)+'">确认更新截止时间</button>';
    html+='</div></div>';
  }
  return html+'<button class="button secondary" data-action="create-anyway">仍然新建</button>';
}
function matchSnapshot(fields,matches){return JSON.stringify({fields,targets:matches.map(m=>({id:m.task.id,version:m.version}))});}
function showMatches(card,matches,fields){
  card.dataset.reviewedFields=matchSnapshot(fields,matches);
  $('.duplicate-panel',card).innerHTML=matchingHtml(matches,fields);
}
async function draftAction(event) {
  const button=event.target.closest('[data-action]'); if(!button)return;
  const card=button.closest('[data-draft-id]'),action=button.dataset.action;
  if(card.dataset.busy==='true')return;
  card.dataset.busy='true';setButtonBusy(button,true,action==='discard'?'丢弃中…':action==='match-source'?'读取中…':'核对中…');$('.field-error',card).textContent='';
  try {
    if(action==='match-source'){await showTaskSources(button.dataset.target);return;}
    if(action==='check'||action==='create-anyway'){
      const fields=readEditor(card);
      const {matches,change_notice}=await api(`/api/drafts/${card.dataset.draftId}/matches`,{method:'POST',body:fields});
      const snapshot=matchSnapshot(fields,matches);
      if((matches.length||change_notice) && (action!=='create-anyway'||card.dataset.reviewedFields!==snapshot)){
        showMatches(card,matches,fields);return;
      }
      const task=await api(`/api/drafts/${card.dataset.draftId}/confirm`,{method:'POST',body:{confirmed:true,fields,duplicate_reviewed:action==='create-anyway'}});
      toast(`已创建：${task.title}`);
     }else if(action==='apply-deadline'||action==='apply-cancel'){
      const fields=readEditor(card);
      const {matches}=await api('/api/drafts/'+card.dataset.draftId+'/matches',{method:'POST',body:fields});
      if(card.dataset.reviewedFields!==matchSnapshot(fields,matches)){showMatches(card,matches,fields);throw new Error('信息已变化，请重新核对对比内容后确认。');}
      const match=matches.find(m=>m.task.id===button.dataset.target);
      if(!match)throw new Error('关联目标已变化，请重新核对。');
      const cancel=action==='apply-cancel';
      const task=await api('/api/drafts/'+card.dataset.draftId+'/apply-change',{method:'POST',body:{confirmed:true,task_id:match.task.id,version:match.version,action:cancel?'cancel':'deadline',deadline:cancel?null:fields.deadline,deadline_text:cancel?null:fields.deadline_text}});
      toast((cancel?'已取消':'已更新期限')+'：'+task.title+'；变更历史已保存。');
    }else if(action==='link'){
      const task=await api(`/api/drafts/${card.dataset.draftId}/link`,{method:'POST',body:{confirmed:true,task_id:button.dataset.target}});
      toast(`已关联原文：${task.title}；原字段不变。`);
    }else if(action==='discard'){await api(`/api/drafts/${card.dataset.draftId}/discard`,{method:'POST'});toast('草稿已丢弃。');}
    else return;
    captureDrafts();state.drafts=state.drafts.filter(d=>d.id!==card.dataset.draftId);renderDrafts();updateCount();
  }catch(error){$('.field-error',card).textContent=error.message;}
  finally{card.dataset.busy='false';setButtonBusy(button,false);}
}
async function reviewMessageDrafts(message){
  captureDrafts();const data=await api('/api/drafts');
  const drafts=data.drafts.filter(d=>d.message_id===message.id);
  if(!drafts.length){toast('该消息的草稿已处理，可在待办中心查看。');return;}
  state.messages.set(message.id,message);
  const known=new Set(state.drafts.map(d=>d.id));state.drafts.push(...drafts.filter(d=>!known.has(d.id)));
  renderDrafts();showView('inbox');$('#draftSection').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
}
function currentMessage() {
  return {raw_text:$('#rawText').value.trim(),source_group:$('#sourceGroup').value.trim()||null,sent_at:$('#sentAt').value?`${$('#sentAt').value}:00+08:00`:null};
}
function renderQueue() {
  $('#batchList').innerHTML=state.queue.map((m,index)=>`<div class="batch-entry"><span>${index+1}. ${esc(m.raw_text.slice(0,60))} ${m.raw_text.length>60?'…':''}</span><button type="button" class="small-btn" data-remove="${index}" aria-label="移除第 ${index+1} 条消息">移除</button></div>`).join('');
  $('#batchLabel').textContent=state.queue.length?`已加入 ${state.queue.length} 条消息`:'每次最多 20 条';
}
let analysisTimer=null;function setBusy(value) {$('#analysisStatus').hidden=!value;clearInterval(analysisTimer);if(value){const start=performance.now();$('#analysisElapsed').textContent='0 秒';analysisTimer=setInterval(()=>$('#analysisElapsed').textContent=Math.floor((performance.now()-start)/1000)+' 秒',1000);}
  state.busy=value;
  for (const button of $('#extractForm').querySelectorAll('button'))button.disabled=value;
  $('#extractForm').setAttribute('aria-busy',String(value));
  $('#extractForm button[type="submit"]').textContent=value?'分析中…':'分析通知';
}
async function absorb(result) {
  state.messages.set(result.message.id,result.message);
  if(result.error){
    const entry=document.createElement('div'); entry.className='failure-entry';
    const text=document.createElement('p'); text.textContent=`${result.message.raw_text.slice(0,80)}：${result.error}`;
    const retry=document.createElement('button'); retry.className='small-btn'; retry.textContent='重试这条消息';
    retry.onclick=async()=>{retry.disabled=true;try{const next=await api(`/api/messages/${result.message.id}/retry`,{method:'POST'});entry.remove();captureDrafts();await absorb(next);renderDrafts();}catch(error){text.textContent=error.message;retry.disabled=false;}};
    entry.append(text,retry); $('#failures').append(entry);
  }else{
    state.drafts.push(...result.drafts);
    if(!result.drafts.length)toast('这条消息没有需要行动的任务。');
  }
}
async function extract(event) {
  event.preventDefault(); if(state.busy)return;
  const messages=[...state.queue]; const current=currentMessage(); if(current.raw_text)messages.push(current);
  if(!messages.length){$('#extractError').textContent='请粘贴通知内容。';return;}
  if(messages.length>20){$('#extractError').textContent='每次最多分析 20 条消息。';return;}
  captureDrafts(); setBusy(true); $('#extractError').textContent='';
  try{
    const data=await api('/api/messages/extract',{method:'POST',body:{messages}});
    for(const result of data.results)await absorb(result);
    state.queue=[];renderQueue();$('#rawText').value='';renderDrafts();
    if(state.drafts.length)$('#draftSection').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  }catch(error){$('#extractError').textContent=error.message;}
  finally{setBusy(false);}
}
async function manualDraft() {
  if(state.busy)return;setBusy(true);captureDrafts();
  try{
    const message=currentMessage();message.raw_text ||= '手动创建的待办';
    await absorb(await api('/api/messages/manual',{method:'POST',body:message}));renderDrafts();$('#draftSection').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  }catch(error){$('#extractError').textContent=error.message;}finally{setBusy(false);}
}
async function loadConfig(){
  try{const config=await api('/api/config');modelConfig=config;$('#provider').value=config.provider;previewProvider();$('#modelStatus').textContent=`${providerLabels[config.provider]} · ${config.llm_model?'已配置，待检测':'待配置'}`;$('#modelDot').className='status-dot offline';$('#destinationNotice').textContent=config.provider==='local'?'本地模型 · 通知在本机处理':`${providerLabels[config.provider]} · 分析时发送所选原文与发送时间`;$('.sidebar-note p').textContent='原文与待办保存在本机；云端仅发送本次分析的消息。';}
  catch(error){$('#modelStatus').textContent='后端连接失败';toast(error.message);}
  if(typeof syncAutomationPrivacy==='function')syncAutomationPrivacy();
}
function previewProvider(){
  const provider=$('#provider').value,profile=modelConfig?.profiles[provider];
  if(!profile)return;
  $('#baseUrl').value=profile.llm_base_url;$('#baseUrl').readOnly=provider!=='local';$('#modelId').value=profile.llm_model;
  $('#modelId').placeholder=provider==='local'?'服务端实际模型 ID':provider==='deepseek'?'检测后选择，如 deepseek-flash':'检测后选择支持 Chat Completions 的文本模型';
  $('#apiKey').value='';$('#clearKey').checked=false;$('#keyFields').hidden=provider==='local';
  $('#keyStatus').textContent=profile.has_api_key?'已有密钥：留空保留，输入新值替换。':'请填写并保存密钥。';
  $('#providerHelp').textContent=provider==='local'?'启动 LM Studio 本地服务后，检测模型。':`需该服务的 API Key。分析会发送通知内容，可能产生费用。`;
  $('#modelOptions').textContent='';$('#settingsError').textContent='';
}
async function saveConfig(){
  const data=await api('/api/config',{method:'PUT',body:{provider:$('#provider').value,llm_base_url:$('#baseUrl').value.trim(),llm_model:$('#modelId').value.trim(),api_key:$('#apiKey').value||null,clear_api_key:$('#clearKey').checked}});
  modelConfig=data;$('#apiKey').value='';return data;
}

async function initialize(){
  const providerSection=document.createElement('div');providerSection.innerHTML='<label for="provider">模型来源</label><select id="provider"><option value="local">LM Studio（本地）</option><option value="deepseek">DeepSeek 官方 API</option><option value="openai">OpenAI 官方 API（ChatGPT 系列）</option></select><p id="providerHelp" class="dialog-copy"></p>';
  $('#settingsForm .dialog-copy').replaceWith(providerSection);
  const keyFields=document.createElement('div');keyFields.id='keyFields';keyFields.hidden=true;keyFields.innerHTML='<label for="apiKey">API Key</label><input id="apiKey" type="password" autocomplete="new-password" placeholder="输入服务商提供的密钥"><p id="keyStatus" class="field-hint"></p><label class="checkbox-label"><input id="clearKey" type="checkbox">清除已保存密钥</label><p class="field-hint">密钥由当前 Windows 用户加密保存，不在页面回显。</p>';
  $('#settingsForm .settings-actions').before(keyFields);$('#provider').onchange=previewProvider;
  const destination=document.createElement('p');destination.id='destinationNotice';destination.className='destination-notice';$('.composer .panel-header').after(destination);
  $('#rawText').required=false;
  $('#settingsForm .close-btn').type='button';$('#settingsForm .close-btn').onclick=()=>$('#settingsDialog').close();
  const batch=document.createElement('div');batch.innerHTML='<div class="batch-toolbar"><button class="small-btn" id="queueBtn" type="button">加入批量</button><span id="batchLabel">每次最多 20 条</span></div><div id="batchList" class="batch-list"></div><div id="failures"></div>';
  $('.helper-line').before(batch);
  $('#queueBtn').onclick=()=>{if(!currentMessage().raw_text){$('#extractError').textContent='先填写这条通知的内容。';return;}if(state.queue.length>=19){$('#extractError').textContent='批量队列已满，可开始分析。';return;}state.queue.push(currentMessage());$('#rawText').value='';$('#sentAt').value='';$('#sourceGroup').value='';renderQueue();toast('已加入批量队列。');};
  $('#batchList').onclick=event=>{const b=event.target.closest('[data-remove]');if(b){state.queue.splice(Number(b.dataset.remove),1);renderQueue();}};
  $('#extractForm').onsubmit=extract;$('#manualBtn').onclick=manualDraft;$('#draftList').onclick=draftAction;$('#taskList').onclick=taskAction;
  $('#newTaskBtn').onclick=()=>showView('inbox');$('#refreshBtn').onclick=()=>loadTasks({button:$('#refreshBtn')});
  document.querySelectorAll('[data-filter]').forEach(button=>{button.setAttribute('role','tab');button.setAttribute('aria-selected',String(button.classList.contains('active')));button.onclick=()=>{state.filter=button.dataset.filter;syncTaskNavigation();document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-selected',String(b===button));});loadTasks();};});
  const reminder=document.createElement('div');reminder.className='reminder-choice';reminder.innerHTML='<label for="reminderHours">提前提醒</label><select id="reminderHours"><option value="2">2 小时</option><option value="24">1 天</option><option value="48">2 天</option></select>';
  $('.task-toolbar').append(reminder);$('#reminderHours').value=reminderHours;$('#reminderHours').onchange=()=>{reminderHours=Number($('#reminderHours').value);localStorage.setItem('campusflow-reminder-hours',reminderHours);loadTasks();};
  $('#settingsBtn').onclick=()=>$('#settingsDialog').showModal();$('#closeSource').onclick=()=>$('#sourceDialog').close();$('#closeEdit').onclick=()=>$('#editDialog').close();
  $('#settingsForm').onsubmit=async event=>{event.preventDefault();const button=$('#settingsForm button[value=default]');if(button.disabled)return;setButtonBusy(button,true,'保存中…');try{await saveConfig();$('#settingsDialog').close();await loadConfig();toast('设置已保存。');}catch(error){$('#settingsError').textContent=error.message;}finally{setButtonBusy(button,false);}};
  $('#detectModelsBtn').textContent='保存并检测模型';
  $('#detectModelsBtn').onclick=async()=>{const button=$('#detectModelsBtn');setButtonBusy(button,true,'检测中…');$('#settingsError').textContent='';try{await saveConfig();await loadConfig();const {models}=await api('/api/models');$('#modelOptions').innerHTML=models.map(id=>`<button type="button" class="model-option" data-model="${esc(id)}">${esc(id)}</button>`).join('')||'服务已连接，但未返回模型。';$('#modelOptions').onclick=event=>{const b=event.target.closest('[data-model]');if(b)$('#modelId').value=b.dataset.model;};$('#modelStatus').textContent=`${providerLabels[modelConfig.provider]} · 服务已连接`;$('#modelDot').className='status-dot ready';toast('模型连接已检查。');}catch(error){$('#settingsError').textContent=error.message;$('#modelStatus').textContent=`${providerLabels[modelConfig?.provider||'local']} · 未连接`;}finally{setButtonBusy(button,false);}};
  $('#editForm').onsubmit=async event=>{event.preventDefault();const button=$('#editForm button[type="submit"]');setButtonBusy(button,true,'保存中…');try{const fields=readEditor($('#editForm'));delete fields.deadline_precision;await api(`/api/tasks/${state.editing}`,{method:'PATCH',body:fields});$('#editDialog').close();loadTasks();document.dispatchEvent(new Event('tasks-changed'));toast('待办已更新。');}catch(error){$('#editError').textContent=error.message;}finally{setButtonBusy(button,false);}};
  initializeCompletedManagement();initializeWorkbench();initializeShell();await loadConfig();await updateCount();
  try{const data=await api('/api/drafts');state.drafts=data.drafts;for(const draft of state.drafts){if(!state.messages.has(draft.message_id))state.messages.set(draft.message_id,await api(`/api/messages/${draft.message_id}`));}renderDrafts();}catch(error){$('#extractError').textContent=`草稿恢复失败：${error.message}`;}
  setInterval(()=>{if(!$('#tasksView').hidden&&!document.querySelector('dialog[open],.action-menu:popover-open'))loadTasks();},60000);
}
document.addEventListener('DOMContentLoaded',initialize);
