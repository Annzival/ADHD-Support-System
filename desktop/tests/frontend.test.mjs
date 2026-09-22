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
async function setup(t,missing=false,surface='main'){
 const directory=await mkdtemp(join(tmpdir(),'i01-ui-'));
 const data=join(directory,'data'),bootstrap=join(directory,'bootstrap.json');
 const seed=spawnSync(python,['-m','agent_core','seed','--data-dir',data,'--confirm-development-fixture','--start-delay','-1',...(missing?['--without-duration']:[])],{cwd:root});
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
   const upstream=await fetch(material.endpoint+req.url.replace('/api/','/v1/'),{method:req.method,headers:{Authorization:'Bearer '+material.token},body:req.method==='POST'?Buffer.concat(body):undefined});
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
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
 const browser=await chromium.launch({headless:true,executablePath:process.env.I01_BROWSER_EXECUTABLE});t.after(()=>browser.close());
 const page=await browser.newPage();
 // Only the native WebView2 message sink is replaced; the page must load the real runtime.
 await page.addInitScript(()=>{window.__hostMessages=[];window.chrome.webview={postMessage:message=>window.__hostMessages.push(message)};});
 await page.goto('http://127.0.0.1:'+server.address().port+'/?surface='+surface);
 const snapshot=async()=>await (await fetch(material.endpoint+'/v1/state',{headers:{Authorization:'Bearer '+material.token}})).json();
 return {page,snapshot,lose:()=>{loseResponse=true;},hidden:()=>hidden};
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
