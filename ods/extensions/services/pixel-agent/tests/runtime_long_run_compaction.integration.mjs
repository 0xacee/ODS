// Exact pinned runtime, loopback provider, disposable state; no model inference.
// RTX Spark, 2026-10-16: one long Portal run compacted on the loop guard's
// estimate while the provider prompt was 35-46k of 131k tokens, and the later
// overflow compaction sent ~190k tokens of transcript in one summary request,
// which failed the run. ODS_LONG_RUN_COMPACTION_BASELINE=1 loads the previous
// reviewed recipes; the same assertions then fail.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {once} from 'node:events';
import {createHash} from 'node:crypto';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';

const pkg = process.env.OPENCLAW_PACKAGE_DIR;
assert.ok(pkg, 'provide the pinned reviewed OpenClaw package');
const baseline = process.env.ODS_LONG_RUN_COMPACTION_BASELINE === '1';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ods-long-run-'));
process.env.OPENCLAW_STATE_DIR = path.join(root, 'state');
process.env.OPENCLAW_CONFIG_PATH = path.join(root, 'openclaw.json');
const sha = value => createHash('sha256').update(value).digest('hex');
// The reviewed recipes this change extends; installed runtimes migrate from them.
const PREVIOUS = {
  'compaction-budget': '2e64e5eb0e35f5f363865d4f51bba54a599c9ac745241120b0a826e97613288e',
  'compaction-empty': '12fe33a44b48cfe9c5fe95e3f797371ff1e33d548877a95e5d5d0199088738fd',
};
function apply(source, replacements) {
  for (const [before, after] of replacements) {
    assert.equal(source.split(before).length, 2, 'each reviewed anchor is unique');
    source = source.replace(before, () => after);
  }
  return source;
}
function unapply(source, replacements) {
  for (const [before, after] of [...replacements].reverse()) {
    assert.equal(source.split(after).length, 2, 'each reviewed replacement is unique');
    source = source.replace(after, () => before);
  }
  return source;
}
function reviewed(name, module) {
  const manifest = JSON.parse(fs.readFileSync(new URL(`../host/openclaw-${name}.json`, import.meta.url)));
  const filename = path.join(pkg, 'dist', module);
  let original = fs.readFileSync(filename, 'utf8');
  const digest = sha(original);
  const applied = digest === manifest.patchedSha256 ? manifest.replacements : manifest.previousReplacements?.[digest];
  if (applied) original = unapply(original, applied);
  assert.equal(sha(original), manifest.sourceSha256, 'reject unreviewed native bytes');
  const patched = apply(original, manifest.replacements);
  assert.equal(sha(patched), manifest.patchedSha256);
  const previous = name in PREVIOUS ? manifest.previousReplacements[PREVIOUS[name]] : undefined;
  return {manifest, filename, original, patched, previous: previous && apply(original, previous)};
}
const recipes = Object.fromEntries([
  ['compaction-budget', 'selection-BEwSQKM-.js'],
  ['tool-result-projection', 'tool-result-truncation-CbxVHy2D.js'],
  ['compaction-resume', 'sessions-CZbwb3_c.js'],
  ['compaction-empty', 'proxy-Bsfwfsp-.js'],
  ['compaction-no-work', 'compact-DuWIsaq_.js'],
].map(([name, module]) => [name, reviewed(name, module)]));
const sources = new Map(Object.values(recipes).map(recipe =>
  [pathToFileURL(recipe.filename).href, baseline && recipe.previous ? recipe.previous : recipe.patched]));
