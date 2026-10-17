// RTX Spark, 2026-10-16. 18:09Z the owner asked Portal "Increase enemies by
// 10%" (session 02269765); the model called pixel_ods_ask_user with two
// questions and said it would make the change once answered. 20:28Z, after a
// 20:24:50Z gateway restart, the card's answer (dashboard answersMessage)
// became the first message of a new native session 8b4c4b17. The model read
// its own question as the owner asking where to apply it, answered with a
// location and edited nothing.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {createAskUserTool, requestsChoiceQuestion} from '../plugin/ask-user.mjs';
import {requestsNewPlaygroundProject} from '../plugin/playground-projects.mjs';
import {createPendingClarifications, answersClarification, clarificationAnswerContext,
  PENDING_CLARIFICATION_TTL_MS} from '../plugin/pending-clarification.mjs';
import {createToolLoopGuard, userMessageAuthorizesRecursiveDelete, RECURSIVE_DELETE_REQUIRES_OWNER_REASON} from '../plugin/tool-loop-guard.mjs';
import {promptContractForAgent} from '../plugin/prompt-contract.mjs';
import {ACTIVITY_CONTRACT} from '../plugin/activity-display.mjs';
import {GOAL_CONTRACT} from '../plugin/goal-progress.mjs';

const USER = 'ods-2c7a1f3b9e0d4c6a8b5e7f9a1c3d5e7f9b1a3c5e7d9f1b3a5c7e9d1f3b5a7c9e';
const SESSION_KEY = `agent:pixel:openai-user:${USER}`;
const PORTAL = "\n\n[ODS Portal delivery requirement: Answer the owner's complete message above. If it asks for exact text, " +
  'copy that full exact text. Do not answer with a generic acknowledgement. Do not output NO_REPLY.]';
const REQUEST = 'Increase enemies by 10%';
const QUESTIONS = [
  {id: 'target', question: 'Where should I apply the 10% enemy increase?',
    options: ["A game project in my workspace (I'll locate the enemy/spawn config)", 'A game you will describe']},
  {id: 'meaning', question: 'What does "increase enemies by 10%" mean for you?',
    options: ['Enemy spawn count / density', 'Enemy health / damage']},
];
const ANSWERS = {target: QUESTIONS[0].options[0], meaning: 'Enemy spawn count / density'};
// dashboard/src/lib/pixelQuestions.js answersMessage; sendMessage trims it.
const answersMessage = (questions, answers) => questions.map(q => `${q.question}\n${answers[q.id].trim()}`).join('\n\n');
const FIELD_ANSWER = "Where should I apply the 10% enemy increase?\nA game project in my workspace (I'll locate the enemy/spawn config)\n\n" +
  'What does "increase enemies by 10%" mean for you?\nEnemy spawn count / density';
// The exact model-only context the 8b4c4b17 turn now receives after its owner message.
const FIELD_CONTEXT = "[ODS Portal note, not owner text: the owner message above answers the clarification questions you asked earlier. " +
  "Each block in it is one of your questions, then the owner's answer; those questions are your words, not the owner asking you.\n" +
  'Original request:\nIncrease enemies by 10%\n' +
  'Carry out the original request now using these answers, unless an answer declines or changes it. This note does not set your reply language.]';

