import logging
import requests
import uuid

from config import FHIR_BASE

logger = logging.getLogger(__name__)


ORGANIZATION_ID_NAMESPACE = uuid.UUID(
    "f5b69752-178f-4fe5-854e-14b37e98cd2e"
)


def _organization_sort_key(resource: dict):
    resource_id = resource.get("id") or ""

    try:
        numeric_id = int(resource_id)
    except (TypeError, ValueError):
        numeric_id = 10**18

    active_rank = 0 if resource.get("active", True) else 1

    return (
        active_rank,
        numeric_id,
        resource_id,
    )


def _stable_organization_id(
    identifier_system: str,
    identifier_value: str,
) -> str:
    return str(
        uuid.uuid5(
            ORGANIZATION_ID_NAMESPACE,
            f"{identifier_system}|{identifier_value}",
        )
    )


def find_organization(
    identifier_system: str,
    identifier_value: str
):
    response = requests.get(
        f"{FHIR_BASE}/Organization",
        params={
            "identifier":
                f"{identifier_system}|{identifier_value}"
        },
        headers={
            "Accept": "application/fhir+json"
        }
    )

    response.raise_for_status()

    bundle = response.json()

    total = bundle.get("total", 0)

    if total == 0:
        return None

    entries = bundle.get("entry", [])

    if not entries:
        return None

    entries = sorted(
        entries,
        key=lambda entry: _organization_sort_key(
            entry.get("resource", {})
        ),
    )

    if total > 1:

        logger.warning(
            "Mehrere Organizations gefunden für %s|%s (%s Treffer)",
            identifier_system,
            identifier_value,
            total
        )

        for entry in entries:
            logger.warning(
                " -> Organization/%s",
                entry["resource"]["id"]
            )

        logger.warning(
            " -> verwende canonical Organization/%s",
            entries[0]["resource"]["id"],
        )

    return entries[0]["resource"]


def create_organization(
    identifier_system: str,
    identifier_value: str,
    name: str,
    telecom=None,
    address=None
):
    organization = {
        "resourceType": "Organization",
        "meta": {
            "profile": [
                "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-organization"
            ]
        },
        "active": True,
        "identifier": [
            {
                "system": identifier_system,
                "value": identifier_value
            }
        ],
        "name": name
    }

    if telecom:
        organization["telecom"] = telecom

    if address:
        organization["address"] = [address]

    organization_id = _stable_organization_id(
        identifier_system,
        identifier_value,
    )

    organization["id"] = organization_id

    response = requests.put(
        f"{FHIR_BASE}/Organization/{organization_id}",
        json=organization,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json"
        }
    )

    response.raise_for_status()

    created = response.json()

    if not created.get("id"):
        raise Exception(
            f"Organization erstellt, aber keine FHIR-ID erhalten: {created}"
        )

    logger.info(
        "Organization erstellt: Organization/%s",
        created["id"]
    )

    return created


def update_organization(
    organization_id: str,
    identifier_system: str,
    identifier_value: str,
    name: str,
    telecom=None,
    address=None
):
    organization = {
        "resourceType": "Organization",
        "id": organization_id,
        "meta": {
            "profile": [
                "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-organization"
            ]
        },
        "active": True,
        "identifier": [
            {
                "system": identifier_system,
                "value": identifier_value
            }
        ],
        "name": name
    }

    if telecom:
        organization["telecom"] = telecom

    if address:
        organization["address"] = [address]

    response = requests.put(
        f"{FHIR_BASE}/Organization/{organization_id}",
        json=organization,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json"
        }
    )

    response.raise_for_status()

    return response.json()


def get_or_create_organization(
    identifier_system: str,
    identifier_value: str,
    name: str,
    telecom=None,
    address=None
):
    existing = find_organization(
        identifier_system,
        identifier_value
    )

    if existing:
        update_organization(
            organization_id=existing["id"],
            identifier_system=identifier_system,
            identifier_value=identifier_value,
            name=name,
            telecom=telecom,
            address=address
        )

        logger.info(
            "Organization gefunden: Organization/%s",
            existing["id"]
        )

        return existing

    logger.info(
        "Organization wird neu angelegt: %s",
        name
    )

    created = create_organization(
        identifier_system=identifier_system,
        identifier_value=identifier_value,
        name=name,
        telecom=telecom,
        address=address
    )

    return created