// Linux browser checks for the embedded client; not Windows notification evidence.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtemp, readFile, rm, unlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

const root=resolve(fileURLToPath(new URL('../..',import.meta.url)));
const python=process.env.I01_TEST_PYTHON || 'python3';
// Use the runtime shipped by the locked Go module, never a substitute readiness script.
const moduleInfo=spawnSync(process.env.I01_TEST_GO || 'go',['list','-m','-json','github.com/wailsapp/wails/v3'],{cwd:join(root,'desktop')});
assert.equal(moduleInfo.status,0,moduleInfo.stderr.toString());
const runtimePath=join(JSON.parse(moduleInfo.stdout).Dir,'internal/assetserver/bundledassets/runtime.js');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function setup(t,missing=false,surface='main',fixtureArgs=[]){
 const directory=await mkdtemp(join(tmpdir(),'i01-ui-'));
 const data=join(directory,'data'),bootstrap=join(directory,'bootstrap.json');
 const seed=spawnSync(python,['-m','agent_core','seed','--data-dir',data,'--confirm-development-fixture','--start-delay','-1',...(missing?['--without-duration']:[]),...fixtureArgs],{cwd:root});
 assert.equal(seed.status,0,seed.stderr.toString());
 let core=spawn(python,['-m','agent_core','serve','--data-dir',data,'--bootstrap',bootstrap],{cwd:root,stdio:'ignore'});
 t.after(async()=>{core.kill();await rm(directory,{recursive:true,force:true});});
 let material;
 for(let i=0;i<100;i++){try{material=JSON.parse(await readFile(bootstrap));break;}catch{await delay(30);}}
 assert.ok(material);await unlink(bootstrap);
 let loseResponse=false,hidden=0;
 const server=createServer(async(req,res)=>{
  if(req.url==='/wails/runtime.js'){res.setHeader('Content-Type','application/javascript');res.end(await readFile(runtimePath));return;}
  if(req.url.startsWith('/api/')){
   const body=[];for await(const chunk of req)body.push(chunk);
   const upstream=await fetch(material.endpoint+req.url.replace('/api/','/v1/'),{method:req.method,headers:{Authorization:'Bearer '+material.token,Connection:'close'},body:req.method==='POST'?Buffer.concat(body):undefined});
   const text=await upstream.text();
   if(loseResponse && req.url==='/api/commands'){loseResponse=false;res.writeHead(503,{'Content-Type':'application/json'});res.end('{"error":"response_lost"}');return;}
   res.writeHead(upstream.status,{'Content-Type':'application/json'});res.end(text);return;
  }
  if(req.url==='/ui/notice'){res.setHeader('Content-Type','application/json');res.end('null');return;}
  if(req.url.startsWith('/ui/hide')){hidden++;res.writeHead(204);res.end();return;}
  const name=req.url.split('?')[0];const relative=name==='/'?'index.html':name.slice(1);
  if(!['index.html','app.js','style.css'].includes(relative)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',relative.endsWith('.js')?'text/javascript':relative.endsWith('.css')?'text/css':'text/html');
  res.end(await readFile(join(root,'desktop','frontend',relative)));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
 const browser=await chromium.launch({headless:true,executablePath:process.env.I01_BROWSER_EXECUTABLE});t.after(()=>browser.close());
 const page=await browser.newPage();
 // Only the native WebView2 message sink is replaced; the page must load the real runtime.
 await page.addInitScript(()=>{window.__hostMessages=[];window.chrome.webview={postMessage:message=>window.__hostMessages.push(message)};});
 await page.goto('http://127.0.0.1:'+server.address().port+'/?surface='+surface);
 const snapshot=async()=>await (await fetch(material.endpoint+'/v1/state',{headers:{Authorization:'Bearer '+material.token,Connection:'close'}})).json();
 const restart=async()=>{
  await new Promise(resolve=>{core.once('exit',resolve);core.kill();});
  core=spawn(python,['-m','agent_core','serve','--data-dir',data,'--bootstrap',bootstrap],{cwd:root,stdio:'ignore'});
  let next;for(let i=0;i<100;i++){try{next=JSON.parse(await readFile(bootstrap));break;}catch{await delay(30);}}
  assert.ok(next);material=next;await unlink(bootstrap);
 };
 return {page,snapshot,restart,lose:()=>{loseResponse=true;},hidden:()=>hidden};
}
async function visible(page,text){await page.getByText(text,{exact:false}).first().waitFor({timeout:5000});}

test('EX-02: opening/cancelling duration preserves state; native closure saves minimal evidence',async t=>{
 const {page,snapshot,hidden}=await setup(t,true);
 await page.getByRole('button',{name:'立即开始',exact:true}).click();
 assert.equal((await snapshot()).sessions.length,0);
 await page.getByRole('button',{name:'取消',exact:true}).click();
 assert.equal((await snapshot()).interventions[0].status,'pending');
 await page.getByRole('button',{name:'立即开始',exact:true}).click();
 await page.getByRole('spinbutton').fill('2');
 await page.getByRole('button',{name:'确认时长并开始'}).click();
 await visible(page,'执行会话已建立');
 let state=await snapshot();assert.equal(state.checkpoints[0].due_at-state.sessions[0].entered_at,120);
 await page.getByRole('button',{name:'已经完成',exact:true}).click();
 await visible(page,'正在等待收尾');
 assert.equal((await snapshot()).active_session.status,'awaiting_closure');
 await page.evaluate(()=>window.dispatchEvent(new Event('host-close')));
 await visible(page,'已保存执行证据');
 state=await snapshot();assert.equal(state.evidence[0].closure,'explicit_skip');assert.equal(state.active_session,null);
 assert.equal(hidden(),1);
});

test('AT-02: client retries the same command after a committed response is lost',async t=>{
 const {page,snapshot,lose}=await setup(t);
 await page.getByRole('button',{name:'立即开始',exact:true}).waitFor();lose();
 await page.getByRole('button',{name:'立即开始',exact:true}).click();
 await visible(page,'暂时无法确认保存结果');
 const before=await snapshot();assert.equal(before.sessions.length,1);
 await page.getByRole('button',{name:'重试同一次操作'}).click();
 await visible(page,'执行会话已建立');
 const after=await snapshot();assert.deepEqual(after.sessions,before.sessions);assert.equal(after.events.length,before.events.length);
 await page.getByRole('button',{name:'已经完成',exact:true}).click();
 await visible(page,'正在等待收尾');
 await page.getByRole('combobox').selectOption('partial');
 await page.getByRole('button',{name:'完成收尾',exact:true}).click();
 await visible(page,'已确认部分完成');
 assert.equal((await snapshot()).actions[0].status,'pending');
});

// ExecJS queues until Wails receives this readiness message. Directly dispatching
// host-close (as the older test did) bypasses that boundary and misses this defect.
for (const surface of ['main','overlay']) test(`embedded ${surface} loads Wails runtime before native close delivery`,async t=>{
 const {page,snapshot,hidden}=await setup(t,true,surface);
 await page.getByRole('button',{name:'立即开始',exact:true}).waitFor();
 await page.waitForFunction(()=>window.__hostMessages.includes('wails:runtime:ready'),{},{timeout:2000});
 const source=await readFile(join(root,'desktop/main_windows.go'),'utf8');
 const closeScript=source.match(/w\.ExecJS\("([^"\n]+)"\)/)[1];
 await page.getByRole('button',{name:'立即开始',exact:true}).click();
 await page.getByRole('button',{name:'确认时长并开始'}).click();
 await visible(page,'执行会话已建立');
 const before=await snapshot();
 await page.evaluate(closeScript);
 for(let i=0;i<50 && hidden()===0;i++)await delay(20);
 assert.equal(hidden(),1,'executing window close must hide the window');
 assert.deepEqual((await snapshot()).sessions,before.sessions);
 await page.getByRole('button',{name:'已经完成',exact:true}).click();
 await visible(page,'正在等待收尾');
 await page.evaluate(closeScript);
 await visible(page,'已保存执行证据');
 const after=await snapshot();
 assert.equal(hidden(),2,'closure must be saved before hiding');
 assert.equal(after.active_session,null);
 assert.equal(after.evidence.length,1);
 assert.equal(after.evidence[0].closure,'explicit_skip');
});

for (const surface of ['main','overlay']) test(`closure draft survives failed poll on ${surface}`,async t=>{
 const {page,snapshot}=await setup(t,false,surface);
 await page.getByRole('button',{name:'立即开始',exact:true}).click();
 await visible(page,'执行会话已建立');
 await page.getByRole('button',{name:'已经完成',exact:true}).click();
 await visible(page,'正在等待收尾');
 await page.getByRole('combobox').selectOption('partial');
 await page.getByRole('spinbutton').fill('12');
 const before=await snapshot();
 await page.route('**/api/state',route=>route.fulfill({status:503,body:'{}',contentType:'application/json'}));
 await visible(page,'智能体核心暂不可用');
 await page.unroute('**/api/state');
 await visible(page,'已连接智能体核心');
 assert.deepEqual((await snapshot()).sessions,before.sessions);
 assert.equal(await page.getByRole('combobox').inputValue(),'partial');
 assert.equal(await page.getByRole('spinbutton').inputValue(),'12');
 await page.getByRole('button',{name:'完成收尾',exact:true}).click();
 await visible(page,'已保存执行证据');
 const after=await snapshot();assert.equal(after.evidence[0].result,'partial');
 assert.equal(after.evidence[0].actual_duration_seconds,720);
});


test('I02 EX-03/04: already-started confirmation and retrospective completion',async t=>{
 const {page,snapshot}=await setup(t);
 await page.getByRole('button',{name:'我已经开始',exact:true}).click();
 assert.equal((await snapshot()).sessions.length,0);
 await page.getByRole('button',{name:'取消',exact:true}).click();
 await page.getByRole('button',{name:'我已经完成',exact:true}).click();
 await visible(page,'正在等待收尾');
 assert.equal((await snapshot()).checkpoints.length,0);
 await page.getByRole('button',{name:'跳过收尾',exact:true}).click();
 await visible(page,'已保存执行证据');assert.equal((await snapshot()).sessions[0].entry_source,'already_completed');
});

test('I02 EX-05/06: cancel reschedule then skip only this arrangement',async t=>{
 const {page,snapshot}=await setup(t);
 await page.getByRole('button',{name:'改到具体时间',exact:true}).click();
 const before=await snapshot();await page.getByRole('button',{name:'取消',exact:true}).click();
 assert.deepEqual((await snapshot()).arrangements,before.arrangements);
 await page.getByRole('button',{name:'今天不做',exact:true}).click();
 for(let i=0;i<100&&(await snapshot()).decisions.length===0;i++)await delay(20);
 const after=await snapshot();assert.equal(after.decisions.length,1);assert.equal(after.sessions.length,0);assert.equal(after.actions[0].status,'pending');
});

test('I02 SES-04/REC-05: native close after pause saves packet and resume creates linked session',async t=>{
 const {page,snapshot}=await setup(t);
 await page.getByRole('button',{name:'立即开始',exact:true}).click();await visible(page,'执行会话已建立');
 const old=(await snapshot()).active_session.id;
 await page.getByRole('button',{name:'暂停并保存恢复包',exact:true}).click();await visible(page,'正在等待收尾');
 await page.evaluate(()=>window.dispatchEvent(new Event('host-close')));await visible(page,'已暂停并保存恢复包');
 await page.getByRole('button',{name:'从此暂停包继续',exact:true}).click();
 await page.getByRole('button',{name:'确认时长并开始',exact:true}).click();await visible(page,'执行会话已建立');
 const after=await snapshot();assert.notEqual(after.active_session.id,old);assert.equal(after.packets[0].used_by,after.active_session.id);
});

test('I02 SES-01/07: continue keeps session and correction appends to evidence',async t=>{
 const {page,snapshot}=await setup(t,false,'main',['--duration','1']);
 await page.getByRole('button',{name:'立即开始',exact:true}).click();await visible(page,'约定的检查时间已到');
 const old=(await snapshot()).active_session.id;
 await page.getByRole('button',{name:'继续并确认下一检查时间',exact:true}).click();
 await page.getByRole('button',{name:'确认时长并开始',exact:true}).click();await visible(page,'执行会话已建立');
 assert.equal((await snapshot()).active_session.id,old);assert.equal((await snapshot()).checkpoints.length,2);
 await page.getByRole('button',{name:'已经完成',exact:true}).click();await visible(page,'正在等待收尾');
 await page.getByRole('button',{name:'跳过收尾',exact:true}).click();await visible(page,'已保存执行证据');
 const original=(await snapshot()).evidence;
 await page.getByRole('button',{name:'追加事实更正',exact:true}).click();
 await page.getByRole('combobox').selectOption('partial');
 await page.getByLabel('更正内容').fill('只完成第一段');await page.getByLabel('更正原因').fill('测试更正');
 await page.getByRole('button',{name:'保存更正',exact:true}).click();await visible(page,'更正：只完成第一段');
 assert.deepEqual((await snapshot()).evidence,original);assert.equal((await snapshot()).corrections.length,1);
});

test('I02 REC-10: restart reveals current plan and explicit switch keeps old result unknown',async t=>{
 const {page,snapshot,restart}=await setup(t,false,'main',['--second-delay','3','--second-version','Q']);
 await page.getByRole('button',{name:'立即开始',exact:true}).click();await visible(page,'执行会话已建立');
 const old=(await snapshot()).active_session.id;await delay(3100);await restart();
 await page.getByRole('button',{name:'切换到当前计划（旧结果保持未知）',exact:true}).click();
 await page.getByRole('button',{name:'确认时长并开始',exact:true}).click();
 for(let i=0;i<100&&(await snapshot()).active_session.id===old;i++)await delay(20);
 const after=await snapshot();assert.notEqual(after.active_session.id,old);assert.equal(after.active_session.plan_version,'Q');
 assert.equal(after.sessions.find(s=>s.id===old).exit_reason,'user_selected_switch');assert.equal(after.evidence.length,0);assert.equal(after.packets.length,0);
});

test('I02 EX-05: concrete reschedule creates successor and invalidates old surface',async t=>{
 const {page,snapshot}=await setup(t);
 await page.getByRole('button',{name:'改到具体时间',exact:true}).click();
 const value=await page.evaluate(()=>{const d=new Date(Date.now()+300000);d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,16);});
 await page.getByLabel('新的开始时间').fill(value);
 await page.getByRole('button',{name:'确认改期',exact:true}).click();
 for(let i=0;i<100&&(await snapshot()).arrangements.length===1;i++)await delay(20);
 const s=await snapshot();assert.equal(s.arrangements.length,2);assert.equal(s.arrangements.find(a=>a.id==='arrangement-a').status,'rescheduled');
 assert.equal(s.sessions.length,0);assert.equal(s.interventions[0].status,'resolved');
});

test('I02 DESK-05: defer recovery preserves passive entry without changing execution facts',async t=>{
 const {page,snapshot}=await setup(t);
 await page.getByRole('button',{name:'暂不决定',exact:true}).click();
 for(let i=0;i<100&&!(await snapshot()).recoveries.some(r=>r.status==='deferred');i++)await delay(20);
 await visible(page,'稍后处理上次上下文');
 const s=await snapshot();assert.equal(s.sessions.length,0);assert.equal(s.evidence.length,0);
 await page.locator('summary').filter({hasText:'上次执行'}).click();await page.locator('summary').filter({hasText:'当前计划'}).click();
 assert.equal(await page.locator('details[open]').count(),2);
});
