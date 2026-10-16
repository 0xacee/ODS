import assert from 'node:assert/strict';
import {test} from 'node:test';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createWorkspacePreviewInspectTool,normalizeWorkspacePreviewInspectionParams as normalize,validateWorkspacePreviewInspectionReceipt as validate,
  inspectionPlanHash,INSPECTION_KIND,INSPECTION_SCOPE,PRESS_INSPECTION_SCOPE,PRESS_KEYS,MAX_PRESS_HOLD_MS} from '../plugin/workspace-preview-inspect.mjs';
import {attemptedPreviewBehavior,boundPreviewBehavior,boundRenderedPreviewInspection,boundStaticPreviewInspection,previewBehaviorInstruction} from '../plugin/preview-interaction-assurance.mjs';

const preview={siteId:'site-'+'a'.repeat(24),sha256:'a'.repeat(64)};
const press=(key='Space',extra={})=>({action:'press',locator:{selector:'#game'},key,...extra});
const text=(expectedText,selector='#score')=>({action:'assert-text',locator:{selector},expectedText});
const click=selector=>({action:'click',locator:{selector}});
const params=(...steps)=>({...preview,viewport:{width:800,height:600},steps});
const state=extra=>({count:1,visible:true,display:'block',visibility:'visible',opacity:'1',hidden:false,hiddenUntilFound:false,rectCount:1,...extra});
function receipt(request) {
  return {schemaVersion:1,kind:INSPECTION_KIND,status:'passed',siteId:request.siteId,sha256:request.sha256,planSha256:inspectionPlanHash(request),viewport:request.viewport,
    steps:request.steps.map((s,index)=>({index,...s,stable:true,status:'passed',
      before:s.action==='assert-text'?state({text:{actual:s.expectedText,truncated:false}}):state(),
      ...(s.action==='press'?{focus:{element:true,document:true}}:{}),...(['press','click'].includes(s.action)?{after:state()}:{})})),
    diagnostics:{renderedHiddenAttributeCount:0,hiddenUntilFoundCount:0},blockedRequests:[],scope:INSPECTION_SCOPE+PRESS_INSPECTION_SCOPE};
}
// The receipt of a plan that stopped at its first press, which failed.
function failedPress(request,errorCode,{focus,blockedRequests=[]}={}) {
  const value=receipt(request);
  value.status='failed';value.blockedRequests=blockedRequests;
  const at=request.steps.findIndex(s=>s.action==='press');
  value.steps=value.steps.slice(0,at+1);
  Object.assign(value.steps[at],{status:'failed',errorCode});
  delete value.steps[at].after;
  if(focus) value.steps[at].focus=focus; else delete value.steps[at].focus;
  return value;
}
const execute=async(plan,result)=>createWorkspacePreviewInspectTool({request:async()=>result}).execute('press',plan);

// The capsule protocol in Python decides what the broker accepts and hashes.
function python(requests) {
  const script='import json,sys\nsys.path.insert(0,sys.argv[1])\nimport preview_inspection_protocol as p\n'+
    'out={"keys":list(p.PRESS_KEYS),"scope":p.PRESS_SCOPE,"base":p.SCOPE,"hold":p.PRESS_HOLD_MS,"max":p.MAX_PRESS_HOLD_MS,"requests":[]}\n'+
    'for r in json.load(sys.stdin):\n'+
    '    try: p.validate_request(r); out["requests"].append({"valid":True,"hash":p.plan_hash(r),"scope":p.inspection_scope(r)})\n'+
    '    except p.Invalid: out["requests"].append({"valid":False})\n'+
    'print(json.dumps(out))\n';
  const result=spawnSync(process.platform==='win32'?'python':'python3',['-c',script,fileURLToPath(new URL('../host',import.meta.url))],
    {input:JSON.stringify(requests),encoding:'utf8',windowsHide:true});
  assert.equal(result.status,0,result.stderr);
  return JSON.parse(result.stdout);
}

test('press accepts exactly one allowlisted key and a bounded hold',()=>{
  assert.equal(PRESS_KEYS.length,44);
  for(const key of PRESS_KEYS) normalize(params(press(key)));
  for(const holdMs of [0,100,MAX_PRESS_HOLD_MS]) assert.equal(normalize(params(press('Space',{holdMs}))).steps[0].holdMs,holdMs);
  assert.equal(Object.hasOwn(normalize(params(press())).steps[0],'holdMs'),false,'the default hold is not written into the plan');
  for(const key of ['Control+a','Meta','Shift','F5','hello','A','KeyA','Digit1','space','ArrowRight+Space',' ','','\n',1,null,['a']]) {
    assert.throws(()=>normalize(params(press(key))),error=>error.inputHints?.[0]?.includes('steps[0].key'),JSON.stringify(key));
  }
  for(const holdMs of [-1,MAX_PRESS_HOLD_MS+1,1.5,true,'100',null,undefined,NaN,Infinity]) {
    assert.throws(()=>normalize(params(press('Space',{holdMs}))),error=>error.inputHints?.[0]?.includes('steps[0].holdMs'),String(holdMs));
  }
  const missing=press();delete missing.key;
  for(const step of [missing,press('a',{value:'a'}),press('a',{expectedText:'a'}),press('a',{modifiers:['Shift']}),
    {...click('#game'),key:'a'},{action:'assert-visible',locator:{selector:'#game'},holdMs:100}]) {
    assert.throws(()=>normalize(params(step)),undefined,JSON.stringify(step));
  }
});

