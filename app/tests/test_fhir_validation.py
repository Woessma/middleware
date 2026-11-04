import copy
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from main import app
from services.fhir_validation_service import FhirValidationError, validate_fhir_bundle


BUNDLE = {"resourceType": "Bundle", "type": "collection", "entry": []}
OUTCOME = {
    "resourceType": "OperationOutcome",
    "issue": [{
        "severity": "error", "code": "invalid",
        "diagnostics": "Synthetic profile violation",
        "expression": ["Bundle.entry[0]"],
    }],
}


class FhirValidationServiceTests(unittest.TestCase):
    def test_only_calls_internal_validate_and_preserves_input_and_outcome(self):
        source = copy.deepcopy(BUNDLE)
        response = Mock(status_code=200)
        response.json.return_value = OUTCOME
        with (
            patch("services.fhir_validation_service.FHIR_BASE", "http://internal/fhir/"),
            patch("services.fhir_validation_service.requests.post", return_value=response) as post,
        ):
            self.assertEqual(validate_fhir_bundle(source), (200, OUTCOME))
        self.assertEqual(source, BUNDLE)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args, ("http://internal/fhir/Bundle/$validate",))
        self.assertEqual(post.call_args.kwargs["json"], source)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(post.call_args.kwargs["timeout"], 120)

    def test_rejects_non_bundle_before_network_access(self):
        with patch("services.fhir_validation_service.requests.post") as post:
            with self.assertRaises(ValueError):
                validate_fhir_bundle({"resourceType": "Patient"})
        post.assert_not_called()

    def test_rejects_upstream_failures_and_malformed_success(self):
        for status, body in (
            (500, OUTCOME), (302, OUTCOME),
            (400, {"resourceType": "OperationOutcome", "issue": [
                {"severity": "information", "code": "informational"},
            ]}),
            (200, {"resourceType": "Bundle"}),
            (200, {"resourceType": "OperationOutcome", "issue": []}),
            (200, {"resourceType": "OperationOutcome", "issue": [{}]}),
            (200, {"resourceType": "OperationOutcome", "issue": ["invalid"]}),
            (200, {"resourceType": "OperationOutcome", "issue": [
                {"severity": [], "code": "invalid"},
            ]}),
            (200, []),
        ):
            with self.subTest(status=status, body=body):
                response = Mock(status_code=status)
                response.json.return_value = body
                with patch("services.fhir_validation_service.requests.post", return_value=response):
                    with self.assertRaises(FhirValidationError):
                        validate_fhir_bundle(BUNDLE)
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("invalid JSON")
        with patch("services.fhir_validation_service.requests.post", return_value=response):
            with self.assertRaises(FhirValidationError):
                validate_fhir_bundle(BUNDLE)
        with patch("services.fhir_validation_service.requests.post", side_effect=requests.Timeout):
            with self.assertRaises(FhirValidationError):
                validate_fhir_bundle(BUNDLE)


class CdaValidationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_existing_bundle_validation_returns_original_outcome_without_import(self):
        with (
            patch("main.validate_fhir_bundle", return_value=(200, OUTCOME)) as validate,
            patch("main._stabilize_bundle") as stabilize,
            patch("main.requests.post") as post,
        ):
            response = self.client.post("/fhir/validate", json=BUNDLE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), OUTCOME)
        self.assertIn("application/fhir+json", response.headers["content-type"])
        validate.assert_called_once_with(BUNDLE)
        stabilize.assert_not_called()
        post.assert_not_called()

    def test_cda_raw_form_and_file_validation_for_both_bundle_types(self):
        for bundle_type in ("transaction", "document"):
            for body in (
                {"content": b"<ClinicalDocument />"},
                {"data": {"raw_xml": "<ClinicalDocument />"}},
                {"files": {"file": ("synthetic.xml", b"<ClinicalDocument />", "application/xml")}},
            ):
                with (
                    self.subTest(bundle_type=bundle_type, body=body),
                    patch("main.cda_to_fhir_bundle", return_value=BUNDLE) as convert,
                    patch("main._validate_bundle", side_effect=lambda bundle: bundle),
                    patch("main.validate_fhir_bundle", return_value=(200, OUTCOME)) as validate,
                ):
                    response = self.client.post(
                        "/cda/validate", params={"bundle_type": bundle_type}, **body
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), OUTCOME)
                convert.assert_called_once_with(b"<ClinicalDocument />", bundle_type=bundle_type)
                validate.assert_called_once_with(BUNDLE)

    def test_vacd_validation_applies_document_profiles_without_preparing_import(self):
        bundle = {
            "resourceType": "Bundle", "type": "document",
            "entry": [{"resource": {"resourceType": "Composition", "id": "synthetic"}}],
        }
        with (
            patch("main.cda_to_fhir_bundle", return_value=bundle) as convert,
            patch("main._validate_bundle", side_effect=lambda value: value),
            patch("main.validate_fhir_bundle", return_value=(200, OUTCOME)) as validate,
            patch("main._stabilize_bundle") as stabilize,
        ):
            response = self.client.post("/cda/vacd/validate", content=b"<ClinicalDocument />")
        self.assertEqual(response.status_code, 200)
        convert.assert_called_once_with(b"<ClinicalDocument />", bundle_type="document")
        validated = validate.call_args.args[0]
        self.assertIn(
            "http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-document-immunization-administration",
            validated["meta"]["profile"],
        )
        stabilize.assert_not_called()

    def test_invalid_input_never_invokes_validator(self):
        with patch("main.validate_fhir_bundle") as validate:
            self.assertEqual(self.client.post("/cda/validate").status_code, 400)
            self.assertEqual(
                self.client.post("/cda/validate?bundle_type=invalid", content=b"<x/>").status_code,
                422,
            )
            self.assertEqual(self.client.post("/cda/vacd/validate").status_code, 400)
        validate.assert_not_called()

    def test_upstream_input_errors_keep_original_status_and_diagnostics(self):
        for status in (400, 422):
            with self.subTest(status=status):
                upstream = Mock(status_code=status)
                upstream.json.return_value = OUTCOME
                with patch("services.fhir_validation_service.requests.post", return_value=upstream):
                    response = self.client.post("/fhir/validate", json=BUNDLE)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), OUTCOME)

    def test_failed_validation_is_not_a_success_response(self):
        for exception, status in (
            (FhirValidationError("Internal FHIR validator unavailable"), 502),
            (ValueError("A FHIR Bundle is required"), 400),
        ):
            with self.subTest(status=status), patch("main.validate_fhir_bundle", side_effect=exception):
                response = self.client.post("/fhir/validate", json=BUNDLE)
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["issue"][0]["severity"], "error")

    def test_vacd_import_alias_is_disabled(self):
        with patch("main.cda_to_fhir_bundle") as convert:
            response = self.client.post("/cda/vacd/import", content=b"<ClinicalDocument />")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["issue"][0]["code"], "not-supported")
        convert.assert_not_called()
