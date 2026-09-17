from xml.etree import ElementTree as ET

from parser.cda.patient_parser import parse_patient


def test_parse_epic_patient_includes_extended_demographics():
	root = ET.parse(
		"app/tests/data/CDA-EPIC.xml"
	).getroot()

	patient = parse_patient(root)

	assert patient.birth_date == "1975-11-15"
	assert patient.gender == "male"
	assert patient.deceased is False
	assert patient.marital_status.code == "S"
	assert patient.addresses[0].use == "home"
	assert patient.addresses[0].state == "BE"
	assert patient.telecoms[0].use == "mobile"
	assert patient.names[0].use == "official"
	assert patient.names[0].prefix == ["Herr"]


def test_parse_at_patient_includes_ch_core_relevant_details():
	root = ET.parse(
		"app/tests/data/CDA-AT.xml"
	).getroot()

	patient = parse_patient(root)

	assert patient.birth_date == "1961-12-24"
	assert patient.marital_status.code == "M"
	assert patient.religion.code == "101"
	assert patient.place_of_birth is not None
	assert patient.place_of_birth.text == "Graz"
	assert patient.communications[0].language.code == "de"
	assert patient.communications[0].preferred is True
	assert patient.contacts[0].name.family == "Sorgenvoll"
	econ_contact = next(
		contact for contact in patient.contacts
		if contact.name is not None and contact.name.text == "Julia Tochter"
	)
	assert econ_contact.relationship.text == "Notfallkontakt"
	assert any(coding["code"] == "ECON" for coding in econ_contact.relationship.codings)
	assert patient.contacts[0].telecoms[0].use == "mobile"
	assert patient.names[0].prefix == ["Dipl.Ing.", "Hofrat"]
	assert patient.names[0].suffix == ["BSc", "MBA"]
	assert any(
		name.family == "VorDerHeirat" and name.use == "old"
		for name in patient.names
	)


def test_parse_mwo_patient_includes_participant_contact():
	root = ET.parse(
		"app/tests/data/CDA_MWO.xml"
	).getroot()

	patient = parse_patient(root)

	matching_contacts = [
		contact for contact in patient.contacts
		if contact.name is not None and contact.name.text == "Claudia Maria Enz Wöss"
	]

	assert len(matching_contacts) == 1

	contact = matching_contacts[0]

	assert contact.relationship is not None
	assert contact.relationship.text == "Ehepartner/-in"
	assert contact.relationship.codings[0]["code"] == "contactData"
	assert any(coding["code"] == "SPS" for coding in contact.relationship.codings)
	assert any(coding["code"] == "other" for coding in contact.relationship.codings)
	assert contact.telecoms[0].use == "mobile"
	assert contact.address is not None
	assert contact.address.use == "home"
	assert contact.address.state == "LU"
	assert len(contact.identifiers) == 1
	assert contact.identifiers[0].system == "urn:oid:1.2.840.114350.1.13.521.2.7.2.827665"
	assert contact.identifiers[0].value == "519870"