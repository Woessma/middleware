import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services.umzh_convert_service import cda_to_etoc_document_bundle, cda_to_umzh_bundle


class UmzhConvertTests(unittest.TestCase):
    def setUp(self):
        self.epic_path = Path(__file__).parent / "data" / "CDA-EPIC.xml"

    def _bundle_lookup_response(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"entry": []}
        return response

    def test_cda_to_umzh_bundle_returns_service_request_and_task(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch("services.cda_bundle_service.get_or_create_patient", return_value="123"), \
             patch("services.cda_bundle_service.get_or_create_practitioner", return_value="456"), \
             patch("services.cda_bundle_service.get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_to_umzh_bundle(self.epic_path.read_bytes())

        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "collection")
        self.assertEqual(len(bundle.get("entry", [])), 3)
        self.assertIn("fullUrl", bundle["entry"][0])
        self.assertIn("fullUrl", bundle["entry"][1])

        resources = [entry["resource"] for entry in bundle["entry"]]

        service_request = next(
            resource for resource in resources
            if resource["resourceType"] == "ServiceRequest"
        )

        task = next(
            resource for resource in resources
            if resource["resourceType"] == "Task"
        )

        diagnostic_report = next(
            resource for resource in resources
            if resource["resourceType"] == "DiagnosticReport"
        )

        self.assertEqual(
            service_request["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-umzh-connect/StructureDefinition/ch-umzh-connect-servicerequest",
        )
        self.assertIn(
            "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-servicerequest",
            service_request["meta"]["profile"],
        )
        self.assertEqual(
            task["meta"]["profile"][0],
            "http://fhir.ch/ig/ch-umzh-connect/StructureDefinition/ch-umzh-connect-coordinationtask",
        )
        self.assertEqual(
            task["focus"]["reference"],
            f"http://fhir-server:8080/fhir/ServiceRequest/{service_request['id']}",
        )
        self.assertEqual(
            task["basedOn"][0]["reference"],
            f"http://fhir-server:8080/fhir/ServiceRequest/{service_request['id']}",
        )
        self.assertTrue(task["requester"]["reference"].startswith("http://"))
        self.assertTrue(task["owner"]["reference"].startswith("http://"))
        self.assertEqual(
            diagnostic_report["basedOn"][0]["reference"],
            f"http://fhir-server:8080/fhir/ServiceRequest/{service_request['id']}",
        )
        self.assertEqual(diagnostic_report["status"], "final")
        self.assertIn("result", diagnostic_report)

    def test_cda_to_umzh_bundle_updated_stage_adds_questionnaire_output(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch("services.cda_bundle_service.get_or_create_patient", return_value="123"), \
             patch("services.cda_bundle_service.get_or_create_practitioner", return_value="456"), \
             patch("services.cda_bundle_service.get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_to_umzh_bundle(
                self.epic_path.read_bytes(),
                workflow_stage="updated",
            )

        resources = [entry["resource"] for entry in bundle["entry"]]

        task = next(
            resource for resource in resources
            if resource["resourceType"] == "Task"
        )

        questionnaire = next(
            resource for resource in resources
            if resource["resourceType"] == "Questionnaire"
        )

        diagnostic_report = next(
            resource for resource in resources
            if resource["resourceType"] == "DiagnosticReport"
        )

        self.assertEqual(task["status"], "in-progress")
        self.assertEqual(
            task["businessStatus"]["text"],
            "The fulfiller needs more information in order to proceed with the fulfillment of the request",
        )
        self.assertEqual(task["output"][0]["valueReference"]["reference"], f"http://fhir-server:8080/fhir/Questionnaire/{questionnaire['id']}")
        self.assertEqual(diagnostic_report["status"], "final")

    def test_cda_to_umzh_bundle_completed_stage_adds_questionnaire_response(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch("services.cda_bundle_service.get_or_create_patient", return_value="123"), \
             patch("services.cda_bundle_service.get_or_create_practitioner", return_value="456"), \
             patch("services.cda_bundle_service.get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_to_umzh_bundle(
                self.epic_path.read_bytes(),
                workflow_stage="completed",
            )

        resources = [entry["resource"] for entry in bundle["entry"]]

        task = next(
            resource for resource in resources
            if resource["resourceType"] == "Task"
        )

        questionnaire_response = next(
            resource for resource in resources
            if resource["resourceType"] == "QuestionnaireResponse"
        )

        diagnostic_report = next(
            resource for resource in resources
            if resource["resourceType"] == "DiagnosticReport"
        )

        self.assertEqual(task["status"], "completed")
        self.assertTrue(task["input"][0]["valueReference"]["reference"].endswith(f"QuestionnaireResponse/{questionnaire_response['id']}"))
        self.assertEqual(questionnaire_response["questionnaire"], "http://fulfiller.example.org/ch-umzh-connect/QuestionnaireSmokingStatus")
        self.assertEqual(diagnostic_report["status"], "final")

    def test_cda_to_umzh_bundle_sandbox_target_uses_sandbox_urls(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch("services.cda_bundle_service.get_or_create_patient", return_value="123"), \
             patch("services.cda_bundle_service.get_or_create_practitioner", return_value="456"), \
             patch("services.cda_bundle_service.get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_to_umzh_bundle(
                self.epic_path.read_bytes(),
                workflow_stage="initial",
                target="sandbox-placer",
            )

        resources = [entry["resource"] for entry in bundle["entry"]]

        service_request = next(
            resource for resource in resources
            if resource["resourceType"] == "ServiceRequest"
        )

        task = next(
            resource for resource in resources
            if resource["resourceType"] == "Task"
        )

        diagnostic_report = next(
            resource for resource in resources
            if resource["resourceType"] == "DiagnosticReport"
        )

        self.assertTrue(service_request["subject"]["reference"].startswith("http://localhost:8080/fhir/Patient/"))
        self.assertTrue(task["focus"]["reference"].startswith("http://localhost:8080/fhir/ServiceRequest/"))
        self.assertEqual(task["requester"]["reference"], "http://localhost:8084/fhir/Organization/HospitalP")
        self.assertEqual(task["owner"]["reference"], "http://localhost:8084/fhir/Organization/HospitalF")
        self.assertTrue(diagnostic_report["subject"]["reference"].startswith("http://localhost:8080/fhir/Patient/"))

    def test_cda_to_etoc_document_bundle_builds_document_bundle(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch("services.cda_bundle_service.get_or_create_patient", return_value="123"), \
             patch("services.cda_bundle_service.get_or_create_practitioner", return_value="456"), \
             patch("services.cda_bundle_service.get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_to_etoc_document_bundle(
                self.epic_path.read_bytes(),
                workflow_stage="initial",
            )

        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "document")
        self.assertIn("identifier", bundle)
        self.assertEqual(bundle["identifier"]["system"], "urn:ietf:rfc:3986")
        self.assertTrue(bundle["identifier"]["value"].startswith("urn:uuid:"))
        self.assertIn("timestamp", bundle)
        self.assertIn(
            "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-document",
            bundle["meta"]["profile"],
        )

        first_resource = bundle["entry"][0]["resource"]
        self.assertEqual(first_resource["resourceType"], "Composition")
        self.assertIn(
            "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-composition",
            first_resource["meta"]["profile"],
        )

    def test_cda_to_etoc_document_bundle_contains_order_referral_section(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch("services.cda_bundle_service.get_or_create_patient", return_value="123"), \
             patch("services.cda_bundle_service.get_or_create_practitioner", return_value="456"), \
             patch("services.cda_bundle_service.get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_to_etoc_document_bundle(
                self.epic_path.read_bytes(),
                workflow_stage="initial",
            )

        resources = [entry["resource"] for entry in bundle["entry"]]

        service_request = next(
            resource for resource in resources
            if resource["resourceType"] == "ServiceRequest"
        )

        composition = bundle["entry"][0]["resource"]
        sections = composition.get("section", [])

        order_referral = next(
            section for section in sections
            if ((section.get("code") or {}).get("coding") or [{}])[0].get("code") == "93037-0"
        )

        purpose_section = next(
            section for section in sections
            if ((section.get("code") or {}).get("coding") or [{}])[0].get("code") == "42349-1"
        )

        order_referral_refs = [entry["reference"] for entry in order_referral.get("entry", [])]
        self.assertTrue(any("Questionnaire/" in ref for ref in order_referral_refs))
        self.assertTrue(any("QuestionnaireResponse/" in ref for ref in order_referral_refs))
        self.assertTrue(any(ref.endswith(f"ServiceRequest/{service_request['id']}") for ref in order_referral_refs))

        purpose_refs = [entry["reference"] for entry in purpose_section.get("entry", [])]
        self.assertTrue(any(ref.endswith(f"ServiceRequest/{service_request['id']}") for ref in purpose_refs))

    def test_cda_to_etoc_document_bundle_applies_lab_observation_profile(self):
        with patch("fhir.bundle.requests.get", return_value=self._bundle_lookup_response()), \
             patch("services.cda_bundle_service.get_or_create_patient", return_value="123"), \
             patch("services.cda_bundle_service.get_or_create_practitioner", return_value="456"), \
             patch("services.cda_bundle_service.get_or_create_organization", return_value={"id": "789"}):
            bundle = cda_to_etoc_document_bundle(
                self.epic_path.read_bytes(),
                workflow_stage="initial",
            )

        observations = [
            entry["resource"]
            for entry in bundle.get("entry", [])
            if (entry.get("resource") or {}).get("resourceType") == "Observation"
        ]

        self.assertTrue(len(observations) > 0)

        profiled_observations = [
            obs
            for obs in observations
            if "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-lab-observation"
            in ((obs.get("meta") or {}).get("profile") or [])
        ]

        self.assertTrue(len(profiled_observations) > 0)


if __name__ == "__main__":
    unittest.main()
