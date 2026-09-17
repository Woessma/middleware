import copy
import json

import requests

from config import FHIR_BASE


def _resource_signature(resource: dict) -> str:
    normalized = copy.deepcopy(resource)
    normalized.pop("id", None)
    normalized.pop("meta", None)

    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _fetch_page(resource_type: str, params: dict, base_url: str):
    response = requests.get(
        f"{base_url.rstrip('/')}/{resource_type}",
        params=params,
        headers={"Accept": "application/fhir+json"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def find_exact_fhir_duplicates(
    resource_type: str = "MedicationStatement",
    patient_id: str | None = None,
    fhir_base: str = FHIR_BASE,
    count: int = 200,
):
    fhir_base = fhir_base or FHIR_BASE

    if not resource_type:
        raise ValueError("resource_type is required")

    params = {"_count": str(count)}

    if patient_id:
        params["patient"] = patient_id

    resources = []
    next_url = None

    while True:
        if next_url:
            response = requests.get(
                next_url,
                headers={"Accept": "application/fhir+json"},
                timeout=60,
            )
            response.raise_for_status()
            bundle = response.json()
        else:
            bundle = _fetch_page(resource_type, params, fhir_base)

        for entry in bundle.get("entry", []) or []:
            resource = entry.get("resource") or {}

            if resource.get("resourceType") == resource_type:
                resources.append(resource)

        next_url = None
        for link in bundle.get("link", []) or []:
            if link.get("relation") == "next" and link.get("url"):
                next_url = link["url"]
                break

        if not next_url:
            break

    grouped = {}
    for resource in resources:
        signature = _resource_signature(resource)
        grouped.setdefault(signature, []).append(resource)

    duplicates = []
    for signature, items in grouped.items():
        if len(items) < 2:
            continue

        duplicates.append(
            {
                "signature": signature,
                "count": len(items),
                "ids": [item.get("id") for item in items if item.get("id")],
            }
        )

    duplicates.sort(key=lambda item: (-item["count"], item["ids"][0] if item["ids"] else ""))

    return {
        "resourceType": resource_type,
        "patientId": patient_id,
        "count": len(resources),
        "duplicateGroups": duplicates,
    }