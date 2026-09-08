import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Execute the real registration block with controlled owners. Gateway auth and
// installed restart/readback still require real integration qualification.
const source = fs.readFileSync(new URL('../plugin/index.js', import.meta.url), 'utf8');
const start = source.indexOf('    api.registerHttpRoute({path: "/pixel-ods/access-runtime"');
const end = source.indexOf('    api.on("tool_result_persist"', start);
assert.ok(start >= 0 && end > start);
function setup(deny = false) {
  let route;
  const calls = [], result = {source: 'current-runtime-config'};
  vm.runInNewContext(source.slice(start, end), {
    api: {registerHttpRoute(value) { route = value; }},
    managedRuntime: {assertTransition() { calls.push('owner'); if (deny) throw new Error(); }, status: () => ({available: true})},
    accessRuntime: {readSettings(token, revision) { calls.push(['read', token, revision]); return result; }},
    sendJson(res, status, body) { Object.assign(res, {status, body}); },
  });
  return {route, calls, result};
}
async function request(route, body, method = 'POST') {
  const res = {};
  const req = {url: '/pixel-ods/access-runtime', method, async *[Symbol.asyncIterator]() { yield Buffer.from(JSON.stringify(body)); }};
  await route.handler(req, res);
  return res;
}
const body = {operation: 'settings-readback', token: 'a'.repeat(64), revision: 'b'.repeat(64)};

test('readback composes existing authenticated route and managed owner check', async () => {
  const {route, calls, result} = setup();
  assert.equal(route.auth, 'gateway');
  assert.equal(route.match, 'exact');
  const res = await request(route, body);
  assert.equal(res.status, 200);
  assert.equal(res.body, result);
  assert.deepEqual(calls, ['owner', ['read', body.token, body.revision]]);
});
test('busy managed owner prevents readback without reaching config', async () => {
  const {route, calls} = setup(true);
  assert.equal((await request(route, body)).status, 409);
  assert.deepEqual(calls, ['owner']);
});
test('unknown fields and malformed identities fail before owner or readback', async () => {
  for (const changed of [{...body, path: '/private'}, {...body, token: 'bad'}, {...body, revision: null}]) {
    const {route, calls} = setup();
    assert.equal((await request(route, changed)).status, 409);
    assert.deepEqual(calls, []);
  }
});
test('GET remains status-only and does not expose settings or enter transition', async () => {
  const {route, calls} = setup();
  const res = await request(route, null, 'GET');
  assert.equal(res.status, 200);
  assert.deepEqual(calls, []);
  assert.equal(res.body.source, undefined);
});

test('registration supplies the SDK current snapshot lazily, separate from startup probe config', () => {
  const begin = source.indexOf('    accessRuntime ??= createAccessRuntime(');
  const finish = source.indexOf('    const managedRuntime =', begin);
  assert.ok(begin >= 0 && finish > begin);
  const startup = {generation: 'startup'};
  let current = {generation: 'current'}, reads = 0;
  const context = {api: {config: startup, runtime: {config: {current() { reads++; return current; }}}},
    accessRuntime: undefined, createAccessRuntime: options => options,
    createOpenClawCodingTools() {}, resolveSandboxContext() {}, execCancellationControl: {},
    OPENCLAW_VERSION: '2026.6.33'};
  vm.runInNewContext(source.slice(begin, finish), context);
  const options = context.accessRuntime;
  assert.equal(reads, 0);
  assert.equal(options.config(), startup);
  assert.equal(options.settingsConfig(), current);
  current = {generation: 'reloaded'};
  assert.equal(options.settingsConfig(), current);
  assert.equal(reads, 2);
});
