const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const html = readFileSync(resolve(__dirname, '../../test-client.html'), 'utf8');

function workbench() {
  const elements = {
    fileInput: {files: []},
    payload: {value: ''},
    params: {querySelectorAll: () => []}
  };
  const context = vm.createContext({
    URL, FormData, Blob,
    el: elements,
    auth: () => ({Authorization: 'Bearer synthetic-test-token'}),
    window: {location: {origin: 'https://middleware.example'}},
    document: {getElementById: () => ({value: 'https://api.example/v1'})}
  });
  const script = html.slice(html.indexOf('const sampleBundle='), html.indexOf('const el='));
  const approved = html.slice(html.indexOf('const approvedUseCaseIds='), html.indexOf('function current()'));
  const requests = html.slice(html.indexOf('function urlFor('), html.indexOf('function parse('));
  vm.runInContext(`${script}\n${approved}\n${requests}\nthis.approved=visibleCases();`, context);
  return {context, elements, cases: context.approved};
}

test('only implemented routes are released', () => {
  const {cases} = workbench();
  assert.deepEqual(Array.from(cases, item => item.id), [
    'patient-everything', 'bundle-import', 'cda-convert', 'cda-import',
    'emed-convert', 'emed-import', 'emed-qr-convert', 'emed-qr-import', 'echosos-resolve'
  ]);
});

for (const id of ['emed-convert', 'emed-import']) {
  test(`${id}: JSON and CHMED16A use matching content types and BridgeLink URL`, () => {
    const {context, elements, cases} = workbench();
    const item = cases.find(item => item.id === id);
    for (const [payload, contentType] of [
      ['{"Medicaments":[]}', 'application/json'],
      ['CHMED16A0{"Medicaments":[]}', 'text/plain; charset=utf-8'],
      ['CHMED16A1synthetic', 'text/plain; charset=utf-8']
    ]) {
      elements.payload.value = payload;
      const request = context.requestFor(item);
      assert.equal(request.headers['Content-Type'], contentType);
      assert.equal(request.headers.Authorization, 'Bearer synthetic-test-token');
      assert.equal(request.body, payload);
      assert.equal(context.urlFor(item).href, 'https://api.example/v1' + item.path);
    }
    elements.payload.value = '{invalid';
    assert.throws(() => context.requestFor(item));
  });
}

test('FHIR bundle import uses the supported BridgeLink import route', () => {
  const {context, elements, cases} = workbench();
  const item = cases.find(item => item.id === 'bundle-import');
  elements.payload.value = JSON.stringify(item.template);
  assert.equal(context.urlFor(item).pathname, '/v1/emediplan/import');
  assert.equal(context.requestFor(item).headers['Content-Type'], 'application/fhir+json');
});

for (const id of ['emed-qr-convert', 'emed-qr-import']) {
  test(`${id}: multipart file goes to the existing same-origin middleware endpoint`, () => {
    const {context, elements, cases} = workbench();
    const item = cases.find(item => item.id === id);
    assert.throws(() => context.requestFor(item), /Datei/);
    elements.fileInput.files = [Object.assign(new Blob(['synthetic'], {type: 'image/png'}), {name: 'qr.png'})];
    const request = context.requestFor(item);
    assert.equal(context.urlFor(item).href, 'https://middleware.example' + item.path);
    assert.equal(request.headers['Content-Type'], undefined);
    assert.equal(request.body.get('file').name, 'qr.png');
  });
}

test('EchoSOS URL uses resolve, not the unsupported external qr route', () => {
  const {context, elements, cases} = workbench();
  const item = cases.find(item => item.id === 'echosos-resolve');
  elements.payload.value = 'https://eid.echosos.com/#synthetic';
  assert.equal(context.urlFor(item).pathname, '/v1/echosos/resolve');
  assert.equal(context.requestFor(item).body, elements.payload.value);
});
