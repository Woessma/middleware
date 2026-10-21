# app/fhir/identifiers.py

import copy
import json


def import_resource_identity(resource: dict) -> str:
    normalized = copy.deepcopy(resource)
    for field in ("id", "meta", "identifier"):
        normalized.pop(field, None)
    if normalized.get("text", {}).get("status") == "generated":
        normalized.pop("text")
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def get_cda_identifier_value(
    root: str | None,
    extension: str | None = None
) -> str | None:

    if extension:
        return extension

    return root


def build_cda_identifier(
    root: str,
    extension: str | None = None
) -> dict:

    value = get_cda_identifier_value(
        root,
        extension
    )

    identifier = {
        "system": f"urn:oid:{root}"
    }

    if value:
        identifier["value"] = value

    return identifier