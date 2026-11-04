const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const xml = readFileSync(
  resolve(__dirname, '../../bridgelink/code-templates/OL_CORE.xml'), 'utf8'
);
const scripts = Array.from(
  xml.matchAll(/<code><!\[CDATA\[([\s\S]*?)\]\]><\/code>/g),
  match => match[1]
);
assert.equal(scripts.length, 3);
const core = vm.createContext({});
vm.runInContext(scripts.join('\n'), core);

function headers(values) {
  return {
    getHeader(name) {
      const key = Object.keys(values).find(key => key.toLowerCase() === name.toLowerCase());
      return key === undefined ? null : values[key];
    }
  };
}

function readRequest(values, body) {
  return core.olCoreReadHttpRequest({get: key => values[key]}, body);
}

test('headers use MessageHeaders.getHeader and preserve the original value', () => {
  const value = 'Bearer synthetic-test-value';
  assert.equal(core.olCoreGetHeader(headers({authorization: value}), 'Authorization'), value);
  assert.equal(core.olCoreGetHeader(headers({AUTHORIZATION: value}), 'Authorization'), value);
  assert.equal(core.olCoreGetHeader(headers({}), 'Authorization'), '');
  assert.equal(core.olCoreGetHeader(null, 'Authorization'), '');
  assert.equal(core.olCoreGetHeader(headers({Accept: {toString: () => 'application/json'}}), 'Accept'), 'application/json');
  assert.throws(() => core.olCoreGetHeader({}, 'Authorization'));
});

test('request parsing preserves query, body, percent encoding and trailing slash', () => {
  const body = '<ClinicalDocument>synthetic</ClinicalDocument>\n';
  const request = readRequest({
    uri: '/V1/CDA/VACD/Convert/?bundle_type=document&x=A%2FB?C',
    method: 'post',
    headers: headers({authorization: 'Bearer synthetic-test-value'})
  }, body);
  assert.equal(request.method, 'POST');
  assert.equal(request.path, '/v1/cda/vacd/convert/');
  assert.equal(request.query, '?bundle_type=document&x=A%2FB?C');
  assert.equal(request.body, body);
  assert.equal(request.authorization, 'Bearer synthetic-test-value');
});

test('request parsing keeps existing empty-value and whitespace behavior', () => {
  const empty = readRequest({}, '');
  assert.equal(empty.path, '');
  assert.equal(empty.query, '');
  assert.equal(empty.method, '');
  assert.equal(empty.authorization, '');
  assert.equal(empty.body, '');
  const request = readRequest({uri: ' /V1/CDA/convert ', method: ' post '}, 'raw');
  assert.equal(request.path, ' /v1/cda/convert ');
  assert.equal(request.method, ' POST ');
  assert.equal(readRequest({uri: '/v1/cda/import'}, 'raw').query, '');
  assert.equal(readRequest({uri: '/v1/cda/import?'}, 'raw').query, '?');
});

test('gateway errors preserve the existing map contract and escape diagnostics', () => {
  for (const [status, code] of [[400, 'invalid'], ['404', 'not-found'], [502, 'exception']]) {
    const values = new Map([['responseTarget', 'hapi']]);
    core.olCoreSetGatewayError(
      {put: (key, value) => values.set(key, value)},
      status, code, 'Synthetic "message"\nwith newline'
    );
    assert.equal(values.get('gatewayErrorStatusCode'), String(status));
    assert.deepEqual(JSON.parse(values.get('gatewayError')), {
      resourceType: 'OperationOutcome',
      issue: [{
        severity: 'error', code,
        diagnostics: 'Synthetic "message"\nwith newline'
      }]
    });
    assert.equal(values.get('responseTarget'), 'hapi');
    assert.equal(values.size, 3);
  }
});

test('invalid error arguments fail explicitly before modifying the map', () => {
  for (const [status, code, diagnostics] of [
    [200, 'invalid', 'error'], [600, 'invalid', 'error'],
    ['400 bad', 'invalid', 'error'], [null, 'invalid', 'error'],
    [400, '', 'error'], [400, 'invalid', null]
  ]) {
    const values = new Map();
    assert.throws(() => core.olCoreSetGatewayError(
      {put: (key, value) => values.set(key, value)}, status, code, diagnostics
    ));
    assert.equal(values.size, 0);
  }
});
