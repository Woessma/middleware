CH_CORE_COMPOSITION_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-composition"
)

CH_IPS_COMPOSITION_PROFILE = (
    "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-composition"
)

CH_IPS_DOCUMENT_TYPE = {
    "coding": [
        {
            "system": "http://loinc.org",
            "code": "60591-5",
            "display": "Patient summary Document",
        }
    ]
}

CH_EPR_CONFIDENTIALITY_EXTENSION_URL = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/"
    "ch-ext-epr-confidentialitycode"
)


def _build_codeable_concept(code: dict | None) -> dict | None:
    if not code:
        return None

    coding = {}

    if code.get("codeSystem"):
        coding["system"] = code["codeSystem"]

    if code.get("code"):
        coding["code"] = code["code"]

    if code.get("displayName"):
        coding["display"] = code["displayName"]

    concept = {}

    if coding:
        concept["coding"] = [coding]

    text = code.get("originalText") or code.get("displayName")

    if text:
        concept["text"] = text

    return concept or None


def _section_key(section_code: str | None, section_title: str | None) -> tuple[str | None, str | None]:
    normalized_title = None

    if section_title:
        normalized_title = " ".join(
            section_title.strip().lower().split()
        )

    return section_code, normalized_title


def build_ch_core_composition(
    patient_reference: str,
    document_type_code: dict | None,
    title: str | None,
    date: str | None,
    section_summaries: list[dict],
    clinical_note_references: list[dict],
    composition_identifier: dict | None = None,
    practitioner_reference: str | None = None,
    organization_reference: str | None = None,
    encounter_reference: str | None = None,
    language: str | None = None,
    section_resource_references: list[dict] | None = None,
    use_ch_ips_profile: bool = False,
) -> dict:
    composition = {
        "resourceType": "Composition",
        "meta": {
            "profile": [
                (
                    CH_IPS_COMPOSITION_PROFILE
                    if use_ch_ips_profile
                    else CH_CORE_COMPOSITION_PROFILE
                ),
            ]
        },
        "status": "final",
        "subject": {
            "reference": patient_reference,
        },
        "section": [],
    }

    if composition_identifier:
        composition["identifier"] = composition_identifier

    type_concept = (
        CH_IPS_DOCUMENT_TYPE
        if use_ch_ips_profile
        else _build_codeable_concept(document_type_code)
    )

    if type_concept:
        composition["type"] = type_concept

    if title:
        composition["title"] = title

    if date:
        composition["date"] = date

    if language:
        composition["language"] = language

    author_references = []

    if practitioner_reference:
        author_references.append(
            {
                "reference": practitioner_reference,
            }
        )

    if organization_reference:
        author_references.append(
            {
                "reference": organization_reference,
            }
        )

    if not author_references:
        author_references.append(
            {
                "reference": patient_reference,
            }
        )

    composition["author"] = author_references

    if encounter_reference:
        composition["encounter"] = {
            "reference": encounter_reference,
        }

    if organization_reference:
        composition["custodian"] = {
            "reference": organization_reference,
        }

    if use_ch_ips_profile:
        composition["confidentiality"] = "N"
        composition["_confidentiality"] = {
            "extension": [
                {
                    "url": CH_EPR_CONFIDENTIALITY_EXTENSION_URL,
                    "valueCodeableConcept": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "17621005",
                                "display": "Normal (qualifier value)",
                            }
                        ]
                    },
                }
            ]
        }

    references_by_section = {}

    for note_reference in (
        clinical_note_references + (section_resource_references or [])
    ):
        key = _section_key(
            note_reference.get("sectionCode"),
            note_reference.get("sectionTitle"),
        )

        references_by_section.setdefault(key, []).append(
            {
                "reference": note_reference["reference"],
            }
        )

    for section in section_summaries:
        section_code = section.get("code") or {}
        section_title = section.get("title")

        section_entry = {}

        if section_title:
            section_entry["title"] = section_title

        section_concept = _build_codeable_concept(section_code)

        if section_concept:
            section_entry["code"] = section_concept

        section_key = _section_key(
            section_code.get("code"),
            section_title,
        )

        note_references = references_by_section.get(section_key, [])

        if note_references:
            section_entry["entry"] = note_references

        if section_entry:
            composition["section"].append(section_entry)

    if not composition["section"]:
        composition.pop("section")

    return composition