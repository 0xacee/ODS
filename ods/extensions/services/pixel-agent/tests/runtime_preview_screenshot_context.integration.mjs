// Preview screenshots against the pinned runtime's own context rules, executed
// from the exact reviewed sources, not copies: history image pruning before
// each prompt, and the text-only compaction summary request.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {createHash} from 'node:crypto';
import {MAX_PREVIEW_SCREENSHOTS_PER_RUN} from '../plugin/preview-screenshot.mjs';
import {INSPECTION_KIND, createWorkspacePreviewInspectTool, inspectionPlanHash, normalizeWorkspacePreviewInspectionParams}
  from '../plugin/workspace-preview-inspect.mjs';

const root = process.env.OPENCLAW_PACKAGE_DIR;
assert.ok(root, 'provide the reviewed OpenClaw package explicitly');
const sha = value => createHash('sha256').update(value).digest('hex');
// The installed bytes ODS runs: the recipe's patched source.
function reviewed(name, module) {
  const recipe = JSON.parse(fs.readFileSync(new URL(`../host/openclaw-${name}.json`, import.meta.url)));
  let source = fs.readFileSync(path.join(root, 'dist', module), 'utf8');
  const applied = sha(source) === recipe.patchedSha256 ? recipe.replacements : recipe.previousReplacements?.[sha(source)];
  if (applied) for (const [before, after] of [...applied].reverse()) { assert.equal(source.split(after).length, 2); source = source.replace(after, before); }
  assert.equal(sha(source), recipe.sourceSha256, 'reject unknown native runtime bytes');
  for (const [before, after] of recipe.replacements) { assert.equal(source.split(before).length, 2); source = source.replace(before, after); }
  assert.equal(sha(source), recipe.patchedSha256);
  return source;
}
function region(source, name, exported) {
  const start = source.indexOf(`//#region ${name}\n`);
  const end = source.indexOf('//#endregion', start);
  assert.ok(start >= 0 && end > start, name);
  return vm.runInNewContext(`${source.slice(start, end)}\n${exported}`, {Set, Map, Array, Object, JSON, String});
}
const prune = region(reviewed('compaction-budget', 'selection-BEwSQKM-.js'),
  'src/agents/embedded-agent-runner/run/history-image-prune.ts', 'pruneProcessedHistoryImages');
const serialize = region(reviewed('compaction-empty', 'proxy-Bsfwfsp-.js'),
  'packages/agent-core/src/harness/compaction/utils.ts', 'serializeConversation');

// The real tool's result for a vision model, from a stand-in broker.
const site = {siteId: 'site-' + 'a'.repeat(24), sha256: 'a'.repeat(64)};
const PLAN = {...site, viewport: {width: 800, height: 600}, steps: [{action: 'assert-visible', locator: {selector: '#game'}}]};
const segment = (marker, payload) => Buffer.concat([Buffer.from([0xff, marker, (payload.length + 2) >> 8, (payload.length + 2) & 255]), payload]);
function jpeg(seed) {
  const frame = Buffer.from([8, 600 >> 8, 600 & 255, 800 >> 8, 800 & 255, 1, 1, 0x11, 0]);
  return Buffer.concat([Buffer.from([0xff, 0xd8]), segment(0xc0, frame), segment(0xda, Buffer.from([1, 1, 0, 0, 0x3f, 0])),
    Buffer.alloc(2000, seed), Buffer.from([0xff, 0xd9])]);
}
async function inspection(seed) {
  const request = normalizeWorkspacePreviewInspectionParams(structuredClone(PLAN));
  const image = jpeg(seed);
  const state = {count: 1, visible: true, display: 'block', visibility: 'visible', opacity: '1', hidden: false, hiddenUntilFound: false, rectCount: 1};
  const receipt = {schemaVersion: 1, kind: INSPECTION_KIND, status: 'passed', ...site, planSha256: inspectionPlanHash(request),
    viewport: request.viewport, steps: [{index: 0, ...request.steps[0], before: state, stable: true, status: 'passed'}],
    diagnostics: {renderedHiddenAttributeCount: 0, hiddenUntilFoundCount: 0}, blockedRequests: [],
    scope: 'Only the listed CSS layout visibility, normalized visible-text assertions and click dispatches were tested; not pixel paint, occlusion, clipping, a full accessibility audit, or overall functionality.'};
  const tool = createWorkspacePreviewInspectTool({request: async () => ({...receipt, screenshot: {status: 'captured', mimeType: 'image/jpeg',
    width: 800, height: 600, bytes: image.length, sha256: sha(image), data: image.toString('base64')}}),
  screenshots: {capability: () => ({supported: true, directive: {maxSide: 1200, maxPixels: 1048576, maxBytes: 131072}}), reserve: () => 'reserved'}});
  const result = await tool.execute(`call-${seed}`, structuredClone(PLAN));
  assert.deepEqual(result.content.map(block => block.type), ['text', 'image']);
  return {role: 'toolResult', toolCallId: `call-${seed}`, toolName: 'pixel_ods_workspace_preview_inspect', content: result.content, timestamp: 1000 + seed};
}
const call = seed => ({role: 'assistant', content: [{type: 'toolCall', id: `call-${seed}`, name: 'pixel_ods_workspace_preview_inspect', arguments: PLAN}]});
const images = messages => messages.flatMap(message => Array.isArray(message.content) ? message.content.filter(block => block.type === 'image') : []);

test('screenshots leave the prompt once their turn is older than the last three; the current run keeps all of its own', async () => {
  const messages = [];
  for (let turn = 0; turn < 5; turn++) {
    messages.push({role: 'user', content: `turn ${turn}`}, call(turn), await inspection(turn), {role: 'assistant', content: [{type: 'text', text: 'Looked.'}]});
  }
  messages.push({role: 'user', content: 'current'});
  for (let n = 0; n < MAX_PREVIEW_SCREENSHOTS_PER_RUN; n++) messages.push(call(10 + n), await inspection(10 + n));
  const sent = prune(messages);
  const kept = images(sent).map(block => Buffer.from(block.data, 'base64').at(-3));
  // The current turn counts once it has an assistant message, so it is one of the three.
  assert.deepEqual(kept, [3, 4, 10, 11, 12], 'turns 0 to 2 are pruned; the current run keeps every screenshot it took');
  assert.ok(images(sent).length <= 3 * MAX_PREVIEW_SCREENSHOTS_PER_RUN, 'at most three turns of bounded runs');
  for (const turn of [0, 1, 2]) {
    const message = sent.find(item => item.toolCallId === `call-${turn}`);
    assert.deepEqual(message.content.map(block => block.type), ['text', 'text']);
    assert.match(message.content[1].text, /already processed by model/);
    // What the model was told about that screenshot stays in its text.
    assert.match(message.content[0].text, /Screenshot attached: one 800x600 JPEG/);
  }
  assert.equal(images(messages).length, 5 + MAX_PREVIEW_SCREENSHOTS_PER_RUN, 'the stored transcript is not mutated');
});

test('a compaction summary request carries the screenshot sentence, never its bytes', async () => {
  const result = await inspection(7);
  const text = serialize([{role: 'user', content: 'Fix the arena.'}, call(7), result]);
  assert.match(text, /\[Tool result\]: Preview inspection passed\. .*Screenshot attached: one 800x600 JPEG of the whole 800x600 preview viewport/s);
  assert.doesNotMatch(text, new RegExp(result.content[1].data.slice(0, 32).replace(/[+/]/g, '\\$&')));
});
