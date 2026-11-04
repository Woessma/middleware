const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const xml = readFileSync(resolve(__dirname, '../../bridgelink/api_route_dispatcher.xml'), 'utf8');
const decode = value => value.replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&apos;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&');
const scripts = Array.from(xml.matchAll(/<script>([\s\S]*?)<\/script>/g), m => decode(m[1]));
const auth = scripts.find(script => script.includes('return omniLinkJwtAuthenticate();'));
const response = scripts.find(script => script.includes('function setClientResponse'));
assert.ok(auth);
assert.ok(response);

function authenticate(method, headers, jwtResult) {
  let jwtCalls = 0;
  const context = vm.createContext({
    sourceMap: new Map([
      ['method', method], ['headers', {getHeader: name => headers[name] || null}]
    ]),
    omniLinkJwtAuthenticate: () => { jwtCalls++; return jwtResult; }
  });
  const result = vm.runInContext(`(function(){${auth}})()`, context);
  return {result, jwtCalls};
}

test('only approved-origin GET/POST preflights bypass JWT', () => {
  for (const method of ['GET', 'POST']) {
    assert.deepEqual(authenticate('OPTIONS', {
      Origin: 'https://middleware.local.omnilink.ch',
      'Access-Control-Request-Method': method
    }, false), {result: true, jwtCalls: 0});
  }
  for (const headers of [
    {}, {Origin: 'https://evil.invalid', 'Access-Control-Request-Method': 'POST'},
    {Origin: 'https://middleware.local.omnilink.ch', 'Access-Control-Request-Method': 'DELETE'}
  ]) {
    assert.deepEqual(authenticate('OPTIONS', headers, true), {result: false, jwtCalls: 0});
  }
});

test('actual requests always retain original JWT authentication', () => {
  for (const method of ['POST', 'GET', 'DELETE']) {
    for (const jwtResult of [false, true]) {
      assert.deepEqual(authenticate(method, {
        Origin: 'https://middleware.local.omnilink.ch',
        'Access-Control-Request-Method': 'POST'
      }, jwtResult), {result: jwtResult, jwtCalls: 1});
    }
  }
});

test('preflight response is empty 204 instead of falling through to HAPI', () => {
  const statuses = new Map();
  const context = vm.createContext({
    channelMap: new Map([['corsPreflight', 'true'], ['responseTarget', 'none']]),
    responseMap: {put: (key, value) => statuses.set(key, value)},
    logger: {error: assert.fail, warn: assert.fail}
  });
  vm.runInContext(response, context);
  assert.equal(context.msg, '');
  assert.equal(statuses.get('responseStatusCode'), '204');
});

test('listener response headers allow only exact workbench origin and expected headers', () => {
  const block = xml.match(/<responseHeaders class="linked-hash-map">([\s\S]*?)<\/responseHeaders>/)[1];
  assert.match(block, /https:\/\/middleware\.local\.omnilink\.ch/);
  assert.match(block, /GET, POST, OPTIONS/);
  assert.match(block, /Authorization, Content-Type, Accept/);
  assert.doesNotMatch(block, /\*|Access-Control-Allow-Credentials/);
});
