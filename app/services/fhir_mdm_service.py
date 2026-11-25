import re

import requests

from config import FHIR_BASE
from fhir.bundle import rewrite_bundle_references


MATCH_GRADE_URL = "http://hl7.org/fhir/StructureDefinition/match-grade"
MDM_RESOURCE_TYPES = {"Patient", "Practitioner", "Organization"}
MATCH_GRADES = {"certain", "probable", "possible"}
MDM_RECORD_STATUS_SYSTEM = "http://hapifhir.io/fhir/NamingSystem/mdm-record-status"


class FhirMdmLookupError(RuntimeError):
    pass


class FhirMdmMatchConflictError(ValueError):
    pass


def _confirmed_link_fields(parameter: dict, resource_type: str) -> tuple[str, str]:
    parts = parameter.get("part")
    if not isinstance(parts, list) or not all(isinstance(part, dict) for part in parts):
        raise FhirMdmLookupError("FHIR MDM link query returned invalid link parts")
    fields = {}
    for name in ("sourceResourceId", "goldenResourceId", "matchResult"):
        values = [part.get("valueString") for part in parts if part.get("name") == name]
        if len(values) != 1 or not isinstance(values[0], str):
            raise FhirMdmLookupError("FHIR MDM link query returned invalid link fields")
        fields[name] = values[0]
    reference_pattern = rf"{re.escape(resource_type)}/[A-Za-z0-9.-]{{1,64}}"
    if (
        fields["matchResult"] != "MATCH"
        or not re.fullmatch(reference_pattern, fields["sourceResourceId"])
        or not re.fullmatch(reference_pattern, fields["goldenResourceId"])
        or fields["sourceResourceId"] == fields["goldenResourceId"]
    ):
        raise FhirMdmLookupError("FHIR MDM link query returned an invalid MATCH link")
    return fields["sourceResourceId"], fields["goldenResourceId"]


def _link_parameters(response) -> list[dict]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise FhirMdmLookupError("FHIR MDM link query returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("resourceType") != "Parameters":
        raise FhirMdmLookupError("FHIR MDM link query did not return Parameters")
    parameters = payload.get("parameter", [])
    if not isinstance(parameters, list) or not all(
        isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"]
        for p in parameters
    ):
        raise FhirMdmLookupError("FHIR MDM link query returned invalid parameters")
    return parameters


def find_mdm_matches(resource: dict, fhir_base: str = FHIR_BASE):
    resource_type = resource.get("resourceType")
    if resource_type not in MDM_RESOURCE_TYPES:
        raise ValueError("Unsupported MDM resourceType")

    url = f"{fhir_base.rstrip('/')}/$mdm-match"
    parameters = [
        {"name": "resource", "resource": resource},
        {"name": "resourceType", "valueString": resource_type},
    ]

    response = requests.post(
        url,
        json={"resourceType": "Parameters", "parameter": parameters},
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        },
        timeout=60,
    )
    response.raise_for_status()
    try:
        bundle = response.json()
    except ValueError as exc:
        raise FhirMdmLookupError("FHIR MDM match returned invalid JSON") from exc

    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise FhirMdmLookupError("FHIR MDM match did not return a Bundle")

    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise FhirMdmLookupError("FHIR MDM match returned invalid entries")

    matches = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise FhirMdmLookupError("FHIR MDM match returned an invalid entry")
        candidate = entry.get("resource")
        if (
            not isinstance(candidate, dict)
            or candidate.get("resourceType") != resource_type
            or not isinstance(candidate.get("id"), str)
            or not candidate["id"]
        ):
            raise FhirMdmLookupError("FHIR MDM match returned an invalid resource")

        search = entry.get("search") or {}
        if not isinstance(search, dict):
            raise FhirMdmLookupError("FHIR MDM match returned invalid match metadata")
        extensions = search.get("extension") or []
        if not isinstance(extensions, list):
            raise FhirMdmLookupError("FHIR MDM match returned invalid match metadata")
        grade = next(
            (
                extension.get("valueCode")
                for extension in extensions
                if isinstance(extension, dict)
                and extension.get("url") == MATCH_GRADE_URL
            ),
            None,
        )
        if not isinstance(grade, str) or grade not in MATCH_GRADES:
            raise FhirMdmLookupError("FHIR MDM match returned an unknown match grade")
        matches.append({"resource": candidate, "grade": grade})

    return matches


def find_linked_golden_id(
    resource_type: str, source_id: str, fhir_base: str = FHIR_BASE,
) -> str | None:
    source_reference = f"{resource_type}/{source_id}"
    response = requests.get(
        f"{fhir_base.rstrip('/')}/$mdm-query-links",
        params={
            "resourceId": source_reference,
            "resourceType": resource_type,
            "matchResult": "MATCH",
            "_count": 2,
        },
        headers={"Accept": "application/fhir+json"},
        timeout=60,
    )
    response.raise_for_status()
    parameters = _link_parameters(response)
    golden_ids = []
    for parameter in parameters:
        if parameter.get("name") == "next":
            raise FhirMdmMatchConflictError(f"{resource_type} has too many confirmed MDM links.")
        if parameter.get("name") != "link":
            continue
        source, target = _confirmed_link_fields(parameter, resource_type)
        if source != source_reference:
            raise FhirMdmLookupError("FHIR MDM link query returned an invalid MATCH link")
        golden_ids.append(target.split("/", 1)[1])

    if len(golden_ids) > 1:
        raise FhirMdmMatchConflictError(
            f"{resource_type} does not have a unique confirmed link to a Golden Record."
        )
    return golden_ids[0] if golden_ids else None


