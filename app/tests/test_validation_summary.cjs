const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const html = readFileSync(resolve(__dirname, '../../test-client.html'), 'utf8');
function element(tag) {
  return {
    tag, children: [], textContent: '', hidden: false,
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; }
  };
}
function setup() {
  const summary = element('div');
  const context = vm.createContext({
    el: {validationSummary: summary, output: element('pre')},
    document: {createElement: element}
  });
  vm.runInContext(html.slice(html.indexOf('function validationReports('), html.indexOf('function status(')), context);
  return {context, summary};
}
const profile = 'http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-patient|6.0.0';
const issue = (severity, diagnostics) => ({severity, code: 'processing', diagnostics});

test('PMLC document and outcome stay separate while the profile summary is displayed', () => {
  const {context, summary} = setup();
  context.el.documentDownloadBtn = {hidden: true, disabled: true};
  const response = {status: 'invalid', bundle: {resourceType: 'Bundle', type: 'document'},
    validation: {resourceType: 'OperationOutcome', issue: [issue('error', profile)]}};
  context.display(response);
  assert.equal(summary.hidden, false);
  assert.equal(context.validationReports(response)[0].title, 'CH-EMED-EPR Medikationsliste');
  assert.equal(context.el.output.textContent, JSON.stringify(response, null, 2));
  assert.equal(context.el.documentDownloadBtn.hidden, false);
  assert.equal(context.el.documentDownloadBtn.disabled, false);
  context.display('Request läuft …');
  assert.equal(context.el.documentDownloadBtn.hidden, true);
  assert.equal(context.el.documentDownloadBtn.disabled, true);
});

test('explicit Husky phase/profile attribution is preserved without changing the outcome', () => {
  const {context} = setup();
  const outcome = {resourceType: 'OperationOutcome', issue: [
    {...issue('error', 'Missing rules'), extension: [
      {url: 'urn:omnilink:validation:profile', valueString: 'epic-ccda'}
    ]},
    {...issue('warning', 'Schema warning'), extension: [
      {url: 'urn:omnilink:validation:profile', valueString: 'CDA R2 XSD (Husky 3.5.0)'}
    ]}
  ]};
  const before = JSON.stringify(outcome);
  const result = context.validationProfileSummary(outcome);
  assert.equal(result.groups[0].profile, 'epic-ccda');
  assert.equal(result.groups[1].profile, 'CDA R2 XSD (Husky 3.5.0)');
  assert.equal(JSON.stringify(outcome), before);
});

test('counts errors/fatal, warnings and information once and preserves unknown attribution', () => {
  const {context} = setup();
  const outcome = {resourceType: 'OperationOutcome', issue: [
    issue('error', `Failed (from ${profile}).`),
    issue('fatal', `Failed ${profile}`),
    issue('warning', `Warning ${profile}`),
    issue('information', `Slice did not match ${profile}`),
    issue('warning', 'Unknown coding http://loinc.org'),
    issue('error', 'Base FHIR structure is invalid')
  ]};
  const before = JSON.stringify(outcome);
  const result = context.validationProfileSummary(outcome);
  assert.deepEqual(JSON.parse(JSON.stringify(result.counts)), {errors: 3, warnings: 2, information: 1});
  assert.equal(result.groups.length, 2);
  assert.equal(result.groups.find(group => group.profile === profile).errors, 2);
  assert.equal(result.groups.find(group => group.profile === profile).warnings, 1);
  assert.equal(result.groups.find(group => group.profile === 'Profil nicht eindeutig angegeben').issues.length, 2);
  assert.equal(JSON.stringify(outcome), before);
});

test('multiple profile mentions are not double counted and are not truncated', () => {
  const {context} = setup();
  const second = 'http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-immunization';
  const result = context.validationProfileSummary({issue: [
    issue('warning', `${profile}, ${second}; repeated ${profile}.`)
  ]});
  assert.equal(result.groups.length, 1);
  assert.equal(result.groups[0].warnings, 1);
  assert.equal(result.groups[0].profile, `${profile} + ${second}`);
});

test('resource profile context is distinct from explicit attribution and run-only fallback', () => {
  const {context} = setup();
  const run = 'http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-document-immunization-administration|6.0.0';
  const outcome = {resourceType: 'OperationOutcome',
    extension: [{url: 'urn:omnilink:validation:profile', valueString: run}],
    issue: [
      {...issue('error', 'Unknown vaccine code'), extension: [
        {url: 'urn:omnilink:validation:context-profile', valueString: profile}
      ]},
      issue('warning', 'Bundle warning'),
      {...issue('warning', `Explicit ${profile}`), extension: [
        {url: 'urn:omnilink:validation:context-profile', valueString: run}
      ]}
    ]};
  const before = JSON.stringify(outcome);
  const result = context.validationProfileSummary(outcome);
  assert.equal(result.groups.length, 3);
  assert.equal(result.groups.find(group => group.errors).profile, `Ressourcenprofil (Kontext): ${profile}`);
  assert.ok(result.groups.some(group => group.profile === `Prüflauf (Einzelprofil nicht angegeben): ${run}`));
  assert.ok(result.groups.some(group => group.profile === profile));
  assert.deepEqual(JSON.parse(JSON.stringify(result.counts)), {errors: 1, warnings: 2, information: 0});
  assert.equal(JSON.stringify(outcome), before);
});

