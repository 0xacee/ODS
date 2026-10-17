// RTX Spark, Elf of Doom round 9 (Qwen3.8-Flash-Next): the owner said one
// solid colour covers the arena at the end of every frame. The agent found the
// cause (ui.js:748 assigns a canvas to fillStyle, so the last colour fills the
// viewport), showed that its preview check cannot see canvas pixels, and wrote
// the owner that explanation. Its press + assert-painted check had failed, so
// Portal replaced the whole reply with its host delivery and the explanation
// never reached the owner. A failed preview outcome now keeps the agent's
// final prose and appends the unchanged host facts after it.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {createToolLoopGuard} from '../plugin/tool-loop-guard.mjs';
import {createIngressServer} from '../host/pixel_ingress.mjs';
import {PREVIEW_INSPECTION_TOOL} from '../plugin/preview-interaction-assurance.mjs';
import {INSPECTION_KIND, PAINT_INSPECTION_SCOPE, PRESS_INSPECTION_SCOPE, STEP_INSPECTION_SCOPE, createWorkspacePreviewInspectTool,
  inspectionPlanHash} from '../plugin/workspace-preview-inspect.mjs';
import {PREVIEW_CHECK_LABEL, PREVIEW_CLAIM_NOTE, claimsVerifiedSuccess, explainedPreviewDelivery}
  from '../plugin/preview-explanation.mjs';

const runId = 'chatcmpl_7e1f0d2c-4b8a-4c3e-9d5f-0a1b2c3d4e5f';
const context = {agentId: 'pixel', runId, sessionId: 'elf-session', sessionKey: 'elf-key'};
const OWNER = 'Still the same: when I start a realm the whole arena is just one flat colour. Fix it in elf-of-doom, ' +
  "then pull up a fresh preview and actually look at it before you say it's fixed.";
const GAME = '<!doctype html><title>Elf of Doom</title><canvas id="arena" width="960" height="540"></canvas><script src="ui.js"></script>';
// The agent's root-cause reply (paraphrased from the round 9 transcript).
const EXPLANATION = 'Your observation is exactly the diagnostic I needed. The cause is `ui.js:748`: ' +
  '`g.fillStyle = vignetteSprite(); g.fillRect(0, 0, W, H);` runs after the world is drawn. `vignetteSprite()` returns a canvas, ' +
  'and a canvas is not a valid `fillStyle`, so the previous colour stays set and that last full-viewport fill covers the arena: ' +
  'the health-bar green when orcs are on screen, the floor colour otherwise.\n\n' +
  'My preview check reported the same single colour even with the canvas fully blanked, so my tool cannot see canvas pixels at all. ' +
  'Let me use your eyes instead: the fix is to draw the vignette with `drawImage` or drop that fill. I have not changed line 748 yet.';
const FALSE_CLAIM = 'Fixed! The arena renders again and every check passed.';
const SCOPE = 'Publication scope: this receipt verifies the published snapshot, not functional behavior or completion of other requested work.';
const PLAN = {viewport: {width: 1280, height: 800}, steps: [
  {action: 'press', locator: {selector: '#arena'}, key: 'Space'},
  {action: 'assert-painted', locator: {selector: '#arena'}},
]};

const shown = {count: 1, visible: true, display: 'block', visibility: 'visible', opacity: '1', hidden: false, hiddenUntilFound: false, rectCount: 1};
function receipt(params, {painted}) {
  const paint = painted
    ? {width: 256, height: 144, distinctColors: 212, dominant: {hex: '#1b2a1f', percent: 41},
      colors: [{name: 'dark gray', hex: '#1b2a1f', percent: 41}, {name: 'green', hex: '#3f7a2c', percent: 22}], fingerprint: '0f1e2d3c4b5a6978'}
    : {width: 256, height: 144, distinctColors: 1, dominant: {hex: '#8fce3a', percent: 100},
      colors: [{name: 'green', hex: '#8fce3a', percent: 100}], fingerprint: '8fce3a8fce3a8fce'};
  return request => ({schemaVersion: 1, kind: INSPECTION_KIND, status: painted ? 'passed' : 'failed',
    siteId: params.siteId, sha256: params.sha256, planSha256: inspectionPlanHash(request), viewport: params.viewport,
    steps: [
      {index: 0, action: 'press', locator: {selector: '#arena'}, key: 'Space', before: shown, after: shown,
        focus: {element: false, document: true}, stable: true, status: 'passed'},
      {index: 1, action: 'assert-painted', locator: {selector: '#arena'}, before: shown, stable: true,
        status: painted ? 'passed' : 'failed', ...(painted ? {} : {errorCode: 'uniform_paint'}), paint},
    ],
    diagnostics: {renderedHiddenAttributeCount: 0, hiddenUntilFoundCount: 0}, blockedRequests: [],
    scope: STEP_INSPECTION_SCOPE + PRESS_INSPECTION_SCOPE + PAINT_INSPECTION_SCOPE});
}

