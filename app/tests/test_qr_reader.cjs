const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const {gzipSync} = require('node:zlib');

const html = readFileSync(resolve(__dirname, '../../erezept-emediplan-reader.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function client(overrides = {}) {
  const elements = new Map();
  class BrowserURL extends URL {
    static createObjectURL() { return 'blob:synthetic-preview'; }
    static revokeObjectURL() {}
  }
  function element(tag = 'div') {
    return {
      tag, children: [], textContent: '', hidden: false, value: '', disabled: false,
      classList: {add() {}, remove() {}},
      setAttribute(name, value) { this[name] = value; },
      addEventListener() {},
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      get childElementCount() { return this.children.length; }
    };
  }
  const context = vm.createContext({
    URL: BrowserURL, TypeError, Error, Set, Uint8Array, setTimeout,
    Blob, DecompressionStream, TextDecoder, atob, AbortSignal,
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element
    },
    navigator: {},
    window: {addEventListener() {}},
    ...overrides
  });
  vm.runInContext(script, context);
  return {context, elements};
}

test('reader script compiles without browser syntax errors', () => {
  assert.doesNotThrow(() => new vm.Script(script));
});

test('QR and metadata results have distinct explicit source labels', () => {
  const {context, elements} = client();
  context.addResult('https://example.org/qr', 'test.pdf / Seite 1');
  context.addResult('https://example.org/metadata', 'test.pdf / XMP: signedChmed', 'PDF-Metadaten-Link');
  const cards = elements.get('results').children;
  assert.equal(cards[0].children[0].textContent, 'QR / Inhalt aus sichtbarem QR-Code');
  assert.equal(cards[0].children[0].className, 'source-label');
  assert.equal(cards[1].children[0].textContent, 'Metadaten / Link aus unsichtbaren PDF-Metadaten');
  assert.equal(cards[1].children[0].className, 'source-label metadata');
});

test('PDF selection creates local preview; replacement and clear release URLs', () => {
  const created = [];
  const revoked = [];
  class PreviewURL extends URL {
    static createObjectURL(file) { created.push(file.name); return 'blob:' + file.name; }
    static revokeObjectURL(url) { revoked.push(url); }
  }
  const {context, elements} = client({URL: PreviewURL});
  context.selectFiles([{name: 'one.pdf', type: 'application/pdf', size: 100}]);
  const previews = elements.get('pdfPreviews');
  assert.equal(previews.hidden, false);
  const section = previews.children[0];
  assert.equal(section.children[1].tag, 'object');
  assert.equal(section.children[1].type, 'application/pdf');
  assert.equal(section.children[1].data, 'blob:one.pdf');
  assert.equal(section.children[3].href, 'blob:one.pdf');
  context.selectFiles([{name: 'two.PDF', type: '', size: 100}]);
  assert.deepEqual(revoked, ['blob:one.pdf']);
  assert.deepEqual(created, ['one.pdf', 'two.PDF']);
  context.selectFiles([]);
  assert.equal(previews.hidden, true);
  assert.equal(previews.childElementCount, 0);
  assert.deepEqual(revoked, ['blob:one.pdf', 'blob:two.PDF']);
});

test('PNG, JPEG and WebP have image previews; invalid files have explicit warnings', () => {
  const {context, elements} = client();
  for (const [name, type] of [['photo.png', 'image/png'], ['photo.jpeg', 'image/jpeg'],
    ['photo.webp', 'image/webp'], ['photo.JPG', '']]) {
    context.selectFiles([{name, type, size: 100}]);
    const previews = elements.get('pdfPreviews');
    assert.equal(previews.hidden, false);
    const preview = previews.children[0].children[1];
    assert.equal(preview.tag, 'img');
    assert.equal(preview.src, 'blob:synthetic-preview');
    assert.match(preview.alt, /Bild-Vorschau/);
  }
  context.selectFiles([{name: 'unsupported.svg', type: 'image/svg+xml', size: 100}]);
  assert.equal(elements.get('pdfPreviews').hidden, true);
  context.selectFiles([
    {name: 'empty.pdf', size: 0},
    {name: 'large.pdf', size: 31 * 1024 * 1024}
  ]);
  for (const section of elements.get('pdfPreviews').children) {
    assert.equal(section.childElementCount, 2);
    assert.match(section.children[1].textContent, /Keine Vorschau/);
  }
});

