import copy
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

import requests
from fastapi.testclient import TestClient

from main import app
from mappers.medication_mapper import map_medication_section
from parser.cda.section_parser import extract_sections
from services.medication_import_validation_service import MedicationImportRejected, validate_medication_import


BUNDLE = {"resourceType": "Bundle", "type": "transaction", "entry": [
    {"fullUrl": "urn:uuid:00000000-0000-4000-8000-000000000001",
     "resource": {"resourceType": "MedicationStatement", "id": "s1", "status": "active",
                  "identifier": [{"system": "https://example.test/import", "value": "stable-id"}],
                  "subject": {"reference": "Patient/p1"}, "medicationCodeableConcept": {"text": "Synthetic"}},
     "request": {"method": "PUT", "url": "MedicationStatement/s1"}},
]}
ERROR = {"resourceType": "OperationOutcome", "issue": [
    {"severity": "error", "code": "invalid", "diagnostics": "Synthetic profile failure"},
]}
WARNING = {"resourceType": "OperationOutcome", "issue": [
    {"severity": "warning", "code": "incomplete", "diagnostics": "Synthetic warning"},
]}


def registry(url, **kwargs):
    profile = kwargs["params"]["url"]
    response = Mock(status_code=200)
    response.json.return_value = {"resourceType": "Bundle", "entry": [
        {"resource": {"resourceType": "StructureDefinition", "url": profile}},
    ]}
    return response


class MedicationImportValidationTests(unittest.TestCase):
    def test_validates_exact_returned_final_bundle_without_replacing_duplicate_identity(self):
        original = copy.deepcopy(BUNDLE)
        with patch("services.medication_import_validation_service.requests.get", side_effect=registry), \
             patch("services.medication_import_validation_service.validate_fhir_bundle",
                   return_value=(200, WARNING)) as validate:
            result = validate_medication_import(BUNDLE)
        self.assertEqual(BUNDLE, original)
        self.assertEqual(result["entry"][0]["resource"]["identifier"],
                         BUNDLE["entry"][0]["resource"]["identifier"])
        self.assertIn("ch-core-medicationstatement", str(result["entry"][0]["resource"]["meta"]["profile"]))
        validate.assert_called_once_with(result)

    def test_errors_even_http_200_and_engine_failure_block_import(self):
        with patch("services.medication_import_validation_service.requests.get", side_effect=registry):
            for status in (200, 400, 422):
                with patch("services.medication_import_validation_service.validate_fhir_bundle",
                           return_value=(status, ERROR)):
                    with self.assertRaises(MedicationImportRejected) as error:
                        validate_medication_import(BUNDLE)
                    self.assertEqual(error.exception.status_code, 422)
                    self.assertEqual(error.exception.outcome, ERROR)
        with patch("services.medication_import_validation_service.requests.get", side_effect=requests.Timeout):
            with self.assertRaises(MedicationImportRejected) as error:
                validate_medication_import(BUNDLE)
            self.assertEqual(error.exception.status_code, 502)

    def test_unknown_profile_blocks_and_non_medication_routes_do_not_change(self):
        result = Mock(status_code=200)
        result.json.return_value = {"resourceType": "Bundle", "entry": []}
        with patch("services.medication_import_validation_service.requests.get", return_value=result), \
             patch("services.medication_import_validation_service.validate_fhir_bundle") as validate:
            with self.assertRaises(MedicationImportRejected) as error:
                validate_medication_import(BUNDLE)
            self.assertEqual(error.exception.status_code, 422)
            validate.assert_not_called()
        source = {"resourceType": "Bundle", "type": "transaction", "entry": []}
        with patch("services.medication_import_validation_service.requests.get") as get:
            self.assertIs(validate_medication_import(source), source)
            get.assert_not_called()

    def test_cda_prepare_and_emediplan_paths_block_without_bridge_write(self):
        client = TestClient(app)
        with patch("main.cda_convert", return_value=BUNDLE), \
             patch("main.validate_medication_import", side_effect=MedicationImportRejected(422, ERROR)), \
             patch("main._bridge_link_post") as bridge:
            response = client.post("/cda/prepare", content=b"<ClinicalDocument/>",
                                   headers={"Authorization": "Bearer synthetic"})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json(), ERROR)
            bridge.assert_not_called()
        for path, body in (
            ("/emediplan/prepare", {"json": BUNDLE}),
            ("/emediplan/import-bundle", {"json": BUNDLE}),
            ("/emediplan/import", {"content": b'{"Medicaments":[]}'}),
            ("/emediplan/qr/import", {"content": b"synthetic-image"}),
        ):
            with self.subTest(path=path), \
                 patch("main._stabilize_bundle", side_effect=lambda bundle: bundle), \
                 patch("main.enrich_emediplan_bundle", side_effect=lambda bundle: bundle), \
                 patch("main._reconcile_emediplan_patients", side_effect=lambda bundle: bundle), \
                 patch("main._reconcile_existing_emediplan_resources", side_effect=lambda bundle: bundle), \
                 patch("main._validate_bundle", side_effect=lambda bundle: bundle), \
                 patch("main.emediplan_to_fhir_bundle", return_value=BUNDLE), \
                 patch("main.extract_emediplan_payload_from_file", return_value=b'{"Medicaments":[]}'), \
                 patch("main.validate_medication_import", side_effect=MedicationImportRejected(422, ERROR)), \
                 patch("main._bridge_link_post") as bridge:
                response = client.post(path, headers={"Authorization": "Bearer synthetic"}, **body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json(), ERROR)
                bridge.assert_not_called()

    def test_contained_unknown_profile_and_invalid_registry_responses_block(self):
        source = copy.deepcopy(BUNDLE)
        unknown = "https://example.test/StructureDefinition/unknown-contained"
        source["entry"][0]["resource"]["contained"] = [{
            "resourceType": "Medication", "id": "m1", "meta": {"profile": [unknown]},
        }]

        def lookup(url, **kwargs):
            response = registry(url, **kwargs)
            if kwargs["params"]["url"] == unknown:
                response.json.return_value = {"resourceType": "Bundle", "entry": []}
            return response

        with patch("services.medication_import_validation_service.requests.get", side_effect=lookup), \
             patch("services.medication_import_validation_service.validate_fhir_bundle") as validate:
            with self.assertRaises(MedicationImportRejected) as error:
                validate_medication_import(source)
            self.assertEqual(error.exception.status_code, 422)
            validate.assert_not_called()
        for body in ([], {"resourceType": "OperationOutcome"}, {"resourceType": "Bundle", "entry": [None]}):
            response = Mock(status_code=200)
            response.json.return_value = body
            with self.subTest(body=body), \
                 patch("services.medication_import_validation_service.requests.get", return_value=response):
                with self.assertRaises(MedicationImportRejected) as error:
                    validate_medication_import(BUNDLE)
                self.assertEqual(error.exception.status_code, 502)