// One Elf of Doom turn through the real guard: write, publish, then the
// press + assert-painted check (failed: one colour; or painted), and the
// agent's final reply at finalization when `reply` is a string.
async function elfTurn({reply, painted = false, before, after} = {}) {
  const guard = createToolLoopGuard({workspacePreviewInspectionAvailable: true});
  guard.observeRun(context, 'pixel', {prompt: OWNER});
  let sequence = 0;
  const invoke = (toolName, params, result) => {
    const ctx = {...context, toolName, toolCallId: `call-${sequence++}`};
    const prepared = guard.beforeToolCall({toolName, runId, toolCallId: ctx.toolCallId, params}, ctx);
    assert.notEqual(prepared?.block, true, prepared?.blockReason);
    const actual = prepared?.params ?? params;
    if (result) guard.afterToolCall({toolName, runId, toolCallId: ctx.toolCallId, params: actual, result}, ctx);
    return actual;
  };
  before?.({guard, invoke});
  const written = invoke('write', {path: 'elf-of-doom/index.html', content: GAME},
    {content: [{type: 'text', text: 'Successfully wrote file.'}]});
  const relativeDirectory = written.path.slice(0, -'/index.html'.length);
  const sha256 = createHash('sha256').update(relativeDirectory + GAME).digest('hex'), siteId = `site-${sha256.slice(0, 24)}`;
  const preview = {schemaVersion: 1, kind: 'ods-pixel-workspace-preview', status: 'succeeded', relativeDirectory, siteId, sha256,
    entryFile: 'index.html', entrySha256: createHash('sha256').update(GAME).digest('hex'), files: 2, bytes: 4096, port: 9437,
    url: `http://${siteId}.localhost:9437/${siteId}/`, httpStatus: 200, readbackVerified: true, executable: false, overwritten: false};
  invoke('pixel_ods_workspace_preview', {relativeDirectory}, {details: preview});
  const params = {siteId, sha256, ...structuredClone(PLAN)};
  const capsule = receipt(params, {painted});
  const tool = createWorkspacePreviewInspectTool({request: async request => capsule(request)});
  const prepared = invoke(PREVIEW_INSPECTION_TOOL, params);
  const ctx = {...context, toolName: PREVIEW_INSPECTION_TOOL, toolCallId: `call-${sequence - 1}`};
  const result = await tool.execute(ctx.toolCallId, prepared);
  guard.afterToolCall({toolName: PREVIEW_INSPECTION_TOOL, runId, toolCallId: ctx.toolCallId, params: prepared, result,
    ...(result.isError ? {error: result.content[0].text} : {})}, ctx);
  after?.({guard, invoke, preview});
  if (typeof reply === 'string') guard.beforeAgentFinalize({lastAssistantMessage: reply}, context);
  return {guard, preview, inspection: result, delivery: guard.deliveryVerificationForRun(runId)};
}

