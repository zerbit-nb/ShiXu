/* Settings presentation only. Persisted values still come from each controller. */
const settingsMotionPreference=matchMedia('(prefers-reduced-motion: reduce)');
const settingsTextMotions=new Map(),settingsSwitchMotions=new Map();
function settingsCanAnimate(el){return !settingsMotionPreference.matches&&el.getClientRects().length>0&&!document.hidden;}
function finishSettingsText(el){
  const previous=settingsTextMotions.get(el);
  if(previous){clearTimeout(previous.timer);previous.width?.cancel();settingsTextMotions.delete(el);}
  el.classList.remove('is-changing');
  delete el.dataset.previous;
}
function setSettingsStatus(el,next){
  if(!el)return;
  next=String(next);
  if(el.dataset.statusText===next)return;
  const initialized=el.dataset.statusText!==undefined;
  const previous=el.dataset.statusText??el.textContent;
  const oldWidth=el.getBoundingClientRect().width;
  finishSettingsText(el);
  el.dataset.statusText=next;
  el.classList.add('settings-status');
  el.setAttribute('role','status');el.setAttribute('aria-live','polite');el.setAttribute('aria-atomic','true');
  // Generated outgoing text is visual only; the accessible label is current.
  el.setAttribute('aria-label',next);
  const label=document.createElement('span');label.className='settings-status-label';label.textContent=next;
  el.replaceChildren(label);
  if(!initialized||!settingsCanAnimate(el))return;
  const newWidth=el.getBoundingClientRect().width;
  el.dataset.previous=previous;
  void el.offsetWidth;
  el.classList.add('is-changing');
  const width=el.animate([{width:oldWidth+'px'},{width:newWidth+'px'}],{duration:240,easing:'cubic-bezier(.22,1,.36,1)'});
  const timer=setTimeout(()=>finishSettingsText(el),280);
  settingsTextMotions.set(el,{width,timer});
}
function setSettingsSwitch(button,on){
  if(!button)return;
  on=!!on;
  const initialized=button.dataset.switchState!==undefined;
  if(initialized&&button.dataset.switchState===String(on))return;
  const thumb=button.firstElementChild;
  const start=getComputedStyle(thumb).transform;
  settingsSwitchMotions.get(button)?.cancel();settingsSwitchMotions.delete(button);
  button.setAttribute('aria-checked',String(on));button.dataset.switchState=String(on);
  if(!initialized||!settingsCanAnimate(button))return;
  // Same timing and overshoot as the reference, scaled to this track's travel.
  const animation=thumb.animate([
    {transform:start==='none'?'translateX(0)':start,offset:0},
    {transform:'translateX('+(on?17:-1)+'px)',offset:.55},
    {transform:'translateX('+(on?16:0)+'px)',offset:.8},
    {transform:'translateX('+(on?16:0)+'px)',offset:1}
  ],{duration:350,easing:'cubic-bezier(.34,1.35,.64,1)'});
  settingsSwitchMotions.set(button,animation);
  animation.onfinish=()=>{if(settingsSwitchMotions.get(button)===animation)settingsSwitchMotions.delete(button);};
}
settingsMotionPreference.addEventListener('change',()=>{
  if(!settingsMotionPreference.matches)return;
  for(const el of settingsTextMotions.keys())finishSettingsText(el);
  for(const animation of settingsSwitchMotions.values())animation.cancel();
  settingsSwitchMotions.clear();
});
