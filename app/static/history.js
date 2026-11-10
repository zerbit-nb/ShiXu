/* Startup catch-up is backend-owned; this panel exposes consent and coverage. */
let historyConfig=null,historyBusy=false;
function renderHistory(data){
  historyConfig=data;
  setSettingsSwitch($('#historyToggle'),data.enabled);
  setSettingsStatus($('#historyStatus'),data.enabled?'已开启':'已关闭');
  const names={qq:'QQ',wechat:'微信'};
  const notes={source_limit:'达到读取上限',pagination_stalled:'历史接口未继续返回更早消息',
    source_unavailable:'历史记录暂不可读，请检查连接',interrupted:'上次补收中断'};
  $('#historyResults').textContent=data.enabled?Object.keys(names).map(source=>{
    const runs=data.runs.filter(r=>r.source===source);
    if(!runs.length)return names[source]+'：等待连接或下次启动';
    const running=runs.some(r=>r.state==='collecting'),partial=runs.find(r=>r.state==='partial');
    const count=runs.reduce((sum,r)=>sum+r.received,0);
    return names[source]+'：'+(running?'补收中':partial?'部分补收':'已检查本机可读记录')+' · 新增 '+count+' 条'+
      (partial?'（'+(notes[partial.reason]||'请检查连接后重新启动')+'）':'')+
      (runs.some(r=>r.has_changes)?' · 含变更通知，请在收件箱核对':'');
  }).join('\n'):'';
}
async function loadHistory(){
  if(historyBusy)return;
  historyBusy=true;
  try{renderHistory(await api('/api/history'));$('#historyToggle').disabled=false;$('#historyError').textContent='';}
  catch(error){$('#historyError').textContent=error.message;setSettingsStatus($('#historyStatus'),'读取失败');}
  finally{historyBusy=false;}
}
document.addEventListener('DOMContentLoaded',()=>{
  const row=document.createElement('section');row.className='connection-row reception-filter-row';
  row.innerHTML='<span class="connection-monogram">'+uiIcon('download')+'</span><div><h2 id="historyTitle">启动补收</h2><p id="historyHint">补收已选群今天的通知，自动整理沿用现有开关</p><details class="history-help"><summary>读取范围</summary><p>按北京时间从零点检查本机可读文本，已处理消息不重复加入。开启后，启动拾序会自动启动已配置的微信采集；已运行的采集下次启动生效。云端自动整理可能产生费用。明确闲聊进入垃圾桶，其他消息保留核对。</p></details><p id="historyResults" class="field-hint" role="status"></p><p id="historyError" class="form-error" role="alert"></p></div><span class="reception-filter-control"><span id="historyStatus">读取中…</span><button id="historyToggle" type="button" class="reception-filter-switch" role="switch" aria-checked="false" aria-labelledby="historyTitle" aria-describedby="historyHint" disabled><span aria-hidden="true"></span></button></span>';
  $('#connectionsView .connection-list').append(row);
  $('#historyToggle').onclick=async()=>{
    if(historyBusy||!historyConfig)return;
    historyBusy=true;$('#historyToggle').disabled=true;
    try{renderHistory(await api('/api/history',{method:'PUT',body:{enabled:!historyConfig.enabled}}));$('#historyError').textContent='';}
    catch(error){$('#historyError').textContent=error.message;}
    finally{historyBusy=false;$('#historyToggle').disabled=false;}
  };
  loadHistory();setInterval(()=>{if(!document.hidden&&state.route==='connections')loadHistory();},5000);
});
