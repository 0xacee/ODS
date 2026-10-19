import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const {start} = await import(process.env.PIXEL_INGRESS_MODULE ?? '../host/pixel_ingress.mjs');

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function eventually(check) {
  const deadline = Date.now() + 2000;
  while (Date.now() < deadline) {
    try { check(); return; } catch { await delay(10); }
  }
  check();
}
function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'px-refresh-'));
  const config = path.join(dir, 'openclaw.json');
  const status = path.join(dir, 'status.json');
  const write = (model, context = 65536) => {
    fs.writeFileSync(config, JSON.stringify({
      gateway: {auth: {token: 'synthetic-refresh-test-token'}},
      agents: {list: [{id: 'pixel', model: 'ods-gateway/ods/current'}]},
      models: {providers: {'ods-gateway': {models: [{
        id: 'ods/current', name: `ODS Current (${model})`,
        contextWindow: context, maxTokens: 8192, reasoning: false,
      }]}}},
    }), {mode: 0o600});
    fs.chmodSync(config, 0o600);
  };
  write('local-before.gguf');
  return {dir, config, status, write, cfg: {
    socketPath: path.join(dir, 'ingress.sock'), gatewayTokenFile: config,
    gatewayPort: 18999, statusFile: status, statusIntervalMs: 10,
    ingressGid: null, odsVersion: '3.0.0',
  }};
}
const ok = () => ({status: 200, body: {cancel: async () => {}}});
const unavailableDocker = (_command, _args, _options, callback) => callback(new Error('unavailable'));

test('running ingress follows rewritten model config and reports unsafe evidence as unknown', async () => {
  const f = fixture();
  const inspections = [];
  const h = await start(f.cfg, {deps: {
    fetch: async () => ok(),
    execFile: (_command, args, _options, callback) => {
      inspections.push(args[0]);
      if (args[0] === 'ps') callback(null, JSON.stringify({Names:'ods-llama-server',Status:'Up (healthy)'})+'\n', '');
      else callback(null, JSON.stringify(['--model','/models/unrelated-local.gguf','--ctx-size','32768']), '');
    },
  }});
  const runtime = () => JSON.parse(fs.readFileSync(f.status, 'utf8')).runtime;
  try {
    assert.equal(runtime().model, 'local-before.gguf');
    f.write('remote/after', 131072);
    await eventually(() => assert.deepEqual(runtime(), {model:'remote/after', context_length:131072}));
    fs.chmodSync(f.config, 0o644);
    await eventually(() => assert.equal(runtime(), null));
    f.write('restored-local.gguf');
    await eventually(() => assert.equal(runtime().model, 'restored-local.gguf'));
    fs.writeFileSync(f.config, '{invalid json');
    await eventually(() => assert.equal(runtime(), null));
    assert.ok(inspections.every(operation => operation === 'ps'));
  } finally {
    await h.close();
    fs.rmSync(f.dir, {recursive:true, force:true});
  }
});

test('periodic status probes do not overlap and close waits for the active projection', async () => {
  const f = fixture();
  let calls = 0;
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  const h = await start(f.cfg, {deps: {
    fetch: async () => { if (++calls > 1) await blocked; return ok(); },
    execFile: unavailableDocker,
  }});
  let closing;
  try {
    await eventually(() => assert.equal(calls, 2));
    await delay(60);
    assert.equal(calls, 2);
    let closed = false;
    closing = h.close().then(() => { closed = true; });
    await delay(20);
    assert.equal(closed, false);
    release();
    await closing;
    const final = fs.readFileSync(f.status, 'utf8');
    await delay(30);
    assert.equal(calls, 2);
    assert.equal(fs.readFileSync(f.status, 'utf8'), final);
  } finally {
    release();
    await (closing ?? h.close());
    fs.rmSync(f.dir, {recursive:true, force:true});
  }
});