test('details.text is considered; information-only outcome reports zero errors and warnings', () => {
  const {context, summary} = setup();
  assert.equal(context.validationProfileSummary({issue: [
    {severity: 'warning', details: {text: `From ${profile}`}}
  ]}).groups[0].profile, profile);
  context.display({resourceType: 'OperationOutcome', issue: [issue('information', 'All OK')]});
  assert.equal(summary.hidden, false);
  assert.ok(summary.children.some(child => child.textContent.includes('0 Fehler · 0 Warnungen')));
});

test('uses safe text rendering for diagnostics and clears summary for non-outcome responses', () => {
  const {context, summary} = setup();
  const outcome = {resourceType: 'OperationOutcome', issue: [
    {...issue('error', '<img src=x onerror=alert(1)>'), expression: ['Bundle.entry[0]']}
  ]};
  context.display(outcome);
  const table = summary.children.find(child => child.tag === 'table');
  const details = table.children.find(child => child.tag === 'tbody').children[0].children[0].children[0];
  const item = details.children[1].children[0];
  assert.equal(item.children[1].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(item.children[2].textContent, 'Feld: Bundle.entry[0]');
  assert.equal(context.el.output.textContent, JSON.stringify(outcome, null, 2));
  assert.doesNotMatch(html.slice(html.indexOf('function renderValidationSummary('), html.indexOf('function status(')), /innerHTML/);
  context.display({resourceType: 'Bundle'});
  assert.equal(summary.hidden, true);
  assert.equal(summary.children.length, 0);
});

test('VACD validation phases remain separate and are not combined into one profile count', () => {
  const {context, summary} = setup();
  const result = {
    send: {status: 'sent', validation: {
      before_patient: {resourceType: 'OperationOutcome', issue: [issue('warning', profile)]},
      before_bundle: {resourceType: 'OperationOutcome', issue: [issue('warning', profile)]}
    }}
  };
  context.display(result);
  assert.equal(context.validationReports(result).length, 2);
  assert.equal(summary.children.filter(child => child.tag === 'table').length, 2);
});

test('starting a request resets stale summaries, metadata and download state on fetch failure', async () => {
  const {context, summary} = setup();
  context.el.runBtn = {disabled: false};
  context.el.responseMeta = {textContent: 'old HTTP 200'};
  context.el.reuseBtn = {disabled: false};
  context.el.downloadBtn = {disabled: false};
  context.performance = {now: () => 0};
  context.current = () => ({id: 'cda-validate'});
  context.urlFor = () => 'https://example.invalid';
  context.requestFor = () => ({});
  context.status = () => {};
  context.errorText = () => 'Network failed';
  context.fetch = async () => { throw Error('Network failed'); };
  vm.runInContext(html.slice(html.indexOf('async function run()'), html.indexOf('async function check()')), context);
  context.display({resourceType: 'OperationOutcome', issue: [issue('error', profile)]});
  await context.run();
  assert.equal(summary.hidden, true);
  assert.equal(context.el.responseMeta.textContent, '');
  assert.equal(context.el.downloadBtn.disabled, true);
  assert.equal(context.el.reuseBtn.disabled, true);
  assert.equal(context.el.runBtn.disabled, false);
});

test('HTTP-200 errors remain errors, warnings are highlighted and failed sends stay blocked', async () => {
  for (const [value, expectedType] of [
    [{resourceType: 'OperationOutcome', issue: [issue('error', profile)]}, 'error'],
    [{resourceType: 'OperationOutcome', issue: [issue('warning', profile)]}, 'running'],
    [{resourceType: 'OperationOutcome', issue: [issue('information', 'OK')]}, 'success'],
    [{send: {status: 'partial-error', bundle: {error: 'Rejected'}, validation: {
      before_bundle: {resourceType: 'OperationOutcome', issue: [issue('warning', profile)]}
    }}}, 'error']
  ]) {
    const {context} = setup();
    for (const id of ['runBtn', 'reuseBtn', 'downloadBtn']) context.el[id] = {};
    context.el.responseMeta = {};
    context.performance = {now: () => 0};
    context.current = () => ({id: 'cda-validate'});
    context.urlFor = () => 'https://example.invalid';
    context.requestFor = () => ({});
    context.responseMetadata = () => 'HTTP 200';
    context.status = (message, type) => { context.latestStatus = {message, type}; };
    context.errorText = error => error.message;
    context.fetch = async () => ({status: 200, ok: true,
      headers: {get: () => 'application/json'}, text: async () => JSON.stringify(value)});
    vm.runInContext(html.slice(html.indexOf('function parse('), html.indexOf('function validationReports(')), context);
    vm.runInContext(html.slice(html.indexOf('function fhirResponseError('), html.indexOf('async function check()')), context);
    await context.run();
    assert.equal(context.latestStatus.type, expectedType);
    assert.equal(context.el.downloadBtn.disabled, false);
    assert.equal(context.el.output.textContent, JSON.stringify(value, null, 2));
  }
});