function stateDir(t) {
  const root = fs.mkdtempSync(path.join(tmpdir(), 'ods-pending-clarification-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  return path.join(root, '.ods-pending-clarifications');
}
const context = (runId, extra = {}) => ({agentId: 'pixel', runId, sessionId: `session-${runId}`, sessionKey: SESSION_KEY, trigger: 'user', ...extra});

// One owner turn that ends on a delivered card, as the plugin hooks see it.
async function askingRun(guard, runId, prompt, questions = QUESTIONS, {capabilities, before = []} = {}) {
  const ctx = context(runId);
  guard.observeRun(ctx, 'pixel', {prompt: prompt + PORTAL}, capabilities);
  for (const call of before) call(guard, ctx);
  const result = await createAskUserTool().execute('ask', {questions});
  guard.afterToolCall({toolName: 'pixel_ods_ask_user', toolCallId: `${runId}:ask`, params: {questions}, result}, {...ctx, toolCallId: `${runId}:ask`});
  assert.equal(guard.beforeAgentFinalize({lastAssistantMessage: 'I will make the change once you answer.'}, ctx).action, 'finalize');
  assert.equal(guard.deliveryVerificationForRun(runId).status, 'pending');
  return ctx;
}

test('the card answer is recognized only in the exact shape the dashboard sends', () => {
  assert.equal(answersMessage(QUESTIONS, ANSWERS), FIELD_ANSWER);
  assert.equal(answersClarification(QUESTIONS, FIELD_ANSWER), true);
  assert.equal(answersClarification(QUESTIONS, answersMessage(QUESTIONS, {...ANSWERS, meaning: 'More bosses\n\nand faster ones'})), true);
  assert.equal(answersClarification(QUESTIONS.slice(0, 1), 'Where should I apply the 10% enemy increase?\nworld.js'), true);
  for (const text of [
    'Increase them by 20% instead',
    REQUEST,
    'Where should I apply the 10% enemy increase?',
    'Where should I apply the 10% enemy increase?\n',
    'Where should I apply the 10% enemy increase?\nworld.js',
    `Please: ${FIELD_ANSWER}`,
    answersMessage([...QUESTIONS].reverse(), ANSWERS),
    FIELD_ANSWER.replace('\n\nWhat does', '\nWhat does'),
    'Where should I apply the 10% enemy increase?\n\n\nWhat does "increase enemies by 10%" mean for you?\nEnemy spawn count / density',
    `${FIELD_ANSWER.split('\n\n')[1]}\n\n${FIELD_ANSWER.split('\n\n')[0]}`,
  ]) assert.equal(answersClarification(QUESTIONS, text), false, text);
  for (const questions of [undefined, [], [{question: ''}]]) assert.equal(answersClarification(questions, FIELD_ANSWER), false);
});

test('records are private, bounded, replaced by a newer card, consumed once and expire', t => {
  let clock = Date.parse('2026-10-16T18:10:00Z');
  const dir = stateDir(t), store = createPendingClarifications({stateDir: dir, now: () => clock});
  assert.equal(store.take(SESSION_KEY), null, 'no store directory yet');
  assert.equal(store.remember({sessionKey: SESSION_KEY, runId: 'ask', questions: QUESTIONS, request: REQUEST + PORTAL}), true);
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(dir).mode & 0o777, 0o700);
    for (const name of fs.readdirSync(dir)) assert.equal(fs.statSync(path.join(dir, name)).mode & 0o777, 0o600);
  }
  const [name] = fs.readdirSync(dir);
  assert.match(name, /^[a-f0-9]{64}\.json$/, 'one hashed record, no temporary file');
  assert.ok(!name.includes(USER.slice(4, 20)), 'the chat identity is hashed again');
  clock += 2 * 60 * 60 * 1000 + 18 * 60 * 1000;
  assert.deepEqual(store.take(SESSION_KEY), {schemaVersion: 1, sessionHash: name.slice(0, 64), runId: 'ask',
    createdAt: Date.parse('2026-10-16T18:10:00Z'), request: REQUEST, questions: QUESTIONS, earlierAnswers: []});
  assert.deepEqual(fs.readdirSync(dir), [], 'consumed');
  assert.equal(store.take(SESSION_KEY), null);

  assert.equal(store.remember({sessionKey: SESSION_KEY, runId: 'first', questions: QUESTIONS, request: 'first'}), true);
  assert.equal(store.remember({sessionKey: SESSION_KEY, runId: 'second', questions: QUESTIONS.slice(1), request: 'second'}), true);
  const newer = store.take(SESSION_KEY);
  assert.equal(newer.runId, 'second');
  assert.deepEqual(newer.questions, QUESTIONS.slice(1));
  assert.equal(store.take(SESSION_KEY), null);

  const long = 'a'.repeat(3999) + '\u{1F600}' + 'b'.repeat(2000);
  assert.equal(store.remember({sessionKey: SESSION_KEY, runId: 'long', questions: QUESTIONS, request: long,
    earlierAnswers: ['one', 'two', 'x'.repeat(5000) + PORTAL]}), true);
  const bounded = store.take(SESSION_KEY);
  assert.equal(bounded.request, 'a'.repeat(3999) + ' [shortened]', 'no lone surrogate at the cut');
  assert.deepEqual(bounded.earlierAnswers, ['two', 'x'.repeat(2000) + ' [shortened]']);

  for (const value of [
    {sessionKey: 'agent:pixel:main', runId: 'r', questions: QUESTIONS, request: REQUEST},
    {sessionKey: SESSION_KEY, runId: 'r', questions: [{...QUESTIONS[0], options: ['one']}], request: REQUEST},
    {sessionKey: SESSION_KEY, runId: 'r', questions: QUESTIONS, request: PORTAL},
    {sessionKey: SESSION_KEY, runId: '', questions: QUESTIONS, request: REQUEST},
  ]) assert.equal(store.remember(value), false);
  assert.equal(store.take('agent:pixel:main'), null);
  assert.deepEqual(fs.readdirSync(dir), []);

  assert.equal(store.remember({sessionKey: SESSION_KEY, runId: 'stale', questions: QUESTIONS, request: REQUEST}), true);
  clock += PENDING_CLARIFICATION_TTL_MS + 1;
  assert.equal(store.take(SESSION_KEY), null, 'expired');
  assert.deepEqual(fs.readdirSync(dir), []);
  assert.equal(store.remember({sessionKey: SESSION_KEY, runId: 'future', questions: QUESTIONS, request: REQUEST}), true);
  clock -= 2 * 60 * 1000;
  assert.equal(store.take(SESSION_KEY), null, 'a record from the future is not trusted');

  const file = path.join(dir, `${'0'.repeat(64)}.json`);
  fs.writeFileSync(file, '{"schemaVersion":1}', {mode: 0o600});
  const forged = createPendingClarifications({stateDir: dir, now: () => clock});
  assert.equal(forged.remember({sessionKey: SESSION_KEY, runId: 'ask', questions: QUESTIONS, request: REQUEST}), true);
  const target = fs.readdirSync(dir).find(name => name !== path.basename(file));
  fs.writeFileSync(path.join(dir, target), JSON.stringify({...JSON.parse(fs.readFileSync(path.join(dir, target), 'utf8')), extra: true}));
  assert.throws(() => forged.take(SESSION_KEY), /Invalid clarification record/);
  assert.equal(fs.existsSync(path.join(dir, target)), false, 'an invalid record is removed, never used');
});