class MedicationSourceMetadataTests(unittest.TestCase):
    def test_missing_or_unrecognized_cda_status_does_not_assert_active_medication(self):
        for status in (None, "synthetic-unrecognized"):
            result = map_medication_section({"entries": [{"statusCode": status}]}, "Patient/p1", {})[0]
            self.assertEqual(result["status"], "unknown")

    def test_unit_text_is_not_automatically_claimed_to_be_ucum(self):
        section = {"entries": [{"statusCode": "active", "doseQuantity": {"value": "1", "unit": "Tablette"}}]}
        statement = map_medication_section(section, "Patient/p1", {})[0]
        quantity = statement["dosage"][0]["doseAndRate"][0]["doseQuantity"]
        self.assertEqual(quantity["unit"], "Tablette")
        self.assertNotIn("system", quantity)
        self.assertNotIn("code", quantity)

    def test_direct_author_identity_and_assertion_time_are_preserved_without_changing_dedup(self):
        plain = {"statusCode": "active", "id": {"root": "2.25.123", "extension": "med1"},
                 "text": "Synthetic instruction", "consumable": {"code": {"displayName": "Synthetic"}}}
        authored = {**plain, "authorDisplay": "Synthetic author", "medicationAuthors": [
            {"identifiers": [{"root": "2.25.123", "extension": "author1"}], "time": "20261105080000+0100"},
        ]}
        first = map_medication_section({"entries": [plain]}, "Patient/p1", {})[0]
        second = map_medication_section({"entries": [authored]}, "Patient/p1", {})[0]
        self.assertEqual(first["identifier"], second["identifier"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["dateAsserted"], "2026-11-05T08:00:00+01:00")
        self.assertEqual(second["informationSource"]["identifier"]["value"], "author1")
        self.assertEqual(second["note"][0]["time"], second["dateAsserted"])
        self.assertNotIn("dateAsserted", first)
        resolved = map_medication_section({"entries": [authored]}, "Patient/p1", {
            "practitioner_id": "known-author",
            "practitioner_identifiers": [{"system": "urn:oid:2.25.123", "value": "author1"}],
        })[0]
        self.assertEqual(resolved["informationSource"]["reference"], "Practitioner/known-author")
        self.assertEqual(resolved["note"][0]["authorReference"]["reference"], "Practitioner/known-author")

    def test_parser_keeps_direct_medication_author_separate_from_nested_comment_author(self):
        xml = ET.fromstring("""
            <ClinicalDocument xmlns="urn:hl7-org:v3"><component><structuredBody><component><section>
            <code code="10160-0"/><entry><substanceAdministration classCode="SBADM" moodCode="EVN">
            <author><time value="20261105080000+0100"/><assignedAuthor>
            <id root="2.25.123" extension="entry-author"/></assignedAuthor></author>
            <entryRelationship><observation><author><time value="20200101"/><assignedAuthor>
            <id root="2.25.123" extension="comment-author"/></assignedAuthor></author>
            </observation></entryRelationship></substanceAdministration></entry>
            </section></component></structuredBody></component></ClinicalDocument>
        """)
        entry = extract_sections(xml)[0]["entries"][0]
        self.assertEqual(len(entry["medicationAuthors"]), 1)
        self.assertEqual(entry["medicationAuthors"][0]["identifiers"][0]["extension"], "entry-author")