const loader = registerHooks({load(url, context, next) {
  return sources.has(url) ? {format: 'module', source: sources.get(url), shortCircuit: true} : next(url, context);
}});
const native = await import(pathToFileURL(path.join(pkg, 'dist/proxy-Bsfwfsp-.js')));
const {t: runEmbeddedAgent} = await import(pathToFileURL(path.join(pkg, 'dist/embedded-agent-CJx-nG3W.js')));
const {compactEmbeddedAgentSessionDirect} = await import(pathToFileURL(path.join(pkg, 'dist/compact-DuWIsaq_.js')));
test.after(async () => {
  // Windows refuses to remove the shared state database while it is open.
  const {n: closeStateDatabases} = await import(pathToFileURL(path.join(pkg, 'dist/openclaw-state-db-BtpXMqJX.js')));
  closeStateDatabases(); loader.deregister(); await fs.promises.rm(root, {recursive: true, force: true});
});

// Spark profile: 131k context, 8k output, ODS reserve/keep, 16k tool results.
const WINDOW = 131072, OUTPUT = 8192, RESERVE = 32768;
const SUMMARY_SYSTEM = 'You are a context summarization assistant.';
const textOf = content => typeof content === 'string' ? content
  : Array.isArray(content) ? content.map(block => typeof block?.text === 'string' ? block.text : '').join('') : '';
const requestChars = body => body.messages.reduce((sum, message) => sum + textOf(message.content).length
  + (message.tool_calls ? JSON.stringify(message.tool_calls).length : 0), 0);
// The openai-completions transport's own input estimate (4 chars/token, 1.25 margin).
const transportTokens = body => Math.ceil(requestChars(body) / 4 * 1.25);
function provider(t, respond) {
  const bodies = [];
  const server = http.createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks)); bodies.push(body);
    const reply = respond(body);
    if (reply.status) {
      res.writeHead(reply.status, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({error: {code: reply.status, message: reply.error, type: 'exceed_context_size_error'}}));
      return;
    }
    res.writeHead(200, {'Content-Type': 'text/event-stream'});
    res.write('data: ' + JSON.stringify({id: 'fixture', object: 'chat.completion.chunk', choices: [{index: 0, delta: {role: 'assistant', ...reply.delta}, finish_reason: null}]}) + '\n\n');
    res.end('data: ' + JSON.stringify({id: 'fixture', object: 'chat.completion.chunk', choices: [{index: 0, delta: {}, finish_reason: reply.delta.tool_calls ? 'tool_calls' : 'stop'}],
      usage: {prompt_tokens: Math.ceil(requestChars(body) / 4), completion_tokens: 20, total_tokens: Math.ceil(requestChars(body) / 4) + 20}}) + '\n\ndata: [DONE]\n\n');
  });
  server.listen(0, '127.0.0.1');
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  return {bodies, ready: once(server, 'listening').then(() => server.address().port)};
}
function config(area, port) {
  const workspace = path.join(area, 'workspace'), agentDir = path.join(area, 'agent');
  fs.mkdirSync(workspace, {recursive: true}); fs.mkdirSync(agentDir, {recursive: true});
  const value = {agents: {defaults: {workspace, skipBootstrap: true, model: 'fixture/model', contextTokens: WINDOW,
    compaction: {reserveTokens: RESERVE, reserveTokensFloor: 0, keepRecentTokens: 8192}, heartbeat: {every: '0m'}},
  list: [{id: 'pixel', default: true, workspace, agentDir, contextLimits: {toolResultMaxChars: 16000}}]},
  tools: {allow: ['read'], loopDetection: {enabled: false}}, plugins: {enabled: false},
  models: {mode: 'replace', providers: {fixture: {api: 'openai-completions', baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: 'fixture-only',
    models: [{id: 'model', name: 'Fixture', contextWindow: WINDOW, maxTokens: OUTPUT, reasoning: false, input: ['text']}]}}}};
  fs.writeFileSync(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(value));
  return {config: value, workspace, agentDir};
}
// Content-free synthetic source: about 30k characters, like the game's ui.js.
const source = lines => Array.from({length: lines}, (_, i) => `  const cell${i} = grid.cells[${i}] ?? spawn(${i});`).join('\n');

