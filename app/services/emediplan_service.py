import base64
import datetime as dt
import gzip
import hashlib
import json
import re
import uuid
import xml.dom.minidom
import xml.etree.ElementTree as ET
import requests

from fhir.bundle import build_bundle_entry
from services.refdata_service import lookup_gln
from terminology.emediplan_medication_map import resolve_medication_identity


EMEDIPLAN_PREFIX = "CHMED16A"
CH_CORE_PRACTITIONER_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-practitioner"
)
GLN_SYSTEM = "urn:oid:2.51.1.3"

PATIENT_IDENTIFIER_SYSTEM_MAP = {
    1: "https://emediplan.ch/fhir/NamingSystem/patient-insurance-card",
}

MEDICATION_IDENTIFIER_SYSTEM_MAP = {
    2: "urn:epc:id:sgtin",
    3: "https://emediplan.ch/fhir/NamingSystem/pharmacode",
    4: "https://emediplan.ch/fhir/NamingSystem/product-number",
}

SNOMED_SYSTEM = "http://snomed.info/sct"
CH_EMED_MEDICATION_PROFILE = (
    "http://fhir.ch/ig/ch-emed/StructureDefinition/ch-emed-medication"
)
EMEDIPLAN_DISPENSING_CATEGORY_EXTENSION = (
    "https://emediplan.ch/fhir/StructureDefinition/dispensing-category"
)

MEASUREMENT_DEFINITIONS = {
    1: {
        "loinc": "29463-7",
        "display": "Body weight",
        "default_unit": "kg",
    },
    2: {
        "loinc": "8302-2",
        "display": "Body height",
        "default_unit": "cm",
    },
}

MEASUREMENT_UNITS = {
    (1, 2): "kg",
    (2, 1): "cm",
}

RISK_CATEGORY_DISPLAY = {
    1: "Renal insufficiency",
    2: "Liver insufficiency",
    3: "Reproduction",
    4: "Competitive athlete",
    5: "Operating vehicles or machines",
    6: "Allergies",
    7: "Diabetes",
}

RISK_ID_DISPLAY = {
    1: {
        597: "Renal insufficiency, terminal (Clcr <15 ml/min)",
        575: "Renal insufficiency, severe (Clcr >=15-29 ml/min)",
        576: "Renal insufficiency, moderate (Clcr >=30-59 ml/min)",
        577: "Renal insufficiency, mild (Clcr >=60-89 ml/min)",
    },
    2: {
        572: "Liver insufficiency, severe (Child-Pugh C)",
        573: "Liver insufficiency, moderate (Child-Pugh B)",
        574: "Liver insufficiency, mild (Child-Pugh A)",
    },
    3: {
        78: "Pregnancy",
        77: "Breastfeeding",
        612: "Women of childbearing potential",
    },
    4: {},
    5: {},
    6: {
        555: "Allergy to penicillins",
        571: "Allergy to acetylsalicylic acid",
    },
    7: {
        779: "Diabetes mellitus type 1",
        780: "Diabetes mellitus type 2",
    },
}


def _clean(value):
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        return value if value else None

    return value


def _is_valid_gln(value):
    # GLN/GTIN-13 use the GS1 mod-10 check digit (no external lookup needed to
    # validate the format; full name/address enrichment still requires
    # refdata.ch's registered SOAP/XML API).
    if not value or not value.isdigit() or len(value) != 13:
        return False

    digits = [int(c) for c in value]
    payload, check_digit = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload)))
    return (10 - (total % 10)) % 10 == check_digit


def _stable_id(prefix, *parts):
    raw = "|".join([str(p or "") for p in parts])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:24]}"


def _gender_from_emediplan(value):
    mapping = {
        1: "male",
        2: "female",
    }
    return mapping.get(value, "unknown")


def _decode_chmed16a_string(payload_text):
    compact = re.sub(r"\s+", "", payload_text)

    if not compact.startswith(EMEDIPLAN_PREFIX):
        raise ValueError("Unsupported eMediplan transmission format")

    if len(compact) <= len(EMEDIPLAN_PREFIX):
        raise ValueError("Missing CHMED16A payload")

    payload = compact[len(EMEDIPLAN_PREFIX) + 1 :]

    if not payload:
        raise ValueError("Empty CHMED16A payload")

    compressed = base64.b64decode(payload)
    json_bytes = gzip.decompress(compressed)
    return json.loads(json_bytes.decode("utf-8"))


def parse_emediplan_payload(raw_content):
    text = raw_content.decode("utf-8").strip()

    if not text:
        raise ValueError("Empty eMediplan payload")

    if text.startswith("{"):
        return json.loads(text)

    if text.startswith(EMEDIPLAN_PREFIX):
        return _decode_chmed16a_string(text)

    raise ValueError(
        "Unsupported payload. Provide CHMED16A string or CHMED16A JSON object"
    )


def _build_patient(patient_data):
    patient_data = patient_data or {}

    identifiers = []

    for item in patient_data.get("Ids", []) or []:
        id_type = item.get("Type")
        value = _clean(item.get("Val"))
        system = PATIENT_IDENTIFIER_SYSTEM_MAP.get(id_type)

        if value and system:
            identifiers.append(
                {
                    "system": system,
                    "value": value,
                }
            )

    patient_id = _stable_id(
        "pat",
        _clean(patient_data.get("BDt")),
        _clean(patient_data.get("FName")),
        _clean(patient_data.get("LName")),
        json.dumps(identifiers, sort_keys=True),
    )

    patient = {
        "resourceType": "Patient",
        "id": patient_id,
        "name": [
            {
                "family": _clean(patient_data.get("LName")) or "Unknown",
                "given": [
                    _clean(patient_data.get("FName")) or "Unknown",
                ],
            }
        ],
        "gender": _gender_from_emediplan(patient_data.get("Gender")),
    }

    birth_date = _clean(patient_data.get("BDt"))
    if birth_date:
        patient["birthDate"] = birth_date

    street = _clean(patient_data.get("Street"))
    zip_code = _clean(patient_data.get("Zip"))
    city = _clean(patient_data.get("City"))

    if street or zip_code or city:
        address = {}
        if street:
            address["line"] = [street]
        if zip_code:
            address["postalCode"] = zip_code
        if city:
            address["city"] = city
        patient["address"] = [address]

    telecom = []
    phone = _clean(patient_data.get("Phone"))
    email = _clean(patient_data.get("Email"))

    if phone:
        telecom.append(
            {
                "system": "phone",
                "value": phone,
            }
        )

    if email:
        telecom.append(
            {
                "system": "email",
                "value": email,
            }
        )

    if telecom:
        patient["telecom"] = telecom

    if identifiers:
        patient["identifier"] = identifiers

    return patient


