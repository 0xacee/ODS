import test from 'node:test';
import assert from 'node:assert/strict';
import {createRunProgressBudget, failedToolOutcome, isLiteralEcho, lookupFoundNothing, RUN_PROGRESS_LIMITS} from '../plugin/run-progress-budget.mjs';

test('only a single lookup that completed with exit 1 and no output found nothing', () => {
  const receipt = (exitCode, text = '', details = {}) => ({content:[{type:'text', text:`${text}\n\n(Command exited with code ${exitCode})`}],
    details:{status:'completed', exitCode, durationMs:3, ...details}});
  const empty = receipt(1);
  for (const command of [
    'grep -n "function drawEnemyEnt" -A 12 chars.js',
    'cd Playground/elf-of-doom && grep -n "function drawEnemyEnt" -A 12 chars.js',
    "cd 'Playground/elf of doom' && grep -rn 'hitSet|fromEnemy' *.js",
    'grep -rn "a\\|b" .', 'egrep -n "x" f', 'fgrep -n x f', 'rg -n "x" src', 'git grep -n "x"', 'which node nodejs deno bun',
    '  grep -n x f  ',
  ]) assert.equal(lookupFoundNothing(command, empty), true, command);
  for (const command of [
    'grep -n x f | head', 'cat f | grep x', 'grep x f; echo $?', 'grep x f || true', 'grep x f && echo y',
    'grep x f > out', 'grep x f 2>/dev/null', 'grep x $(ls)', 'grep x `ls`', 'grep x f\nrm f', 'grep x f &',
    'cd a && cd b && grep x f', 'echo grep x', 'grepx -n f', 'sh -c "grep x f"', 'find . -name x', 'test -f x',
    'diff a b', 'command -v node', 'python3 -c "print(1)"', 'grep "unclosed', 'grep x\\ y f', '', 42, undefined,
  ]) assert.equal(lookupFoundNothing(command, empty), false, String(command));
  const search = 'grep -n x f';
  for (const result of [
    receipt(0), receipt(2), receipt(127), receipt(128), receipt(1, 'f:1: x'), receipt(1, 'grep: f: No such file or directory'),
    receipt(1, '', {status:'running'}), receipt(1, '', {status:'failed'}), receipt(1, '', {sessionId:'s-1'}),
    {content:[{type:'text', text:''}], details:{status:'completed', exitCode:1.5}},
    {content:[{type:'text', text:''}], details:{status:'completed'}}, {details:{status:'completed', exitCode:1, aggregated:'x'}},
    undefined, null, {},
  ]) assert.equal(lookupFoundNothing(search, result), false, JSON.stringify(result));
  assert.equal(lookupFoundNothing(search, {details:{status:'completed', exitCode:1, aggregated:''}}), true);
  assert.equal(lookupFoundNothing('grep '.padEnd(4100, 'x'), empty), false);
});

test('outer and nested failure receipts do not masquerade as successful progress', () => {
  for (const event of [{error:'unavailable'}, {result:{isError:true}},
    {result:{details:{exitCode:1}}}, {result:{details:{status:'blocked'}}},
    {result:{details:{result:{isError:true}}}}]) assert.equal(failedToolOutcome(event), true);
  assert.equal(failedToolOutcome({result:{content:[{type:'text',text:'Example error: failed'}],details:{exitCode:0}}}), false);
});

test('consecutive malformed calls trip a sticky run-wide fuse', () => {
  const budget = createRunProgressBudget();
  for (let i = 0; i < 4; i++) {
    budget.beginModelRound();
    budget.observeResult({callId: `call-${i}`, tool:'tool_call', failed:true});
    assert.equal(budget.exhausted, i === 3);
  }
  budget.observeResult({callId:'recovery', tool:'read', params:{path:'file'}, failed:false});
  assert.equal(budget.exhausted, true);
});

test('alternating discovery and failures cannot reset consecutive failure allowance', () => {
  const budget = createRunProgressBudget();
  for (let i = 0; i < 4; i++) {
    budget.observeResult({callId:`search-${i}`, tool:'tool_search', params:{query:String(i)}, failed:false});
    budget.observeResult({callId:`bad-${i}`, tool:'tool_call', failed:true});
    assert.equal(budget.exhausted, i === 3);
  }
  assert.equal(budget.exhausted, true);
});

test('discovery-only rounds are bounded even with distinct successful searches', () => {
  const budget = createRunProgressBudget();
  for (let i = 0; i < 8; i++) {
    assert.equal(budget.beginModelRound(), false);
    budget.observeResult({callId:`discover-${i}`, tool:i % 2 ? 'tool_describe' : 'tool_search',
      params:{query:String(i)}, failed:false});
  }
  assert.equal(budget.beginModelRound(), true);
});

test('missing tool hooks are bounded at model continuation level', () => {
  const budget = createRunProgressBudget();
  for (let i = 0; i < 8; i++) assert.equal(budget.beginModelRound(), false);
  assert.equal(budget.beginModelRound(), true);
});