test('only HTTP(S) links can be opened', () => {
  const {context} = client();
  for (const value of ['javascript:alert(1)', 'data:text/html,test', 'file:///tmp/test',
    '/relative', 'plain text', 'https://']) {
    assert.equal(context.httpUrl(value), null, value);
  }
  const value = 'https://example.org/#a+b/c=&other=%20';
  assert.equal(context.httpUrl(value).href, value);
  assert.equal(context.httpUrl('http://example.org/').protocol, 'http:');
});

test('input formats are restricted to PDF and supported raster images', () => {
  const {context} = client();
  assert.equal(context.fileKind({name: 'SCAN.PDF', type: ''}), 'pdf');
  assert.equal(context.fileKind({name: 'photo.JPEG', type: ''}), 'image');
  assert.equal(context.fileKind({name: 'scan', type: 'image/webp'}), 'image');
  assert.throws(() => context.fileKind({name: 'test.svg', type: 'image/svg+xml'}), /Format/);
});

test('QR contents and filenames remain text; link is isolated from opener', () => {
  const {context, elements} = client();
  const payload = '<img src=x onerror=alert(1)>';
  context.addResult(payload, '<script>filename</script>');
  let card = elements.get('results').children[0];
  assert.equal(card.children[1].textContent, '<script>filename</script>');
  assert.equal(card.children[2].value, payload);
  assert.equal(card.children[3].children.length, 1);
  context.addResult('https://example.org/#sensitive', 'synthetic.png');
  card = elements.get('results').children[1];
  const link = card.children[3].children[1];
  assert.equal(link.href, 'https://example.org/#sensitive');
  assert.equal(link.target, '_blank');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.equal(link.referrerPolicy, 'no-referrer');
});

test('missing clipboard access is reported explicitly', async () => {
  const {context, elements} = client();
  context.addResult('text', 'synthetic.png');
  await elements.get('results').children[0].children[3].children[0].onclick();
  assert.match(elements.get('status').textContent, /Kopieren fehlgeschlagen/);
  assert.equal(elements.get('status').className, 'status error');
});

test('links offer copying and opening in a new tab only, without an embedded view', () => {
  const {context, elements} = client();
  const value = 'https://example.org/#a+b/c=&other=%20';
  context.addResult(value, 'synthetic.png');
  const card = elements.get('results').children[0];
  assert.equal(card.children[3].childElementCount, 2);
  assert.equal(card.children[3].children[1].href, value);
  assert.equal(card.children[3].children[1].target, '_blank');
  assert.equal(card.childElementCount, 5);
  assert.ok(!html.includes("createElement('iframe')"));
  assert.ok(!html.includes('Hier anzeigen'));
});

test('non-HTTP content cannot create an embedded page', () => {
  const {context, elements} = client();
  context.addResult('javascript:alert(1)', 'synthetic.png');
  const card = elements.get('results').children[0];
  assert.equal(card.children[3].childElementCount, 1);
  assert.equal(card.childElementCount, 5);
});

test('multiple symbols are decoded together and repeated contents are deduplicated', async () => {
  const {context} = client();
  const image = {data: new Uint8ClampedArray(16 * 16 * 4), width: 16, height: 16};
  const result = await context.decodeCanvas({
    width: 16, height: 16, getContext: () => ({getImageData: () => image})
  }, async (input, options) => {
    assert.equal(input, image);
    assert.deepEqual(Array.from(options.formats), ['QRCode']);
    assert.equal(options.tryHarder, true);
    return [{text: 'same'}, {text: 'same'}, {text: 'different'}];
  });
  assert.deepEqual(Array.from(result), ['same', 'different']);
});

test('unreadable QR text is explicitly reported instead of an empty successful result', async () => {
  const {context} = client();
  await assert.rejects(() => context.decodeCanvas({
    width: 16, height: 16, getContext: () => ({getImageData: () => ({})})
  }, async () => [{text: ''}]), /kein lesbarer Text/);
});