test('abandoned cards expire to make room and the store refuses new chats only when full', t => {
  let clock = Date.now();
  const dir = stateDir(t), store = createPendingClarifications({stateDir: dir, now: () => clock, maximumSessions: 2});
  const key = n => `agent:pixel:openai-user:ods-${String(n).repeat(64)}`;
  assert.equal(store.remember({sessionKey: key(1), runId: 'a', questions: QUESTIONS, request: REQUEST}), true);
  assert.equal(store.remember({sessionKey: key(2), runId: 'b', questions: QUESTIONS, request: REQUEST}), true);
  assert.equal(store.remember({sessionKey: key(3), runId: 'c', questions: QUESTIONS, request: REQUEST}), false, 'full');
  assert.equal(store.remember({sessionKey: key(2), runId: 'b2', questions: QUESTIONS, request: REQUEST}), true, 'a chat with a card may replace it');
  clock += PENDING_CLARIFICATION_TTL_MS + 60 * 1000;
  assert.equal(store.remember({sessionKey: key(3), runId: 'c', questions: QUESTIONS, request: REQUEST}), true);
  assert.equal(fs.readdirSync(dir).length, 1, 'expired records were deleted');
  assert.equal(store.take(key(3)).runId, 'c');
});

test('field case: the answer in a replacement session gets its request as model-only context once', async t => {
  const store = createPendingClarifications({stateDir: stateDir(t)});
  const warnings = [];
  await askingRun(createToolLoopGuard({pendingClarifications: store}), 'run-02269765', REQUEST);
  // A gateway restart drops every in-memory run; the record is on disk.
  const guard = createToolLoopGuard({pendingClarifications: store, warn: message => warnings.push(message)});
  const answer = context('run-8b4c4b17');
  const event = {prompt: FIELD_ANSWER + PORTAL, messages: []};
  const before = structuredClone(event);
  guard.observeRun(answer, 'pixel', event);
  assert.equal(guard.clarificationContextForRun(answer.runId), FIELD_CONTEXT);
  assert.deepEqual(event, before, 'the owner turn is not rewritten');
  assert.deepEqual(guard.ownerIntentEventForRun(answer.runId, event), before, 'classifiers read the owner turn unchanged');
  assert.equal(guard.promptContextForRun(answer.runId), undefined, 'nothing is prepended to the owner turn');
  // Every attempt of that run keeps it; the next run never sees it again.
  guard.observeRun(answer, 'pixel', {prompt: 'Continue where you left off.'});
  assert.equal(guard.clarificationContextForRun(answer.runId), FIELD_CONTEXT);
  const repeat = context('run-repeat');
  guard.observeRun(repeat, 'pixel', event);
  assert.equal(guard.clarificationContextForRun(repeat.runId), undefined);
  assert.deepEqual(warnings, []);
  assert.equal(clarificationAnswerContext({request: REQUEST, earlierAnswers: []}), FIELD_CONTEXT);
});

