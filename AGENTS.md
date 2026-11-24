# Agent instructions

## Project scope

This repository contains the Python FHIR middleware. Application code lives in
`app/`; this repository does not use a top-level `src/` directory.

- BridgeLink owns orchestration and routing.
- The middleware parses, transforms, maps, and prepares FHIR resources and bundles.
- HAPI FHIR is the source of truth for stored FHIR resources.

## Read the relevant documentation

- `docs/architecture.md` describes the current system and data flows.
- `docs/ENDPOINTS.md` documents API behavior and request boundaries.
- `docs/hapi-mdm.md` describes MDM matching and import decisions.
- `docs/decisions/` contains accepted architectural decisions.
- `docs/TEST-CLIENT.md` documents the API workbench and its side effects.
- `docs/project-memory.md` is a dated project log, not an authoritative
  description of current runtime state.

Read only the documents relevant to the task. Keep `docs/` as the canonical
knowledge base; do not copy its content into a parallel agent-knowledge tree.

## Engineering rules

- Preserve the responsibility split between BridgeLink, middleware, and HAPI.
- Preserve read-only versus write behavior and convert versus import boundaries.
  Update the relevant tests and documentation when changing those boundaries.
- Treat ambiguous MDM matches as conflicts. Do not select a record arbitrarily
  or treat MDM failures as "no match".
- Do not add credentials, real patient data, or real identifiers to the repository,
  logs, or test fixtures.
- Make focused changes and follow the existing patterns in the affected code.

## Verification

Run the smallest existing test or validation command that covers the change.
Update the canonical documentation when behavior or an API contract changes.
Verify operational claims against current configuration or tests; dated project
notes may no longer reflect the live environment.