test('empty image closes bitmap and frees canvas', async () => {
  let closed = false;
  const {context} = client({
    createImageBitmap: async () => ({width: 10, height: 10, close() { closed = true; }})
  });
  const canvas = {
    width: 10, height: 10,
    getContext: () => ({
      fillRect() {}, drawImage() {},
      getImageData: () => ({data: new Uint8ClampedArray(400), width: 10, height: 10})
    })
  };
  context.canvasOf = () => canvas;
  assert.equal(await context.scanImage({name: 'empty.png'}, async () => []), 0);
  assert.equal(closed, true);
  assert.equal(canvas.width, 0);
});

test('oversized image is rejected and bitmap is closed', async () => {
  let closed = false;
  const {context} = client({
    createImageBitmap: async () => ({width: 6000, height: 6000, close() { closed = true; }})
  });
  await assert.rejects(() => context.scanImage({}, () => null), /24 Megapixel/);
  assert.equal(closed, true);
});

test('PDF scans every page at both resolutions, deduplicates per page and releases resources', async () => {
  const {context} = client();
  const rendered = [];
  const sources = [];
  let cleanup = 0;
  let destroyed = 0;
  context.loadPdf = async () => ({
    getDocument: () => ({
      promise: Promise.resolve({
        numPages: 2,
        getMetadata: async () => ({metadata: null}),
        getPage: async number => ({
          getViewport: ({scale}) => ({width: 100 * scale, height: 200 * scale}),
          render: ({viewport}) => { rendered.push([number, viewport.width]); return {promise: Promise.resolve()}; },
          cleanup() { cleanup++; }
        })
      }),
      destroy: async () => { destroyed++; }
    })
  });
  context.canvasOf = () => ({getContext() { return {}; }});
  context.decodeCanvas = async () => ['https://example.org/'];
  context.addResult = (value, source) => sources.push(source);
  const count = await context.scanPdf({name: 'test.pdf', arrayBuffer: async () => new ArrayBuffer(0)}, null, () => {});
  assert.equal(count, 2);
  assert.deepEqual(rendered, [[1, 150], [1, 300], [2, 150], [2, 300]]);
  assert.deepEqual(sources, ['test.pdf / Seite 1', 'test.pdf / Seite 2']);
  assert.equal(cleanup, 2);
  assert.equal(destroyed, 1);
});

test('file errors do not prevent remaining inputs; controls recover and partial results are counted', async () => {
  const {context, elements} = client();
  context.loadDecoder = async () => () => null;
  context.scanImage = async file => {
    context.addResult('https://example.org/', file.name);
    throw new Error('Failure after partial result');
  };
  context.selectFiles([
    {name: 'empty.pdf', type: 'application/pdf', size: 0},
    {name: 'huge.pdf', type: 'application/pdf', size: 31 * 1024 * 1024},
    {name: 'scan.png', type: 'image/png', size: 100}
  ]);
  await context.scanFiles();
  const message = elements.get('status').textContent;
  assert.match(message, /^1 Eintrag\/Eintraege erkannt/);
  assert.match(message, /Datei ist leer/);
  assert.match(message, /30 MB/);
  assert.match(message, /Failure after partial result/);
  assert.equal(elements.get('scan').disabled, false);
  assert.equal(elements.get('clear').disabled, false);
});

test('PDF page limit and password failure release the loading task', async () => {
  for (const password of [false, true]) {
    const {context} = client();
    let destroyed = false;
    context.loadPdf = async () => ({
      getDocument: () => ({
        promise: password
          ? Promise.reject(Object.assign(new Error('Password required'), {name: 'PasswordException'}))
          : Promise.resolve({numPages: 101}),
        destroy: async () => { destroyed = true; }
      })
    });
    await assert.rejects(() => context.scanPdf({
      name: 'test.pdf', arrayBuffer: async () => new ArrayBuffer(0)
    }, null, () => {}), password ? /Password required/ : /maximal 100/);
    assert.equal(destroyed, true);
  }
});

