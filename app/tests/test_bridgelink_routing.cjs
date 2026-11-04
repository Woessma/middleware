const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const root = resolve(__dirname, '../../bridgelink');
const scripts = ['OL_CORE', 'OL_ROUTING'].flatMap(name => {
  const xml = readFileSync(resolve(root, `code-templates/${name}.xml`), 'utf8');
  const matches = Array.from(
    xml.matchAll(/<code><!\[CDATA\[([\s\S]*?)\]\]><\/code>/g),
    match => match[1]
  );
  assert.equal(matches.length, name === 'OL_CORE' ? 3 : 2);
  return matches;
}).join('\n');
const transformer = readFileSync(resolve(root, 'transformers/route-request.js'), 'utf8');

function dispatch(method, uri, body = 'synthetic input', baseUrl, extraHeaders = {}) {
  const values = new Map();
  const logs = [];
  const source = new Map([
    ['method', method], ['uri', uri],
    ['headers', {getHeader: name => name === 'Authorization'
      ? 'synthetic authorization' : extraHeaders[name] || null}]
  ]);
  const context = vm.createContext({
    sourceMap: source,
    connectorMessage: {getRawData: () => body},
    channelMap: {put: (key, value) => values.set(key, value)},
    logger: {
      info: message => logs.push(['info', message]),
      warn: message => logs.push(['warn', message])
    }
  });
  vm.runInContext(scripts, context);
  if (baseUrl === undefined) {
    vm.runInContext(transformer, context);
  } else {
    context.baseUrl = baseUrl;
    vm.runInContext(
      'olRouteApply(olCoreReadHttpRequest(sourceMap, connectorMessage.getRawData()), channelMap, baseUrl, logger);',
      context
    );
  }
  return {values, logs, context};
}

const routes = [
  ['POST', '/v1/cda/vacd/convert', '/cda/vacd/convert', 'none', true, 'vacd.convert'],
  ['POST', '/v1/cda/vacd/import', '/cda/vacd/prepare', 'none', true, 'vacd.import'],
  ['POST', '/v1/cda/vacd/validate', '/cda/vacd/validate', 'none', true, 'vacd.validate'],
  ['POST', '/v1/cda/validate', '/cda/validate', 'none', true, 'cda.validate'],
  ['POST', '/v1/fhir/validate', '/fhir/validate', 'none', false, 'fhir.validate'],
  ['POST', '/v1/cda/convert', '/cda/convert', 'none', true, 'cda.convert'],
  ['POST', '/v1/cda/import', '/cda/convert', 'hapi', true, 'cda.import'],
  ['POST', '/v1/emediplan/import', '/emediplan/prepare', 'hapi', false, 'emediplan.import'],
  ['POST', '/v1/emediplan/convert', '/emediplan/convert', 'none', false, 'emediplan.convert'],
  ['POST', '/v1/echosos/resolve', '/echosos/qr', 'hapi', false, 'echosos.resolve'],
  ['GET', '/v1/.well-known/jwks.json', '/.well-known/jwks.json', 'none', false, 'epic.jwks']
];

for (const [method, path, upstream, responseTarget, forwardQuery, id] of routes) {
  test(`${id}: transformer preserves destination, query, method and map contract`, () => {
    for (const query of ['', '?bundle_type=document&x=A%2FB?C']) {
      const {values, logs, context} = dispatch(method.toLowerCase(), path.toUpperCase() + query);
      assert.equal(values.get('targetUrl'),
        'https://middleware.local.omnilink.ch' + upstream + (forwardQuery ? query : ''));
      assert.equal(values.get('responseTarget'), responseTarget);
      assert.equal(values.get('requestBody'), method === 'GET' ? '' : 'synthetic input');
      assert.equal(values.get('targetMethod'), method);
      assert.equal(values.get('middlewareAuthorization'), 'synthetic authorization');
      assert.equal(values.has('gatewayError'), false);
      assert.equal(values.has('gatewayErrorStatusCode'), false);
      assert.equal(values.size, 5);
      assert.equal(context.olRouteResolve(method, path).id, id);
      assert.equal(logs.some(([level]) => level === 'warn'), false);
      assert.equal(logs.some(([, message]) => message.includes('synthetic authorization')), false);
      assert.equal(logs.some(([, message]) => message.includes('synthetic input')), false);
    }
  });
}

