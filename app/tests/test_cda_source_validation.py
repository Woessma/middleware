import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from main import app
from services.cda_validation_service import CdaValidationError, validate_cda_source, MAX_CDA_BYTES


OUTCOME = {"resourceType": "OperationOutcome", "issue": [
    {"severity": "error", "code": "not-supported", "diagnostics": "Missing Schematron"}
]}
XML = b'<ClinicalDocument xmlns="urn:hl7-org:v3"/>'


class CdaSourceValidationTests(unittest.TestCase):
    def test_internal_request_preserves_xml_and_outcome(self):
        response = Mock(status_code=200)
        response.json.return_value = OUTCOME
        with patch("services.cda_validation_service.requests.post", return_value=response) as post:
            self.assertEqual(validate_cda_source(XML, "xsd"), (200, OUTCOME))
        self.assertEqual(post.call_args.kwargs["data"], XML)
        self.assertEqual(post.call_args.kwargs["headers"]["X-Validation-Level"], "xsd")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(post.call_args.kwargs["timeout"], (5, 60))

    def test_input_bounds_before_network(self):
        with patch("services.cda_validation_service.requests.post") as post:
            for xml, level in ((b"", "full"), (XML, "invalid"), (b"x" * (MAX_CDA_BYTES + 1), "xsd")):
                with self.assertRaises(ValueError):
                    validate_cda_source(xml, level)
            post.assert_not_called()

    def test_unavailable_or_invalid_outcome_fails_explicitly(self):
        for status, body in ((503, OUTCOME), (302, OUTCOME), (200, {}), (200, []),
                             (200, {"resourceType": "OperationOutcome", "issue": []}),
                             (400, {"resourceType": "OperationOutcome", "issue": [
                                 {"severity": "information", "code": "informational"}
                             ]})):
            response = Mock(status_code=status)
            response.json.return_value = body
            with self.subTest(status=status, body=body):
                with patch("services.cda_validation_service.requests.post", return_value=response):
                    with self.assertRaises(CdaValidationError):
                        validate_cda_source(XML)
        with patch("services.cda_validation_service.requests.post", side_effect=requests.Timeout):
            with self.assertRaises(CdaValidationError):
                validate_cda_source(XML)
        response = Mock(status_code=200)
        response.json.side_effect = ValueError()
        with patch("services.cda_validation_service.requests.post", return_value=response):
            with self.assertRaises(CdaValidationError):
                validate_cda_source(XML)

    def test_raw_form_file_do_not_convert_or_write(self):
        client = TestClient(app)
        for body in ({"content": XML}, {"data": {"raw_xml": XML.decode()}},
                     {"files": {"file": ("synthetic.xml", XML, "application/xml")}}):
            with patch("main.validate_cda_source", return_value=(200, OUTCOME)) as validate, \
                 patch("main.cda_to_fhir_bundle") as convert, patch("main.requests.post") as post:
                response = client.post("/cda/source/validate?level=xsd", **body)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), OUTCOME)
                validate.assert_called_once_with(XML, "xsd")
                convert.assert_not_called()
                post.assert_not_called()

    def test_endpoint_invalid_oversized_and_unavailable(self):
        client = TestClient(app)
        with patch("main.validate_cda_source") as validate:
            self.assertEqual(client.post("/cda/source/validate?level=invalid", content=XML).status_code, 422)
            self.assertEqual(client.post("/cda/source/validate", content=b"x" * (MAX_CDA_BYTES + 1)).status_code, 413)
            validate.assert_not_called()
        self.assertEqual(client.post("/cda/source/validate", content=b"").status_code, 400)
        with patch("main.validate_cda_source", side_effect=CdaValidationError("Unavailable")):
            response = client.post("/cda/source/validate", content=XML)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()["issue"][0]["severity"], "error")
