import hashlib
import re
import uuid

from domain.patient import Address, HumanName, Identifier, PatientData, Telecom
from builders.ch_core_patient_builder import build_ch_core_patient
from fhir.narrative import ensure_resource_narrative


HL7_V2_IDENTIFIER_SYSTEM = "https://hl7.org/fhir/sid/us-ssn"
LOCAL_IDENTIFIER_SYSTEM = "https://woess.ch/fhir/NamingSystem/hl7v2"
LOINC_SYSTEM = "http://loinc.org"
LOCAL_CODE_SYSTEM = "https://woess.ch/fhir/CodeSystem/hl7v2-local"


def _clean(value):
    value = (value or "").strip()
    return value or None


def _components(value):
    return (value or "").split("^")


def _parse_timestamp(value):
    value = _clean(value)
    if not value or len(value) < 8:
        return None
    if len(value) >= 14:
        time_value = f"T{value[8:10]}:{value[10:12]}:{value[12:14]}Z"
    elif len(value) >= 12:
        time_value = f"T{value[8:10]}:{value[10:12]}:00Z"
    else:
        time_value = ""
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" + time_value


def _parse_date(value):
    value = _clean(value)
    if not value or len(value) < 8:
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _fhir_resource_id(identifier):
    identifier = _clean(identifier)
    if not identifier:
        return str(uuid.uuid4())
    return f"hl7-{identifier}"


def _parse_patient(pid):
    patient = PatientData()
    patient_identifier = _components(pid[3] if len(pid) > 3 else None)
    patient_id = _clean(patient_identifier[0] if patient_identifier else None)
    assigning_authority = _clean(patient_identifier[3] if len(patient_identifier) > 3 else None)
    identifier_type = _clean(patient_identifier[4] if len(patient_identifier) > 4 else None)
    identifier_system = (
        f"https://woess.ch/fhir/NamingSystem/hl7v2/{assigning_authority}"
        if assigning_authority
        else LOCAL_IDENTIFIER_SYSTEM
    )
    patient.identifiers = [
        Identifier(system=identifier_system, value=patient_id)
    ] if patient_id else []

    name = _components(pid[5] if len(pid) > 5 else "")
    patient.names = [
        HumanName(family=_clean(name[0]), given=[_clean(name[1])] if len(name) > 1 and _clean(name[1]) else [])
    ] if _clean(name[0]) else []

    patient.birth_date = _parse_date(pid[7] if len(pid) > 7 else None)
    gender = _clean(pid[8] if len(pid) > 8 else None)
    patient.gender = {"M": "male", "F": "female", "O": "other"}.get(gender, "unknown") if gender else None

    telecom = _clean(pid[13] if len(pid) > 13 else None)
    if telecom:
        patient.telecoms = [Telecom(system="phone", value=telecom)]

    address = _components(pid[11] if len(pid) > 11 else "")
    if any(_clean(part) for part in address):
        patient.addresses = [
            Address(
                lines=[_clean(address[0])] if _clean(address[0]) else [],
                city=_clean(address[2] if len(address) > 2 else None),
                postal_code=_clean(address[4] if len(address) > 4 else None),
                country=_clean(address[5] if len(address) > 5 else None),
            )
        ]
    return patient


