'use strict';
const content = document.querySelector('#content');
const error = document.querySelector('#error');
const retry = document.querySelector('#retry');
const surface = new URLSearchParams(location.search).get('surface') || 'main';
let state, signature, pending, durationOpen = false, closeRequested = false, busy = false;
const messages = {
 stale_context: '此操作对应的状态已变化。已读取当前状态。',
 active_session_exists: '已有执行会话或等待收尾，请先处理当前会话。',
 expired_or_resolved_context: '原入口已结束或过期，请查看当前状态。',
 expired_context_i02_lifecycle_not_available: '已超出本次开发验收窗口。完整到期处理属于 I-02。',
 checkpoint_outside_development_window: '检查时间超出开发验收窗口，请缩短本次时长。',
 duration_confirmation_required: '请确认本次时长和相应的检查时间。',
 invalid_actual_duration: '实际用时需为正数，或留空表示未知。'
};
async function request(path, body) {
 const response = await fetch(path, {method:body === undefined ? 'GET':'POST', headers:{'X-I01-Client':'1','Content-Type':'application/json'},body:body === undefined ? undefined:JSON.stringify(body)});
 const result = response.status === 204 ? {} : await response.json();
 return {status:response.status,result};
}
function button(label, callback, primary=false) {
 const element=document.createElement('button');element.textContent=label;element.className=primary?'primary':'';element.onclick=callback;element.disabled=!!pending||busy;content.append(element);return element;
}
function paragraph(text, tag='p', className='') {const e=document.createElement(tag);e.textContent=text;e.className=className;content.append(e);return e;}
function date(value) {return new Date(value*1000).toLocaleTimeString('zh-CN');}
async function submit(kind,target,version,payload={}) {
 if (pending || busy) return;
 pending={kind,target,version,payload,command_id:crypto.randomUUID()};
 await sendPending();
}
async function sendPending() {
 if (!pending || busy) return;
 busy=true;retry.hidden=true;error.textContent='';render();
 try {
  const {status,result}=await request('/api/commands',pending);
  if (status === 200) {pending=null;durationOpen=false;await refresh();if(closeRequested) await hide();}
  else if(status === 409 || status === 400){pending=null;closeRequested=false;error.textContent=messages[result.error]||'操作未提交。请查看当前状态。';await refresh();}
  else {throw new Error('unavailable');}
 } catch (_) {
  error.textContent='暂时无法确认保存结果。恢复连接后可重试同一次操作，不会重复创建会话。';retry.hidden=false;closeRequested=false;
 } finally {busy=false;render();}
}
retry.onclick=sendPending;
async function hide(){closeRequested=false;await request('/ui/hide?surface='+surface,{});}
window.addEventListener('host-close',async()=>{
 if(pending||busy){error.textContent='本次保存结果尚未确认，请先重试。';return;}
 try {
  const latest=await request('/api/state');if(latest.status!==200)throw new Error();state=latest.result;
  if(state.active_session?.status==='awaiting_closure') {closeRequested=true;await submit('skip_closure',state.active_session.id,state.active_session.version);}
  else await hide();
 }catch(_){error.textContent='无法读取当前状态，暂未关闭。可重连后再操作，或从托盘退出并保留状态。';}
});
function render(){
 if(!state)return;
 content.replaceChildren();
 const action=state.actions[0],session=state.active_session;
 paragraph(action?.title || '没有开发夹具','h1');
 const arrangement=state.arrangements.find(a=>a.id===(session?.arrangement_id || 'arrangement-a'));
 if (arrangement && state.now>=arrangement.window_end && (session || arrangement.status!=='ended')) {
  paragraph('本次开发验收窗口已结束。自动到期收束与完整恢复尚未交付（I-02）；原事实已保留。');return;
 }
 if(session?.status==='executing'){
  const cp=state.checkpoints.find(c=>c.session_id===session.id);
  paragraph(cp.status==='due'?'约定的检查时间已到。完成后可报告结果。':'执行会话已建立。检查时间：'+date(cp.due_at));
  button('已经完成',()=>submit('report_complete',session.id,session.version),true);
  paragraph('继续并确认下一检查时间、暂停并保存恢复包：I-01 尚未交付。','small');
  paragraph('会话 '+session.id+' · 检查点 '+cp.id,'p','facts');
 }else if(session?.status==='awaiting_closure'){
  paragraph('已记录完成报告，正在等待收尾。收尾结束后才释放当前会话。');
  const label=document.createElement('label');label.textContent='确认结果 ';const select=document.createElement('select');
  for(const [value,text] of [['completed','全部完成'],['partial','部分完成']]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}label.append(select);content.append(label);
  const durationLabel=document.createElement('label');durationLabel.textContent='实际用时（分钟，可留空） ';const input=document.createElement('input');input.type='number';input.min='0.1';input.step='0.1';durationLabel.append(input);content.append(durationLabel);
  button('完成收尾',()=>submit('finish_closure',session.id,session.version,{result:select.value,actual_duration_seconds:input.value===''?null:Number(input.value)*60}),true);
  button('跳过收尾',()=>submit('skip_closure',session.id,session.version));
  paragraph('关闭当前界面也会按跳过收尾保存最小证据；未填写内容保持未知。','small');
 }else if(state.evidence.length){
  const evidence=state.evidence[state.evidence.length-1];paragraph('已保存执行证据，会话已结束。');paragraph(evidence.result==='completed'?'已确认全部完成。':'已确认部分完成，行动没有被标为全部完成。');
  paragraph('可从托盘退出。重复验收使用新的隔离数据目录。','small');paragraph('证据 '+evidence.id,'p','facts');
 }else{
  const intervention=state.interventions.find(i=>i.status==='pending' && state.now<i.expires_at);
  if(!intervention){paragraph('等待约定时间：'+date(arrangement.start_at));}
  else if(durationOpen){
   paragraph('确认从现在起多久后检查；确认前不会创建会话。');
   const label=document.createElement('label');label.textContent='本次预计时长（分钟） ';const input=document.createElement('input');input.type='number';input.min='0.1';input.max='180';input.step='0.1';input.value='1';label.append(input);content.append(label);
   const preview=paragraph('确认后，首次检查在 1 分钟后。');input.oninput=()=>preview.textContent='确认后，首次检查在 '+input.value+' 分钟后。';
   button('确认时长并开始',()=>submit('start',intervention.id,intervention.version,{duration_seconds:Number(input.value)*60,duration_confirmed:true}),true);
   button('取消',()=>{durationOpen=false;render();});
  }else{
   paragraph(arrangement.duration_confirmed?'已确认时长：'+arrangement.duration_seconds/60+' 分钟；立即开始后据此建立首次检查点。':'尚未确认本次时长。');
   button('立即开始',()=>{if(arrangement.duration_confirmed)submit('start',intervention.id,intervention.version);else{durationOpen=true;render();}},true);
   paragraph('已经开始、已经完成、改期、今天不做：I-01 尚未交付。','small');
  }
 }
}
async function refresh(){
 try {
  const {status,result}=await request('/api/state');if(status!==200)throw new Error();
  state=result;document.querySelector('#connection').textContent='已连接智能体核心 · 状态已持久保存';
  const key=JSON.stringify([result.sessions,result.interventions,result.checkpoints,result.evidence,result.deliveries,result.now>=result.arrangements[0]?.window_end]);
  if(key!==signature){signature=key;render();}
  const notice=await request('/ui/notice');document.querySelector('#notice').textContent=notice.result?.valid===false?'原通知上下文已失效，当前显示的是 Core 最新状态。':notice.result?.valid===true?'已从系统通知返回对应行动。':'';
 }catch(_){document.querySelector('#connection').textContent='智能体核心暂不可用，正在重新连接…';for(const b of content.querySelectorAll('button'))b.disabled=true;signature=null;}
}
refresh();setInterval(refresh,600);
