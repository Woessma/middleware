import logging
import re
from urllib.parse import quote

import requests

from config import (
    FHIR_BASE,
    FHIR_EXTERNAL_BASE_URL,
    FHIR_EXTERNAL_PASSWORD,
    FHIR_EXTERNAL_TIMEOUT,
    FHIR_EXTERNAL_USERNAME,
)

logger = logging.getLogger(__name__)


class PatientMatchConflictError(ValueError):
    pass


class PatientLookupError(RuntimeError):
    pass


def _search_patient_resources(search_params):
    params = {**search_params, "_count": "2"}
    response = requests.get(
        f"{FHIR_BASE.rstrip('/')}/Patient",
        params=params,
        headers={"Accept": "application/fhir+json"},
        timeout=FHIR_EXTERNAL_TIMEOUT,
    )
    response.raise_for_status()
    bundle = response.json()
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise PatientLookupError("FHIR Patient-Suche lieferte kein Bundle.")

    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise PatientLookupError("FHIR Patient-Suche lieferte ungültige Einträge.")
    resources = [
        entry.get("resource")
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("resource"), dict)
        and entry["resource"].get("resourceType") == "Patient"
    ]
    total = bundle.get("total", len(resources))
    if not isinstance(total, int):
        total = len(resources)
    return resources, total


def _single_patient_match(resources, total, search_type):
    if total > 1 or len(resources) > 1:
        raise PatientMatchConflictError(
            f"Patient ist nicht eindeutig (Suchart: {search_type})."
        )
    return resources[0] if resources else None


def find_patient_by_id(patient_id):
    if not isinstance(patient_id, str) or not re.fullmatch(
        r"[A-Za-z0-9.-]{1,64}",
        patient_id,
    ):
        raise ValueError("Ungültige FHIR Patient-ID.")
    response = requests.get(
        f"{FHIR_BASE.rstrip('/')}/Patient/{quote(patient_id, safe='')}",
        headers={"Accept": "application/fhir+json"},
        timeout=FHIR_EXTERNAL_TIMEOUT,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    patient = response.json()
    if not isinstance(patient, dict) or patient.get("resourceType") != "Patient":
        raise PatientLookupError("FHIR Patient-Read lieferte keine Patient-Ressource.")
    return patient


def find_matching_patient(patient_resource):
    """Find an existing local Patient by identifier, then exact name and birth date."""
    identifiers = patient_resource.get("identifier") or []
    if isinstance(identifiers, dict):
        identifiers = [identifiers]

    matches = {}
    for identifier in identifiers:
        if not isinstance(identifier, dict):
            continue
        system = identifier.get("system")
        value = identifier.get("value")
        if not system or not value:
            continue

        params = {"identifier": f"{system}|{value}"}
        resources, total = _search_patient_resources(params)
        warn_if_external_patient_duplicate(params, "identifier")
        match = _single_patient_match(resources, total, "identifier")
        if match:
            patient_id = match.get("id")
            if not patient_id:
                raise PatientLookupError("Gefundener FHIR Patient enthält keine ID.")
            matches[patient_id] = match

    if len(matches) > 1:
        raise PatientMatchConflictError(
            "Patienten-Identifier verweisen auf unterschiedliche FHIR-Patienten."
        )
    if matches:
        return next(iter(matches.values()))

    names = patient_resource.get("name") or []
    name = next(
        (
            item
            for item in names
            if isinstance(item, dict)
            and item.get("family")
            and (item.get("given") or [])
            and str(item.get("family")).casefold() != "unknown"
            and str(item["given"][0]).casefold() != "unknown"
        ),
        None,
    )
    birth_date = patient_resource.get("birthDate")
    if not name or not birth_date:
        if not identifiers:
            raise ValueError(
                "Patient kann ohne Identifier oder Name und Geburtsdatum nicht sicher abgeglichen werden."
            )
        return None

    params = {
        "family": name["family"],
        "given": name["given"][0],
        "birthdate": birth_date,
    }
    resources, total = _search_patient_resources(params)
    warn_if_external_patient_duplicate(params, "name-given-birthdate")

    exact_matches = []
    expected_family = str(name["family"]).casefold()
    expected_given = str(name["given"][0]).casefold()
    for resource in resources:
        if resource.get("birthDate") != birth_date:
            continue
        for existing_name in resource.get("name") or []:
            if not isinstance(existing_name, dict):
                continue
            given = existing_name.get("given") or []
            if (
                str(existing_name.get("family") or "").casefold() == expected_family
                and given
                and str(given[0]).casefold() == expected_given
            ):
                exact_matches.append(resource)
                break

    if total > len(resources):
        raise PatientMatchConflictError(
            "Patientenabgleich liefert mehr Treffer als sicher geprüft werden können."
        )
    return _single_patient_match(exact_matches, len(exact_matches), "name-given-birthdate")


def warn_if_external_patient_duplicate(search_params, search_type):
    """Check the read-only external FHIR server and log matches without using its IDs."""
    if not FHIR_EXTERNAL_BASE_URL:
        return 0

    if not FHIR_EXTERNAL_USERNAME or not FHIR_EXTERNAL_PASSWORD:
        logger.warning(
            "Externe Patientendublettenprüfung übersprungen: "
            "FHIR_EXTERNAL_USERNAME und FHIR_EXTERNAL_PASSWORD sind nicht vollständig konfiguriert"
        )
        return 0

    params = dict(search_params)
    params["_count"] = "1"

    try:
        response = requests.get(
            f"{FHIR_EXTERNAL_BASE_URL.rstrip('/')}/Patient",
            params=params,
            headers={"Accept": "application/fhir+json"},
            auth=(FHIR_EXTERNAL_USERNAME, FHIR_EXTERNAL_PASSWORD),
            timeout=FHIR_EXTERNAL_TIMEOUT,
        )
        response.raise_for_status()
        bundle = response.json()
    except (requests.RequestException, ValueError):
        logger.warning(
            "Externe Patientendublettenprüfung fehlgeschlagen (Suchart: %s)",
            search_type,
        )
        return 0

    if not isinstance(bundle, dict):
        logger.warning(
            "Externe Patientendublettenprüfung erhielt kein FHIR-Bundle (Suchart: %s)",
            search_type,
        )
        return 0

    entries = bundle.get("entry", []) or []
    if not isinstance(entries, list):
        entries = []
    match_count = bundle.get("total", len(entries))
    if not isinstance(match_count, int):
        match_count = len(entries)
    if match_count == 0 and entries:
        match_count = len(entries)

    if match_count:
        logger.warning(
            "Mögliche Patientendublette auf externem FHIR-Server "
            "(Suchart: %s, Treffer: %s); externer Datensatz bleibt unverändert",
            search_type,
            match_count,
        )

    return match_count


def find_patient(identifier_system, identifier_value):
    search_params = {"identifier": f"{identifier_system}|{identifier_value}"}
    response = requests.get(
        f"{FHIR_BASE.rstrip('/')}/Patient",
        params=search_params,
        headers={"Accept": "application/fhir+json"}
    )
    response.raise_for_status()

    bundle = response.json()
    warn_if_external_patient_duplicate(search_params, "identifier")

    if bundle.get("total", 0) > 0:
        return bundle["entry"][0]["resource"]

    return None


def create_patient(patient_resource):
    payload = dict(patient_resource)
    payload.pop("id", None)

    response = requests.post(
        f"{FHIR_BASE}/Patient",
        json=payload,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json"
        }
    )
 
    response.raise_for_status()

    created = response.json()

    return created


