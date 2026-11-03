import logging
import requests

from config import (
    FHIR_BASE,
    FHIR_EXTERNAL_BASE_URL,
    FHIR_EXTERNAL_PASSWORD,
    FHIR_EXTERNAL_TIMEOUT,
    FHIR_EXTERNAL_USERNAME,
)

logger = logging.getLogger(__name__)


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
 