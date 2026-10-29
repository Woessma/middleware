const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const html = readFileSync(resolve(__dirname, '../../echosos-fhir-test.html'), 'utf8');
const importCode = html.slice(html.indexOf('async function importEcho(){'),
  html.indexOf('const renderWithMedicationOrder=render;'));
const validationCode = html.slice(html.indexOf('function isEchoSosUrl(value){'),
  html.indexOf('function nameOf(p)'));
const sourceUrl = 'https://eid.echosos.com/#f=Test&l=Example&g=fGBP&i=Test%20%26%20text';
const transaction = {
  resourceType: 'Bundle',
  type: 'transaction-response',
  entry: [{response: {status: '200 OK', location: 'Patient/test-id/_history/1'}}]
};

function client({file, camera = '', preview = {source_url: sourceUrl},
  previewError, result = transaction} = {}) {
  const elements = {
    qrFile: {files: file ? [file] : []},
    qrPreview: {classList: {remove() {}}},
    import: {disabled: false},
    patientId: {value: ''}
  };
  const calls = [];
  const messages = [];
  const patients = [];
  const rendered = [];
  const context = vm.createContext({
    URL, Set,
    cameraValue: camera,
    $: id => elements[id],
    base: () => '/echosos/import',
    show: (message, error) => messages.push({message, error}),
    renderEchoPreview: value => rendered.push(value),
    loadPatientEverything: async id => patients.push(id),
    request: async (url, options) => {
      calls.push({url, options});
      if (url === '/echosos/preview') {
        if (previewError) throw previewError;
        return preview;
      }
      return result;
    }
  });
  vm.runInContext(validationCode + '\n' + importCode, context);
  return {context, calls, messages, patients, rendered, elements};
}

for (const [name, input] of [
  ['PNG', {file: {name: 'synthetic.png', type: 'image/png'}}],
  ['PKPass', {file: {name: 'synthetic.pkpass', type: ''}}],
  ['camera', {camera: sourceUrl}]
]) {
  test(`${name}: preview original input, import decoded URL only`, async () => {
    const state = client(input);
    await state.context.importEcho();
    assert.equal(state.calls.length, 2);
    assert.equal(state.calls[0].url, '/echosos/preview');
    assert.equal(state.calls[0].options.body, input.file || input.camera);
    assert.equal(state.calls[0].options.headers['Content-Type'],
      input.file ? input.file.type || 'application/vnd.apple.pkpass' : 'text/plain; charset=utf-8');
    const sent = state.calls[1];
    assert.equal(sent.url, '/echosos/import');
    assert.equal(sent.options.method, 'POST');
    assert.equal(sent.options.body, sourceUrl);
    assert.equal(sent.options.headers['Content-Type'], 'text/plain; charset=utf-8');
    assert.equal(sent.options.headers.Accept, 'application/json');
    assert.deepEqual(state.patients, ['test-id']);
    assert.equal(state.rendered.length, 1);
    assert.equal(state.elements.import.disabled, false);
  });
}

for (const preview of [{}, {source_url: null}, {source_url: 123},
  {source_url: 'https://example.org/#f=Test'}, {source_url: 'not a URL'}]) {
  test(`invalid preview URL blocks import: ${JSON.stringify(preview)}`, async () => {
    const state = client({file: {name: 'synthetic.png', type: 'image/png'}, preview});
    await state.context.importEcho();
    assert.equal(state.calls.length, 1);
    assert.equal(state.rendered.length, 0);
    assert.equal(state.patients.length, 0);
    assert.equal(state.messages.at(-1).error, true);
    assert.equal(state.elements.import.disabled, false);
  });
}

test('preview failure blocks import', async () => {
  const state = client({camera: sourceUrl, previewError: new Error('Decode failed')});
  await state.context.importEcho();
  assert.equal(state.calls.length, 1);
  assert.equal(state.messages.at(-1).message, 'Decode failed');
  assert.equal(state.messages.at(-1).error, true);
  assert.equal(state.elements.import.disabled, false);
});

test('FHIR error does not start patient lookup or confirm persistence', async () => {
  const state = client({camera: sourceUrl, result: {
    ...transaction,
    entry: [{response: {status: '400 Bad Request'}}]
  }});
  await state.context.importEcho();
  assert.equal(state.patients.length, 0);
  assert.equal(state.messages.at(-1).error, true);
  assert.match(state.messages.at(-1).message, /FHIR-Import fehlgeschlagen/);
  assert.equal(state.elements.import.disabled, false);
});

function allergyTable(resources) {
  const context = vm.createContext({authorOf: () => 'Synthetic author'});
  const functions = [
    html.slice(html.indexOf('function clean(value)'), html.indexOf('function isEchoSosUrl')),
    html.slice(html.indexOf('function coding(x)'), html.indexOf('function valueOf(r)')),
    html.slice(html.indexOf('function summaryTable('), html.indexOf('function contactCategory')),
    html.slice(html.indexOf('function allergySummaryTable('), html.indexOf('const renderBase=render;'))
  ];
  vm.runInContext(functions.join('\n'), context);
  return context.allergySummaryTable(resources);
}

test('allergy summary includes manifestations and clinical attributes', () => {
  const table = allergyTable([{
    code: {text: 'Erdnüsse'},
    clinicalStatus: {coding: [{code: 'active'}]},
    verificationStatus: {coding: [{code: 'confirmed'}]},
    type: 'allergy',
    category: ['food'],
    reaction: [{manifestation: [{text: 'Atemnot'}]}]
  }]);
  for (const value of ['Erdnüsse', 'Atemnot', 'active', 'confirmed', 'allergy', 'food',
    'Synthetic author', 'Reaktionen', 'Verifizierung', 'Typ', 'Kategorie']) {
    assert.ok(table.includes(value), `Missing ${value}`);
  }
  assert.ok(table.includes('<td>nicht angegeben</td>'));
});

test('allergy summary preserves multiple reactions, severities and categories safely', () => {
  const table = allergyTable([{
    category: ['food', 'medication'],
    reaction: [
      {manifestation: [{text: 'Rash'}, {coding: [{display: 'Dyspnea'}]}],
        severity: 'severe', description: '<script>unsafe</script>',
        onset: '2026-10-29', exposureRoute: {text: 'Oral'}},
      {manifestation: [{coding: [{code: '267036007'}]}], severity: 'mild'}
    ]
  }]);
  for (const value of ['Rash, Dyspnea', 'Schweregrad: severe', 'Schweregrad: mild',
    '267036007', 'food, medication', 'Beginn:', 'Expositionsweg: Oral',
    '&lt;script&gt;unsafe&lt;/script&gt;']) {
    assert.ok(table.includes(value), `Missing ${value}`);
  }
  assert.ok(!table.includes('<script>'));
});

test('missing allergy attributes remain unspecified, not negative findings', () => {
  assert.equal(allergyTable([]), '');
  const table = allergyTable([{}]);
  assert.equal((table.match(/<td>nicht angegeben<\/td>/g) || []).length, 7);
});

test('unconfirmed patient assertions have an explicit source label', () => {
  const resource = {
    patient: {reference: 'Patient/synthetic'},
    asserter: {reference: 'Patient/synthetic'},
    verificationStatus: {coding: [{
      system: 'http://terminology.hl7.org/CodeSystem/allergyintolerance-verification',
      code: 'unconfirmed'
    }]}
  };
  assert.ok(allergyTable([resource]).includes('Unbestätigt – Patientenangabe'));
  resource.asserter.reference = 'Practitioner/synthetic';
  assert.ok(!allergyTable([resource]).includes('Patientenangabe'));
});