test('Elf of Doom: the failed paint check is the real uniform-colour receipt', async () => {
  const {inspection, delivery} = await elfTurn();
  assert.equal(inspection.isError, true);
  assert.equal(inspection.details.status, 'failed');
  assert.match(inspection.content[0].text, /captured one color only \(#8fce3a\)/);
  assert.equal(delivery.status, 'failed');
  assert.match(delivery.text, /^The attempted preview interaction checks have not passed browser inspection\./m);
});

test('Elf of Doom: the agent explanation reaches the owner, followed by the unchanged host facts', async () => {
  const plain = await elfTurn({reply: ''});
  const {guard, preview, delivery} = await elfTurn({reply: EXPLANATION});
  assert.equal(delivery.status, 'failed', 'keeping the prose never certifies the preview');
  assert.deepEqual(delivery.preview, plain.delivery.preview);
  assert.equal(delivery.text, `${EXPLANATION}\n\n${PREVIEW_CHECK_LABEL} ${plain.delivery.text}`);
  assert.doesNotMatch(delivery.text, new RegExp(PREVIEW_CLAIM_NOTE.slice(0, 30)), 'an honest diagnosis is not contradicted');
  assert.match(delivery.text, /attempted preview interaction checks have not passed browser inspection/);
  assert.ok(delivery.text.endsWith(`Your preview is ready.\n\n[Open preview](${preview.url})\n\nPublished from your workspace.`));
  assert.equal(Object.keys(delivery).sort().join(), Object.keys(plain.delivery).sort().join(), 'the ingress schema is unchanged');
  // Channel delivery sends the same text in place of the model's reply.
  assert.equal(guard.replyPayloadSending({runId, kind: 'final', payload: {text: EXPLANATION}}).payload.text, delivery.text);
});

for (const stream of [false, true]) test(`Elf of Doom: Portal ingress delivers the kept explanation (stream=${stream})`, {timeout: 10000}, async () => {
  const {delivery} = await elfTurn({reply: EXPLANATION});
  const gateway = createServer((request, response) => {
    request.resume();
    request.on('end', () => {
      response.writeHead(200, {'Content-Type': 'application/json'});
      response.end(JSON.stringify(request.url === '/pixel-ods/subagent-delivery'
        ? {schemaVersion: 1, kind: 'ods-subagent-delivery', runId, status: 'not-delegated'}
        : request.url === '/pixel-ods/verification' ? delivery
          : {id: runId, choices: [{index: 0, message: {role: 'assistant', content: EXPLANATION}, finish_reason: 'stop'}]}));
    });
  });
  const listen = server => new Promise((resolve, reject) => {
    server.once('error', reject); server.listen(0, '127.0.0.1', () => resolve(server.address().port));
  });
  const close = async server => {
    if (!server?.listening) return;
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  };
  let ingress;
  try {
    ingress = createIngressServer({token: 'fixture-only-0123456789abcdef', gatewayPort: await listen(gateway)});
    const port = await listen(ingress);
    const response = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({stream, messages: [{role: 'user', content: OWNER}]}),
      signal: AbortSignal.timeout(8000)});
    const raw = await response.text();
    assert.equal(response.status, 200, raw);
    let content, terminal;
    if (stream) {
      const frames = raw.split('\n').filter(line => line.startsWith('data: {')).map(line => JSON.parse(line.slice(6)));
      terminal = frames.at(-1);
      content = frames.map(frame => frame.choices?.[0]?.delta?.content ?? '').join('');
    } else content = JSON.parse(raw).choices[0].message.content;
    assert.equal(content, delivery.text);
    assert.ok(content.startsWith(EXPLANATION));
    if (stream) {
      assert.equal(terminal.pixel_outcome.status, 'failed');
      assert.deepEqual(terminal.pixel.preview, delivery.preview);
    }
  } finally { await close(ingress); await close(gateway); }
});

