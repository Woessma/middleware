import logging
import requests
import uuid

from config import FHIR_BASE

logger = logging.getLogger(__name__)


PRACTITIONER_ID_NAMESPACE = uuid.UUID(
    "8df56d0e-6f74-4ff8-9da9-8dc71867464e"
)


def _practitioner_sort_key(resource: dict):
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


def _stable_practitioner_id(
    identifier_system: str,
    identifier_value: str,
) -> str:
    return str(
        uuid.uuid5(
            PRACTITIONER_ID_NAMESPACE,
            f"{identifier_system}|{identifier_value}",
        )
    )


def find_practitioner(
    identifier_system: str,
    identifier_value: str
):
    response = requests.get(
        f"{FHIR_BASE}/Practitioner",
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

    entries = bundle.get(
        "entry",
        []
    )

    if not entries:
        return None

    entries = sorted(
        entries,
        key=lambda entry: _practitioner_sort_key(
            entry.get("resource", {})
        ),
    )

    if len(entries) > 1:
        logger.warning(
            "Mehrere Practitioner gefunden für %s|%s (%s Treffer)",
            identifier_system,
            identifier_value,
            len(entries),
        )

        for entry in entries:
            logger.warning(
                " -> Practitioner/%s",
                entry["resource"]["id"],
            )

        logger.warning(
            " -> verwende canonical Practitioner/%s",
            entries[0]["resource"]["id"],
        )

    return entries[0]["resource"]


def create_practitioner(
    practitioner: dict
):
    identifiers = practitioner.get("identifier", [])

    if not identifiers:
        raise ValueError(
            "Practitioner besitzt keinen Identifier"
        )

    identifier = identifiers[0]
    practitioner_id = _stable_practitioner_id(
        identifier["system"],
        identifier["value"],
    )

    payload = dict(practitioner)
    payload["id"] = practitioner_id

    response = requests.put(
        f"{FHIR_BASE}/Practitioner/{practitioner_id}",
        json=payload,
        headers={
            "Content-Type":
                "application/fhir+json",
            "Accept":
                "application/fhir+json"
        }
    )

    response.raise_for_status()

    return response.json()


def update_practitioner(
    practitioner_id: str,
    practitioner: dict,
):
    payload = dict(practitioner)
    payload["id"] = practitioner_id

    response = requests.put(
        f"{FHIR_BASE}/Practitioner/{practitioner_id}",
        json=payload,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        },
    )

    response.raise_for_status()

    return response.json()


def get_or_create_practitioner(
    practitioner: dict
):
    identifiers = practitioner.get(
        "identifier",
        []
    )

    if not identifiers:
        raise ValueError(
            "Practitioner besitzt keinen Identifier"
        )

    identifier = identifiers[0]

    existing = find_practitioner(
        identifier["system"],
        identifier["value"]
    )

    if existing:
        update_practitioner(
            existing["id"],
            practitioner,
        )
        logger.info("Practitioner gefunden: %s", existing["id"])
        return existing["id"]

    created = create_practitioner(
        practitioner
    )

    logger.info("Practitioner erstellt: %s", created["id"])

    return created["id"]