def _posology_text(posology):
    doses = posology.get("D")

    if not isinstance(doses, list) or len(doses) != 4:
        return None

    labels = ["Morgen", "Mittag", "Abend", "Nacht"]
    parts = []

    for label, dose in zip(labels, doses):
        parts.append(f"{label}: {dose}")

    return ", ".join(parts)


def _medication_status_from_posology(posology):
    dt_to = _clean(posology.get("DtTo"))

    if not dt_to:
        return "active"

    try:
        end_date = dt.date.fromisoformat(dt_to)
        if end_date < dt.date.today():
            return "completed"
    except ValueError:
        return "active"

    return "active"


def _private_field_value(medicament, *field_names):
    pfields = medicament.get("PFields") or []

    if not isinstance(pfields, list):
        return None

    normalized_candidates = {name.strip().lower() for name in field_names}

    for field in pfields:
        if not isinstance(field, dict):
            continue

        name = _clean(field.get("Nm"))
        value = _clean(field.get("Val"))

        if not name or not value:
            continue

        if name.lower() in normalized_candidates:
            return value

    return None


def _extract_snomed_coding(medicament):
    code = (
        _clean(medicament.get("SnomedCode"))
        or _clean(medicament.get("SNOMEDCode"))
        or _clean(medicament.get("Snomed"))
        or _private_field_value(
            medicament,
            "SNOMED",
            "SNOMED_CT",
            "SNOMED_CODE",
            "SnomedCode",
        )
    )

    if not code:
        return None

    display = (
        _clean(medicament.get("SnomedDisplay"))
        or _clean(medicament.get("SNOMEDDisplay"))
        or _private_field_value(
            medicament,
            "SNOMED_DISPLAY",
            "SnomedDisplay",
        )
    )

    coding = {
        "system": SNOMED_SYSTEM,
        "code": code,
    }

    if display:
        coding["display"] = display

    return coding


def _codeable_concept_from_source(value):
    value = _clean(value)

    if not value:
        return None

    if isinstance(value, dict):
        codings = []
        for coding in value.get("coding") or []:
            if not isinstance(coding, dict):
                continue

            code = _clean(coding.get("code"))
            display = _clean(coding.get("display") or coding.get("displayName"))
            system = _clean(coding.get("system"))

            if not (code or display):
                continue

            coding_entry = {}
            if system:
                coding_entry["system"] = system
            if code:
                coding_entry["code"] = code
            if display:
                coding_entry["display"] = display
            codings.append(coding_entry)

        result = {}
        text = _clean(value.get("text") or value.get("display") or value.get("displayName"))
        if text:
            result["text"] = text
        if codings:
            result["coding"] = codings
        return result or None

    return {"text": value}


def _ratio_from_source(value):
    if not isinstance(value, dict):
        return None

    ratio = {}

    numerator = value.get("numerator") or {}
    denominator = value.get("denominator") or {}

    if isinstance(numerator, dict):
        quantity = {}
        if numerator.get("value") is not None:
            quantity["value"] = numerator.get("value")
        if numerator.get("unit"):
            quantity["unit"] = numerator.get("unit")
        if numerator.get("system"):
            quantity["system"] = numerator.get("system")
        if numerator.get("code"):
            quantity["code"] = numerator.get("code")
        if quantity:
            ratio["numerator"] = quantity

    if isinstance(denominator, dict):
        quantity = {}
        if denominator.get("value") is not None:
            quantity["value"] = denominator.get("value")
        if denominator.get("unit"):
            quantity["unit"] = denominator.get("unit")
        if denominator.get("system"):
            quantity["system"] = denominator.get("system")
        if denominator.get("code"):
            quantity["code"] = denominator.get("code")
        if quantity:
            ratio["denominator"] = quantity

    return ratio or None


def _to_decimal(value):
    cleaned = _clean(value)

    if cleaned is None:
        return None

    normalized = cleaned.replace(",", ".")

    try:
        return float(normalized)
    except ValueError:
        return None


def _build_measurement_observation(patient_reference, measurement):
    measurement_type = measurement.get("Type")
    measurement_value_raw = measurement.get("Val")
    definition = MEASUREMENT_DEFINITIONS.get(measurement_type)

    if not definition:
        return None

    quantity_value = _to_decimal(measurement_value_raw)

    if quantity_value is None:
        return None

    unit = MEASUREMENT_UNITS.get(
        (measurement_type, measurement.get("Unit")),
        definition["default_unit"],
    )

    identifier_value = _stable_id(
        "emed-meas-ident",
        patient_reference,
        measurement_type,
        measurement.get("Unit"),
        measurement_value_raw,
    )

    return {
        "resourceType": "Observation",
        "id": _stable_id(
            "emed-meas",
            patient_reference,
            measurement_type,
            measurement.get("Unit"),
            measurement_value_raw,
        ),
        "identifier": [
            {
                "system": "https://emediplan.ch/fhir/NamingSystem/measurement-observation",
                "value": identifier_value,
            }
        ],
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": definition["loinc"],
                    "display": definition["display"],
                }
            ],
            "text": definition["display"],
        },
        "subject": {
            "reference": patient_reference,
        },
        "valueQuantity": {
            "value": quantity_value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
            "code": unit,
        },
    }


def _build_risk_condition(patient_reference, category_id, risk_id):
    category_display = RISK_CATEGORY_DISPLAY.get(
        category_id,
        f"Risk category {category_id}",
    )
    risk_display = (
        RISK_ID_DISPLAY.get(category_id, {}).get(risk_id)
        or f"Risk {risk_id}"
    )

    text = f"{category_display}: {risk_display}"

    return {
        "resourceType": "Condition",
        "id": _stable_id(
            "emed-risk",
            patient_reference,
            category_id,
            risk_id,
        ),
        "identifier": [
            {
                "system": "https://emediplan.ch/fhir/NamingSystem/risk-condition",
                "value": _stable_id(
                    "emed-risk-ident",
                    patient_reference,
                    category_id,
                    risk_id,
                ),
            }
        ],
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                        "code": "problem-list-item",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "https://emediplan.ch/fhir/CodeSystem/risk-id",
                    "code": str(risk_id),
                    "display": risk_display,
                },
                {
                    "system": "https://emediplan.ch/fhir/CodeSystem/risk-category",
                    "code": str(category_id),
                    "display": category_display,
                },
            ],
            "text": text,
        },
        "subject": {
            "reference": patient_reference,
        },
    }