test('the plugin mirrors the Python key list, scope, validation and plan hash',()=>{
  const samples=[params(press()),params(press('ArrowRight',{holdMs:0}),text('1')),params(press('z',{holdMs:1000})),
    params(press('Control+a')),params(press('A')),params(press('Space',{holdMs:1001})),params(press('Space',{holdMs:true})),
    params({...click('#game'),key:'a'})];
  const requests=samples.map(sample=>({schemaVersion:1,action:'inspect',...sample}));
  const py=python(requests);
  assert.deepEqual(py.keys,[...PRESS_KEYS]);
  assert.equal(py.scope,PRESS_INSPECTION_SCOPE);
  assert.equal(py.base,INSPECTION_SCOPE);
  assert.equal(py.hold,100);
  assert.equal(py.max,MAX_PRESS_HOLD_MS);
  samples.forEach((sample,i)=>{
    let request;
    try { request=normalize(sample); } catch { request=undefined; }
    assert.equal(py.requests[i].valid,request!==undefined,JSON.stringify(sample));
    if(request) {
      assert.equal(py.requests[i].hash,inspectionPlanHash(request));
      assert.equal(py.requests[i].scope,validate(receipt(request),request).scope);
    }
  });
});

test('the schema states keys as an enum and bounds the hold, so local grammars stay simple',()=>{
  const {parameters,description}=createWorkspacePreviewInspectTool({request:async()=>{}});
  const step=parameters.properties.steps.items.properties;
  assert.ok(step.action.enum.includes('press'));
  assert.deepEqual(step.key.enum,[...PRESS_KEYS]);
  assert.equal(step.key.pattern,undefined);
  assert.deepEqual([step.holdMs.type,step.holdMs.minimum,step.holdMs.maximum],['integer',0,MAX_PRESS_HOLD_MS]);
  assert.doesNotMatch(description,/does not simulate keystrokes/);
  assert.match(description,/use press with key/);
  assert.match(description,/Press refuses text fields; use fill for those\./);
});

test('a press receipt binds key, hold, focus and the after observation',()=>{
  const request=normalize(params(text('0'),press('ArrowRight'),text('1'))),good=receipt(request);
  assert.equal(validate(good,request),good);
  const unfocusable=structuredClone(good);unfocusable.steps[1].focus.element=false;
  assert.equal(validate(unfocusable,request).status,'passed','a canvas without tabindex leaves the body focused');
  for(const change of [r=>delete r.steps[1].after,r=>delete r.steps[1].focus,r=>r.steps[1].focus.document=false,
    r=>r.steps[1].focus.element='true',r=>r.steps[1].focus.active=false,r=>r.steps[1].key='Enter',r=>r.steps[1].holdMs=100,
    r=>r.steps[1].before.visible=false,r=>r.steps[1].stable=false,r=>r.steps[0].focus={element:true,document:true},
    r=>r.scope=INSPECTION_SCOPE,
    r=>r.scope='Only the listed CSS layout visibility assertions and click dispatches were tested; not pixel paint, occlusion, clipping, a full accessibility audit, or overall functionality.']) {
    const bad=structuredClone(good);change(bad);assert.throws(()=>validate(bad,request),undefined,change.toString());
  }
  const held=normalize(params(press('Space',{holdMs:400}),text('1'))),heldReceipt=receipt(held);
  assert.equal(validate(heldReceipt,held),heldReceipt);
  for(const change of [r=>r.steps[0].holdMs=300,r=>delete r.steps[0].holdMs]) {
    const bad=structuredClone(heldReceipt);change(bad);assert.throws(()=>validate(bad,held));
  }
});

test('a legacy-scope receipt never satisfies a press plan, even one without text assertions',()=>{
  const request=normalize(params(press(),{action:'assert-visible',locator:{selector:'#game'}}));
  const legacy={...receipt(request),scope:'Only the listed CSS layout visibility assertions and click dispatches were tested; not pixel paint, occlusion, clipping, a full accessibility audit, or overall functionality.'};
  assert.throws(()=>validate(legacy,request),/invalid inspection binding/);
});

