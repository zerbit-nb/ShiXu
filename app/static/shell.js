/* View ownership and navigation. Connections keep independent controllers. */
const viewNames={tasks:'待办中心',upcoming:'即将截止',completed:'已完成',inbox:'导入通知',messages:'消息收件箱',connections:'设置与连接',qq:'QQ 连接',wechat:'微信采集'};
function syncTaskNavigation(){
  if(state.filter==='completed')state.route='completed';
  else if(state.route!=='upcoming'||state.filter!=='pending')state.route='tasks';
  $('#taskPageTitle').textContent=viewNames[state.route];
  $('#taskPageHint').textContent=state.route==='completed'?'做过的事，都在这里。':state.route==='upcoming'?'按截止日期，安排接下来的事。':'先完成眼前重要的事。';
  document.querySelectorAll('[data-view]').forEach(b=>{const active=b.dataset.view===state.route;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  $('#viewLabel').textContent=viewNames[state.route];
}
function showView(route){
  if(!viewNames[route])route='tasks';
  document.querySelectorAll('.action-menu:popover-open').forEach(m=>m.hidePopover());
  if(typeof closeTaskDetail==='function')closeTaskDetail();
  closeTaskSearch();
  const taskView=['tasks','upcoming','completed'].includes(route);
  state.route=route;
  const view=taskView?'tasks':route;
  for(const id of ['inbox','tasks','messages','connections','qq','wechat'])$('#'+id+'View').hidden=id!==view;
  document.querySelectorAll('[data-view]').forEach(b=>{const active=b.dataset.view===route;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  $('#viewLabel').textContent=viewNames[route];
  if(taskView){
    state.filter=route==='completed'?'completed':'pending';
    document.querySelectorAll('[data-filter]').forEach(b=>{const active=b.dataset.filter===state.filter;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});
    syncTaskNavigation();loadTasks();
  }
  if(route==='messages')loadUnifiedInbox();
  if(route==='connections')loadReceptionFilter();
  if(route==='qq'){loadQQSettings().catch(e=>$('#qqError').textContent=e.message);loadQQInbox();loadBridgeStatus();}
  if(route==='wechat')loadWechatInbox();
  if(location.hash!=='#'+route)history.replaceState(null,'','#'+route);
  $('.main').scrollTop=0;
}
function initializeShell(){
  document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=uiIcon(el.dataset.icon));
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));
  $('.brand').onclick=e=>{e.preventDefault();showView('tasks');};
  document.querySelectorAll('[data-open-connection]').forEach(b=>b.onclick=()=>showView(b.dataset.openConnection));
  $('#connectionModelBtn').onclick=()=>$('#settingsDialog').showModal();
  $('#quickImport').onclick=()=>{showView('inbox');$('#rawText').focus();};
  $('#importMessageBtn').onclick=()=>{showView('inbox');$('#rawText').focus();};
  $('#quickNewTask').onclick=openNewTask;
  $('#newTaskForm').onsubmit=saveNewTask;
  for(const id of ['closeNewTask','cancelNewTask'])$('#'+id).onclick=()=>{if(!newTaskSaving)$('#newTaskDialog').close();};
  $('#newTaskDialog').addEventListener('cancel',event=>{if(newTaskSaving)event.preventDefault();});
  $('#quickAdd').addEventListener('click',()=>{const menu=$('#quickAddMenu'),r=$('#quickAdd').getBoundingClientRect();menu.style.left=Math.max(8,Math.min(innerWidth-192,r.right-184))+'px';menu.style.top=r.bottom+8+'px';});
  addEventListener('hashchange',()=>{const route=location.hash.slice(1);if(viewNames[route])showView(route);});
  document.addEventListener('drafts-rendered',()=>{const count=state.drafts.length;$('#navDraftCount').hidden=!count;$('#navDraftCount').textContent=count;});
  showView(viewNames[location.hash.slice(1)]?location.hash.slice(1):'tasks');
}

// Keep unsaved input in this dialog only; opening or cancelling never writes data.
let newTaskSaving=false;
function openNewTask(){
  if(state.busy||newTaskSaving)return;
  const menu=$('#quickAddMenu');if(menu.matches(':popover-open'))menu.hidePopover();
  if(!$('#newTaskFields').children.length)$('#newTaskFields').innerHTML=editor({title:'',materials:[],priority:'normal'});
  $('#newTaskError').textContent='';
  $('#newTaskDialog').showModal();
  $('#newTaskDialog [data-field=title]').focus();
}
async function saveNewTask(event){
  event.preventDefault();if(newTaskSaving)return;
  const form=$('#newTaskForm'),error=$('#newTaskError'),button=$('#newTaskSubmit');
  error.textContent='';let fields;
  try{fields=readEditor(form);}catch(e){error.textContent=e.message;return;}
  newTaskSaving=true;form.setAttribute('aria-busy','true');
  setButtonBusy(button,true,'保存中…');
  form.querySelectorAll('input,textarea,select,button').forEach(el=>el.disabled=true);
  let result;
  try{
    result=await api('/api/messages/manual',{method:'POST',body:{raw_text:'手动创建：'+fields.title+(fields.description?'\n'+fields.description:''),source:'manual',fields}});
  }catch(e){error.textContent=e.message;return;}
  finally{
    newTaskSaving=false;form.removeAttribute('aria-busy');
    form.querySelectorAll('input,textarea,select,button').forEach(el=>el.disabled=false);
    setButtonBusy(button,false);
  }
  // The draft is saved. Reset before rendering so a rendering error cannot resubmit it.
  $('#newTaskDialog').close();$('#newTaskFields').replaceChildren();
  captureDrafts();await absorb(result);renderDrafts();showView('inbox');
  const card=document.querySelector('[data-draft-id="'+result.drafts[0].id+'"]');
  card?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
  $('[data-field=title]',card||document)?.focus({preventScroll:true});
  toast('已保存草稿，请核对后创建。');
}