def _build_medical_data_resources(patient_data, patient_reference):
    med_data = (patient_data or {}).get("Med") or {}
    resources = []

    for measurement in med_data.get("Meas", []) or []:
        observation = _build_measurement_observation(
            patient_reference,
            measurement,
        )

        if observation:
            resources.append(observation)

    for category in med_data.get("Rc", []) or []:
        category_id = category.get("Id")
        risks = category.get("R") or []

        if not category_id or not isinstance(risks, list):
            continue

        for risk_id in risks:
            condition = _build_risk_condition(
                patient_reference,
                category_id,
                risk_id,
            )
            resources.append(condition)

    return resources


def _medication_statement_signature(
    patient_reference,
    med_id_type,
    med_id,
    medicament,
):
    posologies = medicament.get("Pos") or []
    first = posologies[0] if posologies else {}

    return {
        "patient_reference": patient_reference,
        "medication": {
            "id_type": med_id_type,
            "id": med_id,
        },
        "effective_period": {
            "start": _clean(first.get("DtFrom")),
            "end": _clean(first.get("DtTo")),
        },
        "dosage_text": _posology_text(first) if first else None,
        "application_instruction": _clean(medicament.get("AppInstr")),
        "reason": _clean(medicament.get("TkgRsn")),
        "auto_med": medicament.get("AutoMed"),
        "reserve": first.get("InRes") if first else None,
    }


def _append_resource_if_new(resources, seen_resource_keys, resource):
    resource_key = (
        resource.get("resourceType"),
        resource.get("id"),
    )

    if resource_key in seen_resource_keys:
        return

    seen_resource_keys.add(resource_key)
    resources.append(resource)


def _build_medication_resources(medicament, patient_reference):
    raw_med_id = _clean(medicament.get("Id"))
    raw_med_id_type = medicament.get("IdType")

    resolved = resolve_medication_identity(
        raw_med_id_type,
        raw_med_id,
    )

    med_id = resolved.get("id") or raw_med_id
    med_id_type = resolved.get("id_type") or raw_med_id_type
    med_display = resolved.get("display") or med_id
    med_form = resolved.get("form")
    med_ingredient = resolved.get("ingredient")
    med_strength = resolved.get("strength")
    med_dispensing_category = resolved.get("dispensing_category")

    med_statement_signature = _medication_statement_signature(
        patient_reference,
        med_id_type,
        med_id,
        medicament,
    )

    med_resource_id = _stable_id("med", med_id_type, med_id)
    med_stmt_identifier = _stable_id(
        "medstmt-ident",
        json.dumps(med_statement_signature, sort_keys=True),
    )

    medication = {
        "resourceType": "Medication",
        "id": med_resource_id,
        "meta": {
            "profile": [
                CH_EMED_MEDICATION_PROFILE,
            ]
        },
        "status": "active",
        "code": {
            "text": med_display or "Medication",
        },
    }

    if med_dispensing_category:
        medication["extension"] = [
            {
                "url": EMEDIPLAN_DISPENSING_CATEGORY_EXTENSION,
                "valueCode": med_dispensing_category,
            }
        ]

    coding_entries = []

    primary_system = MEDICATION_IDENTIFIER_SYSTEM_MAP.get(med_id_type)
    if primary_system and med_id:
        coding_entries.append(
            {
                "system": primary_system,
                "code": med_id,
                "display": med_display,
            }
        )

    # Keep original source code as additional coding when identity was normalized.
    source_system = MEDICATION_IDENTIFIER_SYSTEM_MAP.get(raw_med_id_type)
    if source_system and raw_med_id:
        is_same_as_primary = (
            source_system == primary_system
            and raw_med_id == med_id
        )

        if not is_same_as_primary:
            coding_entries.append(
                {
                    "system": source_system,
                    "code": raw_med_id,
                    "display": raw_med_id,
                }
            )

    snomed_coding = _extract_snomed_coding(medicament)
    if snomed_coding:
        coding_entries.append(snomed_coding)

    if coding_entries:
        unique_codings = []
        seen = set()

        for coding in coding_entries:
            key = (coding.get("system"), coding.get("code"))

            if key in seen:
                continue

            seen.add(key)
            unique_codings.append(coding)

        medication["code"] = {
            "coding": unique_codings,
            "text": med_display,
        }

    if med_form:
        medication["form"] = _codeable_concept_from_source(med_form)

    ingredient_concept = _codeable_concept_from_source(med_ingredient)
    ingredient_strength = _ratio_from_source(med_strength)

    if ingredient_concept or ingredient_strength:
        ingredient_entry = {}

        if ingredient_concept:
            ingredient_entry["itemCodeableConcept"] = ingredient_concept

        if ingredient_strength:
            ingredient_entry["strength"] = ingredient_strength

        if ingredient_entry:
            medication["ingredient"] = [ingredient_entry]

    if raw_med_id and raw_med_id_type in MEDICATION_IDENTIFIER_SYSTEM_MAP:
        medication.setdefault("identifier", []).append(
            {
                "system": MEDICATION_IDENTIFIER_SYSTEM_MAP[raw_med_id_type],
                "value": raw_med_id,
            }
        )

    statement = {
        "resourceType": "MedicationStatement",
        "id": _stable_id("medstmt", med_stmt_identifier),
        "identifier": [
            {
                "system": "https://emediplan.ch/fhir/NamingSystem/medicationstatement",
                "value": med_stmt_identifier,
            }
        ],
        "status": "active",
        "subject": {
            "reference": patient_reference,
        },
        "medicationReference": {
            "reference": f"Medication/{med_resource_id}",
            "display": med_display or "Medication",
        },
    }

    posologies = medicament.get("Pos") or []
    if posologies:
        first = posologies[0]
        statement["status"] = _medication_status_from_posology(first)

        effective_period = {}
        dt_from = _clean(first.get("DtFrom"))
        dt_to = _clean(first.get("DtTo"))

        if dt_from:
            effective_period["start"] = dt_from
        if dt_to:
            effective_period["end"] = dt_to

        if effective_period:
            statement["effectivePeriod"] = effective_period

        dosage_text = _posology_text(first)
        dosage_parts = []

        app_instr = _clean(medicament.get("AppInstr"))
        if app_instr:
            dosage_parts.append(app_instr)

        if dosage_text:
            dosage_parts.append(dosage_text)

        if dosage_parts:
            statement["dosage"] = [
                {
                    "text": " | ".join(dosage_parts),
                }
            ]

        if first.get("InRes") == 1:
            statement.setdefault("note", []).append(
                {
                    "text": "Reserve medication",
                }
            )

    reason = _clean(medicament.get("TkgRsn"))
    if reason:
        statement["reasonCode"] = [
            {
                "text": reason,
            }
        ]

    auto_med = medicament.get("AutoMed")
    if auto_med == 1:
        statement.setdefault("note", []).append(
            {
                "text": "Self-medication",
            }
        )

    practitioner = None
    prescribed_by = _clean(medicament.get("PrscbBy"))

    if prescribed_by:
        if _is_valid_gln(prescribed_by):
            # GLN (Global Location Number), the standard CH identifier for healthcare professionals/orgs.
            practitioner_id = _stable_id("prac-gln", prescribed_by)
            practitioner = {
                "resourceType": "Practitioner",
                "id": practitioner_id,
                "meta": {
                    "profile": [CH_CORE_PRACTITIONER_PROFILE],
                },
                "identifier": [
                    {
                        "system": GLN_SYSTEM,
                        "value": prescribed_by,
                    }
                ],
            }

            # Best-effort enrichment via refdata.ch's official GLN registry (Partner API).
            # Silently skipped when the API isn't configured/reachable or the GLN isn't found.
            refdata_entry = lookup_gln(prescribed_by)
            if refdata_entry:
                if refdata_entry.get("name"):
                    practitioner["name"] = [{"text": refdata_entry["name"]}]
                if refdata_entry.get("address"):
                    address = refdata_entry["address"]
                    practitioner["address"] = [
                        {
                            key: value
                            for key, value in address.items()
                            if value
                        }
                    ]

            statement["informationSource"] = {"reference": f"Practitioner/{practitioner_id}"}
        else:
            statement["informationSource"] = {"display": prescribed_by}

    return medication, statement, practitioner


