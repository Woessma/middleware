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
  const approved = html.slice(html.indexOf('const vacdSendCase='), html.indexOf('function current()'));
  const requests = html.slice(html.indexOf('function urlFor('), html.indexOf('function parse('));
  vm.runInContext(`${script}\n${approved}\n${requests}\nthis.approved=visibleCases();`, context);
  return {context, elements, cases: context.approved};
}

test('only implemented routes are released', () => {
  const {cases} = workbench();
  assert.deepEqual(Array.from(cases, item => item.id), [
    'patient-everything', 'bundle-import', 'cda-convert', 'cda-source-validate', 'cda-validate', 'cda-bundle-validate', 'pmlc-generate', 'cda-import',
    'vacd-convert', 'vacd-validate', 'vacd-husky-validate', 'vacd-bundle-husky-validate', 'vacd-send',
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

for (const id of ['vacd-convert', 'vacd-validate', 'vacd-husky-validate', 'vacd-send', 'cda-validate', 'cda-source-validate']) {
  test(`${id}: raw XML and explicit route`, () => {
    const {context, elements, cases} = workbench();
    const item = cases.find(item => item.id === id);
    elements.payload.value = '<ClinicalDocument />';
    const request = context.requestFor(item);
    assert.equal(request.body, elements.payload.value);
    assert.equal(request.headers['Content-Type'], 'application/xml; charset=UTF-8');
    const url = context.urlFor(item);
    assert.equal(url.origin, id === 'vacd-convert' ? 'https://api.example' : 'https://middleware.example');
  });
}

test('VACD send report errors are not shown as success', () => {
  const {context} = workbench();
  vm.runInContext(html.slice(html.indexOf('function fhirResponseError('), html.indexOf('async function run()')), context);
  assert.match(context.fhirResponseError({send: {status: 'partial-error', bundle: {error: 'rejected'}}}), /rejected/);
  assert.equal(context.fhirResponseError({send: {status: 'sent'}}), '');
  assert.equal(context.fhirResponseError({send: {status: 'skipped', reason: 'no-new-immunizations'}}), '');
});

function externalSummary() {
  const {context} = workbench();
  vm.runInContext(html.slice(html.indexOf('function externalSendSummary('), html.indexOf('function display(')), context);
  return context;
}

test('external summary distinguishes actual destination response from internal validation', () => {
  const context = externalSummary();
  const report = context.externalSendSummary({
    send: {
      status: 'sent', destination_base_url: 'https://target.invalid/fhir',
      patient: {ok: true, matched_existing: false, assigned_id: 'synthetic-patient'},
      immunizations: {new: 3, skipped: 0},
      bundle: {http_status: 201, ok: true, response: {
        resourceType: 'Bundle', type: 'document', id: 'synthetic-document',
        identifier: {system: 'urn:ietf:rfc:3986', value: 'urn:uuid:synthetic'},
        entry: [
          {resource: {resourceType: 'Composition'}},
          {resource: {resourceType: 'Immunization'}},
          {resource: {resourceType: 'Immunization'}}
        ]
      }}
    }
  });
  const rows = Object.fromEntries(Array.from(report.rows, row => [row.label, row.value]));
  assert.equal(rows.Patient, 'Patient am Ziel neu angelegt');
  assert.equal(rows['Zielpatient-ID'], 'synthetic-patient');
  assert.equal(rows['Dokument-HTTP-Status'], '201');
  assert.equal(rows['Neue Impfungen im Versanddokument'], '3');
  assert.equal(rows['Ausgelassene Impfdubletten'], '0');
  assert.equal(rows['Antwort-ID'], 'synthetic-document');
  assert.equal(rows['Ressourcen in der Zielantwort'], 'Composition: 1 · Immunization: 2');
  assert.match(report.note, /kein Einzelbeleg/);
  assert.match(rows.Dokumentversand, /keine unabhängige Leseprüfung/);
});

test('skipped import never claims a new external write', () => {
  const context = externalSummary();
  for (const reason of ['document-already-processed', 'no-new-immunizations']) {
    const report = context.externalSendSummary({send: {status: 'skipped', reason}});
    const row = report.rows.find(row => row.label === 'Dokumentversand');
    assert.match(row.value, /Nicht (erneut )?gesendet/);
    assert.equal(report.response, undefined);
  }
  assert.equal(context.externalSendSummary({resourceType: 'OperationOutcome'}), null);
});

test('external errors and missing patient evidence are explicit', () => {
  const context = externalSummary();
  const report = context.externalSendSummary({send: {
    status: 'partial-error', patient: {ok: true},
    bundle: {http_status: 500, error: 'synthetic error', response: {
      resourceType: 'OperationOutcome', issue: [{severity: 'error', diagnostics: 'Synthetic rejection'}]
    }}
  }});
  const rows = Object.fromEntries(Array.from(report.rows, row => [row.label, row.value]));
  assert.match(rows.Dokumentversand, /Nicht als erfolgreich bestätigt/);
  assert.equal(rows.Patient, 'Aktion nicht ausgewiesen');
  assert.equal(rows.Versandfehler, 'synthetic error');
  assert.equal(rows['Dokument-HTTP-Status'], '500');
  assert.equal(report.response.resourceType, 'OperationOutcome');
});

test('external response renders as text and resets on the next request', () => {
  const context = externalSummary();
  const element = () => ({
    children: [],
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; }
  });
  context.el.externalSummary = element();
  context.document.createElement = element;
  context.renderExternalSummary({send: {
    status: 'sent', bundle: {http_status: 201, response: '<script>untrusted</script>'}
  }});
  assert.equal(context.el.externalSummary.hidden, false);
  const details = context.el.externalSummary.children.at(-1);
  assert.equal(details.children[1].textContent, '<script>untrusted</script>');
  context.renderExternalSummary('Request läuft');
  assert.equal(context.el.externalSummary.hidden, true);
  assert.equal(context.el.externalSummary.children.length, 0);
  assert.match(html, /renderExternalSummary\(value\);renderValidationSummary\(value\)/);
});

test('response metadata separates the browser URL from the configured processing path', () => {
  const {context, cases} = workbench();
  vm.runInContext(html.slice(html.indexOf('function processingPath('), html.indexOf('function populate(')), context);
  for (const [id, path] of [
    ['emed-qr-import', 'Middleware → BridgeLink → HAPI'],
    ['cda-import', 'Middleware → BridgeLink → HAPI'],
    ['emed-import', 'BridgeLink → Middleware → BridgeLink → HAPI'],
    ['emed-qr-convert', 'Middleware (QR-Dekodierung und Konvertierung, kein HAPI-Write)'],
    ['vacd-send', 'Middleware → konfiguriertes externes VACD-FHIR-Ziel'],
    ['cda-source-validate', 'Middleware → interner Husky-CDA-Validator (keine Speicherung)'],
    ['pmlc-generate', 'Middleware → interner HAPI (nur Lesen) → Husky CH-EMED-EPR (keine Speicherung)'],
    ['patient-everything', 'FHIR-Server direkt'],
    ['cda-convert', 'BridgeLink → Middleware (kein HAPI-Write)'],
    ['cda-validate', 'Middleware → interner HAPI-Validator (keine Speicherung)'],
    ['cda-bundle-validate', 'Middleware → interner HAPI-Validator (keine Speicherung)'],
    ['vacd-validate', 'Middleware → interner HAPI-Validator (keine Speicherung)'],
    ['vacd-husky-validate', 'Middleware → interner Husky CH-VACD-6.0.0-Validator (keine Speicherung)'],
    ['vacd-bundle-husky-validate', 'Middleware → interner Husky CH-VACD-6.0.0-Validator (keine Speicherung)']
  ]) {
    const item = cases.find(item => item.id === id);
    const url = context.urlFor(item);
    assert.equal(context.processingPath(item), path);
    assert.equal(context.responseMetadata(item, url, {status: 200}, 42, 'application/json;charset=utf-8'),
      `Request: ${item.method} ${item.target === 'same-origin' ? item.input === 'binary-file' ? 'Datei-Upload' : 'Middleware-Aufruf' : url} · HTTP 200 · 42 ms · application/json\nVerarbeitungsweg (konfigurierter Ablauf): ${path}`);
  }
  assert.match(html, /el\.responseMeta\.textContent=responseMetadata\(/);
  assert.doesNotMatch(html, /Same-origin BridgeLink-Proxy/);
});

test('VACD Husky bundle validation preserves supplied JSON and uses same-origin', () => {
  const {context, elements, cases} = workbench();
  const item = cases.find(item => item.id === 'vacd-bundle-husky-validate');
  const bundle = {resourceType: 'Bundle', type: 'document', entry: []};
  elements.payload.value = JSON.stringify(bundle);
  const request = context.requestFor(item);
  assert.deepEqual(JSON.parse(request.body), bundle);
  assert.equal(request.headers['Content-Type'], 'application/fhir+json');
  assert.equal(context.urlFor(item).href, 'https://middleware.example/fhir/vacd/husky/validate');
});

test('PMLC reuses the active Keycloak Authorization header on its same-origin request', () => {
  const {context, cases} = workbench();
  const item = cases.find(item => item.id === 'pmlc-generate');
  assert.equal(context.requestFor(item).headers.Authorization, context.auth().Authorization);
  assert.equal(context.urlFor(item).origin, 'https://middleware.example');
});

test('route field renders processing flow and direct request path on separate lines', () => {
  const {context, elements, cases} = workbench();
  const element = () => ({
    children: [],
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; }
  });
  elements.route = element();
  context.document.createElement = element;
  vm.runInContext(html.slice(html.indexOf('function processingPath('), html.indexOf('function populate(')), context);
  for (const id of ['emed-qr-import', 'cda-import', 'vacd-send', 'emed-import', 'patient-everything']) {
    const item = cases.find(item => item.id === id);
    context.renderRoute(item);
    const [method, details] = elements.route.children;
    assert.equal(method.textContent, item.method);
    assert.equal(details.className, 'route-details');
    const [flow, path] = details.children;
    assert.equal(flow.className, 'route-flow');
    assert.equal(flow.textContent, 'Verarbeitungsweg (konfiguriert): ' + context.processingPath(item));
    assert.equal(path.className, 'route-path');
    if (item.target === 'same-origin') {
      assert.equal(path.textContent, item.input === 'binary-file' ? 'Request: Datei-Upload' : 'Request: Middleware-Aufruf');
      assert.ok(!path.textContent.includes(item.path));
      const metadata = context.responseMetadata(item, context.urlFor(item), {status: 200}, 42, 'application/json');
      assert.ok(!metadata.includes(item.path));
      assert.ok(!metadata.includes('https://middleware.example'));
    } else {
      assert.ok(path.textContent.endsWith(': ' + item.path));
    }
  }
  assert.match(html, /function render\(\)\{const item=current\(\);renderRoute\(item\)/);
  assert.match(html, /\.route-flow,\.route-path \{ white-space:normal; overflow-wrap:anywhere;/);
});
