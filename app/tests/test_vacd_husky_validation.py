import copy
import json
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from main import app
from services.vacd_validation_service import VacdValidationError, validate_vacd_husky


BUNDLE = {"resourceType": "Bundle", "type": "document", "entry": [
    {"resource": {"resourceType": "Composition", "id": "synthetic"}},
]}
OUTCOME = {"resourceType": "OperationOutcome", "issue": [
    {"severity": "error", "code": "required", "diagnostics": "Synthetic VACD profile violation"},
]}


class VacdHuskyTests(unittest.TestCase):
    def test_posts_exact_bundle_only_to_internal_validator(self):
        original = copy.deepcopy(BUNDLE)
        response = Mock(status_code=422)
        response.json.return_value = OUTCOME
        with patch("services.vacd_validation_service.HUSKY_VALIDATOR_URL", "http://husky:8091/"), \
             patch("services.vacd_validation_service.requests.post", return_value=response) as post:
            self.assertEqual(validate_vacd_husky(BUNDLE), (422, OUTCOME))
        self.assertEqual(BUNDLE, original)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], "http://husky:8091/vacd/validate")
        self.assertEqual(json.loads(post.call_args.kwargs["data"]), original)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_invalid_input_or_oversize_never_calls_engine(self):
        with patch("services.vacd_validation_service.requests.post") as post:
            for bundle in ({}, {"resourceType": "Patient"}, {**BUNDLE, "type": "transaction"}):
                with self.assertRaises(ValueError):
                    validate_vacd_husky(bundle)
            with patch("services.vacd_validation_service.MAX_VACD_BYTES", 1):
                with self.assertRaises(ValueError):
                    validate_vacd_husky(BUNDLE)
            post.assert_not_called()

    def test_engine_failures_and_malformed_outcomes_are_explicit(self):
        for status, body in (
            (503, OUTCOME), (302, OUTCOME), (200, {}), (200, []),
            (200, {"resourceType": "OperationOutcome", "issue": []}),
            (422, {"resourceType": "OperationOutcome", "issue": [
                {"severity": "warning", "code": "incomplete"},
            ]}),
        ):
            with self.subTest(status=status, body=body):
                response = Mock(status_code=status)
                response.json.return_value = body
                with patch("services.vacd_validation_service.requests.post", return_value=response):
                    with self.assertRaises(VacdValidationError):
                        validate_vacd_husky(BUNDLE)
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("Invalid JSON")
        for kwargs in ({"return_value": response}, {"side_effect": requests.Timeout}):
            with patch("services.vacd_validation_service.requests.post", **kwargs):
                with self.assertRaises(VacdValidationError):
                    validate_vacd_husky(BUNDLE)

    def test_error_severity_not_http_success_decides_validation_status(self):
        for severity, expected in (("error", 422), ("fatal", 422), ("warning", 200), ("information", 200)):
            response = Mock(status_code=200)
            response.json.return_value = {"resourceType": "OperationOutcome", "issue": [
                {"severity": severity, "code": "informational"},
            ]}
            with patch("services.vacd_validation_service.requests.post", return_value=response):
                self.assertEqual(validate_vacd_husky(BUNDLE)[0], expected)

    def test_both_endpoints_are_read_only_and_preserve_real_outcome(self):
        client = TestClient(app)
        for path, body in (
            ("/fhir/vacd/husky/validate", {"json": BUNDLE}),
            ("/cda/vacd/husky/validate", {"content": b"<ClinicalDocument />"}),
            ("/cda/vacd/husky/validate", {"data": {"raw_xml": "<ClinicalDocument />"}}),
            ("/cda/vacd/husky/validate", {"files": {"file": ("synthetic.xml", b"<ClinicalDocument />")}}),
        ):
            with self.subTest(path=path, body=body), \
                 patch("main.cda_vacd_convert", return_value=BUNDLE), \
                 patch("main.validate_vacd_husky", return_value=(422, OUTCOME)) as validate, \
                 patch("main.validate_fhir_bundle") as hapi, \
                 patch("main.requests.post") as post:
                response = client.post(path, **body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), OUTCOME)
                self.assertEqual(response.headers["cache-control"], "no-store")
                validate.assert_called_once_with(BUNDLE)
                hapi.assert_not_called()
                post.assert_not_called()

    def test_endpoint_errors_and_existing_hapi_path_remain_separate(self):
        client = TestClient(app)
        for error, status in ((VacdValidationError("Unavailable"), 502), (ValueError("Invalid"), 400)):
            with patch("main.validate_vacd_husky", side_effect=error):
                response = client.post("/fhir/vacd/husky/validate", json=BUNDLE)
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["issue"][0]["severity"], "error")
        with patch("main.cda_vacd_convert", return_value=BUNDLE), \
             patch("main.validate_fhir_bundle", return_value=(200, OUTCOME)) as hapi, \
             patch("main.validate_vacd_husky") as husky:
            response = client.post("/cda/vacd/validate", content=b"<ClinicalDocument />")
            self.assertEqual(response.status_code, 200)
            hapi.assert_called_once_with(BUNDLE)
            husky.assert_not_called()