test('only the card answer from an owner turn takes the record, and any owner turn ends it', async t => {
  const dir = stateDir(t), store = createPendingClarifications({stateDir: dir});
  for (const [prompt, expected] of [['Increase them by 20% instead', false], [FIELD_ANSWER, true]]) {
    const guard = createToolLoopGuard({pendingClarifications: store});
    const asked = await askingRun(guard, `ask-${expected}`, REQUEST);
    // A later attempt of the asking run, a cron turn, a non-Portal session
    // and a team worker in the same chat leave the card pending.
    guard.observeRun(asked, 'pixel', {prompt: FIELD_ANSWER + PORTAL});
    guard.observeRun(context('cron', {trigger: 'cron'}), 'pixel', {prompt: FIELD_ANSWER + PORTAL});
    guard.observeRun(context('main', {sessionKey: 'agent:pixel:main'}), 'pixel', {prompt: FIELD_ANSWER + PORTAL});
    guard.observeRun(context('worker'), 'pixel', {prompt: "You are the Reviewer in the owner's Portal team.\n" + FIELD_ANSWER});
    assert.equal(fs.readdirSync(dir).length, 1);
    const next = context(`next-${expected}`);
    guard.observeRun(next, 'pixel', {prompt: prompt + PORTAL});
    assert.equal(Boolean(guard.clarificationContextForRun(next.runId)), expected, prompt);
    assert.deepEqual(fs.readdirSync(dir), [], 'the card ends with the next owner turn');
    const late = context(`late-${expected}`);
    guard.observeRun(late, 'pixel', {prompt: FIELD_ANSWER + PORTAL});
    assert.equal(guard.clarificationContextForRun(late.runId), undefined);
  }
  // No card is recorded for a team worker or without a store.
  const worker = createToolLoopGuard({pendingClarifications: store});
  const ctx = context('team');
  worker.observeRun(ctx, 'pixel', {prompt: "You are the Builder in the owner's Portal team.\nBuild it."});
  const result = await createAskUserTool().execute('ask', {questions: QUESTIONS});
  worker.afterToolCall({toolName: 'pixel_ods_ask_user', result}, {...ctx, toolCallId: 'ask'});
  assert.deepEqual(fs.readdirSync(dir), []);
  await askingRun(createToolLoopGuard(), 'no-store', REQUEST);
  assert.deepEqual(fs.readdirSync(dir), []);
  // A cancel of the answering run withdraws the note with the rest of the turn.
  const guard = createToolLoopGuard({pendingClarifications: store, abortRunAndDrain: async () => ({aborted: true, drained: true})});
  await askingRun(guard, 'ask-cancel', REQUEST);
  const cancelled = context('answer-cancel');
  guard.observeRun(cancelled, 'pixel', {prompt: FIELD_ANSWER + PORTAL});
  assert.ok(guard.clarificationContextForRun(cancelled.runId));
  assert.equal(await guard.abortUserRun(USER), true);
  assert.equal(guard.clarificationContextForRun(cancelled.runId), undefined);
});