test('genuine progress permits long tasks; repeated success is not endless progress', () => {
  const budget = createRunProgressBudget();
  for (let i = 0; i < 100; i++) {
    assert.equal(budget.beginModelRound(), false);
    budget.observeResult({callId:`read-${i}`, tool:'read', params:{path:`file-${i}`}, failed:false});
  }
  for (let i = 0; i < 12; i++) {
    budget.beginModelRound();
    budget.observeResult({callId:`echo-${i}`, tool:'exec', params:{command:'echo done'}, failed:false});
  }
  assert.equal(budget.exhausted, true);
});

test('after-tool and persist delivery of one failure count only once', () => {
  const budget = createRunProgressBudget();
  for (let i = 0; i < 30; i++) budget.observeResult({callId:'same', failed:true});
  assert.equal(budget.exhausted, false);
  for (let i = 0; i < 3; i++) budget.observeResult({callId:`next-${i}`, failed:true});
  assert.equal(budget.exhausted, true);
});

test('caller-classified metadata cannot reset failures or count as task progress', () => {
  const budget=createRunProgressBudget();
  for(let i=0;i<4;i++) {
    budget.observeResult({callId:`failure-${i}`,tool:'exec',failed:true});
    budget.observeResult({callId:`metadata-${i}`,tool:'tool_call',failed:false,discovery:true});
    assert.equal(budget.exhausted,i===3);
  }
  const failedMetadata=createRunProgressBudget();
  for(let i=0;i<4;i++) failedMetadata.observeResult({callId:`metadata-${i}`,tool:'tool_call',failed:true,discovery:true});
  assert.equal(failedMetadata.exhausted,true,'metadata errors still count');
});

test('mixed failure streaks suspend only their lane and remain sticky after sibling progress', () => {
  const budget=createRunProgressBudget();
  for(let i=0;i<4;i++) {
    budget.observeResult({callId:`extension-${i}`,tool:'prepare',lane:'extension',failed:true});
    budget.observeResult({callId:`metadata-${i}`,tool:'status',lane:'extension',discovery:true,failed:false});
    budget.observeResult({callId:`workspace-${i}`,tool:'write',params:{path:`file-${i}`},lane:'workspace',failed:false});
  }
  assert.equal(budget.exhausted,false);
  assert.deepEqual(budget.exhaustedLanes,['extension']);
  budget.observeResult({callId:'late-success',tool:'prepare',lane:'extension',failed:false});
  assert.equal(budget.laneExhausted('extension'),true);
  assert.equal(budget.laneExhausted('workspace'),false);
});

test('mixed lanes retain global total and no-progress ceilings', () => {
  const total=createRunProgressBudget();
  for(let i=0;i<12;i++) {
    total.observeResult({callId:`failure-${i}`,lane:'extension',failed:true});
    assert.equal(total.exhausted,i===11);
  }
  const rounds=createRunProgressBudget();
  for(let i=0;i<8;i++) {
    assert.equal(rounds.beginModelRound(),false);
    rounds.observeResult({callId:`metadata-${i}`,lane:'extension',tool:'status',discovery:true,failed:false});
  }
  assert.equal(rounds.beginModelRound(),true);
});

test('unclassified failures and two exhausted lanes still stop the full run', () => {
  for(const lane of [undefined,'model-supplied-fake-lane']) {
    const budget=createRunProgressBudget();
    for(let i=0;i<4;i++) budget.observeResult({callId:`unknown-${i}`,lane,failed:true});
    assert.equal(budget.exhausted,true);
  }
  const both=createRunProgressBudget();
  for(const lane of ['extension','workspace']) for(let i=0;i<4;i++) {
    both.observeResult({callId:`${lane}-${i}`,lane,failed:true});
    both.observeResult({callId:`${lane}-${i}`,failed:true});
  }
  assert.deepEqual(both.exhaustedLanes,['extension','workspace']);
  assert.equal(both.exhausted,true);
});

test('an external stop is sticky and changes no limit', () => {
  const budget = createRunProgressBudget();
  budget.stop();
  assert.equal(budget.exhausted, true);
  budget.observeResult({callId: 'later', tool: 'read', params: {path: 'x'}, failed: false});
  assert.equal(budget.exhausted, true);
  assert.deepEqual(RUN_PROGRESS_LIMITS, {consecutiveFailures: 4, totalFailures: 12, roundsWithoutProgress: 8, identicalSuccesses: 2});
});

test('verified pending process receipts do not exhaust progress rounds', () => {
  const budget = createRunProgressBudget();
  for (let i = 0; i < 100; i++) {
    assert.equal(budget.beginModelRound(), false);
    budget.observeResult({callId:`poll-${i}`, tool:'process', pending:true, failed:false});
  }
});

test('read-only echo classification excludes substitutions, redirections and compound commands', () => {
  for (const command of ['echo "Done!"', "echo 'Site ready'", "echo 'literal $HOME' "]) assert.equal(isLiteralEcho(command), true, command);
  for (const command of ['echo "$HOME"', 'echo "$(touch bad)"', 'echo "`touch bad`"', 'echo "ok" > index.html', 'echo "ok"; rm file', 'echo "ok" && run', 'echo "a\\"', undefined]) assert.equal(isLiteralEcho(command), false, command);
});
