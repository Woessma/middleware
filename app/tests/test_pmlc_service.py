import copy
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from main import app
from services.pmlc_service import (
    DOCUMENT_PROFILE, PmlcServiceError, PmlcSourceError,
    fetch_active_statement_source, generate_pmlc,
)


PATIENT = {"resourceType": "Patient", "id": "p1", "name": [{"family": "Synthetic"}]}
MEDICATION = {"resourceType": "Medication", "id": "m1", "code": {"text": "Synthetic medication"}}
STATEMENT = {
    "resourceType": "MedicationStatement", "id": "s1", "status": "active",
    "subject": {"reference": "Patient/p1"}, "medicationReference": {"reference": "Medication/m1"},
    "dosage": [{"text": "Synthetic dosage"}],
}


def response(body, status=200):
    result = Mock(status_code=status)
    result.json.return_value = copy.deepcopy(body)
    return result


def search(resources, following=None):
    result = {"resourceType": "Bundle", "type": "searchset", "entry": [
        {"resource": item} for item in resources
    ]}
    if following:
        result["link"] = [{"relation": "next", "url": following}]
    return result


def report(severity="information"):
    return {
        "status": "invalid" if severity == "error" else "validated",
        "bundle": {"resourceType": "Bundle", "type": "document",
                   "meta": {"profile": [DOCUMENT_PROFILE]},
                   "entry": [{"resource": {"resourceType": "Composition"}}]},
        "validation": {"resourceType": "OperationOutcome", "issue": [
            {"severity": severity, "code": "informational" if severity == "information" else "required"}
        ]},
    }


class PmlcSourceTests(unittest.TestCase):
    def test_pagination_and_references_preserve_source_and_only_read(self):
        second = copy.deepcopy(STATEMENT)
        second["id"] = "s2"
        responses = [response(PATIENT), response(search([STATEMENT], "http://internal/fhir/MedicationStatement?page=2")),
                     response(search([second, MEDICATION]))]
        original = copy.deepcopy(STATEMENT)
        with patch("services.pmlc_service.FHIR_BASE", "http://internal/fhir"), \
             patch("services.pmlc_service.requests.get", side_effect=responses) as get:
            source, patient_url, count = fetch_active_statement_source("p1")
        self.assertEqual(count, 2)
        self.assertEqual(STATEMENT, original)
        self.assertEqual(len(source["entry"]), 4)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["status"], "active")
        for call in get.call_args_list:
            self.assertFalse(call.kwargs["allow_redirects"])
        by_type = {}
        for entry in source["entry"]:
            by_type.setdefault(entry["resource"]["resourceType"], []).append(entry)
        self.assertEqual(by_type["Patient"][0]["fullUrl"], patient_url)
        for entry in by_type["MedicationStatement"]:
            self.assertEqual(entry["resource"]["subject"]["reference"], patient_url)
            self.assertEqual(entry["resource"]["medicationReference"]["reference"],
                             by_type["Medication"][0]["fullUrl"])

    def test_resolves_patient_and_statement_dependencies_without_prescribing(self):
        patient = copy.deepcopy(PATIENT)
        patient["generalPractitioner"] = [{"reference": "Practitioner/pr1"}]
        practitioner = {"resourceType": "Practitioner", "id": "pr1"}
        with patch("services.pmlc_service.requests.get", side_effect=[
                response(patient), response(search([STATEMENT])), response(MEDICATION), response(practitioner),
        ]) as get:
            source, _, _ = fetch_active_statement_source("p1")
        self.assertEqual(len(source["entry"]), 4)
        self.assertEqual(get.call_count, 4)
        self.assertNotIn("MedicationRequest", [e["resource"]["resourceType"] for e in source["entry"]])

    def test_rejects_empty_inactive_other_patient_and_unexpected_search_data(self):
        inactive = {**STATEMENT, "status": "stopped"}
        foreign = {**STATEMENT, "subject": {"reference": "Patient/other"}}
        for resources in ([], [inactive], [foreign], [{"resourceType": "MedicationRequest", "id": "r1"}]):
            with self.subTest(resources=resources):
                with patch("services.pmlc_service.requests.get", side_effect=[
                        response(PATIENT), response(search(resources)),
                ]):
                    with self.assertRaises(PmlcSourceError):
                        fetch_active_statement_source("p1")

    def test_rejects_external_pagination_redirects_reference_and_loop(self):
        foreign_ref = copy.deepcopy(STATEMENT)
        foreign_ref["medicationReference"]["reference"] = "https://external.example/Medication/m1"
        for pages in (
            [response(search([STATEMENT], "https://external.example/fhir?page=2"))],
            [response(search([foreign_ref]))],
            [response(search([STATEMENT], "http://fhir-server:8080/fhir/MedicationStatement"))],
            [response({}, 302)],
        ):
            with patch("services.pmlc_service.FHIR_BASE", "http://fhir-server:8080/fhir"), \
                 patch("services.pmlc_service.requests.get", side_effect=[response(PATIENT), *pages]):
                with self.assertRaises((PmlcSourceError, PmlcServiceError)):
                    fetch_active_statement_source("p1")

    def test_no_partial_plan_on_limits_conflicts_missing_or_invalid_response(self):
        changed = {**STATEMENT, "dosage": [{"text": "changed"}]}
        for pages in (
            [response(search([STATEMENT, changed]))],
            [response(search([STATEMENT])), response({}, 404)],
            [response({"resourceType": "Patient"})],
        ):
            with patch("services.pmlc_service.requests.get", side_effect=[response(PATIENT), *pages]):
                with self.assertRaises((PmlcSourceError, PmlcServiceError)):
                    fetch_active_statement_source("p1")
        with patch("services.pmlc_service.MAX_RESOURCES", 1), \
             patch("services.pmlc_service.requests.get", side_effect=[response(PATIENT), response(search([STATEMENT]))]):
            with self.assertRaises(PmlcSourceError):
                fetch_active_statement_source("p1")
        with patch("services.pmlc_service.requests.get", side_effect=requests.Timeout):
            with self.assertRaises(PmlcServiceError):
                fetch_active_statement_source("p1")

    def test_invalid_patient_id_never_contacts_source(self):
        with patch("services.pmlc_service.requests.get") as get:
            for patient_id in ("", "../Patient/other", "p1?x=1"):
                with self.assertRaises(PmlcSourceError):
                    fetch_active_statement_source(patient_id)
            get.assert_not_called()