def update_patient(patient_id, patient_resource):
    payload = dict(patient_resource)
    payload["id"] = patient_id

    response = requests.put(
        f"{FHIR_BASE}/Patient/{patient_id}",
        json=payload,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json"
        }
    )

    response.raise_for_status()

    return response.json()


def resolve_patient_id(patient_resource):
    """Sucht den Patient in HAPI (read-only); None, wenn nicht vorhanden."""
    identifiers = patient_resource.get("identifier", [])

    if not identifiers:
        raise ValueError(
            "Patient enthält keinen Identifier."
        )

    identifier = identifiers[0]

    existing = find_patient(
        identifier.get("system"),
        identifier.get("value")
    )

    if existing:
        logger.info("Patient gefunden: %s", existing["id"])
        return existing["id"]

    logger.info(
        "Patient nicht in HAPI vorhanden; Anlage erfolgt erst beim Import: %s",
        identifier.get("value"),
    )

    return None


def get_or_create_patient(patient_resource):
    identifiers = patient_resource.get("identifier", [])

    if not identifiers:
        raise ValueError(
            "Patient enthält keinen Identifier."
        )

    # ersten Identifier verwenden
    identifier = identifiers[0]

    identifier_system = identifier.get("system")
    identifier_value = identifier.get("value")

    existing = find_patient(
        identifier_system,
        identifier_value
    )

    if existing:
        update_patient(
            existing["id"],
            patient_resource
        )
        logger.info("Patient gefunden: %s", existing["id"])
        return existing["id"]
 
    logger.info("Patient wird neu angelegt: %s", identifier_value)
 
    created = create_patient(
        patient_resource
    )
 
    return created["id"]
 