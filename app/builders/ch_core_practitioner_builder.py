import uuid

from domain.practitioner import PractitionerData

CH_CORE_PRACTITIONER_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/"
    "ch-core-practitioner"
)


def _normalized_string(value):

    if value is None:
        return None

    return " ".join(str(value).strip().lower().split())


def _normalized_lines(lines):

    return [
        _normalized_string(line)
        for line in (lines or [])
        if _normalized_string(line)
    ]


def _field_richness(value):

    if value is None:
        return 0

    if isinstance(value, str):
        return 1 if value.strip() else 0

    if isinstance(value, list):
        return sum(_field_richness(item) for item in value)

    if isinstance(value, dict):
        return sum(_field_richness(item) for item in value.values())

    return 1


def _is_subset_value(candidate, existing):

    if candidate == existing:
        return True

    if isinstance(candidate, str) and isinstance(existing, str):
        candidate_norm = _normalized_string(candidate)
        existing_norm = _normalized_string(existing)

        if not candidate_norm:
            return True

        if not existing_norm:
            return False

        return (
            candidate_norm == existing_norm
            or existing_norm.startswith(candidate_norm)
        )

    if isinstance(candidate, list) and isinstance(existing, list):
        if all(isinstance(item, str) for item in candidate + existing):
            candidate_norm = _normalized_lines(candidate)
            existing_norm = _normalized_lines(existing)

            if not candidate_norm:
                return True

            if len(candidate_norm) != len(existing_norm):
                return False

            return all(
                _is_subset_value(cand, exist)
                for cand, exist in zip(candidate_norm, existing_norm)
            )

        return candidate == existing

    return False


def _resource_dict_subset(candidate: dict, existing: dict) -> bool:

    for key, candidate_value in candidate.items():
        existing_value = existing.get(key)

        if key not in existing:
            return False

        if not _is_subset_value(candidate_value, existing_value):
            return False

    return True


def _dedupe_resource_dicts(items: list[dict]) -> list[dict]:

    deduped = []

    for item in items:
        replaced_existing = False
        skip_item = False

        for index, existing in enumerate(deduped):
            if _resource_dict_subset(item, existing):
                skip_item = True
                break

            if _resource_dict_subset(existing, item):
                deduped[index] = item
                replaced_existing = True
                break

        if skip_item:
            continue

        if not replaced_existing:
            deduped.append(item)

    return deduped


def _dedupe_human_name_dicts(items: list[dict]) -> list[dict]:

    deduped_by_key = {}
    ordered_keys = []

    for item in items:
        key = (
            _normalized_string(item.get("family")),
            tuple(_normalized_lines(item.get("given", []))),
        )

        current = deduped_by_key.get(key)

        if current is None:
            deduped_by_key[key] = item
            ordered_keys.append(key)
            continue

        if _field_richness(item) > _field_richness(current):
            deduped_by_key[key] = item

    return [deduped_by_key[key] for key in ordered_keys]


def build_ch_core_practitioner(
    practitioner: PractitionerData
) -> dict:

    resource = {
        "resourceType": "Practitioner",
        "id": str(uuid.uuid4()),
        "meta": {
            "profile": [
                CH_CORE_PRACTITIONER_PROFILE
            ]
        }
    }

    identifiers = []

    if practitioner.gln:
        identifiers.append(
            {
                "use": "official",
                "system": "urn:oid:2.51.1.3",
                "value": practitioner.gln
            }
        )

    if practitioner.zsr:
        identifiers.append(
            {
                "system": "urn:oid:2.16.756.5.30.1.123.100.2.1.1",
                "value": practitioner.zsr
            }
        )

    if practitioner.identifiers:

        identifiers.extend(
            [
                {
                    "system": identifier.system,
                    "value": identifier.value
                }
                for identifier in practitioner.identifiers
            ]
        )

    if identifiers:
        resource["identifier"] = _dedupe_resource_dicts(
            identifiers
        )

    if practitioner.names:

        resource["name"] = _dedupe_human_name_dicts([
            {
                "family": name.family,
                "given": name.given
            }
            for name in practitioner.names
        ])

    if practitioner.telecoms:

        resource["telecom"] = _dedupe_resource_dicts([
            {
                "system": telecom.system,
                "value": telecom.value,
                **(
                    {"use": telecom.use}
                    if telecom.use
                    else {}
                )
            }
            for telecom in practitioner.telecoms
        ])

    if practitioner.addresses:

        resource["address"] = _dedupe_resource_dicts([
            {
                "line": address.lines,
                "postalCode": address.postal_code,
                "city": address.city,
                "country": address.country
            }
            for address in practitioner.addresses
        ])

    if practitioner.gender:
        resource["gender"] = practitioner.gender

    if practitioner.birth_date:
        resource["birthDate"] = practitioner.birth_date

    if practitioner.active is not None:
        resource["active"] = practitioner.active

    return resource