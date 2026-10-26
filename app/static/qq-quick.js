/* Only public account labels are kept here; NapCat owns saved authorization. */
let quickLoadGeneration=0;
function clearQuickAccounts(){
  quickLoadGeneration++;setButtonBusy($('#qqQuickRefresh'),false);$('#qqQuickAccount').replaceChildren(new Option('选择快速登录后读取账号',''));
  $('#qqQuickAccount').disabled=true;$('#qqQuickSubmit').disabled=true;$('#qqQuickError').textContent='';
}
async function loadQuickAccounts(){
  if(loginBusy||loginPaused)return;
  const dialogGeneration=loginGeneration, requestGeneration=++quickLoadGeneration;
  const button=$('#qqQuickRefresh'),select=$('#qqQuickAccount');
  setButtonBusy(button,true,'读取中…');select.disabled=true;$('#qqQuickSubmit').disabled=true;$('#qqQuickError').textContent='';$('#qqQuickHint').textContent='正在读取账号…';
  try{
    const data=await loginRequest('quick/accounts');
    if(dialogGeneration!==loginGeneration||requestGeneration!==quickLoadGeneration||!$('#qqLoginDialog').open)return;
    if(!Array.isArray(data.accounts)||data.state!=='quick_accounts')throw new Error(data.message||'无法读取账号，请检查 NapCat 是否运行。');
    const rows=data.accounts.filter(row=>/^[1-9][0-9]{4,19}$/.test(row.account_id));
    const old=select.value;select.replaceChildren(new Option(rows.length?'请选择账号':'没有可快速登录的账号',''));
    for(const row of rows)select.add(new Option(row.nickname?row.nickname+'（'+row.account_id+'）':row.account_id,row.account_id));
    if(rows.some(row=>row.account_id===old))select.value=old;
    else if(rows.length===1)select.value=rows[0].account_id;
    select.disabled=!rows.length;
    $('#qqQuickSubmit').disabled=loginBusy||!select.value;
    $('#qqQuickHint').textContent=rows.length?rows.length+' 个可用账号 · 已保存的登录资格，不代表当前在线':'没有可快速登录的账号。请先扫码或密码登录，再刷新。';
  }catch(error){
    if(dialogGeneration===loginGeneration&&requestGeneration===quickLoadGeneration){select.replaceChildren(new Option('账号读取失败，请刷新重试',''));$('#qqQuickError').textContent=error.message;$('#qqQuickHint').textContent='可改用扫码或密码登录。';}
  }finally{
    if(requestGeneration===quickLoadGeneration)setButtonBusy(button,false);
  }
}
document.addEventListener('DOMContentLoaded',()=>{
  $('#qqQuickRefresh').onclick=loadQuickAccounts;
  $('#qqQuickAccount').onchange=()=>$('#qqQuickSubmit').disabled=loginBusy||!$('#qqQuickAccount').value;
  $('#qqQuickSubmit').onclick=()=>{const account=$('#qqQuickAccount').value;if(!account||loginBusy)return;loginAction('quick',$('#qqQuickSubmit'),{account_id:account});};
});