test('the loop guard measures the projected prompt and leaves a small real prompt uncompacted', {timeout: 90000}, async t => {
  const ROUNDS = 12;
  let rounds = 0;
  const upstream = provider(t, body => {
    if (textOf(body.messages[0]?.content).startsWith(SUMMARY_SYSTEM)) return {delta: {content: 'Summary of the file reads.'}};
    if (rounds >= ROUNDS) return {delta: {content: 'Done.'}};
    return {delta: {tool_calls: [{index: 0, id: `read-${rounds}`, type: 'function', function: {name: 'read', arguments: JSON.stringify({path: 'ui.js', offset: 1 + rounds++ % 2})}}]}};
  });
  const area = fs.mkdtempSync(path.join(root, 'guard-')), {config: value, workspace, agentDir} = config(area, await upstream.ready);
  fs.writeFileSync(path.join(workspace, 'ui.js'), source(640));
  const sessionId = '2aaaaaaa-2222-4333-8444-555555555555', sessionFile = path.join(area, sessionId + '.jsonl');
  fs.writeFileSync(sessionFile, JSON.stringify({type: 'session', version: 3, id: sessionId, timestamp: new Date().toISOString(), cwd: workspace}) + '\n');
  const result = await runEmbeddedAgent({agentId: 'pixel', sessionId, sessionFile, sessionKey: 'agent:pixel:long-run-fixture', workspaceDir: workspace, agentDir,
    config: value, provider: 'fixture', model: 'model', prompt: 'Read ui.js twelve times, then say Done.', runId: 'long-run-guard', trigger: 'user', timeoutMs: 60000});
  const summaries = upstream.bodies.filter(body => textOf(body.messages[0]?.content).startsWith(SUMMARY_SYSTEM));
  const turns = upstream.bodies.filter(body => !summaries.includes(body));
  const trace = JSON.stringify({error: result.meta?.error, rounds, requests: upstream.bodies.length, summaries: summaries.length,
    estimates: turns.map(transportTokens)});
  t.diagnostic(trace);
  assert.equal(summaries.length, 0, 'FAIL: the loop guard compacted a prompt far below the real limit\n' + trace);
  // Each raw result is ~30k characters; twelve of them are what the old guard
  // counted (at 2 characters per token) against the 131k window.
  assert.equal(turns.at(-1).messages.filter(message => message.role === 'tool').length, ROUNDS, trace);
  assert.ok(fs.readFileSync(path.join(workspace, 'ui.js'), 'utf8').length * ROUNDS * 2 > WINDOW * 4 * 0.9);
  assert.equal(result.meta?.error, undefined, trace);
  assert.equal(result.payloads?.map(payload => payload.text ?? '').join(''), 'Done.', trace);
  assert.ok(turns.every(body => transportTokens(body) < 40000), 'the provider prompts stayed small\n' + trace);
});

