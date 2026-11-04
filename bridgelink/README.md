# BridgeLink Code Templates

## OL_CORE (version 1)

Prepared for BridgeLink 26.3.1 using the structure of the local
`api_route_dispatcher` export. On 2026-11-04 the user imported the library,
saved and redeployed the channel, and supplied successful live results:
CDA convert (200, transaction, no HAPI write), eMediplan convert
(200, collection, no HAPI write), and unknown endpoint
(404, OperationOutcome/not-found). Import, 400/401 and outage tests remain
outstanding. No live channel is changed by these repository files alone.

Import file: [OL_CORE.xml](code-templates/OL_CORE.xml).
The XML is the source of truth; tests execute its embedded JavaScript.
Keep the library/template UUIDs stable when updating an existing installation.

| Function | Contract |
|---|---|
| `olCoreGetHeader(headers, name)` | Uses the listener's `MessageHeaders.getHeader`, not a Java Map. Returns the unchanged string value, or `''` if absent. Does not authenticate. |
| `olCoreReadHttpRequest(source, rawBody)` | Returns `method`, `path`, `query`, `body`, `authorization`. Reads `uri`, not `requestPath`. Preserves the existing dispatcher normalization. |
| `olCoreSetGatewayError(target, status, code, diagnostics)` | Writes JSON `gatewayError` and string `gatewayErrorStatusCode`. Rejects invalid arguments by throwing. The caller retains logging and control flow. |

No globalMap, configuration, JWT validation, HTTP calls, routing, encoding
heuristics or clinical processing. Do not log the returned request object:
it contains authorization and the body.

### Import and assign

1. Keep a rollback export of the channel and existing libraries outside Git
   until checked for credentials and clinical data.
2. Open the Code Templates management view and import `OL_CORE.xml`.
   Check that it creates **OL_CORE**, without replacing the JWT library.
3. Check its channel assignment: only `api_route_dispatcher`, ID
   `2aaa5ae8-a6f6-49d1-a469-5a9b77a44b0a`. Automatic inclusion of new channels
   is disabled. Existing library assignments must remain enabled.
4. Save the library. Replace only the initial request-reading section of
   **Source Transformer > Route Request**, through the initialization of
   `responseTarget`, with:

```javascript
var request = olCoreReadHttpRequest(
    sourceMap,
    connectorMessage.getRawData()
);

channelMap.put('middlewareAuthorization', request.authorization);
channelMap.put('requestBody', request.body);
channelMap.put('targetMethod', request.method);
channelMap.put('responseTarget', 'none');

var bodyText = request.body;
var path = request.path;
var query = request.query;
var method = request.method;
```

Keep the existing `PATH` / `METHOD` logs and the complete routing chain below
this section unchanged. In particular, keep the VACD branch as the first `if`,
followed by the CDA `else if`.

5. In the CDA encoding-error branch, replace creation of `encodingErrorJson`
   and its two `channelMap.put` calls with:

```javascript
olCoreSetGatewayError(
    channelMap,
    400,
    'invalid',
    'CDA enth\u00e4lt fehlerhafte Zeichenkodierung. Bitte den Request mit Content-Type: application/xml; charset=UTF-8 senden.'
);
```

Keep the existing warning and `return`.
In the final unknown-endpoint branch, replace creation of `routingErrorJson`
and its two `channelMap.put` calls with:

```javascript
olCoreSetGatewayError(
    channelMap,
    404,
    'not-found',
    'Unknown endpoint: ' + path
);
```

Keep the existing warning. Do not change the destination filters: they must
continue to prevent HAPI writes when `gatewayError` is set.

6. Save and redeploy the channel. No middleware restart is needed.

### Verification and rollback

Run repository tests using an available Node.js runtime:

```sh
node --test app/tests/test_bridgelink_core.cjs app/tests/test_api_workbench.cjs
```

Tests use a MessageHeaders double, not the Java runtime. They verify the
embedded functions, not BridgeLink import or connector execution.

After redeploy, use synthetic inputs to check CDA and VACD conversion
(no write), authorized imports, unknown endpoint (404), the existing CDA
encoding rejection (400), missing/invalid JWT (401), and middleware/HAPI
failure propagation. Repeat a synthetic import to check reuse behavior.
Confirm that the original Authorization value reaches Destination 01,
without logging it. Do not replay clinical messages to external targets.

Path lowercasing and method uppercasing remain unchanged; trailing slashes
and whitespace are not removed, query values are not decoded or lowercased.
The existing encoding heuristic still applies only to the ordinary CDA
branch. Extending it to VACD would be a separate behavioral change.

