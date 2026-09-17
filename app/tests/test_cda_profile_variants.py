import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from builders.ch_core_organization_builder import build_ch_core_organization
from converter.profile_detector import detect_profile
from mappers.organization_mapper import organization_to_fhir_params
from parser.cda.encounter_parser import parse_encounters
from parser.cda.organization_parser import parse_organization
from services import cda_bundle_service


class CdaVariantImportTests(unittest.TestCase):
    def setUp(self):
        self.epic_path = Path(__file__).parent / "data" / "CDA-EPIC.xml"
        self.at_path = Path(__file__).parent / "data" / "CDA-AT.xml"

    def _bundle_lookup_response(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"entry": []}
        return response

    def test_detect_profile_recognizes_epic_and_austrian_documents(self):
        epic_profile = detect_profile(ET.parse(self.epic_path).getroot())
        at_profile = detect_profile(ET.parse(self.at_path).getroot())

        self.assertEqual(epic_profile["vendor"], "EPIC")
        self.assertEqual(epic_profile["profile"], "CCDA")
        self.assertEqual(at_profile["vendor"], "HL7-AT")
        self.assertEqual(at_profile["profile"], "ARZTBRIEF")

    def test_cda_to_fhir_bundle_builds_bundle_for_both_documents(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            epic_bundle = cda_bundle_service.cda_to_fhir_bundle(self.epic_path.read_bytes())
            at_bundle = cda_bundle_service.cda_to_fhir_bundle(self.at_path.read_bytes())

        self.assertEqual(epic_bundle["resourceType"], "Bundle")
        self.assertEqual(at_bundle["resourceType"], "Bundle")
        self.assertGreaterEqual(len(epic_bundle.get("entry", [])), 1)
        self.assertGreaterEqual(len(at_bundle.get("entry", [])), 1)

    def test_at_encounter_parser_uses_encompassing_encounter_fallback(self):
        root = ET.parse(self.at_path).getroot()

        encounters = parse_encounters(root)

        self.assertEqual(len(encounters), 1)
        self.assertEqual(encounters[0].encounter_id, "Az123456")
        self.assertEqual(encounters[0].encounter_class, "AMB")
        self.assertEqual(encounters[0].status, "finished")
        self.assertEqual(encounters[0].start, "20190730104600+0200")
        self.assertEqual(encounters[0].end, "20190730132000+0200")

    def test_at_organization_parser_builds_street_from_street_name_and_house_number(self):
        root = ET.parse(self.at_path).getroot()
        org_node = root.find(
            ".//hl7:custodian/hl7:assignedCustodian/hl7:representedCustodianOrganization",
            {"hl7": "urn:hl7-org:v3"},
        )

        org = parse_organization(org_node)

        self.assertIsNotNone(org)
        self.assertEqual(org.name, "Amadeus Spital")
        self.assertEqual(org.street, "Mozartgasse 1-7")
        self.assertEqual(org.postal_code, "5350")
        self.assertEqual(org.city, "St.Wolfgang")
        self.assertEqual(org.country, "AUT")

    def test_at_organization_uses_root_only_identifier_for_deduplication(self):
        root = ET.parse(self.at_path).getroot()
        org_node = root.find(
            ".//hl7:custodian/hl7:assignedCustodian/hl7:representedCustodianOrganization",
            {"hl7": "urn:hl7-org:v3"},
        )

        org = parse_organization(org_node)
        params = organization_to_fhir_params(org)
        resource = build_ch_core_organization(org)

        self.assertEqual(params["identifier_system"], "urn:oid:1.2.40.0.34.99.4613")
        self.assertEqual(params["identifier_value"], "1.2.40.0.34.99.4613")
        self.assertEqual(
            resource["identifier"],
            [
                {
                    "system": "urn:oid:1.2.40.0.34.99.4613",
                    "value": "1.2.40.0.34.99.4613",
                }
            ],
        )

    def test_at_bundle_contains_single_encounter_resource(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_bundle_service.cda_to_fhir_bundle(self.at_path.read_bytes())

        encounter_entries = [
            entry for entry in bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Encounter"
        ]

        self.assertEqual(len(encounter_entries), 1)
        self.assertEqual(
            encounter_entries[0]["resource"]["identifier"][0],
            {
                "system": "urn:oid:1.2.840.114350.1.13.521.3.7.3.698084.8",
                "value": "Az123456",
            },
        )

    def test_generated_bundles_keep_multiple_posts_per_resource_type(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            epic_bundle = cda_bundle_service.cda_to_fhir_bundle(self.epic_path.read_bytes())

        encounter_entries = [
            entry for entry in epic_bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Encounter"
        ]

        self.assertEqual(len(encounter_entries), 6)

        self.assertTrue(
            all(
                entry.get("request", {}).get("method") in {"POST", "PUT"}
                for entry in encounter_entries
            )
        )

    def test_bundle_includes_patient_resource_with_extended_demographics(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            epic_bundle = cda_bundle_service.cda_to_fhir_bundle(self.epic_path.read_bytes())
            at_bundle = cda_bundle_service.cda_to_fhir_bundle(self.at_path.read_bytes())

        epic_patient_entries = [
            entry for entry in epic_bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Patient"
        ]
        at_patient_entries = [
            entry for entry in at_bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Patient"
        ]

        self.assertEqual(len(epic_patient_entries), 1)
        self.assertEqual(len(at_patient_entries), 1)

        epic_patient = epic_patient_entries[0]["resource"]
        at_patient = at_patient_entries[0]["resource"]

        self.assertIn(
            epic_patient_entries[0]["request"]["method"],
            {"POST", "PUT"},
        )
        self.assertIn(
            epic_patient_entries[0]["request"]["url"],
            {"Patient", "Patient/123"},
        )
        self.assertFalse(epic_patient["deceasedBoolean"])
        self.assertEqual(epic_patient["maritalStatus"]["coding"][0]["code"], "S")
        self.assertEqual(epic_patient["address"][0]["state"], "BE")

        self.assertIn(
            at_patient_entries[0]["request"]["method"],
            {"POST", "PUT"},
        )
        self.assertIn(
            at_patient_entries[0]["request"]["url"],
            {"Patient", "Patient/123"},
        )
        self.assertEqual(at_patient["maritalStatus"]["coding"][0]["code"], "M")
        self.assertEqual(at_patient["communication"][0]["language"]["coding"][0]["code"], "de")
        self.assertEqual(at_patient["contact"][0]["name"]["family"], "Sorgenvoll")

    def test_at_bundle_includes_document_references_and_binary_entries_for_clinical_notes(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_bundle_service.cda_to_fhir_bundle(self.at_path.read_bytes())

        document_reference_entries = [
            entry for entry in bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "DocumentReference"
        ]

        binary_entries = [
            entry for entry in bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Binary"
        ]

        self.assertGreaterEqual(len(document_reference_entries), 1)
        self.assertGreaterEqual(len(binary_entries), 1)

        binary_full_urls = {
            entry["fullUrl"]
            for entry in binary_entries
        }

        attachment_urls = {
            content["attachment"]["url"]
            for entry in document_reference_entries
            for content in entry.get("resource", {}).get("content", [])
            if content.get("attachment", {}).get("url")
        }

        self.assertTrue(attachment_urls)
        self.assertTrue(
            attachment_urls.issubset(binary_full_urls)
        )

    def test_bundle_does_not_include_precreated_practitioner_or_organization(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_bundle_service.cda_to_fhir_bundle(self.epic_path.read_bytes())

        resource_types = [
            entry.get("resource", {}).get("resourceType")
            for entry in bundle.get("entry", [])
        ]

        self.assertNotIn("Practitioner", resource_types)
        self.assertNotIn("Organization", resource_types)

    def test_transaction_bundle_includes_ch_ips_composition_with_section_references(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_bundle_service.cda_to_fhir_bundle(self.at_path.read_bytes())

        composition_entries = [
            entry for entry in bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Composition"
        ]

        self.assertEqual(len(composition_entries), 1)

        composition = composition_entries[0]["resource"]

        self.assertEqual(
            composition["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-composition",
        )
        self.assertEqual(
            composition["type"]["coding"][0]["code"],
            "60591-5",
        )
        self.assertEqual(composition["subject"]["reference"], "Patient/123")
        self.assertEqual(composition["author"][0]["reference"], "Practitioner/456")
        self.assertEqual(composition["custodian"]["reference"], "Organization/789")
        self.assertGreaterEqual(len(composition.get("section", [])), 1)
        self.assertTrue(
            any(section.get("entry") for section in composition["section"])
        )

        bundle_references = {
            (
                f"{entry['resource']['resourceType']}/"
                f"{entry['resource']['id']}"
            )
            for entry in bundle["entry"]
            if entry.get("resource", {}).get("resourceType")
        }
        section_references = {
            entry_reference["reference"]
            for section in composition["section"]
            for entry_reference in section.get("entry", [])
        }
        self.assertTrue(section_references)
        self.assertTrue(section_references.issubset(bundle_references))

        entries_by_reference = {
            (
                f"{entry['resource']['resourceType']}/"
                f"{entry['resource']['id']}"
            ): entry
            for entry in bundle["entry"]
            if entry.get("resource", {}).get("resourceType")
            and entry.get("resource", {}).get("id")
        }
        for reference in section_references:
            self.assertEqual(
                entries_by_reference[reference]["request"],
                {"method": "PUT", "url": reference},
            )

    def test_document_bundle_mode_returns_ch_core_document_bundle(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_bundle_service.cda_to_fhir_bundle(
                self.at_path.read_bytes(),
                bundle_type="document",
            )

        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "document")
        self.assertEqual(
            bundle["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-document",
        )

        self.assertGreaterEqual(len(bundle.get("entry", [])), 1)
        self.assertEqual(
            bundle["entry"][0]["resource"]["resourceType"],
            "Composition",
        )
        self.assertTrue(
            all("request" not in entry for entry in bundle.get("entry", []))
        )

    def test_bundle_includes_related_person_resources_with_ch_core_profile(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch.object(cda_bundle_service, "get_or_create_patient", return_value="123"), \
             patch.object(cda_bundle_service, "get_or_create_practitioner", return_value="456"), \
             patch.object(cda_bundle_service, "get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_bundle_service.cda_to_fhir_bundle(self.epic_path.read_bytes())

        related_person_entries = [
            entry for entry in bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "RelatedPerson"
        ]

        self.assertGreaterEqual(len(related_person_entries), 1)

        profile = related_person_entries[0]["resource"]["meta"]["profile"][0]
        patient_reference = related_person_entries[0]["resource"]["patient"]["reference"]

        self.assertEqual(
            profile,
            "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-relatedperson",
        )
        self.assertEqual(patient_reference, "Patient/123")