class PmlcGenerationTests(unittest.TestCase):
    def test_returns_document_and_its_real_outcome_with_no_store(self):
        source = {"resourceType": "Bundle", "type": "collection", "entry": []}
        for severity in ("error", "information"):
            with patch("services.pmlc_service.fetch_active_statement_source", return_value=(source, "urn:uuid:p", 2)), \
                 patch("services.pmlc_service.requests.post", return_value=response(report(severity))) as post:
                result = generate_pmlc("p1")
            self.assertEqual(result["validation"], report(severity)["validation"])
            self.assertFalse(result["source"]["stored"])
            self.assertFalse(result["source"]["medicationRequestsIncluded"])
            self.assertEqual(result["source"]["activeMedicationStatements"], 2)
            self.assertTrue(post.call_args.args[0].endswith("/emed/pmlc"))
            self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_source_confidentiality_cannot_be_downgraded(self):
        patient = copy.deepcopy(PATIENT)
        patient["meta"] = {"security": [
            {"system": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality", "code": "V"}
        ]}
        source = {"entry": [{"resource": patient}]}
        with patch("services.pmlc_service.fetch_active_statement_source", return_value=(source, "urn:uuid:p", 1)), \
             patch("services.pmlc_service.requests.post") as post:
            with self.assertRaises(PmlcSourceError):
                generate_pmlc("p1", confidentiality="restricted")
            post.assert_not_called()

    def test_rejects_upstream_failures_and_inconsistent_success(self):
        invalid = report()
        invalid["status"] = "invalid"
        malformed = report()
        malformed["bundle"]["entry"] = ["not-an-entry"]
        for upstream in (response({}, 503), response({}), response(invalid), response({}, 302), response(malformed)):
            with patch("services.pmlc_service.fetch_active_statement_source", return_value=({"entry": []}, "urn:uuid:p", 1)), \
                 patch("services.pmlc_service.requests.post", return_value=upstream):
                with self.assertRaises(PmlcServiceError):
                    generate_pmlc("p1")
        with patch("services.pmlc_service.fetch_active_statement_source", return_value=({"entry": []}, "urn:uuid:p", 1)), \
             patch("services.pmlc_service.requests.post", side_effect=requests.Timeout):
            with self.assertRaises(PmlcServiceError):
                generate_pmlc("p1")

    def test_endpoint_status_and_no_store_header(self):
        client = TestClient(app)
        for severity, status in (("error", 422), ("information", 200)):
            with patch("main.authorize_pmlc"), patch("main.generate_pmlc", return_value=report(severity)) as generate:
                result = client.post("/fhir/medications/pmlc/from-server?patient_id=p1")
                self.assertEqual(result.status_code, status)
                self.assertEqual(result.json(), report(severity))
                self.assertEqual(result.headers["cache-control"], "no-store")
                generate.assert_called_once_with("p1", "de-CH", "restricted")
        with patch("main.generate_pmlc") as generate:
            self.assertEqual(client.post("/fhir/medications/pmlc/from-server").status_code, 422)
            self.assertEqual(client.post("/fhir/medications/pmlc/from-server?patient_id=../bad").status_code, 422)
            generate.assert_not_called()
        for error, status in ((PmlcSourceError("Missing source"), 422), (PmlcServiceError("Unavailable"), 502)):
            with patch("main.authorize_pmlc"), patch("main.generate_pmlc", side_effect=error):
                result = client.post("/fhir/medications/pmlc/from-server?patient_id=p1")
                self.assertEqual(result.status_code, status)
                self.assertEqual(result.json()["resourceType"], "OperationOutcome")
