# eMediplan Medication Mapping Files

Stand: 2026-09-04

Place the eMediplan mapping workbooks in this directory so the middleware can resolve Pharmacode and ProductNumber to canonical GTIN and Swissmedic description.

Download source: https://www.emediplan.ch/downloads/ (monthly mapping export).

Expected filenames:

- 20260901__MappingPharmacodeToGtinToSwissmedicDescription.xlsx
- 20260701__MappingProductNumberToSwissmedicDescription.xlsx

Note: pharmacodes can be superseded when a product's packaging changes (e.g. Pharmacode
809693 for "Aldactone 50 mg" was replaced by 809701 in the current Swissmedic export).
Unresolved pharmacodes fall back to the raw code plus a Compendium search link.

You can override file paths via environment variables:

- EMEDIPLAN_PHARMACODE_XLSX
- EMEDIPLAN_PRODUCTNUMBER_XLSX

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

The Refdata.ch partner exports in this directory are used for best-effort enrichment when
creating FHIR resources with a GLN identifier (`urn:oid:2.51.1.3`):

- `Refdata.Partners.Nat.xml` contains natural persons and enriches `Practitioner` name/address.
- `Refdata.Partners.Jur.xml` contains legal persons and enriches `Organization` name/address.

Ensure both exports are present in this directory in every runtime deployment.
Values already supplied by the source document are preserved; the export fills missing fields.
The middleware builds a temporary SQLite index outside the application directory on first
lookup, and rebuilds it when the XML file changes. If a local match is unavailable, the
configured Refdata.ch API remains available as a best-effort fallback.
