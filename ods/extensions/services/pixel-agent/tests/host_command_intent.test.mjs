import test from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

const api = await import(process.env.GUARD_MODULE
  ? pathToFileURL(process.env.GUARD_MODULE).href : '../plugin/tool-loop-guard.mjs');

// Observed on an RTX Spark: game feedback for a Playground canvas game named
// the laptop the owner viewed it on, and "start" in "start screen" read as a
// host action. Every tool, workspace read included, was then blocked until
// the run-progress guard ended the turn.
const SPARK_SENTENCE =
  "On my laptop the start screen gets cut off, the top icon is chopped and I can't see the Try ODS link at all.";
const SPARK_FEEDBACK =
  `Some feedback on the elf game. ${SPARK_SENTENCE} Only work in Playground/elf-of-doom.`;

function call(guard, toolName, params) {
  return guard.beforeToolCall(
    {toolName, runId: 'run-1', params},
    {agentId: 'pixel', toolName, runId: 'run-1', sessionId: 'session-1'},
    'pixel');
}

for (const text of [
  SPARK_SENTENCE,
  SPARK_FEEDBACK,
  'The start menu on my machine is too big.',
  'The start button is hidden on my laptop.',
  'The start page on this computer loads slowly.',
  'On this machine the restart button does nothing.',
  'The update screen on my computer flickers.',
  'On my laptop the install page is blank.',
  'On my machine it looks fine at the start of the level.',
  'The change log on my laptop is empty.',
  'The changelog on my laptop is empty.',
  "The game won't start on my laptop.",
  "On my laptop the game doesn't update the score.",
  'Only work in Playground/elf-of-doom. Restart Docker on my laptop.',
]) {
  test(`describing the owner's project on a host is not a host command: ${text}`, () => {
    assert.equal(api.userMessageRequestsHostCommand([], text), false);
  });
}

for (const text of [
  'Start the docker service on my laptop.',
  "Restart my machine's ODS services.",
  'Update ODS on this machine.',
  'Restart Docker on my laptop.',
  'Run `df -h` on my laptop.',
  'Install htop on this machine.',
  'On my laptop, please restart Docker.',
  'Only work in Playground/elf-of-doom. Restart Docker on this ODS host.',
]) {
  test(`an action verb aimed at the host is still a host command: ${text}`, () => {
    assert.equal(api.userMessageRequestsHostCommand([], text), true);
    assert.deepEqual(api.userMessageOperationsRequirements([], text),
      {required: true, actions: ['raw-shell']});
  });
}

for (const prompt of [SPARK_SENTENCE, SPARK_FEEDBACK]) {
  test(`game feedback keeps workspace tools: ${prompt}`, () => {
    const guard = api.createToolLoopGuard();
    guard.observeRun({agentId: 'pixel', runId: 'run-1', sessionId: 'session-1'}, 'pixel', {prompt});
    const read = call(guard, 'read', {path: 'Playground/elf-of-doom/index.html'});
    assert.notEqual(read?.block, true, read?.blockReason);
    const exec = call(guard, 'exec', {command: 'ls Playground/elf-of-doom'});
    assert.notEqual(exec?.block, true, exec?.blockReason);
  });
}