// The Spark session: an owner request, a first overflow compaction, then 300
// entries of long tool work (reads, edits with code payloads, reasoning).
function sparkSession(workspace) {
  const now = Date.now(), at = offset => new Date(now - 3600000 + offset).toISOString();
  const rows = [{type: 'session', version: 3, id: '3aaaaaaa-2222-4333-8444-555555555555', timestamp: at(0), cwd: workspace}];
  let parent = null, step = 0;
  const add = message => { const id = `entry-${step}`; rows.push({type: 'message', id, parentId: parent, timestamp: at(++step * 1000), message: {timestamp: now - 3600000 + step * 1000, ...message}}); parent = id; };
  add({role: 'user', content: 'Make the browser game waves arrive faster and keep the score panel readable.'});
  const work = i => {
    const edit = i % 3 === 0;
    add({role: 'assistant', stopReason: 'toolUse', api: 'openai-completions', provider: 'fixture', model: 'model', usage: {input: 40000, output: 200, totalTokens: 40200},
      content: [{type: 'thinking', thinking: `Step ${i}: check the wave timer and the panel layout before the next change. `.repeat(12)},
        {type: 'text', text: `Step ${i} of the wave work.`},
        {type: 'toolCall', id: `call-${i}`, name: edit ? 'edit' : 'read', arguments: edit ? {path: 'game/ui.js', oldText: source(30), newText: source(36)} : {path: 'game/ui.js'}}]});
    add({role: 'toolResult', toolCallId: `call-${i}`, toolName: edit ? 'edit' : 'read', isError: false,
      content: [{type: 'text', text: edit ? 'Successfully replaced text in game/ui.js.' : source(90)}]});
  };
  for (let i = 0; i < 10; i++) work(i);
  const firstKept = rows.at(-4).id;
  rows.push({type: 'compaction', id: 'first-overflow', parentId: parent, timestamp: at(++step * 1000), firstKeptEntryId: firstKept, tokensBefore: 68211,
    summary: '## Goal\nSpeed up the waves and keep the score panel readable.\n\n## Progress\n' + '- [x] Earlier wave timer work.\n'.repeat(120)});
  parent = 'first-overflow';
  for (let i = 10; i < 160; i++) work(i);
  assert.equal(rows.filter((row, index) => index > rows.findIndex(r => r.id === 'first-overflow')).length, 300);
  return rows;
}

