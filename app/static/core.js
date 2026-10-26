/* Shared request, state, escaping and feedback primitives. No framework dependency. */
const $ = (selector, root = document) => root.querySelector(selector);
const state = { filter: 'pending', drafts: [], messages: new Map(), queue: [], editing: null, busy: false };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const priorityLabel = { low: '低', normal: '普通', high: '重要' };
let modelConfig = null;
const providerLabels = {local:'LM Studio',deepseek:'DeepSeek 官方 API',openai:'OpenAI 官方 API'};
let reminderHours = Number(localStorage.getItem('campusflow-reminder-hours') || 24);

async function api(url, {method = 'GET', body} = {}) {
  const response = await fetch(url, {method, headers: {'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(e => `${e.loc.slice(1).join(' / ')}：${e.msg}`).join('；') : data.detail;
    throw new Error(detail || `请求失败（${response.status}），请重试。`);
  }
  return data;
}

function toast(message) {
  const item = document.createElement('div');
  item.className = 'toast'; item.textContent = message;
  const region=$('#toastRegion');while(region.children.length>=2)region.firstElementChild.remove();
  region.append(item); setTimeout(() => item.remove(), 4000);
}
function setButtonBusy(button, busy, busyLabel = '处理中…') {
  if (!button) return;
  if (busy) {
    if (!button.dataset.idleLabel) button.dataset.idleLabel = button.innerHTML;
    button.disabled = true;
    button.classList.add('is-loading');
    button.setAttribute('aria-busy', 'true');
    button.textContent = busyLabel;
  } else {
    button.disabled = false;
    button.classList.remove('is-loading');
    button.removeAttribute('aria-busy');
    if (button.dataset.idleLabel) { button.innerHTML = button.dataset.idleLabel; delete button.dataset.idleLabel; }
  }
}
function displayDeadline(task) {
  if (!task.deadline) return task.deadline_text ? '期限待确认' : '无截止时间';
  if (task.deadline.length === 10) return `${task.deadline}（仅日期）`;
  return new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(task.deadline));
}

const sourceNames={qq:'QQ',wechat:'微信',manual:'手动导入'};
function sourceName(source){return sourceNames[source]||source||'来源未知';}
function messageTime(value){if(!value)return '时间未知';const date=new Date(value);return Number.isNaN(date.getTime())?value:date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});}

const messageStatuses={received:'待处理',pending:'待处理',extracting:'正在分析',failed:'分析失败',ready:'已生成草稿',no_action:'无需行动',ignored:'已忽略'};