def _parse_observation(obx, patient_reference, obr):
    identifier = _clean(obx[3] if len(obx) > 3 else None)
    code_parts = _components(identifier)
    code = _clean(code_parts[0] if code_parts else None)
    if not code:
        return None
    system = (
        LOINC_SYSTEM
        if len(code_parts) > 2 and code_parts[2].strip().upper() == "LN"
        else LOCAL_CODE_SYSTEM
    )
    display = _clean(code_parts[1] if len(code_parts) > 1 else None)
    value_parts = _components(obx[5] if len(obx) > 5 else None)
    value = _clean(value_parts[0] if value_parts else None)
    order_identity = "|".join(
        (_clean(obr[index]) if obr and len(obr) > index else None) or ""
        for index in (2, 3, 4, 7)
    )
    observation_identity = "|".join([
        patient_reference,
        order_identity,
        identifier or "",
        value or "",
        _clean(obx[6] if len(obx) > 6 else None) or "",
        _clean(obx[7] if len(obx) > 7 else None) or "",
        _clean(obx[14] if len(obx) > 14 else None) or "",
    ])
    observation_id = hashlib.sha256(
        observation_identity.encode("utf-8")
    ).hexdigest()[:32]

    observation = {
        "resourceType": "Observation",
        "id": observation_id,
        "identifier": [{
            "system": "https://woess.ch/fhir/NamingSystem/hl7v2-observation",
            "value": hashlib.sha256(observation_identity.encode("utf-8")).hexdigest(),
        }],
        "status": {"F": "final", "P": "preliminary"}.get(_clean(obx[11] if len(obx) > 11 else None), "final"),
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory",
                "display": "Laboratory",
            }],
        }],
        "subject": {"reference": patient_reference},
        "code": {"coding": [{"system": system, "code": code, "display": display}] if system else [{"code": code, "display": display}], "text": display or code},
        "valueQuantity": {"value": float(value), "unit": _clean(obx[6] if len(obx) > 6 else None)} if value else {},
    }
    effective_value = obx[14] if len(obx) > 14 and _clean(obx[14]) else None
    effective_value = effective_value or (obr[7] if obr and len(obr) > 7 else None)
    effective = _parse_timestamp(effective_value)
    if effective:
        observation["effectiveDateTime"] = effective
    reference_range = _clean(obx[7] if len(obx) > 7 else None)
    if reference_range:
        observation["referenceRange"] = [{"text": reference_range}]

    interpretation = _clean(obx[8] if len(obx) > 8 else None)
    if interpretation:
        observation["interpretation"] = [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0078",
                "code": interpretation,
            }],
            "text": interpretation,
        }]

    observation["extension"] = [{"url": "https://woess.ch/fhir/StructureDefinition/hl7v2-observation-id", "valueString": identifier}]
    return observation


def parse_oru_r01(message):
    normalized_message = message.replace("\r\n", "\r").replace("\n", "\r")
    normalized_message = re.sub(
        r"\s+(?=(?:MSH|PID|PV1|ORC|OBR|OBX)\|)",
        "\r",
        normalized_message,
    )
    segments = [line for line in normalized_message.split("\r") if line]
    parsed = [segment.split("|") for segment in segments]
    if not parsed or parsed[0][0] != "MSH" or len(parsed[0]) < 9 or parsed[0][8] != "ORU^R01":
        raise ValueError("HL7v2 ORU^R01 message expected")

    pid = next((segment for segment in parsed if segment[0] == "PID"), None)
    if not pid:
        raise ValueError("HL7v2 PID segment is required")
    patient = _parse_patient(pid)
    patient_id = patient.identifiers[0].value if patient.identifiers else str(uuid.uuid4())
    patient_resource = build_ch_core_patient(patient)
    patient_resource_id = _fhir_resource_id(patient_id)
    patient_resource["id"] = patient_resource_id
    patient_reference = f"Patient/{patient_resource_id}"

    entries = [{"resource": patient_resource, "fullUrl": f"urn:uuid:{patient_resource_id}"}]
    obr = None
    seen_observation_ids = set()
    for segment in parsed:
        if segment[0] == "OBR":
            obr = segment
            continue
        if segment[0] == "OBX":
            observation = _parse_observation(segment, patient_reference, obr)
            if observation and observation["id"] not in seen_observation_ids:
                seen_observation_ids.add(observation["id"])
                entries.append({"resource": observation})

    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


def to_transaction_bundle(bundle):
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("FHIR Bundle expected")

    transaction = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [],
    }

    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        if not resource_type or not resource_id:
            raise ValueError("Every HL7v2 resource requires resourceType and id")

        transaction_entry = dict(entry)
        ensure_resource_narrative(resource)
        transaction_entry["request"] = {
            "method": "PUT",
            "url": f"{resource_type}/{resource_id}",
        }
        transaction["entry"].append(transaction_entry)

    return transaction