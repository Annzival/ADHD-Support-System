'use strict';
const content = document.querySelector('#content');
const error = document.querySelector('#error');
const retry = document.querySelector('#retry');
const surface = new URLSearchParams(location.search).get('surface') || 'main';
let closureDraft, actionForm;
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
  if (status === 200) {pending=null;durationOpen=false;actionForm=null;await refresh();if(closeRequested) await hide();}
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
function field(labelText, key, values, type='text', initial='') {
 const label=document.createElement('label');label.textContent=labelText;
 const input=document.createElement('input');input.type=type;input.value=values[key]??initial;
 values[key]=input.value;input.oninput=()=>{values[key]=input.value;};label.append(input);content.append(label);return input;
}
function openForm(kind,record,payload={}) {actionForm={kind,target:record.id,version:record.version,payload,values:{}};render();}
function durationForm(){
 const f=actionForm;paragraph('确认从现在起多久后检查；确认前不会创建或切换会话。');
 field('本次预计时长（分钟） ','minutes',f.values,'number','1');
 button('确认时长并开始',()=>submit(f.kind,f.target,f.version,{...f.payload,duration_seconds:Number(f.values.minutes)*60,duration_confirmed:true,confirmed:true}),true);
 button('取消',()=>{actionForm=null;render();});
}
function render(){
 if(!state)return;
 content.replaceChildren();
 const session=state.active_session;
 if(session?.status!=='awaiting_closure' || closureDraft?.sessionId!==session.id) closureDraft=undefined;
 if(actionForm){
  if(actionForm.kind==='reschedule'){
   paragraph('改期只替换本次安排，其他安排不顺延。新窗口可留空。','h1');
   field('新的开始时间 ','start',actionForm.values,'datetime-local');
   field('新的窗口结束（可留空） ','end',actionForm.values,'datetime-local');
   button('确认改期',()=>submit('reschedule',actionForm.target,actionForm.version,{confirmed:true,start_at:new Date(actionForm.values.start).getTime()/1000,window_end:actionForm.values.end?new Date(actionForm.values.end).getTime()/1000:null}),true);
  }else if(actionForm.kind==='correct_fact'){
   paragraph('追加更正会保留原始事实。','h1');
   const select=document.createElement('select');for(const [v,t] of [['completed','全部完成'],['partial','部分完成'],['paused','暂停'],['unknown','未知']]){const o=document.createElement('option');o.value=v;o.textContent=t;select.append(o);}select.value=actionForm.values.result||'unknown';select.onchange=()=>actionForm.values.result=select.value;content.append(select);
   field('更正内容 ','content',actionForm.values);field('更正原因 ','reason',actionForm.values);
   button('保存更正',()=>submit('correct_fact',actionForm.target,actionForm.version,{...actionForm.values,result:select.value}),true);
  }else {durationForm();return;}
  button('取消',()=>{actionForm=null;render();});return;
 }
 const foreground=state.foreground;
 const starts=state.interventions.filter(i=>i.status==='pending'&&state.now<i.expires_at);
 const selected=starts.find(i=>i.id===foreground?.id);
 const currentAction=state.actions.find(a=>a.id===(session?.action_id||state.arrangements.find(a=>a.id===selected?.arrangement_id)?.action_id));
 paragraph(currentAction?.title||'执行支持','h1');
 if(session?.status==='executing'){
  const cp=state.checkpoints.find(c=>c.session_id===session.id&&['scheduled','due'].includes(c.status));
  paragraph(cp.status==='due'?'约定的检查时间已到。可完成、继续或暂停。':'执行会话已建立。检查时间：'+date(cp.due_at));
  button('已经完成',()=>submit('report_complete',session.id,session.version),true);
  button('暂停并保存恢复包',()=>submit('pause',session.id,session.version));
  if(cp.status==='due')button('继续并确认下一检查时间',()=>openForm('continue',cp));
 }else if(session?.status==='awaiting_closure'){
  if(!closureDraft)closureDraft={sessionId:session.id,result:session.report==='paused'?'paused':'completed',minutes:'',progress:''};
  paragraph('已记录'+(session.report==='paused'?'暂停':'完成')+'报告，正在等待收尾。收尾结束后才释放当前会话。');
  const select=document.createElement('select');
  for(const [value,text] of (session.report==='paused'?[['paused','暂停']]:[['completed','全部完成'],['partial','部分完成']])){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}select.value=closureDraft.result;select.onchange=()=>closureDraft.result=select.value;content.append(select);
  field('实际用时（分钟，可留空） ','minutes',closureDraft,'number');
  if(session.report==='paused')field('已取得的进展（可留空） ','progress',closureDraft);
  button('完成收尾',()=>submit('finish_closure',session.id,session.version,{result:closureDraft.result,actual_duration_seconds:closureDraft.minutes===''?null:Number(closureDraft.minutes)*60,progress:closureDraft.progress||null}),true);
  button('跳过收尾',()=>submit('skip_closure',session.id,session.version));
  paragraph('关闭当前界面也会按跳过收尾保存最小证据；未填写内容保持未知。','small');
 }
 const visibleStarts=surface==='overlay'?(session?[]:selected?[selected]:[]):starts;
 for(const i of visibleStarts){
  const a=state.arrangements.find(a=>a.id===i.arrangement_id), action=state.actions.find(x=>x.id===a.action_id);
  paragraph(action.title,'h2');
  paragraph(a.duration_confirmed?'已确认时长：'+a.duration_seconds/60+' 分钟；立即开始后据此建立首次检查点。':'尚未确认本次时长。');
  button('立即开始',()=>a.duration_confirmed?submit('start',i.id,i.version):openForm('start',i),true);
  button('我已经开始',()=>openForm('already_started',i));
  button('我已经完成',()=>submit('already_completed',i.id,i.version));
  if(surface==='main'){
   button('改到具体时间',()=>openForm('reschedule',i));
   button('今天不做',()=>submit('skip_today',i.id,i.version));
  }
 }
 if(surface==='overlay'){
  if(!session&&state.evidence.length){const e=state.evidence[state.evidence.length-1];paragraph('已保存执行证据，会话已结束。');paragraph(e.result==='partial'?'已确认部分完成，行动没有被标为全部完成。':e.result==='paused'?'已暂停并保存恢复包。':'已确认全部完成。');}
  button('打开主窗口',()=>request('/ui/open',{}));return;
 }
 for(const r of (state.recoveries||[]).filter(r=>['pending','deferred'].includes(r.status))){
  paragraph(r.status==='deferred'?'稍后处理上次上下文':'恢复上下文','h2');
  const detail=(title,text)=>{const d=document.createElement('details');const summary=document.createElement('summary');summary.textContent=title;d.append(summary);const p=document.createElement('p');p.textContent=text;d.append(p);content.append(d);};
  const old=state.sessions.find(s=>s.id===r.source.session_id), a=state.arrangements.find(a=>a.id===r.source.arrangement_id);
  detail('上次执行',old?state.actions.find(a=>a.id===old.action_id)?.title:'只有错过开始记录时，不能据此认定已经执行。');
  detail('当前计划',a?state.actions.find(x=>x.id===a.action_id)?.title:'当前没有可开始的安排。');
  if(old)button('继续上次执行',()=>submit('return_previous',r.id,r.version));
  else if(r.source.previous_intervention_ids.length)button('处理上一项',()=>submit('return_previous',r.id,r.version));
  for(const id of r.source.packet_ids){
   const packet=state.packets.find(p=>p.id===id);paragraph('上次暂停：'+state.actions.find(a=>a.id===packet.action_id)?.title+'；进展：'+(packet.progress||'未知'));
   button('从此暂停包继续',()=>openForm('resume_packet',r,{packet_id:id}));
   if(a)button('按当前计划继续，归档此包',()=>submit('archive_packet',r.id,r.version,{packet_id:id}));
  }
  if(old?.status==='executing'&&a)button('切换到当前计划（旧结果保持未知）',()=>openForm('switch_current',r));
  if(r.status!=='deferred')button('暂不决定',()=>submit('defer_recovery',r.id,r.version));
 }
 for(const e of state.evidence){
  paragraph('已保存执行证据，会话已结束。');paragraph(e.result==='completed'?'已确认全部完成。':e.result==='partial'?'已确认部分完成，行动没有被标为全部完成。':'已暂停并保存恢复包。');
  button('追加事实更正',()=>openForm('correct_fact',e));
 }
 for(const c of state.corrections||[])paragraph('更正：'+c.content+'；原因：'+c.reason);
 if(!session&&!starts.length&&!state.evidence.length)paragraph('当前没有可操作的开始入口；未来安排会按约定时间出现，过期结果保持未知。');
}
async function refresh(){
 try {
  const {status,result}=await request('/api/state');if(status!==200)throw new Error();
  state=result;document.querySelector('#connection').textContent='已连接智能体核心 · 状态已持久保存';
  const key=JSON.stringify([result.sessions,result.interventions,result.checkpoints,result.evidence,result.deliveries,result.recoveries,result.packets,result.corrections,result.foreground]);
  if(key!==signature){signature=key;render();}
  const notice=await request('/ui/notice');document.querySelector('#notice').textContent=notice.result?.message?notice.result.message:notice.result?.valid===false?'原通知上下文已失效，当前显示的是 Core 最新状态。':notice.result?.valid===true?'已从系统通知返回对应行动。':'';
 }catch(_){document.querySelector('#connection').textContent='智能体核心暂不可用，正在重新连接…';for(const b of content.querySelectorAll('button'))b.disabled=true;signature=null;}
}
refresh();setInterval(refresh,600);