For rollback, restore the previous Source Transformer and redeploy. Keep the
JWT library assignment intact; detach OL_CORE only once no channel calls it.

## OL_ROUTING (version 1)

Imported and redeployed by the user on 2026-11-04. CDA convert (200,
transaction), eMediplan convert (200, collection), and unknown endpoint
(404, OperationOutcome/not-found) passed the live baseline tests.
The PDF/QR import returned a successful transaction-response; the shown
Observation remained at version 1. This is not a full verification of all
entries, VACD, error cases or downstream outages.

Requires **OL_CORE**, and does not replace authentication.
Import [OL_ROUTING.xml](code-templates/OL_ROUTING.xml)
in the Code Templates management view, exactly as for OL_CORE.

It contains two functions:

- `olRouteResolve(method, path)`: exact lookup of an existing route, or `null`
  for an unsupported method/path. Expects the normalized OL_CORE values.
- `olRouteApply(request, target, middlewareBaseUrl, log)`: initializes the
  existing channelMap fields, resolves the route, checks the existing CDA
  encoding heuristic, and sets the destination URL or an explicit 400/404.
  Logs retain their existing messages. Does not perform HTTP requests.

| Method | External path | Middleware path | Response target | Forward query |
|---|---|---|---|---|
| POST | `/v1/cda/vacd/convert` | `/cda/vacd/convert` | none | yes |
| POST | `/v1/cda/vacd/import` | `/cda/vacd/prepare` | hapi | yes |
| POST | `/v1/cda/convert` | `/cda/convert` | none | yes |
| POST | `/v1/cda/import` | `/cda/convert` | hapi | yes |
| POST | `/v1/emediplan/import` | `/emediplan/prepare` | hapi | no |
| POST | `/v1/emediplan/convert` | `/emediplan/convert` | none | no |
| POST | `/v1/echosos/resolve` | `/echosos/qr` | hapi | no |
| GET | `/v1/.well-known/jwks.json` | `/.well-known/jwks.json` | none | no |

These are the existing rules, including query omission on eMediplan, EchoSOS
and JWKS. JWKS clears the body and still uses Destination 10 according to its
existing filter. No new endpoint, dynamic Channel Writer, destination,
permission model or external VACD send route is introduced. Destination
filters and response processing remain unchanged.

### Migration

1. Export the current, OL_CORE-enabled channel as a rollback copy.
2. Import OL_ROUTING and check its assignment to `api_route_dispatcher` only.
   Keep both OL_CORE and the existing JWT library assigned. Save libraries.
3. Replace the **complete** Source Transformer > Route Request script with
   [route-request.js](transformers/route-request.js):

```javascript
var request = olCoreReadHttpRequest(
    sourceMap,
    connectorMessage.getRawData()
);

olRouteApply(
    request,
    channelMap,
    'https://middleware.local.omnilink.ch',
    logger
);
```

The base URL is passed explicitly; no new configuration key is required.
It can later be replaced with `$cfg('middleware.baseUrl')` once that property
is configured for the environment. There is no silent URL fallback.

4. Validate Script, save and redeploy the channel. No middleware restart.
5. Repeat the three OL_CORE live tests, then test VACD conversion, synthetic
   imports/reimports, CDA encoding rejection, JWT rejection and downstream
   failures. Node tests do not establish Java-runtime or live success.
6. To roll back, restore the previous OL_CORE-enabled Source Transformer and
   redeploy. Do not remove libraries still referenced by a channel.

Run all directly related tests:

```sh
node --test app/tests/test_bridgelink_core.cjs app/tests/test_bridgelink_routing.cjs app/tests/test_api_workbench.cjs
```

The routing tests execute the exact saved transformer with the scripts from
both XML libraries, using map/header/logger doubles and synthetic data.

## Saved channel snapshot

[api_route_dispatcher.xml](api_route_dispatcher.xml) is the user-supplied
revision 108 export with OL_CORE, OL_ROUTING and the existing JWT library.
The two new libraries' function bodies and Source Transformer match the
tested repository sources. The export contains environment-specific hostnames
and channel/library assignments; review these before importing elsewhere.

Before Git inclusion, populated connector fields, header entries and embedded
credential references were inspected. No literal JWTs, private keys, passwords
or client secrets were found. Authorization is a dynamic channelMap reference;
JWT settings use `$cfg`. No message payload export is included.
The original pre-refactoring export in the local test-data directory is not
part of this snapshot.
