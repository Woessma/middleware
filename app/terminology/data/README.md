# eMediplan Medication Mapping Files

Stand: 2026-11-24

## CDC CVX vaccine codes

`CVX.txt` is the CDC's flat-file CVX code set, bundled for local lookup and validation:

- Source: https://www2a.cdc.gov/vaccines/iis/iisstandards/downloads/CVX.txt
- Snapshot: CDC code set published 2026-09-18.
- The file includes inactive and non-US codes so historic immunizations remain representable.
- Refresh it from the CDC source when updating the code set; the per-code update date is included
  in the file.
- Only curated CVX-to-SNOMED mappings are added in `app/terminology/cvx.py`. Do not infer a
  formulation-specific CVX code from a generic vaccine name.

The eMediplan mapping workbooks are no longer bundled in this directory: the
original pair was secured as `archive/bundled/` (with manifest) in the
persistent `emediplan-mapping-data` volume, and the repository copies were
removed. Medication lookups read only from that persistent archive.

Download source: https://www.emediplan.ch/softwareanbieter (monthly mapping export).

On a fresh deployment (empty volume) the monthly refresh populates the archive;
no seed files are required. Optionally, seed workbooks can be provided in this
directory (or via the env vars below) before the first refresh, using these
filenames:

- MappingPharmacodeToGtinToSwissmedicDescription.xlsx
- MappingProductNumberToSwissmedicDescription.xlsx

Note: pharmacodes can be superseded when a product's packaging changes (e.g. Pharmacode
809693 for "Aldactone 50 mg" was replaced by 809701 in the current Swissmedic export).
Unresolved pharmacodes fall back to the raw code plus a Compendium search link.
The seed-file lookup also accepts the former date-prefixed filenames.

You can configure the seed file paths and archive directory via environment variables:

- EMEDIPLAN_PHARMACODE_XLSX
- EMEDIPLAN_PRODUCTNUMBER_XLSX
- EMEDIPLAN_MAPPING_DATA_DIR

## Automated monthly refresh and archive

The BridgeLink channel `Emediplan_Mapping_Refresh` triggers
`POST /admin/api/emediplan-mappings/refresh` during the first seven days of
each month. The middleware discovers both dated XLSX links on the eMediplan
software-provider page, requires matching publication versions, validates
the workbooks, and archives the untouched pair in
`EMEDIPLAN_MAPPING_DATA_DIR/archive/YYYYMMDD/`.

If seed workbooks are present (see above), they are copied to `archive/bundled/`
on the first successful refresh before the new version is activated; without
seed files this step is skipped. Medication lookups read
only from `archive/bundled/` (when present) and the archived publications in
this persistent directory; `app/terminology/data` is not consulted at runtime.
Each monthly archive contains both source files and a manifest with the source
URLs, SHA-256 hashes, and row counts. `current.json` points to the active
archive; the update is activated only after both workbooks pass validation. The
middleware invalidates its in-process mapping cache after activation. The
persistent directory defaults to `/var/lib/omnilink/emediplan` and is mounted
as the `emediplan-mapping-data` Docker volume.

At runtime, the active publication takes precedence, then older archived
publications are searched for identifiers absent from newer files. If an
identifier occurs in multiple publications, the newest data wins. The source
workbooks remain separate and are never merged or overwritten.

Optional columns that are picked up when present:

- Form / DosageForm / GalenicForm / Darreichungsform
- Ingredient / ActiveIngredient / Wirkstoff / Substance
- Strength / Staerke / DosageStrength
- ATC
- Abgabekategorie / DispensingCategory

## Current usage in middleware

- Used by the eMediplan import path to normalize medication identity.
- Works together with CDA medication translation handling so structured coding can survive
	round-trips (`cda/import` -> FHIR -> `fhir/medications/epic-cda/from-server`).
- Enriched product fields are written to `Medication` (not `MedicationStatement`).
- `Abgabekategorie` is written to `Medication.extension` using the
	`https://emediplan.ch/fhir/StructureDefinition/dispensing-category` URL.

## Refdata.ch Partner GLN files

The Refdata.ch partner exports are used for best-effort enrichment when
creating FHIR resources with a GLN identifier (`urn:oid:2.51.1.3`):

- `Refdata.Partners.Nat.xml` contains natural persons and enriches `Practitioner` name/address.
- `Refdata.Partners.Jur.xml` contains legal persons and enriches `Organization` name/address.

Values already supplied by the source document are preserved; the export fills missing fields.
The middleware builds a temporary SQLite index outside the application directory on first
lookup, and rebuilds it when the XML file changes. If a local match is unavailable, the
configured Refdata.ch API remains available as a best-effort fallback.

### Automated refresh

The exports are no longer bundled in this directory (the files are large and age quickly);
they live in `REFDATA_DATA_DIR` (default `/var/lib/omnilink/refdata`, a persistent Docker
volume) and are fetched via `POST /admin/api/refdata/refresh` (trigger it manually, via
cron, or via a BridgeLink polling channel): the middleware downloads the full partner
export zip from the Refdata API (`REFDATA_PARTNERS_ZIP_URL`, default
`https://api.refdata.ch/partners/1.0/Refdata.Partners.zip`, authenticated with
`REFDATA_API_KEY`), validates both contained XML files, and atomically replaces them.
The SQLite index is rebuilt automatically on the next lookup after a refresh.

On a fresh deployment, trigger the refresh endpoint once; until then GLN enrichment falls
back to the Refdata.ch API. Files dropped into this directory are still picked up as a
fallback when `REFDATA_DATA_DIR` has no data.