test('press failures are bound evidence with actionable feedback',async()=>{
  const plan=params(press('a'),text('1')),request=normalize(plan);
  const refused=failedPress(request,'text_field_press_unsupported');
  assert.equal(validate(refused,request),refused);
  let output=await execute(plan,refused);
  assert.equal(output.isError,true);
  assert.match(output.content[0].text,/editable field, or focus moved to one, so no key was sent/);
  assert.match(output.content[0].text,/use fill for native text and number fields/);
  const redirected=failedPress(request,'text_field_press_unsupported',{focus:{element:false,document:true}});
  assert.equal(validate(redirected,request),redirected);

  const unfocused=failedPress(request,'focus_failed',{focus:{element:false,document:false}});
  assert.equal(validate(unfocused,request),unfocused);
  output=await execute(plan,unfocused);
  assert.match(output.content[0].text,/could not give the preview document keyboard focus/);
  assert.match(output.content[0].text,/same published snapshot/);
  for(const forged of [failedPress(request,'focus_failed'),failedPress(request,'focus_failed',{focus:{element:true,document:true}})])
    assert.throws(()=>validate(forged,request),/invalid press evidence/);

  const failed=failedPress(request,'press_failed',{focus:{element:true,document:true}});
  assert.equal(validate(failed,request),failed);
  output=await execute(plan,failed);
  assert.match(output.content[0].text,/Step 1 \(press\) did not complete/);
  assert.match(output.content[0].text,/Keyboard behavior remains unverified/);

  const navigated=failedPress(request,'press_failed',{focus:{element:true,document:true},blockedRequests:['navigation']});
  assert.equal(validate(navigated,request),navigated);
  assert.match((await execute(plan,navigated)).content[0].text,/inspection guard blocked a page operation/);

  const download=failedPress(request,'unexpected_download',{focus:{element:true,document:true},blockedRequests:['download']});
  assert.equal(validate(download,request),download);
  assert.match((await execute(plan,download)).content[0].text,/blocked an unexpected download attempt/);
  assert.throws(()=>validate({...download,blockedRequests:[]},request),/invalid blocked download evidence/);

  const clickPlan=normalize(params(click('#go'),text('1'))),clickReceipt=receipt(clickPlan);
  clickReceipt.status='failed';clickReceipt.steps=[{...clickReceipt.steps[0],status:'failed',errorCode:'press_failed'}];
  delete clickReceipt.steps[0].after;
  clickReceipt.scope=INSPECTION_SCOPE;
  assert.throws(()=>validate(clickReceipt,clickPlan),/invalid press evidence/);
});

test('an image without press support asks for an inspector update, not a site change',async()=>{
  const plan=params(press(),text('1')),request=normalize(plan);
  const result={schemaVersion:1,kind:INSPECTION_KIND,status:'failed',errorCode:'unsupported_capability',siteId:request.siteId,
    sha256:request.sha256,planSha256:inspectionPlanHash(request),scope:INSPECTION_SCOPE+PRESS_INSPECTION_SCOPE};
  const output=await execute(plan,result);
  assert.equal(output.isError,true);
  assert.match(output.content[0].text,/does not support trusted key presses/);
  assert.match(output.content[0].text,/Update the ODS inspector and its capsule together/);
});

test('passing press plans get key-press feedback, not show/hide coaching',async()=>{
  let plan=params(text('0'),press('Space'),press('ArrowRight'),text('1'));
  let output=await execute(plan,receipt(normalize(plan)));
  assert.equal(output.isError,undefined);
  assert.match(output.content[0].text,/trusted keyboard events to the focused preview page/);
  assert.match(output.content[0].text,/A key press alone proves no result/);
  assert.doesNotMatch(output.content[0].text,/This plan contains no click/);
  assert.ok(output.content[0].text.includes(PRESS_INSPECTION_SCOPE));
  plan=params(text('0'),press('Space'));
  output=await execute(plan,receipt(normalize(plan)));
  assert.match(output.content[0].text,/No assertion follows the last press, so no keyboard result was checked/);
});

test('a missing assertion target after a key press is not blamed on the locator alone',async()=>{
  const plan=params(press('Space'),text('1')),request=normalize(plan),value=receipt(request);
  value.status='failed';value.steps[1]={index:1,...request.steps[1],before:{count:0},stable:true,status:'failed',errorCode:'no_match'};
  const output=await execute(plan,value);
  assert.match(output.content[0].text,/An earlier key press passed, but the requested result remains unverified/);
});

test('evidence policy: presses are behavior, may chain, and the last one needs a postcondition',()=>{
  assert.deepEqual(attemptedPreviewBehavior(params(press()),preview),{requiresInteraction:true});
  const bound=plan=>boundPreviewBehavior(plan,{details:receipt(normalize(plan))},preview,{requiresInteraction:true});
  for(const plan of [params(press(),text('1')),params(text('0'),press('Space'),press('ArrowRight'),text('1')),
    params(press('Space'),click('#pause'),text('Paused'))]) assert.ok(bound(plan),JSON.stringify(plan.steps));
  for(const plan of [params(press()),params(text('0'),press()),params(press(),text('1'),press()),
    params(click('#start'),press(),text('1'))]) assert.equal(bound(plan),undefined,JSON.stringify(plan.steps));
  const plan=params(press(),text('1')),result={details:receipt(normalize(plan))};
  assert.equal(boundStaticPreviewInspection(plan,result,preview),undefined,'a press plan is not read-only');
  assert.ok(boundRenderedPreviewInspection(plan,result,preview));
  assert.match(previewBehaviorInstruction(preview),/Key presses \(press\) may run in a row, but the last one needs a postcondition\./);
});
