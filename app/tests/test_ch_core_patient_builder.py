from xml.etree import ElementTree as ET

from builders.ch_core_patient_builder import build_ch_core_patient
from parser.cda.patient_parser import parse_patient


def test_build_epic_patient_preserves_extended_patient_fields():
    root = ET.parse(
        "app/tests/data/CDA-EPIC.xml"
    ).getroot()

    patient = build_ch_core_patient(
        parse_patient(root)
    )

    assert patient["resourceType"] == "Patient"
    assert patient["meta"]["profile"][0].endswith(
        "ch-core-patient"
    )
    assert patient["deceasedBoolean"] is False
    assert patient["maritalStatus"]["coding"][0]["code"] == "S"
    assert patient["address"][0]["use"] == "home"
    assert patient["address"][0]["state"] == "BE"
    assert patient["telecom"][0]["use"] == "mobile"

    local_identifier = next(
        identifier
        for identifier in patient["identifier"]
        if identifier["system"] == "urn:oid:1.2.840.114350.1.13.521.3.7.3.688884.100"
    )

    assert local_identifier["type"]["coding"][0]["code"] == "MR"
    assert patient["name"][0]["use"] == "official"
    assert patient["name"][0]["prefix"] == ["Herr"]

    epic_contact = next(
        contact
        for contact in patient.get("contact", [])
        if contact.get("name", {}).get("text") == "Bernd Brot"
    )

    role_codings = [
        coding
        for coding in epic_contact["relationship"][0]["coding"]
        if coding.get("system") == "http://terminology.hl7.org/CodeSystem/v3-RoleCode"
    ]

    assert all(
        coding.get("code") or coding.get("display")
        for coding in role_codings
    )


def test_build_at_patient_includes_birthplace_religion_language_and_contact():
    root = ET.parse(
        "app/tests/data/CDA-AT.xml"
    ).getroot()

    patient = build_ch_core_patient(
        parse_patient(root)
    )

    assert patient["maritalStatus"]["coding"][0]["code"] == "M"
    assert patient["communication"][0]["language"]["coding"][0]["code"] == "de"
    assert patient["communication"][0]["preferred"] is True
    assert patient["contact"][0]["relationship"][0]["coding"][0]["code"] == "GUARD"
    assert patient["contact"][0]["name"]["family"] == "Sorgenvoll"
    assert patient["contact"][0]["telecom"][0]["use"] == "mobile"
    assert patient["name"][0]["prefix"] == ["Dipl.Ing.", "Hofrat"]
    assert patient["name"][0]["suffix"] == ["BSc", "MBA"]
    assert any(
        name.get("family") == "VorDerHeirat" and name.get("use") == "old"
        for name in patient["name"]
    )

    birth_place_extension = next(
        extension
        for extension in patient["extension"]
        if extension["url"] == "http://hl7.org/fhir/StructureDefinition/patient-birthPlace"
    )

    religion_extension = next(
        extension
        for extension in patient["extension"]
        if extension["url"] == "http://hl7.org/fhir/StructureDefinition/patient-religion"
    )

    assert birth_place_extension["valueAddress"]["text"] == "Graz"
    assert religion_extension["valueCodeableConcept"]["coding"][0]["code"] == "101"


def test_build_mwo_patient_maps_participant_to_contact_slice_shape():
    root = ET.parse(
        "app/tests/data/CDA_MWO.xml"
    ).getroot()

    patient = build_ch_core_patient(
        parse_patient(root)
    )

    matching_contacts = [
        contact for contact in patient["contact"]
        if contact.get("name", {}).get("text") == "Claudia Maria Enz Wöss"
    ]

    assert len(matching_contacts) == 1

    contact = matching_contacts[0]
    relationship_codings = contact["relationship"][0]["coding"]

    assert relationship_codings[0]["system"] == "http://fhir.ch/ig/ch-core/CodeSystem/ech-11"
    assert relationship_codings[0]["code"] == "contactData"
    assert relationship_codings[1]["system"] == "http://terminology.hl7.org/CodeSystem/v3-RoleCode"
    assert relationship_codings[1]["code"] == "SPS"
    assert contact["relationship"][0]["text"] == "Ehepartner/-in"
    assert contact["telecom"][0]["use"] == "mobile"
    assert contact["address"]["use"] == "home"
    assert contact["extension"][0]["url"] == "https://woess.ch/fhir/StructureDefinition/patient-contact-identifier"
    assert contact["extension"][0]["valueIdentifier"]["system"] == "urn:oid:1.2.840.114350.1.13.521.2.7.2.827665"
    assert contact["extension"][0]["valueIdentifier"]["value"] == "519870"


def test_build_mwo_patient_dedupes_redundant_names_telecoms_and_addresses():
    root = ET.parse(
        "app/tests/data/CDA_MWO.xml"
    ).getroot()

    patient = build_ch_core_patient(
        parse_patient(root)
    )

    assert len(patient["name"]) == 1
    assert len(patient["telecom"]) == 3
    assert len(patient["address"]) == 1
    assert patient["telecom"][1]["use"] == "mobile"
    assert patient["address"][0]["line"] == ["Stutzrain 60"]


def test_build_patient_adds_generated_narrative():
    root = ET.parse(
        "app/tests/data/CDA-EPIC.xml"
    ).getroot()

    patient = build_ch_core_patient(
        parse_patient(root)
    )

    assert patient["text"]["status"] == "generated"
    assert "Generated Narrative: Patient" in patient["text"]["div"]
    assert "Herr MAXIMIN STEPHANE CYPRIEN JOOS-ENGMAN" in patient["text"]["div"]
    assert "DoB: 1975-11-15" in patient["text"]["div"]
    assert "Testhausenstrasse 5" in patient["text"]["div"]