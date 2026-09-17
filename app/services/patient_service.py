import logging
import requests

from config import FHIR_BASE

logger = logging.getLogger(__name__)
 
 
def find_patient(identifier_system, identifier_value):
    url = (
        f"{FHIR_BASE}/Patient"
        f"?identifier={identifier_system}|{identifier_value}"
    )
 
    response = requests.get(
        url,
        headers={"Accept": "application/fhir+json"}
    )
 
    response.raise_for_status()
 
    bundle = response.json()
 
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
 