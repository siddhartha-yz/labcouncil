"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("labcouncil/static/app.js", "utf8");
function boot(storage = new Map(), fetch = async () => { throw new Error("offline"); }) {
  const nodes = new Map();
  const document = {
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, {textContent:"", className:"", addEventListener(){}, querySelector(){return null;}});
      return nodes.get(selector);
    },
    querySelectorAll(){return [];}, addEventListener(){}
  };
  const sessionStorage = {getItem:key=>storage.get(key) || null, setItem:(key,value)=>storage.set(key,value)};
  const context = vm.createContext({document, sessionStorage, fetch, location:{protocol:"file:"}, setTimeout(){},clearTimeout(){},setInterval(){},console, window:{addEventListener(){}}});
  vm.runInContext(source, context);
  // These are view adapters. The state and actual send function remain unchanged.
  vm.runInContext("setComposer=()=>{}; refreshProject=async()=>{}; updateTranscript=()=>{};", context);
  return {run:code=>vm.runInContext(code,context),storage};
}
test("drafts survive reload by group and clearing one leaves the other", () => {
  const ui=boot();
  ui.run('saveDraft("one","尚未发送"); saveDraft("two","另一个群");');
  const reloaded=boot(ui.storage);
  assert.equal(reloaded.run('questionDrafts.get("one")'),"尚未发送");
  assert.equal(reloaded.run('questionDrafts.get("two")'),"另一个群");
  reloaded.run('saveDraft("one", "");');
  const again=boot(ui.storage);
  assert.equal(again.run('questionDrafts.has("one")'),false);
  assert.equal(again.run('questionDrafts.get("two")'),"另一个群");
});
test("restoring an uncertain send never automatically calls the backend", () => {
  let calls=0;
  const storage=new Map([["labcouncil-pending",JSON.stringify([["one",{message:"原消息",message_id:"original-id",created:1}]])]]);
  const ui=boot(storage,async()=>{calls++;});
  assert.equal(calls,0);
  assert.equal(ui.run('pendingSends.get("one").message_id'),"original-id");
  assert.match(ui.run('pendingSends.get("one").error'),/刷新/);
});
test("failed sends are explicitly recovered with the same id and preserve the next draft", async () => {
  const bodies=[];
  const ui=boot(new Map(),async(path,options)=>{
    bodies.push(JSON.parse(options.body));
    if(bodies.length===1) throw new Error("connection reset");
    return {ok:true,json:async()=>({})};
  });
  ui.run('saveDraft("one","下一条草稿"); const original={message:"原消息",message_id:"same-message",created:1}; pendingSends.set("one",original);');
  await assert.rejects(ui.run('sendChat("one",original)'),/本机服务/);
  assert.equal(bodies.length,1);
  assert.equal(ui.run('pendingSends.get("one").message_id'),"same-message");
  assert.equal(ui.run('sending.size'),0);
  const reloaded=boot(ui.storage,async(path,options)=>{
    bodies.push(JSON.parse(options.body));return {ok:true,json:async()=>({})};
  });
  await reloaded.run('sendChat("one",pendingSends.get("one"))');
  assert.equal(bodies.length,2);
  assert.deepEqual(bodies[0],bodies[1]);
  assert.equal(reloaded.run('pendingSends.size'),0);
  assert.equal(reloaded.run('questionDrafts.get("one")'),"下一条草稿");
});
test("each group blocks its own duplicate request while other groups can send", async () => {
  const completions=[];
  const ui=boot(new Map(),()=>new Promise(resolve=>completions.push(()=>resolve({ok:true,json:async()=>({})}))));
  const first=ui.run('sendChat("one",{message:"first",message_id:"first-id"})');
  await ui.run('sendChat("one",{message:"duplicate",message_id:"different-id"})');
  const second=ui.run('sendChat("two",{message:"second",message_id:"second-id"})');
  assert.equal(completions.length,2);
  assert.equal(ui.run('sending.size'),2);
  completions.forEach(done=>done());
  await Promise.all([first,second]);
  assert.equal(ui.run('sending.size'),0);
});
test("a disconnected response recovered from saved records does not remain a send failure", async () => {
  const ui=boot();
  ui.run('currentProject="one"; projectData={}; refreshProject=async()=>{pendingSends.delete("one");savePending();};');
  await ui.run('sendChat("one",{message:"saved",message_id:"saved-id"})');
  assert.equal(ui.run('pendingSends.size'),0);
});
test("readable research reports link both result and operation evidence and retain limits", () => {
  const ui=boot();
  const html=ui.run('artifactDetails({id:"artifact-id",body:{kind:"research",summary:"有限结论",report:{findings:[{finding:"未独立验证",verification:"作者自述",evidence_refs:["operation:operation-id","prior-result"]}],limitations:["没有复现"],next_step:"先核对",evidence_refs:["prior-result"]}}},{})');
  assert.match(html,/\/api\/tool-operations\/operation-id/);
  assert.match(html,/\/api\/evidence\/prior-result/);
  assert.match(html,/没有复现/);
  assert.match(html,/先核对/);
});
test("an acknowledged message is not made uncertain by a subsequent display refresh failure", async () => {
  let calls=0;
  const ui=boot(new Map(),async()=>{calls++;return {ok:true,json:async()=>({})};});
  ui.run('currentProject="one"; saveDraft("one","下一句"); refreshProject=async()=>{throw new Error("display offline");}; pendingSends.set("one",{message:"saved",message_id:"saved-id"});');
  await ui.run('sendChat("one",pendingSends.get("one"))');
  assert.equal(calls,1);
  assert.equal(ui.run('pendingSends.size'),0);
  assert.equal(ui.run('questionDrafts.get("one")'),"下一句");
  assert.equal(ui.run('sending.size'),0);
});
test("proposal scope and explicit timing are visible without opening the full answer", () => {
  const ui=boot();
  const html=ui.run('proposalCard({id:"one",group_messages:[],group_proposal:{message_id:"proposal-original",reset_clock:false,brief:{idea:"核对已有数据 <script>",resources:"自己的五个数据点",work_time:{duration_minutes:30},permissions:{model_calls:false,public_research:true,local_compute:false,retry_public_reads:false}}}})');
  assert.match(html,/自己的五个数据点/);
  assert.match(html,/30 分钟，沿用原截止时间/);
  assert.match(html,/查公开论文与仓库/);
  assert.doesNotMatch(html,/运行已接入的合成计算/);
  assert.match(html,/data-approve-proposal="proposal-original"/);
  assert.match(html,/&lt;script&gt;/);
});
test("tool choice generates explicit grants and revocations without execution intent", () => {
  const ui=boot();
  const text=ui.run('toolMessage({elements:{namedItem:name=>({model_calls:{checked:true},public_research:{checked:false},local_compute:{checked:true},minutes:{value:"30"}}[name])}})');
  assert.match(text,/^本次工作条件：/);
  assert.match(text,/允许调用模型。/);
  assert.match(text,/禁止查询公开论文与仓库。/);
  assert.match(text,/允许本地计算。/);
  assert.match(text,/投入30分钟。/);
});
test("card approval keeps its original scope through an uncertain send and recovery", async () => {
  const bodies=[];
  const ui=boot(new Map(),async(path,options)=>{
    bodies.push(JSON.parse(options.body));
    if(bodies.length===1)throw new Error("reset");
    return {ok:true,json:async()=>({})};
  });
  ui.run('const approval={message:"按这个做",message_id:"approval-original",expected_proposal_id:"proposal-original",created:1};');
  await assert.rejects(ui.run('sendChat("one",approval)'));
  await ui.run('sendChat("one",pendingSends.get("one"))');
  assert.equal(bodies.length,2);
  assert.deepEqual(bodies[0],bodies[1]);
  assert.equal(bodies[1].expected_proposal_id,"proposal-original");
});