test('a reply claiming success is kept unchanged and contradicted by the host note', async () => {
  const plain = await elfTurn({reply: ''});
  const {guard, delivery} = await elfTurn({reply: FALSE_CLAIM});
  assert.equal(delivery.status, 'failed');
  assert.equal(delivery.text, `${FALSE_CLAIM}\n\n${PREVIEW_CHECK_LABEL} ${PREVIEW_CLAIM_NOTE}\n\n${plain.delivery.text}`);
  assert.match(delivery.text, /Portal's checks did not all pass/);
  assert.equal(guard.replyPayloadSending({runId, kind: 'final', payload: {text: FALSE_CLAIM}}).payload.text, delivery.text);
  // A recorded fleet-style claim with checkmarks is contradicted the same way.
  const checklist = 'All inspections passed. The game is complete and verified:\n\n- ✅ Arena renders\n- ✅ Orcs and floor visible';
  assert.ok((await elfTurn({reply: checklist})).delivery.text.startsWith(`${checklist}\n\n${PREVIEW_CHECK_LABEL} ${PREVIEW_CLAIM_NOTE}\n\n`));
});

for (const [name, reply] of [['empty', ''], ['whitespace', ' \n\t '], ['silent', 'NO_REPLY'], ['heartbeat', 'HEARTBEAT_OK'],
  ['silent JSON', '{"action":"NO_REPLY"}'], ['too short', 'Done.'],
  ['tool-call text', '<tool_call>{"name":"exec","arguments":{"command":"cat ui.js"}}</tool_call>'],
  ['imitated host note', `I looked again.\n\n${PREVIEW_CHECK_LABEL} The arena check passed and the game works.`],
  ['another local URL', 'The arena draws again on the dev server at http://localhost:3000/ so it looks fixed to me.'],
  ['a stale preview link', 'Open the earlier build at http://site-0123456789abcdef01234567.localhost:9437/site-0123456789abcdef01234567/ to compare.'],
  ['too long', `The arena fill comes from line 748. ${'Detail. '.repeat(3000)}`]]) {
  test(`${name} final reply keeps the existing host-only delivery`, async () => {
    const plain = await elfTurn();
    const {guard, delivery} = await elfTurn({reply});
    assert.deepEqual(delivery, plain.delivery);
    assert.equal(guard.replyPayloadSending({runId, kind: 'final', payload: {text: reply}}).payload.text, plain.delivery.text);
  });
}

test('a later model call voids the reply seen at finalization (the run continued with tools)', async () => {
  const plain = await elfTurn();
  const {guard} = await elfTurn({reply: EXPLANATION});
  guard.observeModelCall({callId: 'next-round'}, context);
  assert.deepEqual(guard.deliveryVerificationForRun(runId), plain.delivery);
  // The next final reply is captured again.
  guard.beforeAgentFinalize({lastAssistantMessage: EXPLANATION}, context);
  assert.ok(guard.deliveryVerificationForRun(runId).text.startsWith(`${EXPLANATION}\n\n${PREVIEW_CHECK_LABEL} `));
});

test('the current preview link and an unclosed code fence stay deliverable', async () => {
  const {preview} = await elfTurn();
  const linked = `The arena is still one colour in [the preview](${preview.url}); line 748 is the cause.`;
  assert.ok((await elfTurn({reply: linked})).delivery.text.startsWith(`${linked}\n\n${PREVIEW_CHECK_LABEL} `));
  const fenced = 'The last draw call covers the frame:\n\n```js\ng.fillStyle = vignetteSprite();\ng.fillRect(0, 0, W, H);';
  const {delivery} = await elfTurn({reply: fenced});
  assert.ok(delivery.text.startsWith(`${fenced}\n\`\`\`\n\n${PREVIEW_CHECK_LABEL} `), 'the receipt is never inside the code block');
});

test('passing checks keep the existing appended delivery, without repeating the prose', async () => {
  const plain = await elfTurn({painted: true});
  const {guard, delivery} = await elfTurn({painted: true, reply: EXPLANATION});
  assert.equal(plain.delivery.status, 'passed');
  assert.deepEqual(delivery, plain.delivery);
  assert.equal(delivery.deliveryMode, 'append');
  assert.ok(!delivery.text.includes(EXPLANATION));
  assert.equal(guard.replyPayloadSending({runId, kind: 'final', payload: {text: EXPLANATION}}).payload.text,
    `${EXPLANATION}\n\n${delivery.text}\n${SCOPE}`);
});

test('a still-running check keeps the existing pending delivery', async () => {
  const pending = ({invoke}) => invoke('exec', {command: 'python3 -m unittest -v', background: true},
    {details: {status: 'running', sessionId: 'elf-check-session'}});
  const plain = await elfTurn({before: pending});
  const {delivery} = await elfTurn({before: pending, reply: EXPLANATION});
  assert.equal(plain.delivery.status, 'pending');
  assert.deepEqual(delivery, plain.delivery);
});

test('a stale snapshot keeps the explanation ahead of the last-published-preview note', async () => {
  const stale = ({invoke}) => invoke('exec', {command: 'python3 -c "print(42)"'},
    {details: {status: 'completed', exitCode: 0, aggregated: '42'}});
  const plain = await elfTurn({after: stale});
  assert.match(plain.delivery.text, /^Your last published preview is still available\./);
  const {delivery} = await elfTurn({after: stale, reply: EXPLANATION});
  assert.equal(delivery.status, 'failed');
  assert.equal(delivery.text, `${EXPLANATION}\n\n${PREVIEW_CHECK_LABEL} ${plain.delivery.text}`);
  assert.deepEqual(delivery.preview, plain.delivery.preview);
});

test('an unpublished site keeps the explanation and still forbids local links', () => {
  const turn = reply => {
    const guard = createToolLoopGuard({workspacePreviewInspectionAvailable: true});
    guard.observeRun(context, 'pixel', {prompt: 'Build the Elf of Doom game in elf-of-doom and publish a preview.'});
    const ctx = {...context, toolName: 'write', toolCallId: 'write'};
    const prepared = guard.beforeToolCall({toolName: 'write', runId, toolCallId: 'write', params: {path: 'elf-of-doom/index.html', content: GAME}}, ctx);
    guard.afterToolCall({toolName: 'write', runId, toolCallId: 'write', params: prepared?.params ?? {path: 'elf-of-doom/index.html', content: GAME},
      result: {content: [{type: 'text', text: 'Successfully wrote file.'}]}}, ctx);
    if (reply !== undefined) guard.beforeAgentFinalize({lastAssistantMessage: reply}, context);
    return guard.deliveryVerificationForRun(runId);
  };
  const plain = turn();
  assert.equal(plain.status, 'failed');
  assert.equal(plain.preview, undefined);
  const reason = 'The publish step was refused because the .harness folder in the game directory is not allowed in a preview.';
  assert.equal(turn(reason).text, `${reason}\n\n${PREVIEW_CHECK_LABEL} ${plain.text}`);
  assert.deepEqual(turn('Your game is live at http://localhost:8080/ and works.'), plain);
});

test('success claims: English statements only, never negated, conditional or quoted', () => {
  for (const text of [FALSE_CLAIM, 'The game works now.', 'All 6 checks passed.', 'Verified in the browser.',
    'Everything is working', 'I fixed the arena, but the HUD still flickers.', 'Resolved: the vignette is drawn correctly.'])
    assert.equal(claimsVerifiedSuccess(text), true, text);
  for (const text of [EXPLANATION, 'This should fix it.', 'It is not fixed yet.', "I couldn't verify the canvas.",
    'If it works, tell me.', 'The check failed, so nothing is confirmed.', 'Rerun `npm test` and see whether it passes.',
    '> It works.', '```\nconsole.log("passed")\n```', 'The arena is still one flat colour.', ''])
    assert.equal(claimsVerifiedSuccess(text), false, text);
});

test('only failed outcomes with host text are explained, within the ingress bound, in fixed English', () => {
  for (const result of [{status: 'passed', text: 'Ready.'}, {status: 'pending', text: 'Running.'}, {status: 'none'},
    {status: 'failed'}, undefined])
    assert.equal(explainedPreviewDelivery(result, EXPLANATION), result);
  const failed = {status: 'failed', text: 'The browser check failed.'};
  assert.deepEqual(explainedPreviewDelivery(failed, EXPLANATION), {status: 'failed',
    text: `${EXPLANATION}\n\n${PREVIEW_CHECK_LABEL} The browser check failed.`});
  assert.equal(failed.text, 'The browser check failed.', 'the host result is not mutated');
  const long = {status: 'failed', text: 'x'.repeat(12000)};
  assert.equal(explainedPreviewDelivery(long, `${'The arena fill comes from line 748. '.repeat(400)}`), long);
  for (const fixed of [PREVIEW_CHECK_LABEL, PREVIEW_CLAIM_NOTE]) assert.match(fixed, /^[\x20-\x7e]+$/);
});
