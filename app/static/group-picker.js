/* Shared local group selection. Names are always text, never executable markup. */
class GroupPicker {
  constructor(root, {prefix, limit, load, change=()=>{}, inline=false}) {
    this.root=root;this.limit=limit;this.load=load;this.change=change;this.inline=inline;
    this.selected=[];this.groups=[];this.revision=0;this.ready=false;
    root.classList.add('group-picker');
    root.innerHTML='<div class="group-search-row"><svg aria-hidden="true" class="group-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input type="search" autocomplete="off" placeholder="搜索群聊" aria-label="搜索群聊"><button type="button" class="small-btn">读取群聊</button></div><div class="group-results" hidden></div><div class="group-tags" role="list" aria-label="已选群聊"></div><p class="field-hint group-picker-hint" role="status" aria-live="polite"></p>';
    this.input=root.querySelector('input');this.input.id=prefix+'GroupSearch';
    this.refresh=root.querySelector('button');this.refresh.id=prefix+'GroupsRefresh';
    this.results=root.querySelector('.group-results');this.results.id=prefix+'GroupResults';
    this.input.setAttribute('aria-controls',this.results.id);this.input.setAttribute('aria-expanded','false');
    this.tags=root.querySelector('.group-tags');this.hint=root.querySelector('.group-picker-hint');
    if(inline){root.classList.add('group-picker-inline');this.results.before(this.tags);this.results.setAttribute('role','group');this.results.setAttribute('aria-label','可选群聊');this.hideResults();}
    this.refresh.onclick=()=>this.reload();
    this.input.oninput=()=>this.renderResults();
    this.input.onfocus=()=>{if(this.ready)this.renderResults();};
    root.addEventListener('focusout',event=>{if(!root.contains(event.relatedTarget))this.hideResults();});
    this.input.onkeydown=event=>{
      if(event.key==='ArrowDown'){event.preventDefault();this.renderResults();this.results.querySelector('button')?.focus();}
    };
    root.addEventListener('keydown',event=>{
      if(!this.inline&&event.key==='Escape'&&!this.results.hidden){event.preventDefault();event.stopPropagation();this.input.focus();this.hideResults();}
    });
    this.note(inline?'':'读取本机可用群聊后选择，最多 '+limit+' 个。');
  }
  note(text,error=false){this.hint.textContent=text;this.hint.classList.toggle('is-error',error);}
  hideResults(){this.results.hidden=!this.inline;this.input.setAttribute('aria-expanded',String(this.inline));if(this.inline&&!this.ready){this.results.replaceChildren();const empty=document.createElement('p');empty.className='group-results-empty';empty.textContent='点击刷新，读取本机群聊';this.results.append(empty);}}
  cancel(){this.revision++;this.refresh.disabled=false;this.refresh.textContent=this.inline?'刷新':'读取群聊';this.root.removeAttribute('aria-busy');this.hideResults();}
  invalidate(){this.cancel();this.groups=[];this.ready=false;this.input.value='';this.hideResults();}
  reset(groups=[]){this.cancel();this.groups=[];this.ready=false;this.input.value='';this.set(groups);this.hideResults();this.note(this.inline?'':'读取本机可用群聊后选择，最多 '+this.limit+' 个。');}
  set(groups){this.selected=groups.map(g=>({...g}));this.renderTags();if(this.inline)this.renderResults();this.change(this.value());}
  value(){return this.selected.map(g=>({...g}));}
  async reload(){
    const revision=++this.revision;
    this.refresh.disabled=true;this.refresh.textContent='读取中…';this.root.setAttribute('aria-busy','true');
    this.note('正在验证账号并读取群聊…');this.hideResults();
    try{
      const result=await this.load();if(revision!==this.revision)return;
      this.groups=result.groups;this.ready=true;
      // Upgrade the previous name-only selection only when it is unambiguous.
      this.selected=this.selected.map(g=>{
        if(g.legacy){const matches=this.groups.filter(x=>x.name===g.name);return matches.length===1?{...matches[0]}:g;}
        return this.groups.find(x=>x.id===g.id)||g;
      });
      this.renderTags();this.change(this.value());this.renderResults();
      this.note(this.groups.length?(this.inline?'':'已读取 '+this.groups.length+' 个群聊，支持搜索名称。'):'本机未找到可用群聊，请检查微信或 QQ 登录状态。');
    }catch(error){if(revision===this.revision){this.groups=[];this.ready=false;this.hideResults();this.note(error.message,true);}}
    finally{if(revision===this.revision){this.refresh.disabled=false;this.refresh.textContent=this.inline?'刷新':'刷新群聊';this.root.removeAttribute('aria-busy');}}
  }
  add(group){
    if(this.selected.some(g=>g.id===group.id))return;
    if(this.selected.length>=this.limit){this.note('最多选择 '+this.limit+' 个群聊。',true);return;}
    this.selected.push({...group});if(!this.inline)this.input.value='';this.renderTags();this.change(this.value());if(this.inline){this.renderResults();this.note('');return;}this.hideResults();
    this.note('已选 '+this.selected.length+' 个群聊。');this.input.focus();this.hideResults();
  }
  renderTags(){
    this.tags.replaceChildren();
    for(const group of this.selected){
      const chip=document.createElement('span');chip.className='group-chip';chip.setAttribute('role','listitem');chip.dataset.groupId=group.id;
      const name=document.createElement('span');name.className='group-chip-name';name.textContent=group.name;name.title=group.name+(group.legacy?'（旧配置）':' · '+group.id);
      const remove=document.createElement('button');remove.type='button';remove.className='group-chip-remove';remove.textContent='×';remove.setAttribute('aria-label','移除群聊：'+group.name);
      remove.onclick=()=>{this.selected=this.selected.filter(g=>g.id!==group.id);this.renderTags();this.change(this.value());this.renderResults(this.inline);this.note(this.inline?'':'已选 '+this.selected.length+' 个群聊。移除不会删除已有消息。');this.input.focus();if(!this.inline)this.hideResults();};
      chip.append(name,remove);this.tags.append(chip);
    }
  }
  renderResults(show=true){
    this.results.replaceChildren();if(!this.ready){this.hideResults();return;}
    const query=this.input.value.trim().toLocaleLowerCase();
    const matches=this.groups.filter(g=>(this.inline||!this.selected.some(s=>s.id===g.id))&&(g.name.toLocaleLowerCase().includes(query)||g.id.includes(query)));
    for(const group of matches.slice(0,40)){
      const row=document.createElement('button');row.type='button';row.className='group-result';
      const title=document.createElement('span');title.textContent=group.name;
      const id=document.createElement('small');id.textContent=group.id;
      if(this.inline){
        const checked=this.selected.some(g=>g.id===group.id);
        row.setAttribute('role','checkbox');row.setAttribute('aria-checked',String(checked));
        const box=document.createElement('span');box.className='group-result-check';box.setAttribute('aria-hidden','true');box.textContent='✓';row.append(box,title);
        if(this.groups.some(g=>g.id!==group.id&&g.name===group.name))row.append(id);
        row.onclick=()=>{
          if(!checked){this.add(group);}else{this.selected=this.selected.filter(g=>g.id!==group.id);this.renderTags();this.change(this.value());this.renderResults();this.note('');}
          Array.from(this.results.querySelectorAll('button')).find(b=>b.dataset.groupId===group.id)?.focus({preventScroll:true});
        };
        row.dataset.groupId=group.id;
      }else{row.append(title,id);row.onclick=()=>this.add(group);}
      row.onkeydown=event=>{
        if(event.key==='ArrowDown'){event.preventDefault();row.nextElementSibling?.focus();}
        if(event.key==='ArrowUp'){event.preventDefault();(row.previousElementSibling||this.input).focus();}
      };
      this.results.append(row);
    }
    if(!matches.length){const empty=document.createElement('p');empty.textContent=query?'未找到匹配的群聊':'没有其他可选群聊';empty.className='group-results-empty';this.results.append(empty);}
    if(matches.length>40){const hint=document.createElement('p');hint.textContent='继续输入以缩小搜索范围';hint.className='group-results-empty';this.results.append(hint);}
    this.results.hidden=!show&&!this.inline;this.input.setAttribute('aria-expanded',String(show||this.inline));
  }
}