test('decoder loading failure is visible and the scan can be retried', async () => {
  const {context, elements} = client();
  context.selectFiles([{name: 'test.png', type: 'image/png', size: 100}]);
  context.loadDecoder = async () => { throw new Error('Network failed'); };
  await context.scanFiles();
  assert.equal(elements.get('status').className, 'status error');
  assert.equal(elements.get('status').textContent, 'Network failed');
  assert.equal(elements.get('scan').disabled, false);
  assert.equal(elements.get('qrFiles').disabled, false);
});

const medication = {
  Patient: {FName: 'Synthetic', LName: 'Test', BDt: '2000-01-01'},
  Medicaments: [{Id: 'Synthetic medication', IdType: 0, Pos: [{D: [1, 0, 0, 0]}]}]
};
const chmed = 'CHMED16A1' + gzipSync(JSON.stringify(medication)).toString('base64');

test('CHMED direct and signed URL decode to identical original JSON without network calls', async () => {
  const {context} = client({fetch: () => { throw new Error('Unexpected request'); }});
  for (const input of [chmed, 'https://eprescription.hin.ch/#' + chmed + '&i=issuer&s=signature',
    JSON.stringify(medication)]) {
    const data = await context.decodeMedication(input);
    assert.deepEqual(JSON.parse(JSON.stringify(data)), medication);
  }
});

test('invalid/unsupported medication data is rejected explicitly', async () => {
  const {context} = client();
  for (const input of [
    'https://example.org/', 'CHMED16A2abc', 'CHMED16A1invalid',
    '{}', '{"Patient":{},"Medicaments":null}', '{"Patient":[],"Medicaments":[]}',
    'https://example.org/#CHMED16A1%ZZ'
  ]) {
    await assert.rejects(() => context.decodeMedication(input));
  }
});

test('decompression size limit rejects highly compressed oversized JSON', async () => {
  const {context} = client();
  const huge = 'CHMED16A1' + gzipSync(JSON.stringify({
    Patient: {}, Medicaments: [], extra: 'x'.repeat(5 * 1024 * 1024)
  })).toString('base64');
  await assert.rejects(() => context.decodeMedication(huge), /maximal 5 MB/);
});

test('FHIR conversion posts original JSON only to the non-import endpoint', async () => {
  const calls = [];
  const bundle = {resourceType: 'Bundle', type: 'collection', entry: []};
  const {context} = client({fetch: async (url, options) => {
    calls.push({url, options});
    return {ok: true, status: 200, text: async () => JSON.stringify(bundle)};
  }});
  const result = await context.convertMedication(medication);
  assert.equal(result.resourceType, 'Bundle');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/emediplan/convert');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[0].options.body), medication);
});

test('HTTP, non-JSON, non-bundle and clinical errors cannot appear as successful FHIR output', async () => {
  for (const response of [
    {ok: false, status: 400, text: async () => '{"detail":"Invalid medication"}'},
    {ok: false, status: 502, text: async () => '<html>Unavailable</html>'},
    {ok: true, status: 200, text: async () => '{"resourceType":"OperationOutcome","issue":[]}'},
    {ok: true, status: 200, text: async () => JSON.stringify({
      resourceType: 'Bundle', entry: [{resource: {
        resourceType: 'OperationOutcome', issue: [{severity: 'error', diagnostics: 'Invalid dose'}]
      }}]
    })}
  ]) {
    const {context} = client({fetch: async () => response});
    await assert.rejects(() => context.convertMedication(medication));
  }
});

test('original medication view is local; failed conversion retains original JSON and enables retry', async () => {
  let requests = 0;
  const {context} = client({fetch: async () => {
    requests++;
    throw new Error('Network failed');
  }});
  const view = context.medicationView(chmed);
  const actions = view.children[2];
  const outputs = view.children[4];
  assert.equal(outputs.childElementCount, 0);
  assert.equal(requests, 0);
  await actions.children[0].onclick();
  assert.equal(requests, 0);
  assert.equal(outputs.childElementCount, 1);
  assert.deepEqual(JSON.parse(outputs.children[0].children[1].value), medication);
  await actions.children[1].onclick();
  assert.equal(requests, 1);
  assert.equal(outputs.childElementCount, 1);
  assert.equal(actions.children[1].disabled, false);
  assert.match(view.children[3].textContent, /Network failed/);
});
