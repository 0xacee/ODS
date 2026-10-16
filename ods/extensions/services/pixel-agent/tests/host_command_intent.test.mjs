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

function observe(prompt) {
  const guard = api.createToolLoopGuard();
  guard.observeRun({agentId: 'pixel', runId: 'run-1', sessionId: 'session-1'}, 'pixel', {prompt});
  return guard;
}

for (const text of [
  SPARK_SENTENCE,
  SPARK_FEEDBACK,
  // A UI noun names part of the owner's project.
  'The start menu on my machine is too big.',
  'The start button is hidden on my laptop.',
  'The start page on this computer loads slowly.',
  'On this machine the restart button does nothing.',
  'The update screen on my computer flickers.',
  'On my laptop the install page is blank.',
  'On my machine it looks fine at the start of the level.',
  'The change log on my laptop is empty.',
  'The changelog on my laptop is empty.',
  'The start and restart buttons overlap on my laptop.',
  'The title screen and start screens on my laptop get cut off.',
  'The start/restart buttons on my laptop overlap.',
  'The "Start" button is hidden on my laptop.',
  'The “Start” button is hidden on my laptop.',
  // A preposition, quantifier or button press names a moment in the game.
  'This computer shows a black screen at start.',
  'This computer shows a black screen on restart.',
  'This computer shows a black screen after update.',
  'Every restart resets the score on my laptop.',
  'Each restart resets the score on my laptop.',
  'After the latest update the game is slow on my laptop.',
  'The new update broke the game on my laptop.',
  'The last restart fixed it on my laptop.',
  'The restart button freezes my laptop when I press start.',
  // A negation describes what a thing did.
  "The game won't start on my laptop.",
  "On my laptop the game doesn't update the score.",
  "The game can't start on my laptop.",
  "My laptop can't run the game.",
  'The game does not start on my laptop.',
  'The game did not start on my machine.',
  'The game will not start on my laptop.',
  'Why does the game not start on my laptop?',
  'It fails to start on my laptop.',
  'It refuses to start on my laptop.',
  // The owner describes their own action.
  'When I restart the level on my machine it crashes.',
  'When I start the game on my laptop it freezes.',
  'It crashes on my laptop when I start the game.',
  'The game crashes when I run it on my laptop.',
  'My laptop gets hot when I run the game.',
  'I tried to start the game on my laptop and it froze.',
  'Also, on my laptop it crashes after I restart.',
  'One more thing: on my laptop the game crashes when I restart.',
  'Looks great on desktop but on my laptop it crashes when I restart.',
  'The start screen froze my laptop and I had to restart.',
  'The install page crashed my laptop when I tried to run it.',
  'The start menu hangs my laptop until I stop the game.',
  'The update broke my laptop when I start the game.',
  'Work in Playground/elf-of-doom only. When I restart the level on my laptop it crashes.',
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
  'I want to restart Docker on my laptop.',
  // A leading host phrase still names the target of the request.
  'On my laptop, please restart Docker.',
  'On this ODS host, go ahead and restart Docker.',
  'On my laptop, just restart Docker.',
  'On my laptop I need you to restart Docker.',
  'On my machine, sudo apt install htop.',
  'In my laptop terminal run df -h.',
  // A UI noun after a word that opens the request is its object.
  'Delete log files on my laptop.',
  'Change screen resolution on my laptop.',
  'Start screen recording on my machine.',
  'Can you delete log files on my laptop?',
  // The owner could not do it and asks Pixel to.
  "I can't restart Docker on my laptop, please do it for me.",
  "I couldn't install htop on my machine, can you do it?",
  // A workspace scope elsewhere in the message does not hide the request.
  'Only work in Playground/elf-of-doom. Restart Docker on my laptop.',
  'Only work in Playground/elf-of-doom. Restart Docker on this ODS host.',
  'Restart Docker on my laptop. Then only work in Playground/elf-of-doom for the game fix.',
  "You don't have to only work in the sandbox. Restart Docker on my laptop.",
]) {
  test(`an action verb aimed at the host is still a host command: ${text}`, () => {
    assert.equal(api.userMessageRequestsHostCommand([], text), true);
    assert.deepEqual(api.userMessageOperationsRequirements([], text),
      {required: true, actions: ['raw-shell']});
  });
}

for (const prompt of [
  SPARK_SENTENCE,
  SPARK_FEEDBACK,
  'When I restart the level on my machine it crashes.',
  'The start screen froze my laptop and I had to restart.',
]) {
  test(`game feedback keeps workspace tools: ${prompt}`, () => {
    const guard = observe(prompt);
    const read = call(guard, 'read', {path: 'Playground/elf-of-doom/index.html'});
    assert.notEqual(read?.block, true, read?.blockReason);
    const exec = call(guard, 'exec', {command: 'ls Playground/elf-of-doom'});
    assert.notEqual(exec?.block, true, exec?.blockReason);
  });
}

for (const prompt of [
  'On this ODS host, go ahead and restart Docker.',
  'Delete log files on my laptop.',
]) {
  test(`a host request goes through the approval proposal, not generic exec: ${prompt}`, () => {
    const guard = observe(prompt);
    assert.deepEqual(call(guard, 'exec', {command: 'sudo systemctl restart docker'}), {
      block: true,
      blockReason: api.OPERATIONS_HOST_COMMAND_REQUIRES_PROPOSAL_REASON,
    });
    const proposal = call(guard, 'pixel_ods_host_command_propose', {command: 'sudo systemctl restart docker'});
    assert.notEqual(proposal?.block, true, proposal?.blockReason);
  });
}