def emediplan_to_fhir_bundle(raw_content):
    med_object = parse_emediplan_payload(raw_content)
    plan_id = _clean(med_object.get("Id"))

    patient = _build_patient(med_object.get("Patient") or {})
    patient_reference = f"Patient/{patient['id']}"

    resources = [patient]
    seen_resource_keys = {
        (patient.get("resourceType"), patient.get("id")),
    }

    for resource in _build_medical_data_resources(
        med_object.get("Patient") or {},
        patient_reference,
    ):
        _append_resource_if_new(resources, seen_resource_keys, resource)

    medicaments = med_object.get("Medicaments") or []
    for medicament in medicaments:
        medication, statement, practitioner = _build_medication_resources(
            medicament,
            patient_reference,
        )
        _append_resource_if_new(resources, seen_resource_keys, medication)
        _append_resource_if_new(resources, seen_resource_keys, statement)

        if practitioner:
            _append_resource_if_new(resources, seen_resource_keys, practitioner)

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{"resource": resource} for resource in resources],
    }

    if plan_id:
        bundle["identifier"] = {
            "system": "https://emediplan.ch/fhir/NamingSystem/emediplan-plan-id",
            "value": plan_id,
        }

    return bundle


def bundle_to_transaction_bundle(bundle):
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("FHIR Bundle expected")

    if bundle.get("type") == "transaction":
        return bundle

    transaction_entries = []

    for entry in bundle.get("entry", []) or []:
        resource = entry.get("resource") or {}

        if not resource.get("resourceType"):
            continue

        original_resource_type = resource.get("resourceType")
        original_resource_id = resource.get("id")

        transaction_entry = build_bundle_entry(resource)

        aliases = []

        if original_resource_type and original_resource_id:
            aliases.append(f"{original_resource_type}/{original_resource_id}")

        current_resource = transaction_entry.get("resource") or {}
        current_resource_type = current_resource.get("resourceType")
        current_resource_id = current_resource.get("id")

        if current_resource_type and current_resource_id:
            current_reference = f"{current_resource_type}/{current_resource_id}"

            if current_reference not in aliases:
                aliases.append(current_reference)

        if aliases:
            transaction_entry["_referenceAliases"] = aliases

        transaction_entries.append(transaction_entry)

    _rewrite_internal_references_to_fullurl(
        transaction_entries
    )

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": transaction_entries,
    }


def _rewrite_internal_references_to_fullurl(transaction_entries):
    reference_map = {}

    for entry in transaction_entries:
        resource = entry.get("resource") or {}
        full_url = entry.get("fullUrl")

        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")

        if not full_url:
            continue

        aliases = entry.get("_referenceAliases") or []

        if resource_type and resource_id:
            default_alias = f"{resource_type}/{resource_id}"

            if default_alias not in aliases:
                aliases.append(default_alias)

        for alias in aliases:
            if isinstance(alias, str) and alias:
                reference_map[alias] = full_url

    if not reference_map:
        return

    for entry in transaction_entries:
        resource = entry.get("resource") or {}
        _rewrite_reference_values(resource, reference_map)

        entry.pop("_referenceAliases", None)


def _rewrite_reference_values(node, reference_map):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "reference" and isinstance(value, str):
                rewritten = reference_map.get(value)

                if rewritten:
                    node[key] = rewritten
                    continue

            _rewrite_reference_values(value, reference_map)

    elif isinstance(node, list):
        for item in node:
            _rewrite_reference_values(item, reference_map)


def import_bundle_to_fhir_server(bundle, fhir_base, timeout_seconds=300):
    if not fhir_base:
        raise ValueError("FHIR base URL is required")

    transaction_bundle = bundle_to_transaction_bundle(bundle)

    response = requests.post(
        fhir_base.rstrip("/"),
        json=transaction_bundle,
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        },
        timeout=timeout_seconds,
    )

    try:
        response_payload = response.json()
    except Exception:
        response_payload = response.text

    return {
        "status": "imported" if response.status_code < 300 else "error",
        "fhir_status": response.status_code,
        "bundle_entry_count": len(transaction_bundle.get("entry", [])),
        "response": response_payload,
    }