test('every delivered card is recorded: the tool, its Tool Search form and the requested-choice repair', async t => {
  const name = 'pixel_ods_ask_user', id = `openclaw:pixel-ods:${name}`;
  const result = await createAskUserTool().execute('ask', {questions: QUESTIONS});
  const wrapped = {toolName: 'tool_call', params: {id, args: {questions: QUESTIONS}},
    result: {details: {tool: {id, source: 'openclaw', sourceName: 'pixel-ods', name}, result}}};
  const request = 'Me pergunte qual cor com opções para escolher.';
  const text = 'Qual cor principal você prefere?\n\n- Azul\n- Roxo\n- Vermelho';
  const repaired = [{id: 'preference', question: 'Qual cor principal você prefere?', options: ['Azul', 'Roxo', 'Vermelho']}];
  for (const [prompt, ask, questions] of [
    [REQUEST, (guard, ctx) => guard.afterToolCall(wrapped, {...ctx, toolCallId: 'ask'}), QUESTIONS],
    [request, (guard, ctx) => guard.beforeAgentFinalize({lastAssistantMessage: text}, ctx), repaired],
  ]) {
    const guard = createToolLoopGuard({pendingClarifications: createPendingClarifications({stateDir: stateDir(t)})});
    const asking = context(`ask-${questions[0].id}`);
    guard.observeRun(asking, 'pixel', {prompt: prompt + PORTAL});
    ask(guard, asking);
    assert.deepEqual(guard.deliveryVerificationForRun(asking.runId).questions, questions);
    const answer = context(`answer-${questions[0].id}`);
    guard.observeRun(answer, 'pixel', {prompt: answersMessage(questions, {[questions[0].id]: questions[0].options[1], meaning: ANSWERS.meaning}) + PORTAL});
    assert.equal(guard.clarificationContextForRun(answer.runId), clarificationAnswerContext({request: prompt, earlierAnswers: []}));
  }
});

test('a follow-up card keeps the original request and carries the earlier answers', async t => {
  const store = createPendingClarifications({stateDir: stateDir(t)});
  const guard = createToolLoopGuard({pendingClarifications: store});
  await askingRun(guard, 'ask-one', REQUEST, QUESTIONS.slice(0, 1));
  const first = answersMessage(QUESTIONS.slice(0, 1), ANSWERS);
  await askingRun(guard, 'ask-two', first, QUESTIONS.slice(1));
  assert.equal(guard.clarificationContextForRun('ask-two'), FIELD_CONTEXT, 'the first answer ran with its request');
  const last = context('answer-two');
  guard.observeRun(last, 'pixel', {prompt: answersMessage(QUESTIONS.slice(1), ANSWERS) + PORTAL});
  assert.equal(guard.clarificationContextForRun(last.runId), FIELD_CONTEXT.replace(
    'Original request:\nIncrease enemies by 10%\n',
    `Original request:\nIncrease enemies by 10%\nEarlier clarification answers:\n${first}\n`));
});

// Run the same two owner turns through a guard with and without the store and
// compare everything the owner text decides: the owner event, its prompt
// contract, tool decisions, finalization and delivery.
async function ownerTurnTrace(store, {request, questions, answers, history = false, workspace, before, calls = [], finalText}) {
  const guard = createToolLoopGuard(store ? {pendingClarifications: store} : {}), capabilities = workspace?.();
  await askingRun(guard, 'ask', request, questions, {capabilities, before});
  const answerText = answersMessage(questions, answers) + PORTAL;
  const event = {prompt: answerText, messages: history ? [
    {role: 'user', content: request + PORTAL},
    {role: 'assistant', content: [{type: 'toolCall', id: 'ask', name: 'pixel_ods_ask_user', arguments: {questions}}]},
    {role: 'toolResult', toolCallId: 'ask', toolName: 'pixel_ods_ask_user', content: [{type: 'text', text: 'Wait for the owner to answer.'}]},
    {role: 'user', content: answerText},
  ] : []};
  const ctx = context('answer');
  guard.observeRun(ctx, 'pixel', event, capabilities);
  const ownerEvent = guard.ownerIntentEventForRun(ctx.runId, event);
  const trace = {
    ownerEvent, contract: promptContractForAgent(ctx, 'pixel', ownerEvent), prepended: guard.promptContextForRun(ctx.runId) ?? null,
    decisions: calls.map((call, index) => guard.beforeToolCall({toolCallId: `call-${index}`, ...call}, {...ctx, toolCallId: `call-${index}`}) ?? null),
    finalize: guard.beforeAgentFinalize({lastAssistantMessage: finalText ?? 'Done.'}, ctx) ?? null,
    delivery: guard.deliveryVerificationForRun(ctx.runId),
  };
  return {trace, note: guard.clarificationContextForRun(ctx.runId)};
}
async function assertSameOwnerTurn(t, scenario) {
  const plain = await ownerTurnTrace(undefined, scenario);
  const stored = await ownerTurnTrace(createPendingClarifications({stateDir: stateDir(t)}), scenario);
  assert.equal(plain.note, undefined);
  assert.equal(stored.note, clarificationAnswerContext({request: scenario.request, earlierAnswers: []}));
  assert.deepEqual(stored.trace, plain.trace);
  assert.ok(!JSON.stringify(stored.trace).includes('ODS Portal note'), 'the note never reaches owner text');
  return stored.trace;
}

