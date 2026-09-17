from html import escape


NON_DOMAIN_RESOURCE_TYPES = {
    "Binary",
    "Bundle",
    "Parameters",
}


def _codeable_display(value):
    if not isinstance(value, dict):
        return ""

    if value.get("text"):
        return str(value["text"])

    for coding in value.get("coding") or []:
        display = coding.get("display") or coding.get("code")

        if display:
            return str(display)

    return ""


def _reference_display(value):
    if not isinstance(value, dict):
        return ""

    return value.get("display") or value.get("reference") or ""


def _human_name_display(resource):
    names = resource.get("name") or []

    if not names:
        return ""

    name = names[0]

    if name.get("text"):
        return str(name["text"])

    given = " ".join(name.get("given") or [])
    family = name.get("family") or ""

    return " ".join(part for part in [given, family] if part)


def _quantity_display(value):
    if not isinstance(value, dict):
        return ""

    parts = [
        value.get("value"),
        value.get("unit") or value.get("code"),
    ]

    return " ".join(
        str(part)
        for part in parts
        if part is not None and part != ""
    )


def _address_display(value):
    if not isinstance(value, dict):
        return ""

    parts = [
        " ".join(value.get("line") or []),
        value.get("postalCode"),
        value.get("city"),
        value.get("country"),
    ]

    return " ".join(str(part) for part in parts if part)


def _resource_summary(resource):
    resource_type = resource.get("resourceType") or "Resource"

    if resource_type == "Patient":
        return [
            ("Name", _human_name_display(resource)),
            ("Gender", resource.get("gender")),
            ("Birth date", resource.get("birthDate")),
            ("Address", _address_display((resource.get("address") or [{}])[0])),
        ]

    if resource_type == "Observation":
        return [
            ("Code", _codeable_display(resource.get("code"))),
            ("Value", _quantity_display(resource.get("valueQuantity")) or _codeable_display(resource.get("valueCodeableConcept")) or resource.get("valueString")),
            ("Date", resource.get("effectiveDateTime") or resource.get("issued")),
            ("Subject", _reference_display(resource.get("subject"))),
        ]

    if resource_type == "Condition":
        return [
            ("Condition", _codeable_display(resource.get("code"))),
            ("Clinical status", _codeable_display(resource.get("clinicalStatus"))),
            ("Verification", _codeable_display(resource.get("verificationStatus"))),
            ("Subject", _reference_display(resource.get("subject"))),
        ]

    if resource_type == "MedicationStatement":
        return [
            ("Medication", _codeable_display(resource.get("medicationCodeableConcept")) or _reference_display(resource.get("medicationReference"))),
            ("Status", resource.get("status")),
            ("Subject", _reference_display(resource.get("subject"))),
        ]

    if resource_type == "AllergyIntolerance":
        return [
            ("Allergy", _codeable_display(resource.get("code"))),
            ("Clinical status", _codeable_display(resource.get("clinicalStatus"))),
            ("Patient", _reference_display(resource.get("patient"))),
        ]

    if resource_type == "Immunization":
        return [
            ("Vaccine", _codeable_display(resource.get("vaccineCode"))),
            ("Status", resource.get("status")),
            ("Date", resource.get("occurrenceDateTime") or resource.get("recorded")),
            ("Patient", _reference_display(resource.get("patient"))),
        ]

    if resource_type == "Procedure":
        return [
            ("Procedure", _codeable_display(resource.get("code"))),
            ("Status", resource.get("status")),
            ("Date", resource.get("performedDateTime")),
            ("Subject", _reference_display(resource.get("subject"))),
        ]

    if resource_type == "Composition":
        return [
            ("Title", resource.get("title")),
            ("Type", _codeable_display(resource.get("type"))),
            ("Date", resource.get("date")),
            ("Subject", _reference_display(resource.get("subject"))),
            ("Sections", len(resource.get("section") or [])),
        ]

    return [
        ("Display", resource.get("title") or resource.get("name") or _codeable_display(resource.get("code"))),
        ("Status", resource.get("status")),
        ("Subject", _reference_display(resource.get("subject") or resource.get("patient"))),
        ("Date", resource.get("date") or resource.get("authoredOn") or resource.get("recordedDate")),
    ]


def ensure_resource_narrative(resource):
    if not isinstance(resource, dict):
        return resource

    resource_type = resource.get("resourceType")

    if not resource_type or resource_type in NON_DOMAIN_RESOURCE_TYPES:
        return resource

    text = resource.get("text") or {}

    if text.get("div"):
        return resource

    title = f"Generated Narrative: {resource_type} {resource.get('id') or ''}".strip()
    items = []

    for label, value in _resource_summary(resource):
        if value is None or value == "" or value == []:
            continue

        items.append(
            f"<li><b>{escape(str(label))}</b>: {escape(str(value))}</li>"
        )

    content = "".join(items)

    if content:
        content = f"<ul>{content}</ul>"
    else:
        content = f"<p>{escape(resource_type)}</p>"

    resource["text"] = {
        "status": "generated",
        "div": (
            "<div xmlns=\"http://www.w3.org/1999/xhtml\">"
            f"<p><b>{escape(title)}</b></p>"
            f"{content}"
            "</div>"
        ),
    }

    return resource