def import_emediplan_to_fhir_server(raw_content, fhir_base, timeout_seconds=300):
    bundle = emediplan_to_fhir_bundle(raw_content)
    return import_bundle_to_fhir_server(
        bundle,
        fhir_base,
        timeout_seconds=timeout_seconds,
    )


def _extract_patient_from_bundle(bundle):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Patient":
            return resource
    return {}


def _extract_medication_graph(bundle):
    medications = {}
    statements = []

    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")

        if resource_type == "Medication":
            resource_id = resource.get("id")
            if resource_id:
                medications[f"Medication/{resource_id}"] = resource

        if resource_type == "MedicationStatement":
            statements.append(resource)

    return medications, statements


def _extract_practitioners_from_bundle(bundle):
    practitioners = {}

    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Practitioner":
            resource_id = resource.get("id")
            if resource_id:
                practitioners[f"Practitioner/{resource_id}"] = resource

    return practitioners


def _prescriber_details(statement, practitioners_by_ref):
    """Resolves a best-effort (gln, name) pair for the C-CDA Medication Activity author."""
    info_source = statement.get("informationSource") or {}
    practitioner = practitioners_by_ref.get(info_source.get("reference"))

    if practitioner:
        gln = next(
            (
                _clean(identifier.get("value"))
                for identifier in practitioner.get("identifier", [])
                if _clean(identifier.get("value"))
            ),
            None,
        )
        name = None
        for name_entry in practitioner.get("name") or []:
            name = _clean(name_entry.get("text"))
            if name:
                break

        if not name and gln and _is_valid_gln(gln):
            # The bundle's Practitioner may lack a name (e.g. fetched straight from the
            # FHIR server without refdata enrichment) - resolve it via GLN on export too.
            refdata_entry = lookup_gln(gln)
            if refdata_entry and refdata_entry.get("name"):
                name = refdata_entry["name"]

        return gln, name

    display = _clean(info_source.get("display"))
    return None, display


def _cda_effective_time(statement):
    period = statement.get("effectivePeriod") or {}
    start = _clean(period.get("start"))
    end = _clean(period.get("end"))

    if not start:
        effective_datetime = _clean(statement.get("effectiveDateTime"))
        if effective_datetime:
            # PROC-EXP-01: Fall back to effectiveDateTime when no effectivePeriod exists.
            # Convert YYYY-MM-DD or full datetime to CDA TS date precision.
            start = effective_datetime.replace("-", "")[:8]

    result = {}
    if start:
        result["start"] = start.replace("-", "")
    if end:
        result["end"] = end.replace("-", "")

    return result


def _codes_from_medication(medication, statement):
    codeable = medication.get("code") or {}

    if not codeable and statement.get("medicationCodeableConcept"):
        codeable = statement.get("medicationCodeableConcept")

    codings = []

    for coding in codeable.get("coding") or []:
        system = _clean(coding.get("system"))
        code = _clean(coding.get("code"))
        display = _clean(coding.get("display"))

        if not code and not display:
            continue

        codings.append(
            {
                "code": code,
                "system": system,
                "display": display,
            }
        )

    if codings:
        return codings

    # PROC-EXP-02: Last-resort structured code fallback from Medication.identifier.
    fallback_display = _clean(codeable.get("text"))

    identifier = (medication.get("identifier") or [None])[0] or {}
    identifier_system = _clean(identifier.get("system"))
    identifier_value = _clean(identifier.get("value"))

    return [
        {
            "code": identifier_value,
            "system": identifier_system,
            "display": fallback_display,
        }
    ]


def _medication_text(value):
    if isinstance(value, dict):
        return _clean(value.get("text") or value.get("display") or value.get("displayName"))

    return _clean(value)


def _medication_form_code(medication):
    form = medication.get("form") or {}

    if not isinstance(form, dict):
        return None

    coding = (form.get("coding") or [None])[0] or {}
    code = _clean(coding.get("code"))
    system = _clean(coding.get("system"))
    display = _medication_text(form)

    attrs = {}

    if code:
        attrs["code"] = code
    if system:
        attrs["codeSystem"] = system
    if display:
        attrs["displayName"] = display

    return attrs or None


def _medication_detail_parts(medication):
    parts = []

    def quantity_text(quantity):
        if not isinstance(quantity, dict):
            return None

        value = _clean(quantity.get("value"))
        unit = _clean(quantity.get("unit"))

        if value is None and unit is None:
            return None

        if unit in {None, "", "1"}:
            return str(value) if value is not None else None

        if value is None:
            return unit

        return f"{value} {unit}"

    form_text = _medication_text(medication.get("form"))
    if form_text:
        parts.append(f"Form: {form_text}")

    ingredients = medication.get("ingredient") or []
    ingredient_parts = []

    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            continue

        concept = ingredient.get("itemCodeableConcept") or {}
        ingredient_text = _medication_text(concept)

        if ingredient_text:
            ingredient_parts.append(ingredient_text)

    if ingredient_parts:
        parts.append(f"Wirkstoff: {', '.join(dict.fromkeys(ingredient_parts))}")

    if ingredients:
        strength_parts = []

        for ingredient in ingredients:
            if not isinstance(ingredient, dict):
                continue

            strength = ingredient.get("strength") or {}
            numerator = strength.get("numerator") or {}
            denominator = strength.get("denominator") or {}

            numerator_text = quantity_text(numerator)
            denominator_text = quantity_text(denominator)

            if not (numerator_text or denominator_text):
                continue

            text = numerator_text or denominator_text

            if numerator_text and denominator_text:
                text = f"{numerator_text} / {denominator_text}"

            strength_parts.append(text)

        if strength_parts:
            parts.append(f"Staerke: {', '.join(dict.fromkeys(strength_parts))}")

    return parts


def _format_cda_date(value):
    cleaned = _clean(value)
    if not cleaned:
        return None

    cleaned = cleaned.replace("-", "")
    if len(cleaned) >= 8:
        return f"{cleaned[6:8]}.{cleaned[4:6]}.{cleaned[0:4]}"

    return cleaned