test('owner-intent classifiers see the field answer exactly as today, in a new or the same session', async t => {
  for (const history of [false, true]) {
    const trace = await assertSameOwnerTurn(t, {request: REQUEST, questions: QUESTIONS, answers: ANSWERS, history,
      calls: [{toolName: 'read', params: {path: 'Playground/elf-of-doom/world.js'}},
        {toolName: 'edit', params: {path: 'Playground/elf-of-doom/world.js', oldText: 'ROSTER_SCALE = 1.3', newText: 'ROSTER_SCALE = 1.43'}}]});
    assert.equal(trace.ownerEvent.prompt, FIELD_ANSWER + PORTAL);
  }
});

test('a declined delete stays unauthorized: the carried request never reaches the delete guard', async t => {
  const request = 'Delete the folder /workspace/Playground/old recursively';
  const questions = [{id: 'confirm', question: 'Should I permanently delete /workspace/Playground/old and everything in it?',
    options: ['Yes, delete it', 'No, keep it']}];
  const answer = answersMessage(questions, {confirm: 'No, keep it'});
  assert.equal(userMessageAuthorizesRecursiveDelete([], request), true, 'the request alone would authorize it');
  assert.equal(userMessageAuthorizesRecursiveDelete([], answer + PORTAL), false);
  // Why the request stays out of owner text: the refuted in-text frame authorized it.
  assert.equal(userMessageAuthorizesRecursiveDelete([], `Original request:\n${request}\n\n${answer}`), true);
  const trace = await assertSameOwnerTurn(t, {request, questions, answers: {confirm: 'No, keep it'},
    calls: [{toolName: 'exec', params: {command: 'rm -rf /workspace/Playground/old'}}]});
  assert.equal(trace.decisions[0].blockReason, RECURSIVE_DELETE_REQUIRES_OWNER_REASON);
});

test('an answered "ask me questions with options" request does not reopen choice-question intent', async t => {
  const request = 'Build me a choose your own adventure game. Ask me a few questions with options first.';
  const questions = [{id: 'theme', question: 'Which theme do you prefer?', options: ['Fantasy', 'Space']}];
  const answer = answersMessage(questions, {theme: 'Space'});
  assert.equal(requestsChoiceQuestion(request), true);
  assert.equal(requestsChoiceQuestion(answer), false);
  assert.equal(requestsChoiceQuestion(`Original request:\n${request}\n\n${answer}`), true, 'the refuted in-text frame reopened it');
  // The narrow text repair needs ownerQuestionIntent; it stays off as today.
  const trace = await assertSameOwnerTurn(t, {request, questions, answers: {theme: 'Space'},
    finalText: 'Which ending do you prefer?\n- Happy\n- Sad\n- Open'});
  assert.notEqual(trace.delivery.status, 'pending');
});