test('unsupported paths and methods remain 404, with no destination selected', () => {
  const requests = [
    ['POST', '/v1/unknown'], ['GET', '/v1/cda/convert'],
    ['POST', '/v1/.well-known/jwks.json'],
    ['POST', '/v1/cda/convert/'], ['POST', '/v1/cda/%63onvert'],
    ['POST', ' /v1/cda/convert'], ['POST', '/v1/cda/vacd/send'],
    ['', '']
  ];
  for (const [method, path] of requests) {
    const {values, logs} = dispatch(method, path);
    assert.equal(values.get('gatewayErrorStatusCode'), '404');
    assert.deepEqual(JSON.parse(values.get('gatewayError')), {
      resourceType: 'OperationOutcome',
      issue: [{
        severity: 'error', code: 'not-found',
        diagnostics: 'Unknown endpoint: ' + path
      }]
    });
    assert.equal(values.get('responseTarget'), 'none');
    assert.equal(values.has('targetUrl'), false);
    assert.equal(logs.filter(([level]) => level === 'warn').length, 1);
  }
});

test('existing CDA encoding rejection remains 400 and prevents import routing', () => {
  for (const path of ['/v1/cda/convert', '/v1/cda/import']) {
    for (const marker of ['\u00c3', '\u00c2', '\ufffd']) {
      const {values, logs} = dispatch('POST', path, '<synthetic>' + marker + '</synthetic>');
      assert.equal(values.get('gatewayErrorStatusCode'), '400');
      const issue = JSON.parse(values.get('gatewayError')).issue[0];
      assert.equal(issue.code, 'invalid');
      assert.equal(issue.severity, 'error');
      assert.match(issue.diagnostics, /charset=UTF-8/);
      assert.equal(values.get('responseTarget'), 'none');
      assert.equal(values.has('targetUrl'), false);
      assert.ok(logs.some(([level, message]) => level === 'warn' && message.includes('rejected')));
    }
    const {values} = dispatch('POST', path, '<synthetic>Gr\u00fcsse</synthetic>');
    assert.equal(values.has('gatewayError'), false);
  }
});

test('encoding heuristic is not newly applied to VACD, eMediplan or EchoSOS', () => {
  for (const [, path] of routes.filter(([, path]) => ![
    '/v1/cda/convert', '/v1/cda/import'
  ].includes(path))) {
    const {values} = dispatch(path.includes('jwks') ? 'GET' : 'POST', path, '\u00c3\u00c2\ufffd');
    assert.equal(values.has('gatewayError'), false);
    assert.equal(values.has('targetUrl'), true);
  }
});

test('routing has no shared mutable table or clinical processing', () => {
  const {context} = dispatch('POST', '/v1/cda/convert');
  context.olRouteResolve('POST', '/v1/cda/import').middlewarePath = '/unexpected';
  assert.equal(context.olRouteResolve('POST', '/v1/cda/import').middlewarePath, '/cda/convert');
  assert.equal(context.OL_ROUTES, undefined);
  assert.equal(context.globalMap, undefined);
});

test('explicit base URL supports another environment, missing configuration throws', () => {
  const {values} = dispatch('POST', '/v1/cda/convert', 'synthetic', 'https://middleware.example');
  assert.equal(values.get('targetUrl'), 'https://middleware.example/cda/convert');
  for (const baseUrl of ['', null]) {
    assert.throws(() => dispatch('POST', '/v1/cda/import', 'synthetic', baseUrl),
      /middlewareBaseUrl is required/);
  }
});

test('allowed browser preflights return locally without any write destination', () => {
  for (const [method, path] of routes) {
    const {values} = dispatch('OPTIONS', path, '', undefined, {
      Origin: 'https://middleware.local.omnilink.ch',
      'Access-Control-Request-Method': method,
      'Access-Control-Request-Headers': 'authorization, Content-Type'
    });
    assert.equal(values.get('corsPreflight'), 'true');
    assert.equal(values.get('responseTarget'), 'none');
    assert.equal(values.has('targetUrl'), false);
    assert.equal(values.has('fhirJson'), false);
    assert.equal(values.has('gatewayError'), false);
  }
});

test('invalid preflight origins, methods, headers and paths never reach destinations', () => {
  const allowed = {
    Origin: 'https://middleware.local.omnilink.ch',
    'Access-Control-Request-Method': 'POST',
    'Access-Control-Request-Headers': 'authorization,content-type'
  };
  for (const [path, overrides, status] of [
    ['/v1/cda/convert', {Origin: 'https://untrusted.invalid'}, '403'],
    ['/v1/cda/convert', {Origin: ''}, '403'],
    ['/v1/cda/convert', {'Access-Control-Request-Method': 'DELETE'}, '404'],
    ['/v1/cda/convert', {'Access-Control-Request-Headers': 'x-unapproved'}, '403'],
    ['/v1/unknown', {}, '404']
  ]) {
    const {values} = dispatch('OPTIONS', path, '', undefined, {...allowed, ...overrides});
    assert.equal(values.get('gatewayErrorStatusCode'), status);
    assert.equal(values.has('corsPreflight'), false);
    assert.equal(values.has('targetUrl'), false);
    assert.equal(values.has('fhirJson'), false);
  }
});