def _status_display(status):
    mapping = {
        "active": "Aktiv",
        "completed": "Abgeschlossen",
        "on-hold": "Pausiert",
        "stopped": "Gestoppt",
        "entered-in-error": "Fehlerhaft",
        "intended": "Geplant",
        "not-taken": "Nicht eingenommen",
    }
    return mapping.get(_clean(status) or "active", "Aktiv")


def _dose_quantity_text(statement):
    dosage = _primary_dosage(statement)

    for dose_and_rate in dosage.get("doseAndRate") or []:
        quantity = dose_and_rate.get("doseQuantity") or {}
        value = _clean(quantity.get("value"))
        unit = _clean(quantity.get("unit"))

        if value is None and unit is None:
            continue

        if value is None:
            return unit

        if unit:
            return f"{value} {unit}"

        return str(value)

    return None


def _render_epic_medication_table(section, statements, medications_by_ref):
    text = ET.SubElement(section, "text")
    table = ET.SubElement(text, "table")

    colgroup = ET.SubElement(table, "colgroup")
    widths = ["24%", "22%", "10%", "10%", "10%", "12%", "6%", "6%"]
    for width in widths:
        ET.SubElement(colgroup, "col", {"width": width})

    thead = ET.SubElement(table, "thead")
    header_row = ET.SubElement(thead, "tr")
    for header in [
        "Medikation",
        "Anwendungshinweis",
        "Abgabemenge",
        "Wiederholte Bezüge",
        "Letzter Bezug",
        "Beginndatum",
        "Enddatum",
        "Status",
    ]:
        ET.SubElement(header_row, "th").text = header

    tbody = ET.SubElement(table, "tbody")

    for index, statement in enumerate(statements, start=1):
        med_ref = ((statement.get("medicationReference") or {}).get("reference"))
        medication = medications_by_ref.get(med_ref, {})
        med_codes = _codes_from_medication(medication, statement)
        med_code = med_codes[0]

        row = ET.SubElement(tbody, "tr", {"ID": statement.get("id") or f"med{index}"})

        med_cell = ET.SubElement(row, "td")
        med_label = med_code.get("display") or med_code.get("code") or "Unknown medication"
        med_details = _medication_detail_parts(medication)
        med_cell.text = med_label
        if med_details:
            med_cell.text = f"{med_label} | {' | '.join(med_details)}"

        dosage_cell = ET.SubElement(row, "td")
        dosage_text = (statement.get("dosage") or [{}])[0].get("text")
        dosage_cell.text = dosage_text or ""

        quantity_cell = ET.SubElement(row, "td")
        quantity_cell.text = _dose_quantity_text(statement) or ""

        ET.SubElement(row, "td").text = ""
        ET.SubElement(row, "td").text = ""

        effective = _cda_effective_time(statement)
        ET.SubElement(row, "td").text = _format_cda_date(effective.get("start")) or ""
        ET.SubElement(row, "td").text = _format_cda_date(effective.get("end")) or ""
        ET.SubElement(row, "td").text = _status_display(statement.get("status"))


def _primary_dosage(statement):
    dosage = (statement.get("dosage") or [{}])[0]
    return dosage if isinstance(dosage, dict) else {}


def _extract_cda_dose_quantity(statement):
    dosage = _primary_dosage(statement)

    for dose_and_rate in dosage.get("doseAndRate") or []:
        quantity = dose_and_rate.get("doseQuantity") or {}

        value = quantity.get("value")
        unit = _clean(quantity.get("unit"))

        if value is None and not unit:
            continue

        attrs = {}

        if value is not None:
            attrs["value"] = str(value)

        if unit:
            attrs["unit"] = unit

        return attrs

    return None


def _extract_cda_route(statement):
    dosage = _primary_dosage(statement)
    route = dosage.get("route") or {}

    coding = (route.get("coding") or [None])[0] or {}

    code = _clean(coding.get("code"))
    system = _clean(coding.get("system"))
    display = _clean(coding.get("display")) or _clean(route.get("text"))

    if not (code or display):
        return None

    attrs = {}

    if code:
        attrs["code"] = code
    if system:
        attrs["codeSystem"] = system
    if display:
        attrs["displayName"] = display

    return attrs


def _extract_clinical_note_texts(statement):
    dosage_text = _clean(_primary_dosage(statement).get("text"))
    reason_text = _clean((statement.get("reasonCode") or [{}])[0].get("text"))

    status_values = {
        "active",
        "completed",
        "on-hold",
        "stopped",
        "entered-in-error",
        "intended",
        "not-taken",
    }

    note_texts = []

    for note in statement.get("note") or []:
        text = _clean((note or {}).get("text"))

        if not text:
            continue

        lower_text = text.lower()

        if re.fullmatch(r"\d{8,14}(?:[+-]\d{4})?", text):
            continue

        if lower_text in status_values:
            continue

        if dosage_text and text == dosage_text:
            continue

        if reason_text and text == reason_text:
            continue

        note_texts.append(text)

    # PROC-EXP-03: Keep only clinically useful note text in EPIC CDA comment relationships.
    # Preserve order while de-duplicating.
    return list(dict.fromkeys(note_texts))


def _gender_to_cda_code(gender):
    gender_code_map = {
        "male": "M",
        "female": "F",
        "other": "OTH",
        "unknown": "UN",
    }
    return gender_code_map.get(gender, "UN")


def _add_patient_identifiers(patient_role, patient):
    for identifier in patient.get("identifier", []):
        attrs = {}
        system = _clean(identifier.get("system"))
        value = _clean(identifier.get("value"))

        if system:
            attrs["root"] = system
        if value:
            attrs["extension"] = value

        if attrs:
            ET.SubElement(patient_role, "id", attrs)


def _add_patient_addresses(patient_role, patient):
    for address in patient.get("address", []):
        addr_attrs = {}
        use = _clean(address.get("use"))

        if use:
            addr_attrs["use"] = use.upper()

        addr_node = ET.SubElement(patient_role, "addr", addr_attrs)

        for line in address.get("line") or []:
            cleaned = _clean(line)
            if cleaned:
                ET.SubElement(addr_node, "streetAddressLine").text = cleaned

        city = _clean(address.get("city"))
        state = _clean(address.get("state"))
        postal_code = _clean(address.get("postalCode"))
        country = _clean(address.get("country"))

        if city:
            ET.SubElement(addr_node, "city").text = city
        if state:
            ET.SubElement(addr_node, "state").text = state
        if postal_code:
            ET.SubElement(addr_node, "postalCode").text = postal_code
        if country:
            ET.SubElement(addr_node, "country").text = country


