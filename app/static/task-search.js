/* Read-only suggestions reuse the current view's task data and filtering. */
const taskSearchState={open:false,items:[],active:-1,composing:false};
function closeTaskSearch(){
  taskSearchState.open=false;taskSearchState.active=-1;
  $('#taskSearchPanel').hidden=true;
  $('#taskSearch').setAttribute('aria-expanded','false');
  $('#taskSearch').removeAttribute('aria-activedescendant');
}
function positionTaskSearch(){
  const panel=$('#taskSearchPanel');if(panel.hidden)return;
  const r=$('.task-search').getBoundingClientRect(),below=innerHeight-r.bottom-16,above=r.top-16;
  const up=below<180&&above>below;
  panel.classList.toggle('opens-up',up);
  panel.style.maxHeight=Math.max(80,Math.min(360,up?above:below))+'px';
}
function renderTaskSearch(){
  const input=$('#taskSearch'),panel=$('#taskSearchPanel');
  $('#clearTaskSearch').hidden=!input.value;
  if(!taskSearchState.open||$('#tasksView').hidden||completedManager.busy){closeTaskSearch();return;}
  const matches=state.tasksLoaded?orderedTasks(visibleTasks().filter(t=>state.route!=='upcoming'||(t.deadline&&taskDayGroup(t)!=='overdue'))):[];
  const items=matches.slice(0,5);
  taskSearchState.items=items;
  if(taskSearchState.active>=items.length)taskSearchState.active=-1;
  const statuses={pending:'未完成',completed:'已完成',cancelled:'已取消'};
  $('#taskSearchResults').innerHTML=items.map((t,i)=>'<div class="task-search-option" role="option" id="taskSearchOption-'+i+'" aria-selected="'+(i===taskSearchState.active)+'" data-search-index="'+i+'"><span class="task-search-title">'+esc(t.title)+'</span><span class="task-search-meta">'+esc(statuses[t.status]||t.status)+' · '+esc(t.source_group||'手动导入')+'</span></div>').join('');
  const feedback=$('#taskSearchFeedback');feedback.hidden=items.length>0;
  feedback.innerHTML=state.tasksLoaded?(uiIcon('search')+'<strong>'+(input.value.trim()?'没有找到匹配的任务':'当前列表没有任务')+'</strong><span>'+(input.value.trim()?'试试其他关键词或筛选条件':'切换筛选，或新建待办')+'</span>'):('<strong>'+(state.tasksError?'任务读取失败':'正在读取任务…')+'</strong>'+(state.tasksError?'<span>请点击刷新重试</span>':''));
  $('#taskSearchScope').textContent=matches.length>5?'当前列表 · 显示前 5 条 / 共 '+matches.length+' 条':'搜索当前列表 · 回车打开任务';
  panel.hidden=false;input.setAttribute('aria-expanded','true');
  input.removeAttribute('aria-activedescendant');
  if(taskSearchState.active>=0)input.setAttribute('aria-activedescendant','taskSearchOption-'+taskSearchState.active);
  positionTaskSearch();
}
function openTaskSearch(){
  if($('#taskSearch').disabled||completedManager.busy||$('#taskDetail').open)return;
  taskSearchState.open=true;renderTaskSearch();
}
async function selectTaskSearch(index){
  const task=taskSearchState.items[index];if(!task||!state.tasksLoaded||completedManager.busy)return;
  // Keep the search input as the detail's stable return-focus target.
  closeTaskSearch();$('#taskSearch').focus({preventScroll:true});closeTaskSearch();
  await openTaskDetail(task.id);
}
function initializeTaskSearch(){
  const input=$('#taskSearch'),root=$('.task-search'),results=$('#taskSearchResults');
  input.addEventListener('focus',openTaskSearch);
  input.addEventListener('click',openTaskSearch);
  input.addEventListener('input',()=>{taskSearchState.active=-1;taskSearchState.open=true;renderTaskList();});
  input.addEventListener('compositionstart',()=>taskSearchState.composing=true);
  input.addEventListener('compositionend',()=>taskSearchState.composing=false);
  $('#clearTaskSearch').onclick=()=>{
    if(input.disabled||completedManager.busy)return;
    input.value='';taskSearchState.active=-1;taskSearchState.open=true;
    input.focus({preventScroll:true});renderTaskList();
  };
  input.addEventListener('keydown',event=>{
    if(event.isComposing||taskSearchState.composing)return;
    if(event.key==='Escape'){if(taskSearchState.open){event.preventDefault();event.stopPropagation();closeTaskSearch();}return;}
    if(['ArrowDown','ArrowUp'].includes(event.key)){
      event.preventDefault();openTaskSearch();const count=taskSearchState.items.length;if(!count)return;
      const i=taskSearchState.active;
      taskSearchState.active=i<0?(event.key==='ArrowDown'?0:count-1):(i+(event.key==='ArrowDown'?1:-1)+count)%count;
      renderTaskSearch();$('#taskSearchOption-'+taskSearchState.active)?.scrollIntoView({block:'nearest'});
    }
    if(event.key==='Enter'&&taskSearchState.open&&taskSearchState.items.length){
      event.preventDefault();selectTaskSearch(Math.max(0,taskSearchState.active));
    }
    if(event.key==='Tab')closeTaskSearch();
  });
  results.addEventListener('pointerdown',event=>event.preventDefault());
  results.addEventListener('click',event=>{
    const row=event.target.closest('[data-search-index]');if(row)selectTaskSearch(Number(row.dataset.searchIndex));
  });
  root.addEventListener('focusout',event=>{if(!root.contains(event.relatedTarget))closeTaskSearch();});
  document.addEventListener('pointerdown',event=>{if(!root.contains(event.target))closeTaskSearch();});
  addEventListener('resize',positionTaskSearch);
  addEventListener('scroll',positionTaskSearch,true);
}