def make_mdm_same_patient_matcher():
    """Match a source and its confirmed golden Patient in either direction."""
    source_to_golden = {}

    def golden_reference(reference):
        if reference not in source_to_golden:
            golden_id = find_linked_golden_id(
                "Patient", reference.split("/", 1)[1]
            )
            source_to_golden[reference] = (
                f"Patient/{golden_id}" if golden_id else None
            )
        return source_to_golden[reference]

    def same_patient(existing_reference, incoming_reference):
        if not all(
            re.fullmatch(r"Patient/[A-Za-z0-9.-]{1,64}", reference)
            for reference in (existing_reference, incoming_reference)
        ):
            return False
        return (
            golden_reference(existing_reference) == incoming_reference
            or golden_reference(incoming_reference) == existing_reference
        )

    return same_patient


def find_confirmed_patient_source_ids(golden_id: str) -> list[str]:
    golden_reference = f"Patient/{golden_id}"
    response = requests.get(
        f"{FHIR_BASE.rstrip('/')}/$mdm-query-links",
        params={
            "goldenResourceId": golden_reference, "resourceType": "Patient",
            "matchResult": "MATCH", "_count": 50,
        },
        headers={"Accept": "application/fhir+json"},
        timeout=30,
        allow_redirects=False,
    )
    if response.status_code != 200:
        raise FhirMdmLookupError("FHIR MDM link query failed")
    parameters = _link_parameters(response)
    sources = set()
    for parameter in parameters:
        if parameter.get("name") == "next":
            raise FhirMdmLookupError("FHIR MDM source list is incomplete")
        if parameter.get("name") != "link":
            continue
        source, target = _confirmed_link_fields(parameter, "Patient")
        if target != golden_reference:
            raise FhirMdmLookupError("FHIR MDM returned a link for another Golden Patient")
        source_id = source.split("/", 1)[1]
        if source_id in sources:
            raise FhirMdmMatchConflictError("Patient has duplicate confirmed MDM links")
        sources.add(source_id)

    for source_id in sources:
        if find_linked_golden_id("Patient", source_id) != golden_id:
            raise FhirMdmMatchConflictError("Patient source has no unique confirmed Golden Patient")
    return sorted(sources)


def find_mdm_match(resource: dict, fhir_base: str = FHIR_BASE):
    matches = find_mdm_matches(resource, fhir_base=fhir_base)
    if any(match["grade"] != "certain" for match in matches):
        raise FhirMdmMatchConflictError(
            f"{resource['resourceType']} has a possible MDM match; import requires review."
        )

    matches_by_id = {
        match["resource"]["id"]: match["resource"]
        for match in matches
    }
    if not matches_by_id:
        return None

    resource_type = resource["resourceType"]
    golden_ids = set()
    for candidate_id, candidate in matches_by_id.items():
        if any(
            tag.get("system") == MDM_RECORD_STATUS_SYSTEM and tag.get("code") == "GOLDEN_RECORD"
            for tag in candidate.get("meta", {}).get("tag", [])
        ):
            golden_ids.add(candidate_id)
        else:
            linked_id = find_linked_golden_id(resource_type, candidate_id, fhir_base)
            if linked_id is None:
                raise FhirMdmMatchConflictError(
                    f"{resource_type} does not have a unique confirmed link to a Golden Record."
                )
            golden_ids.add(linked_id)

    if len(golden_ids) > 1:
        raise FhirMdmMatchConflictError(
            f"{resource_type} has certain MDM matches to multiple Golden Records."
        )
    golden_id = next(iter(golden_ids))
    if golden_id in matches_by_id:
        return matches_by_id[golden_id]

    response = requests.get(
        f"{fhir_base.rstrip('/')}/{resource_type}/{golden_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60,
    )
    response.raise_for_status()
    try:
        golden = response.json()
    except ValueError as exc:
        raise FhirMdmLookupError("FHIR Golden Record read returned invalid JSON") from exc
    if (
        not isinstance(golden, dict)
        or golden.get("resourceType") != resource_type
        or golden.get("id") != golden_id
    ):
        raise FhirMdmLookupError("FHIR Golden Record read returned an unexpected resource")
    return golden


def reconcile_mdm_resources(bundle: dict):
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ValueError("FHIR Bundle expected")
    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise ValueError("FHIR Bundle entries must be a list")

    reference_map = {}
    entries_to_remove = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            continue
        resource_type = resource.get("resourceType")
        if resource_type not in MDM_RESOURCE_TYPES:
            continue

        existing = find_mdm_match(resource)
        if not existing:
            continue

        target_reference = f"{resource_type}/{existing['id']}"
        previous_id = resource.get("id")
        if previous_id:
            reference_map[f"{resource_type}/{previous_id}"] = target_reference
        if entry.get("fullUrl"):
            reference_map[entry["fullUrl"]] = target_reference
        entries_to_remove.add(id(entry))

    rewrite_bundle_references(bundle, reference_map)
    if entries_to_remove:
        bundle["entry"] = [
            entry for entry in entries if id(entry) not in entries_to_remove
        ]
    return reference_map