def _add_patient_telecoms(patient_role, patient):
    for telecom in patient.get("telecom", []):
        value = _clean(telecom.get("value"))

        if not value:
            continue

        system = _clean(telecom.get("system"))

        if system == "phone" and not value.startswith("tel:"):
            value = f"tel:{value}"
        elif system == "email" and not value.startswith("mailto:"):
            value = f"mailto:{value}"

        attrs = {"value": value}

        use = _clean(telecom.get("use"))
        if use:
            attrs["use"] = use.upper()

        ET.SubElement(patient_role, "telecom", attrs)


def _add_patient_names(patient_node, patient):
    names = patient.get("name") or [{}]

    for name in names:
        name_node = ET.SubElement(patient_node, "name")

        for given in name.get("given") or []:
            cleaned = _clean(given)
            if cleaned:
                ET.SubElement(name_node, "given").text = str(cleaned)

        family = _clean(name.get("family"))
        if family:
            ET.SubElement(name_node, "family").text = family


def _add_patient_optional_demographics(patient_node, patient):
    marital = (patient.get("maritalStatus") or {}).get("coding") or []
    if marital:
        item = marital[0]
        code = _clean(item.get("code"))
        system = _clean(item.get("system"))
        display = _clean(item.get("display"))

        attrs = {}
        if code:
            attrs["code"] = code
        if system:
            attrs["codeSystem"] = system
        if display:
            attrs["displayName"] = display

        if attrs:
            ET.SubElement(patient_node, "maritalStatusCode", attrs)

    deceased = patient.get("deceasedBoolean")
    if isinstance(deceased, bool):
        ET.SubElement(
            patient_node,
            "{urn:hl7-org:sdtc}deceasedInd",
            {"value": "true" if deceased else "false"},
        )

    for communication in patient.get("communication", []):
        language = communication.get("language") or {}
        language_code = None

        for coding in language.get("coding") or []:
            language_code = _clean(coding.get("code"))
            if language_code:
                break

        if not language_code:
            language_code = _clean(language.get("text"))

        if language_code:
            comm_node = ET.SubElement(patient_node, "languageCommunication")
            ET.SubElement(comm_node, "languageCode", {"code": language_code})