for (const trigger of ['overflow', 'manual']) test(`${trigger} compaction of a 300-entry tail sends one bounded summary request and completes`, {timeout: 90000}, async t => {
  const upstream = provider(t, body => {
    // llama.cpp rejects a prompt that does not fit its context.
    if (transportTokens(body) >= WINDOW) return {status: 400, error: 'the request exceeds the available context size, try increasing it'};
    return {delta: {content: '## Goal\nSpeed up the waves.\n\n## Progress\n- [x] Wave timer and panel edits in game/ui.js.'}};
  });
  const area = fs.mkdtempSync(path.join(root, `summary-${trigger}-`)), {config: value, workspace, agentDir} = config(area, await upstream.ready);
  const rows = sparkSession(workspace);
  const sessionId = rows[0].id, sessionFile = path.join(area, sessionId + '.jsonl');
  fs.writeFileSync(sessionFile, rows.map(row => JSON.stringify(row)).join('\n') + '\n');
  const tail = rows.slice(rows.findIndex(row => row.id === 'first-overflow') + 1).map(row => JSON.stringify(row)).join('\n').length;
  assert.ok(tail / 4 > 1.4 * WINDOW, `the tail alone is far larger than the window (${tail} JSON characters)`);
  const outcome = await compactEmbeddedAgentSessionDirect({agentId: 'pixel', sessionId, sessionFile, sessionKey: 'agent:pixel:spark-fixture', workspaceDir: workspace, agentDir,
    config: value, provider: 'fixture', model: 'model', trigger});
  const trace = JSON.stringify({outcome: {ok: outcome.ok, compacted: outcome.compacted, reason: outcome.reason},
    requests: upstream.bodies.map(body => ({estimate: transportTokens(body), max: body.max_tokens ?? body.max_completion_tokens}))});
  t.diagnostic(trace);
  for (const body of upstream.bodies) {
    assert.ok(transportTokens(body) + OUTPUT < WINDOW, 'FAIL: the summary request does not fit the model with its output\n' + trace);
    assert.ok(transportTokens(body) + RESERVE <= WINDOW, 'the input is held to an ordinary turn at the compaction threshold\n' + trace);
    assert.equal(body.max_tokens ?? body.max_completion_tokens, OUTPUT, 'the summary keeps its full output budget\n' + trace);
  }
  assert.ok(upstream.bodies.length >= 1 && upstream.bodies.length <= 2, 'one compaction, at most two summary requests\n' + trace);
  assert.equal(outcome.ok, true, trace); assert.equal(outcome.compacted, true, trace);
  const after = fs.readFileSync(sessionFile, 'utf8').trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(after.filter(row => row.type === 'message'), rows.filter(row => row.type === 'message'), 'the transcript is unchanged');
  assert.equal(after.filter(row => row.type === 'compaction').length, 2, 'a new checkpoint was saved');
  const sent = upstream.bodies.map(body => textOf(body.messages.at(-1).content)).join('\n');
  const steps = [...sent.matchAll(/Step (\d+): check the wave timer/g)].map(match => Number(match[1]));
  assert.ok(steps.length > 0 && Math.max(...steps) >= 150 && Math.min(...steps) > 20,
    `the newest work is summarized whole and the oldest reduced first: ${steps}`);
  assert.match(sent, /Step 11 of the wave work\./, 'replies of reduced steps stay');
  assert.match(sent, /edit\(path="game\/ui\.js", oldText="\[\d+ characters omitted to fit the summary request\]"/, 'a reduced edit keeps its tool and path');
});

const message = (role, content, extra = {}) => ({role, content, timestamp: 1, ...extra});
async function summarize(messages, {previousSummary, contextWindow = WINDOW} = {}) {
  const prompts = [];
  const result = await native.k(messages, {id: 'model', api: 'openai-completions', provider: 'fixture', contextWindow, maxTokens: OUTPUT}, RESERVE,
    undefined, undefined, undefined, undefined, previousSummary, undefined,
    async (_model, context) => ({result: async () => { prompts.push({system: context.systemPrompt, text: context.messages[0].content[0].text}); return {stopReason: 'stop', content: [{type: 'text', text: 'Summary.'}]}; }}));
  assert.equal(result.ok, true);
  return prompts[0];
}

test('a conversation within the budget is summarized exactly as before', async () => {
  const messages = [message('user', 'Fix the score panel.'),
    message('assistant', [{type: 'toolCall', id: 'one', name: 'read', arguments: {path: 'game/ui.js'}}], {stopReason: 'toolUse'}),
    message('toolResult', [{type: 'text', text: source(200)}], {toolCallId: 'one', toolName: 'read'})];
  const prompt = await summarize(messages, {previousSummary: 'Earlier progress.'});
  assert.ok(prompt.text.startsWith(`<conversation>\n${native.N(native.H(messages))}\n</conversation>\n\n<previous-summary>\nEarlier progress.\n</previous-summary>\n\n`));
});

test('an irreducible conversation keeps its newest messages within the budget', async () => {
  const messages = Array.from({length: 40}, (_, i) => message('user', `Request ${i}: ` + 'keep the panel readable. '.repeat(800)));
  const prompt = await summarize(messages, {contextWindow: 65536});
  const chars = prompt.system.length + prompt.text.length;
  assert.ok(Math.ceil(chars / 4 * 1.25) + OUTPUT < 65536, `FAIL: ${chars} characters do not fit a 64k model`);
  assert.match(prompt.text, /\[\d+ earlier messages omitted to fit the summary request\]/);
  assert.match(prompt.text, /Request 39: keep the panel readable/);
  assert.doesNotMatch(prompt.text, /Request 0: /);
});

test('recipes migrate installed runtimes from the previous reviewed bytes', () => {
  for (const name of Object.keys(PREVIOUS)) {
    const {manifest, original, previous} = recipes[name];
    assert.ok(previous, `${name} accepts the previous reviewed hash`);
    assert.equal(sha(previous), PREVIOUS[name]);
    // openclaw_tool_recovery.py: reconstruct the original, then apply the new recipe.
    assert.equal(sha(apply(unapply(previous, manifest.previousReplacements[PREVIOUS[name]]), manifest.replacements)), manifest.patchedSha256);
    for (const [digest, replacements] of Object.entries(manifest.previousReplacements)) {
      assert.equal(sha(apply(original, replacements)), digest, `${name} predecessor ${digest} is exact`);
    }
  }
});