test('Playground keeps the project the request created when its card is answered', async t => {
  const roots = [];
  const workspace = () => {
    const root = fs.mkdtempSync(path.join(tmpdir(), 'ods-clarify-playground-'));
    t.after(() => fs.rmSync(root, {recursive: true, force: true}));
    roots.push(root);
    return {workspaceRoot: root};
  };
  const write = (guard, ctx) => {
    const params = {path: 'snake/index.html', content: '<!doctype html><title>Snake</title>'};
    const decision = guard.beforeToolCall({toolName: 'write', toolCallId: 'write-index', params}, {...ctx, toolCallId: 'write-index'});
    assert.equal(decision.params.path, 'Playground/snake/index.html');
    const root = roots.at(-1);
    fs.writeFileSync(path.join(root, decision.params.path), decision.params.content);
    guard.afterToolCall({toolName: 'write', toolCallId: 'write-index', params: decision.params,
      result: {content: [{type: 'text', text: 'File written'}]}}, {...ctx, toolCallId: 'write-index'});
  };
  const request = 'Build me a snake game';
  const questions = [{id: 'sound', question: 'Should the game have sound effects?', options: ['Yes, add sound', 'No sound']}];
  const answer = answersMessage(questions, {sound: 'Yes, add sound'});
  assert.equal(requestsNewPlaygroundProject(request), true);
  assert.equal(requestsNewPlaygroundProject(answer), false);
  // The refuted in-text frame reserved a second folder (Playground/snake-2).
  assert.equal(requestsNewPlaygroundProject(`Original request:\n${request}\n\n${answer}`), true);
  const trace = await assertSameOwnerTurn(t, {request, questions, answers: {sound: 'Yes, add sound'}, workspace, before: [write],
    calls: [{toolName: 'write', params: {path: 'sound.js', content: 'export const beep = () => {};'}}]});
  assert.equal(trace.decisions[0].params.path, 'Playground/snake/sound.js');
  assert.equal(roots.length, 2);
  for (const root of roots) assert.deepEqual(fs.readdirSync(path.join(root, 'Playground')), ['snake']);
});

// The before_prompt_build hook from index.js with its collaborators stubbed
// and the real guard and store.
function promptHook(guard, goalActive = false) {
  const source = fs.readFileSync(new URL('../plugin/index.js', import.meta.url), 'utf8');
  const begin = source.indexOf('    api.on("before_prompt_build",');
  const finish = source.indexOf('    api.on("model_call_started",', begin);
  assert.ok(begin >= 0 && finish > begin);
  let callback;
  vm.runInNewContext(source.slice(begin, finish), {
    api: {config: {}, on: (_name, fn) => { callback = fn; }}, AGENT_ID: 'pixel',
    accessRuntime: {isProbe: () => false},
    delegationDelivery: {admission: () => undefined, observe() {}, promptContext: () => undefined},
    privateBrowserAccessForAgent: () => false, executionHostForAgent: () => 'sandbox',
    toolLoopGuard: guard, goalProgress: {begin() {}, active: () => goalActive}, taskActivity: {begin() {}},
    promptContractForAgent, configuredContextWindow: 131072, configuredLeanPrompt: false,
    extensionRepositoryContext: async () => '', ACTIVITY_CONTRACT, GOAL_CONTRACT,
    executionLocationContext: () => '', executionContext: () => '',
  });
  return (prompt, ctx) => callback({prompt}, ctx);
}

test('the prompt hook puts the note beside the owner turn, after goal mode, and nowhere else', async t => {
  for (const goalActive of [false, true]) {
    const store = createPendingClarifications({stateDir: stateDir(t)});
    const guard = createToolLoopGuard({pendingClarifications: store});
    const hook = promptHook(guard, goalActive);
    const asking = await hook(REQUEST + PORTAL, context(`ask-${goalActive}`));
    assert.equal(asking.appendContext, goalActive ? GOAL_CONTRACT : undefined);
    const result = await createAskUserTool().execute('ask', {questions: QUESTIONS});
    guard.afterToolCall({toolName: 'pixel_ods_ask_user', result}, {...context(`ask-${goalActive}`), toolCallId: 'ask'});
    const answered = await hook(FIELD_ANSWER + PORTAL, context(`answer-${goalActive}`));
    assert.equal(answered.appendContext, goalActive ? `${GOAL_CONTRACT}\n\n${FIELD_CONTEXT}` : FIELD_CONTEXT);
    assert.equal(answered.prependContext, undefined);
    assert.ok(!answered.appendSystemContext.includes(REQUEST), 'the cached system prompt is unchanged');
    const later = await hook('Thanks!' + PORTAL, context(`later-${goalActive}`));
    assert.equal(later.appendContext, goalActive ? GOAL_CONTRACT : undefined);
  }
});