def fhir_medications_to_epic_cda(bundle):
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("FHIR Bundle expected")

    patient = _extract_patient_from_bundle(bundle)
    medications_by_ref, statements = _extract_medication_graph(bundle)

    ET.register_namespace("", "urn:hl7-org:v3")
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    ET.register_namespace("sdtc", "urn:hl7-org:sdtc")

    root = ET.Element("{urn:hl7-org:v3}ClinicalDocument")

    ET.SubElement(root, "templateId", {"root": "2.16.840.1.113883.10.20.22.1.1"})
    ET.SubElement(root, "templateId", {"root": "2.16.840.1.113883.10.20.22.1.2"})
    ET.SubElement(
        root,
        "code",
        {
            "code": "34133-9",
            "codeSystem": "2.16.840.1.113883.6.1",
            "displayName": "Summarization of Episode Note",
        },
    )
    ET.SubElement(root, "title").text = "eMedication16a import"

    now = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    ET.SubElement(root, "effectiveTime", {"value": now})

    record_target = ET.SubElement(root, "recordTarget")
    patient_role = ET.SubElement(record_target, "patientRole")

    _add_patient_identifiers(patient_role, patient)
    _add_patient_addresses(patient_role, patient)
    _add_patient_telecoms(patient_role, patient)

    patient_node = ET.SubElement(patient_role, "patient")
    _add_patient_names(patient_node, patient)

    birth_date = _clean(patient.get("birthDate"))
    if birth_date:
        ET.SubElement(patient_node, "birthTime", {"value": birth_date.replace("-", "")})

    gender = patient.get("gender")
    ET.SubElement(
        patient_node,
        "administrativeGenderCode",
        {"code": _gender_to_cda_code(gender)},
    )

    _add_patient_optional_demographics(patient_node, patient)

    component = ET.SubElement(root, "component")
    structured_body = ET.SubElement(component, "structuredBody")
    meds_component = ET.SubElement(structured_body, "component")
    section = ET.SubElement(meds_component, "section")

    # PROC-EXP-07: Match the C-CDA R2.1 Medication Activity section templates EPIC itself emits.
    ET.SubElement(section, "templateId", {"root": "2.16.840.1.113883.10.20.22.2.1"})
    ET.SubElement(section, "templateId", {"root": "2.16.840.1.113883.10.20.22.2.1", "extension": "2014-06-09"})
    ET.SubElement(section, "templateId", {"root": "2.16.840.1.113883.10.20.22.2.1.1"})
    ET.SubElement(section, "templateId", {"root": "2.16.840.1.113883.10.20.22.2.1.1", "extension": "2014-06-09"})
    ET.SubElement(
        section,
        "code",
        {
            "code": "10160-0",
            "codeSystem": "2.16.840.1.113883.6.1",
            "displayName": "History of Medication use",
        },
    )
    ET.SubElement(section, "title").text = "Medications"

    text = ET.SubElement(section, "text")
    list_node = ET.SubElement(text, "list")

    practitioners_by_ref = _extract_practitioners_from_bundle(bundle)

    for index, statement in enumerate(statements, start=1):
        med_ref = ((statement.get("medicationReference") or {}).get("reference"))
        medication = medications_by_ref.get(med_ref, {})
        med_codes = _codes_from_medication(medication, statement)
        med_code = med_codes[0]

        med_id = f"med{index}"
        dosage = (statement.get("dosage") or [{}])[0].get("text")
        sig_id = f"sig{index}" if dosage else None

        # PROC-EXP-08: Give the narrative item a stable ID so entries can reference it back
        # (originalText/text reference), matching how EPIC links entries to the human-readable text.
        item_node = ET.SubElement(list_node, "item", {"ID": med_id})
        item_text = med_code.get("display") or med_code.get("code") or "Unknown medication"

        reason_code = (statement.get("reasonCode") or [{}])[0].get("text")
        if reason_code:
            item_text += f" | Reason: {reason_code}"

        if dosage:
            item_node.text = f"{item_text} | "
            content_node = ET.SubElement(item_node, "content", {"ID": sig_id})
            content_node.text = f"Dosage: {dosage}"
        else:
            item_node.text = item_text

        entry = ET.SubElement(section, "entry")
        substance = ET.SubElement(entry, "substanceAdministration", {"classCode": "SBADM", "moodCode": "INT"})

        # PROC-EXP-07: C-CDA R2.1 Medication Activity entry templates.
        ET.SubElement(substance, "templateId", {"root": "2.16.840.1.113883.10.20.22.4.16"})
        ET.SubElement(substance, "templateId", {"root": "2.16.840.1.113883.10.20.22.4.16", "extension": "2014-06-09"})

        if sig_id:
            entry_text = ET.SubElement(substance, "text")
            ET.SubElement(entry_text, "reference", {"value": f"#{sig_id}"})

        status = statement.get("status") or "active"
        ET.SubElement(substance, "statusCode", {"code": status})

        effective = _cda_effective_time(statement)
        if effective:
            # PROC-EXP-04: Export normalized medication validity/start timing as CDA effectiveTime.
            effective_time = ET.SubElement(substance, "effectiveTime")
            if effective.get("start"):
                ET.SubElement(effective_time, "low", {"value": effective["start"]})
            if effective.get("end"):
                ET.SubElement(effective_time, "high", {"value": effective["end"]})

        dose_quantity = _extract_cda_dose_quantity(statement)
        if dose_quantity:
            # PROC-EXP-05: Emit quantitative dose as CDA doseQuantity for EPIC reconciliation.
            ET.SubElement(substance, "doseQuantity", dose_quantity)

        route_code = _extract_cda_route(statement)
        if route_code:
            ET.SubElement(substance, "routeCode", route_code)

        consumable = ET.SubElement(substance, "consumable", {"typeCode": "CSM"})
        manufactured_product = ET.SubElement(consumable, "manufacturedProduct", {"classCode": "MANU"})
        manufactured_material = ET.SubElement(manufactured_product, "manufacturedMaterial")

        code_attrs = {}
        if med_code.get("code"):
            code_attrs["code"] = med_code["code"]
        if med_code.get("system"):
            code_attrs["codeSystem"] = med_code["system"]
        if med_code.get("display"):
            code_attrs["displayName"] = med_code["display"]

        if code_attrs:
            code_element = ET.SubElement(manufactured_material, "code", code_attrs)

            for extra_code in med_codes[1:]:
                translation_attrs = {}

                if extra_code.get("code"):
                    translation_attrs["code"] = extra_code["code"]
                if extra_code.get("system"):
                    translation_attrs["codeSystem"] = extra_code["system"]
                if extra_code.get("display"):
                    translation_attrs["displayName"] = extra_code["display"]

                if translation_attrs:
                    ET.SubElement(code_element, "translation", translation_attrs)
        else:
            # PROC-EXP-09: Match EPIC's own fallback for unresolved medication codes: nullFlavor
            # under RxNorm, an originalText reference back to the narrative, and a generic
            # SNOMED CT "Drug or medicament (substance)" translation.
            code_element = ET.SubElement(
                manufactured_material,
                "code",
                {"nullFlavor": "UNK", "codeSystem": "2.16.840.1.113883.6.88"},
            )
            original_text = ET.SubElement(code_element, "originalText")
            ET.SubElement(original_text, "reference", {"value": f"#{med_id}"})
            ET.SubElement(
                code_element,
                "translation",
                {
                    "code": "410942007",
                    "codeSystem": "2.16.840.1.113883.6.96",
                    "codeSystemName": "SNOMED CT",
                    "displayName": "Drug or medicament (substance)",
                },
            )

        if med_code.get("display"):
            ET.SubElement(manufactured_material, "name").text = med_code["display"]

        gln, prescriber_name = _prescriber_details(statement, practitioners_by_ref)
        if gln or prescriber_name:
            # PROC-EXP-10: Emit the prescriber as the entry's author, matching C-CDA Medication Activity.
            author_node = ET.SubElement(substance, "author")
            assigned_author = ET.SubElement(author_node, "assignedAuthor")
            if gln:
                ET.SubElement(assigned_author, "id", {"root": "2.51.1.3", "extension": gln})
            else:
                ET.SubElement(assigned_author, "id", {"nullFlavor": "UNK"})
            if prescriber_name:
                assigned_person = ET.SubElement(assigned_author, "assignedPerson")
                ET.SubElement(assigned_person, "name").text = prescriber_name

        for note_text in _extract_clinical_note_texts(statement):
            # PROC-EXP-06: Render note text into comment acts linked to the medication entry.
            relationship = ET.SubElement(
                substance,
                "entryRelationship",
                {"typeCode": "SUBJ", "inversionInd": "true"},
            )

            act = ET.SubElement(
                relationship,
                "act",
                {"classCode": "ACT", "moodCode": "INT"},
            )

            # PROC-EXP-07: C-CDA R2.1 Comment Activity entry templates.
            ET.SubElement(act, "templateId", {"root": "2.16.840.1.113883.10.20.22.4.20"})
            ET.SubElement(act, "templateId", {"root": "2.16.840.1.113883.10.20.22.4.20", "extension": "2014-06-09"})

            ET.SubElement(
                act,
                "code",
                {
                    "code": "48767-8",
                    "codeSystem": "2.16.840.1.113883.6.1",
                    "displayName": "Annotation comment",
                },
            )
            ET.SubElement(act, "statusCode", {"code": "completed"})
            ET.SubElement(act, "text").text = note_text

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    parsed = xml.dom.minidom.parseString(xml_bytes)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def fetch_medication_bundle_from_fhir_server(
    fhir_base,
    patient_id=None,
    count=100,
    timeout_seconds=120,
):
    if not fhir_base:
        raise ValueError("FHIR base URL is required")

    params = [
        ("_count", str(count)),
        ("_include", "MedicationStatement:medication"),
        ("_include", "MedicationStatement:subject"),
    ]

    if patient_id:
        params.append(("subject", f"Patient/{patient_id}"))

    response = requests.get(
        f"{fhir_base.rstrip('/')}/MedicationStatement",
        params=params,
        headers={
            "Accept": "application/fhir+json",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    bundle = response.json()

    if bundle.get("resourceType") != "Bundle":
        raise ValueError("FHIR server response is not a Bundle")

    return bundle
